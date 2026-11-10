from __future__ import annotations

import asyncio
import html
import os
from contextlib import asynccontextmanager
from datetime import datetime

from fastapi import FastAPI
from fastapi.responses import HTMLResponse

from .checks import QbittorrentCheck
from .config import load
from .docker_client import DockerClient
from .runner import Runner
from .store import Store


def create_app(config_file: str | None = None) -> FastAPI:
    settings = load(config_file or os.environ.get("CONFIG_FILE", "/config/config.yml"))
    store = Store(settings.db_path)
    docker = DockerClient(settings.docker_host)
    qbit = (
        QbittorrentCheck(settings.qbit_url, settings.qbit_user, settings.qbit_pass)
        if settings.qbit_url
        else None
    )
    runner = Runner(settings, docker, store, qbit)

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        task = asyncio.create_task(runner.loop())
        yield
        task.cancel()
        await docker.aclose()

    app = FastAPI(title="watchdog", lifespan=lifespan)

    @app.get("/healthz")
    async def healthz():
        return {"ok": True}

    @app.get("/api/status")
    async def status():
        return {
            "dry_run": settings.dry_run,
            "groups": {k: vars(v) for k, v in runner.statuses.items()},
            "events": store.recent(50),
        }

    @app.get("/", response_class=HTMLResponse)
    async def index():
        mode = "DRY RUN (no restarts)" if settings.dry_run else "LIVE"
        rows = "".join(
            f"<tr><td>{html.escape(g.name)}</td><td><b>{html.escape(g.state)}</b></td>"
            f"<td>{g.restarts_last_hour}</td><td>{html.escape(g.detail)}</td></tr>"
            for g in runner.statuses.values()
        ) or "<tr><td colspan=4>waiting for first check…</td></tr>"
        ev = "".join(
            f"<tr><td>{datetime.fromtimestamp(e['ts']).strftime('%d %b %H:%M:%S')}</td>"
            f"<td>{html.escape(e['grp'])}</td><td>{html.escape(e['kind'])}</td>"
            f"<td>{html.escape(e['detail'])}</td></tr>"
            for e in store.recent(50)
        )
        return f"""<!doctype html><meta charset=utf-8><meta name=viewport content="width=device-width">
<meta http-equiv=refresh content=15><title>Watchdog</title>
<style>body{{font:15px system-ui;margin:2rem auto;max-width:900px;padding:0 1rem;color:#222}}
table{{border-collapse:collapse;width:100%;margin-bottom:2rem}}td,th{{border-bottom:1px solid #ddd;padding:.4rem;text-align:left}}
@media(prefers-color-scheme:dark){{body{{background:#161616;color:#ddd}}td,th{{border-color:#333}}}}</style>
<h1>Watchdog</h1><p>Mode: <b>{mode}</b></p>
<h2>Groups</h2><table><tr><th>Group<th>State<th>Restarts/h<th>Detail</tr>{rows}</table>
<h2>Events</h2><table><tr><th>Time<th>Group<th>Kind<th>Detail</tr>{ev}</table>"""

    return app


app = None


def get_app() -> FastAPI:
    global app
    if app is None:
        app = create_app()
    return app
