"""Health checks that go beyond Docker's own healthcheck."""
from __future__ import annotations

import httpx

from .engine import CheckResult


class QbittorrentCheck:
    """Logs in to the qBittorrent WebUI and reads transfer info.

    ok=False when the WebUI answers but reports the client as disconnected
    (``connection_status == "disconnected"``). If the WebUI itself cannot be
    reached, that is also a failure: the container may be "Up" but its network
    is dead. Authentication problems are reported as ok=None (unknown) so a
    wrong password never causes restarts.
    """

    def __init__(self, url: str, user: str, password: str, client: httpx.AsyncClient | None = None):
        self.url = url.rstrip("/")
        self.user = user
        self.password = password
        self.http = client or httpx.AsyncClient(timeout=10)

    async def run(self) -> CheckResult:
        try:
            login = await self.http.post(
                f"{self.url}/api/v2/auth/login",
                data={"username": self.user, "password": self.password},
                headers={"Referer": self.url},
            )
        except httpx.HTTPError as exc:
            return CheckResult(False, f"WebUI unreachable ({type(exc).__name__})")
        if login.status_code != 200 or login.text.strip() != "Ok.":
            return CheckResult(None, "login failed; check QBIT_USER/QBIT_PASS")
        try:
            r = await self.http.get(f"{self.url}/api/v2/transfer/info")
            r.raise_for_status()
            status = r.json().get("connection_status")
        except (httpx.HTTPError, ValueError) as exc:
            return CheckResult(False, f"transfer/info failed ({type(exc).__name__})")
        if status == "disconnected":
            return CheckResult(False, "qBittorrent reports disconnected")
        return CheckResult(True, f"connection_status={status}")


class HttpCheck:
    """Plain HTTP GET; ok when status < 400."""

    def __init__(self, url: str, client: httpx.AsyncClient | None = None):
        self.url = url
        self.http = client or httpx.AsyncClient(timeout=10)

    async def run(self) -> CheckResult:
        try:
            r = await self.http.get(self.url)
        except httpx.HTTPError as exc:
            return CheckResult(False, f"unreachable ({type(exc).__name__})")
        return CheckResult(r.status_code < 400, f"HTTP {r.status_code}")
