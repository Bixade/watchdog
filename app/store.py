"""SQLite event log."""
from __future__ import annotations

import sqlite3
import time


class Store:
    def __init__(self, path: str):
        self.db = sqlite3.connect(path, check_same_thread=False)
        self.db.execute(
            "CREATE TABLE IF NOT EXISTS events ("
            "id INTEGER PRIMARY KEY, ts REAL NOT NULL, grp TEXT NOT NULL, "
            "kind TEXT NOT NULL, detail TEXT NOT NULL)"
        )
        self.db.commit()

    def add(self, grp: str, kind: str, detail: str, ts: float | None = None) -> None:
        self.db.execute(
            "INSERT INTO events (ts, grp, kind, detail) VALUES (?,?,?,?)",
            (ts if ts is not None else time.time(), grp, kind, detail),
        )
        self.db.commit()

    def recent(self, limit: int = 50) -> list[dict]:
        rows = self.db.execute(
            "SELECT ts, grp, kind, detail FROM events ORDER BY id DESC LIMIT ?", (limit,)
        ).fetchall()
        return [dict(ts=r[0], grp=r[1], kind=r[2], detail=r[3]) for r in rows]

    def restart_times(self, grp: str, since: float) -> list[float]:
        rows = self.db.execute(
            "SELECT ts FROM events WHERE grp=? AND kind IN ('restart','dry_run') AND ts>=?",
            (grp, since),
        ).fetchall()
        return [r[0] for r in rows]
