"""Optional ntfy notifications. Failures here never break the watchdog."""
from __future__ import annotations

import os

import httpx


async def notify(url: str | None, title: str, message: str) -> None:
    if not url:
        return
    try:
        async with httpx.AsyncClient(timeout=5) as c:
            headers = {"Title": title}
            token = os.environ.get("NTFY_TOKEN")
            if token:
                headers["Authorization"] = f"Bearer {token}"
            await c.post(url, content=message.encode(), headers=headers)
    except httpx.HTTPError:
        pass
