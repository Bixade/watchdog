from __future__ import annotations

import os
from dataclasses import dataclass, field

import yaml

from .engine import GroupConfig


@dataclass
class Settings:
    dry_run: bool = True
    interval: float = 30
    docker_host: str = "http://watchdog-proxy:2375"
    db_path: str = "/data/watchdog.db"
    ntfy_url: str | None = None
    qbit_url: str | None = None
    qbit_user: str = ""
    qbit_pass: str = ""
    groups: list[GroupConfig] = field(default_factory=list)
    qbit_container: str = "qbittorrent"


def load(path: str) -> Settings:
    with open(path) as f:
        raw = yaml.safe_load(f) or {}
    s = Settings(
        dry_run=bool(raw.get("dry_run", True)),
        interval=float(raw.get("interval", 30)),
        db_path=raw.get("db_path", "/data/watchdog.db"),
        qbit_url=raw.get("qbittorrent", {}).get("url"),
        qbit_container=raw.get("qbittorrent", {}).get("container", "qbittorrent"),
    )
    s.docker_host = os.environ.get("DOCKER_HOST", s.docker_host)
    s.ntfy_url = os.environ.get("NTFY_URL") or raw.get("ntfy_url")
    s.qbit_user = os.environ.get("QBIT_USER", "")
    s.qbit_pass = os.environ.get("QBIT_PASS", "")
    for g in raw.get("groups", []):
        keys = {k: v for k, v in g.items() if k in GroupConfig.__dataclass_fields__}
        s.groups.append(GroupConfig(**keys))
    return s
