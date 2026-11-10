"""Minimal Docker Engine API client (inspect + restart) over HTTP.

Talks to a docker-socket-proxy, never to the raw socket.
"""
from __future__ import annotations

from datetime import datetime

import httpx

from .engine import ContainerInfo


def parse_docker_time(value: str | None) -> float | None:
    """Docker timestamps look like 2026-11-10T08:00:00.123456789Z."""
    if not value or value.startswith("0001-"):
        return None
    value = value.rstrip("Z")
    if "." in value:
        head, frac = value.split(".", 1)
        value = f"{head}.{frac[:6]}"
    return datetime.fromisoformat(value + "+00:00").timestamp()


def info_from_inspect(name: str, data: dict) -> ContainerInfo:
    state = data.get("State", {})
    health = (state.get("Health") or {}).get("Status")
    return ContainerInfo(
        name=name,
        exists=True,
        running=bool(state.get("Running")) and not state.get("Restarting"),
        health=health,
        started_at=parse_docker_time(state.get("StartedAt")),
    )


class DockerClient:
    def __init__(self, base_url: str, client: httpx.AsyncClient | None = None):
        self.base_url = base_url.replace("tcp://", "http://").rstrip("/")
        self.http = client or httpx.AsyncClient(base_url=self.base_url, timeout=15)

    async def inspect(self, name: str) -> ContainerInfo:
        r = await self.http.get(f"/containers/{name}/json")
        if r.status_code == 404:
            return ContainerInfo(name=name, exists=False)
        r.raise_for_status()
        return info_from_inspect(name, r.json())

    async def restart(self, name: str, timeout: int = 10) -> None:
        r = await self.http.post(f"/containers/{name}/restart", params={"t": timeout})
        r.raise_for_status()

    async def aclose(self) -> None:
        await self.http.aclose()
