import asyncio, httpx, pytest
from app.checks import QbittorrentCheck
from app.docker_client import DockerClient, parse_docker_time
from app.store import Store
from app.runner import Runner
from app.config import Settings
from app.engine import GroupConfig

def run(c): return asyncio.run(c)

def test_parse_time():
    assert parse_docker_time("2026-11-10T08:00:00.123456789Z") == 1794297600.123456
    assert parse_docker_time("0001-01-01T00:00:00Z") is None

def qb(handler):
    return QbittorrentCheck("http://q", "u", "p", httpx.AsyncClient(transport=httpx.MockTransport(handler)))

def test_qbit_ok_disconnected_unreachable_authfail():
    def h(status):
        def f(req):
            if req.url.path.endswith("login"): return httpx.Response(200, text="Ok.")
            return httpx.Response(200, json={"connection_status": status})
        return f
    assert run(qb(h("connected")).run()).ok is True
    assert run(qb(h("disconnected")).run()).ok is False
    def boom(req): raise httpx.ConnectError("x")
    assert run(qb(boom).run()).ok is False
    def bad(req): return httpx.Response(200, text="Fails.")
    assert run(qb(bad).run()).ok is None

def test_docker_inspect_and_restart():
    calls = []
    def f(req):
        calls.append((req.method, req.url.path))
        if req.method == "GET" and "missing" in req.url.path: return httpx.Response(404)
        if req.method == "GET":
            return httpx.Response(200, json={"State": {"Running": True, "StartedAt": "2026-11-10T08:00:00Z", "Health": {"Status": "healthy"}}})
        return httpx.Response(204)
    d = DockerClient("http://p", httpx.AsyncClient(base_url="http://p", transport=httpx.MockTransport(f)))
    i = run(d.inspect("gluetun")); assert i.running and i.health == "healthy"
    assert run(d.inspect("missing")).exists is False
    run(d.restart("qbittorrent")); assert ("POST", "/containers/qbittorrent/restart") in calls

class FakeDocker:
    def __init__(self, p, q): self.p, self.q, self.restarted = p, q, []
    async def inspect(self, n): return self.p if n == "gluetun" else self.q
    async def restart(self, n): self.restarted.append(n)

def test_runner_dry_run_vs_live(tmp_path):
    from app.engine import ContainerInfo as C
    for dry in (True, False):
        s = Settings(dry_run=dry, groups=[GroupConfig("g", "gluetun", ["qbittorrent"], parent_healthy_grace=0)])
        now = [1000.0]
        d = FakeDocker(C("gluetun", True, True, "healthy", 900), C("qbittorrent", True, True, None, 500))
        st = Store(str(tmp_path / f"{dry}.db"))
        r = Runner(s, d, st, None, clock=lambda: now[0])
        run(r.tick())
        assert d.restarted == ([] if dry else ["qbittorrent"])
        kinds = [e["kind"] for e in st.recent()]
        assert ("dry_run" in kinds) == dry and ("restart" in kinds) == (not dry)
