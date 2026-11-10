from app.engine import ContainerInfo as C, CheckResult as R, Engine, GroupConfig

def mk(**kw):
    return Engine(GroupConfig("g", "gluetun", ["qb"], parent_healthy_grace=60, bad_after=180,
                              settle=120, cooldown=300, max_restarts_per_hour=3, **kw))

def P(started=1000, health="healthy", running=True):
    return C("gluetun", True, running, health, started)

def Q(started=1000):
    return C("qb", True, True, None, started)

BAD = {"qb": R(False, "disconnected")}
OK = {"qb": R(True)}

def test_ok():
    assert mk().evaluate(0, P(), {"qb": Q()}, OK).status.state == "vpn_settling"
    e = mk(); e.evaluate(0, P(), {"qb": Q()}, OK)
    assert e.evaluate(100, P(), {"qb": Q()}, OK).status.state == "ok"

def test_vpn_down_leaves_children_alone():
    e = mk()
    r = e.evaluate(0, P(health="unhealthy"), {"qb": Q()}, BAD)
    assert r.status.state == "waiting_for_vpn" and r.decision is None
    r = e.evaluate(10000, C("gluetun", True, False), {"qb": Q()}, BAD)
    assert r.decision is None

def test_grace_after_vpn_returns():
    e = mk()
    e.evaluate(0, P(health="unhealthy"), {"qb": Q()}, BAD)
    r = e.evaluate(30, P(), {"qb": Q()}, BAD)
    assert r.status.state == "vpn_settling" and r.decision is None

def test_stale_namespace_restarts_immediately():
    e = mk(); e.evaluate(0, P(2000), {"qb": Q(1000)}, OK)
    r = e.evaluate(100, P(2000), {"qb": Q(1000)}, OK)
    assert r.decision and r.decision.targets == ["qb"] and "stale" in r.decision.reason

def test_bad_check_needs_to_persist():
    e = mk(); e.evaluate(0, P(), {"qb": Q()}, OK)
    assert e.evaluate(100, P(), {"qb": Q()}, BAD).status.state == "degraded"
    assert e.evaluate(200, P(), {"qb": Q()}, BAD).decision is None
    assert e.evaluate(290, P(), {"qb": Q()}, BAD).decision is not None

def test_recovery_resets_timer():
    e = mk(); e.evaluate(0, P(), {"qb": Q()}, OK)
    e.evaluate(100, P(), {"qb": Q()}, BAD)
    e.evaluate(150, P(), {"qb": Q()}, OK)
    assert e.evaluate(300, P(), {"qb": Q()}, BAD).decision is None

def test_unknown_check_never_restarts():
    e = mk(); e.evaluate(0, P(), {"qb": Q()}, OK)
    for t in (100, 500, 5000):
        assert e.evaluate(t, P(), {"qb": Q()}, {"qb": R(None, "login failed")}).decision is None

def test_settle_cooldown_and_cap():
    e = mk(); e.evaluate(0, P(2000), {"qb": Q(1000)}, OK)
    assert e.evaluate(100, P(2000), {"qb": Q(1000)}, OK).decision  # restart 1 (stale)
    assert e.evaluate(150, P(2000), {"qb": Q(1000)}, OK).status.state == "settling"
    assert e.evaluate(230, P(2000), {"qb": Q(1000)}, OK).status.state == "cooldown"
    assert e.evaluate(420, P(2000), {"qb": Q(1000)}, OK).decision      # restart 2
    assert e.evaluate(800, P(2000), {"qb": Q(1000)}, OK).decision      # restart 3
    r = e.evaluate(1200, P(2000), {"qb": Q(1000)}, OK)
    assert r.status.state == "gave_up" and r.decision is None
    assert e.evaluate(3800, P(2000), {"qb": Q(1000)}, OK).decision     # window passed

def test_preload_counts_toward_cap():
    e = mk(); e.preload_restarts([10, 20, 30])
    e.evaluate(0, P(2000), {"qb": Q(1000)}, OK)
    r = e.evaluate(100, P(2000), {"qb": Q(1000)}, OK)
    assert r.status.state == "gave_up"

def test_stopped_child_is_not_restarted():
    e = mk(); e.evaluate(0, P(), {"qb": Q()}, OK)
    stopped = C("qb", True, False, None, 1000)
    assert e.evaluate(100, P(), {"qb": stopped}, {}).decision is None


def test_grace_rearms_when_parent_restarts_between_checks():
    e = mk(); e.evaluate(0, P(1000), {"qb": Q(1000)}, OK)
    assert e.evaluate(100, P(1000), {"qb": Q(1000)}, OK).status.state == "ok"
    # gluetun restarted (new StartedAt) but was never seen unhealthy
    r = e.evaluate(130, P(1125), {"qb": Q(1000)}, OK)
    assert r.status.state == "vpn_settling" and r.decision is None
    r = e.evaluate(195, P(1125), {"qb": Q(1000)}, OK)
    assert r.decision and "stale" in r.decision.reason
