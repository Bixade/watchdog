"""Optional ntfy notifications. Failures here never break the watchdog."""
from __future__ import annotations

import httpx


async def notify(url: str | None, title: str, message: str) -> None:
    if not url:
        return
    try:
        async with httpx.AsyncClient(timeout=5) as c:
            await c.post(url, content=message.encode(), headers={"Title": title})
    except httpx.HTTPError:
        pass
