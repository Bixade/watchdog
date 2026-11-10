"""Policy engine: decides when a group of containers needs a restart.

The engine is a pure state machine. It never talks to Docker or the network:
you give it a snapshot (parent container, child containers, check results) and
the current time, and it returns a status plus an optional restart decision.
That keeps the rules easy to test with a fake clock.

Model
-----
A *group* has one parent (for example Gluetun) and children that share the
parent's network (for example qBittorrent and SearXNG with
``network_mode: service:gluetun``).

Rules, in order:
1. Parent down or unhealthy -> do nothing. That is the kill switch working;
   restarting children now would only churn.
2. Parent healthy, but not for ``parent_healthy_grace`` seconds yet -> wait.
3. A restart happened recently (``settle`` seconds) -> wait.
4. A child that started *before* the parent's current start is attached to a
   network namespace that no longer exists ("stale namespace") -> restart.
5. A child whose check keeps failing for ``bad_after`` seconds -> restart.
6. Restarts are limited by ``cooldown`` and ``max_restarts_per_hour``. When
   the limit is reached the engine gives up and reports it instead of looping.
"""
from __future__ import annotations

from collections import deque
from dataclasses import dataclass, field


@dataclass
class ContainerInfo:
    name: str
    exists: bool = True
    running: bool = False
    health: str | None = None  # "healthy", "unhealthy", "starting" or None
    started_at: float | None = None  # unix seconds


@dataclass
class CheckResult:
    ok: bool | None  # None = could not be determined
    detail: str = ""


@dataclass
class GroupConfig:
    name: str
    parent: str
    children: list[str]
    parent_healthy_grace: float = 60
    bad_after: float = 180
    settle: float = 120
    cooldown: float = 300
    max_restarts_per_hour: int = 3
    stale_tolerance: float = 5


@dataclass
class Decision:
    targets: list[str]
    reason: str


@dataclass
class GroupStatus:
    name: str
    state: str  # ok, waiting_for_vpn, vpn_settling, settling, degraded, cooldown, gave_up, restarting
    detail: str = ""
    bad_for: float = 0
    restarts_last_hour: int = 0
    last_restart: float | None = None


@dataclass
class Result:
    status: GroupStatus
    decision: Decision | None = None


@dataclass
class Engine:
    cfg: GroupConfig
    restart_times: deque = field(default_factory=deque)
    parent_ok_since: float | None = None
    bad_since: float | None = None
    settle_until: float = 0
    last_restart: float | None = None
    gave_up: bool = False

    def preload_restarts(self, times: list[float]) -> None:
        """Remember restarts from before a process restart (from the database)."""
        for t in sorted(times):
            self.restart_times.append(t)
        if self.restart_times:
            self.last_restart = self.restart_times[-1]

    def _prune(self, now: float) -> None:
        while self.restart_times and now - self.restart_times[0] > 3600:
            self.restart_times.popleft()

    def evaluate(
        self,
        now: float,
        parent: ContainerInfo,
        children: dict[str, ContainerInfo],
        checks: dict[str, CheckResult],
    ) -> Result:
        cfg = self.cfg
        self._prune(now)

        def status(state: str, detail: str = "") -> GroupStatus:
            bad_for = (now - self.bad_since) if self.bad_since is not None else 0
            return GroupStatus(
                cfg.name, state, detail, bad_for, len(self.restart_times), self.last_restart
            )

        # 1. Parent must be up and healthy.
        parent_ok = parent.exists and parent.running and parent.health in (None, "healthy")
        if not parent_ok:
            self.parent_ok_since = None
            self.bad_since = None
            why = "not found" if not parent.exists else (
                "not running" if not parent.running else f"health={parent.health}"
            )
            return Result(status("waiting_for_vpn", f"{parent.name} {why}; leaving children alone"))

        if self.parent_ok_since is None:
            self.parent_ok_since = now

        # 2. Give the VPN time to settle after it came back.
        if now - self.parent_ok_since < cfg.parent_healthy_grace:
            self.bad_since = None
            return Result(status("vpn_settling", f"{parent.name} healthy for under {cfg.parent_healthy_grace:.0f}s"))

        # 3. A recent restart needs time to take effect.
        if now < self.settle_until:
            self.bad_since = None
            return Result(status("settling", f"restarted recently, judging again in {self.settle_until - now:.0f}s"))

        running_children = [c for c in cfg.children if children.get(c) and children[c].exists and children[c].running]

        # 4. Stale namespace: child started before the parent's current start.
        stale: list[str] = []
        if parent.started_at is not None:
            for c in running_children:
                info = children[c]
                if info.started_at is not None and info.started_at < parent.started_at - cfg.stale_tolerance:
                    stale.append(c)

        # 5. Failing checks.
        bad = [c for c in running_children if checks.get(c) and checks[c].ok is False]
        if bad:
            if self.bad_since is None:
                self.bad_since = now
        else:
            self.bad_since = None
            self.gave_up = False

        reason = None
        if stale:
            reason = f"{', '.join(stale)} started before {parent.name} restarted (stale network namespace)"
        elif bad and self.bad_since is not None and now - self.bad_since >= cfg.bad_after:
            details = "; ".join(f"{c}: {checks[c].detail}" for c in bad)
            reason = f"check failing for {now - self.bad_since:.0f}s ({details})"

        if reason is None:
            if bad:
                return Result(status("degraded", "; ".join(f"{c}: {checks[c].detail}" for c in bad)))
            return Result(status("ok", ""))

        # 6. Limits.
        if len(self.restart_times) >= cfg.max_restarts_per_hour:
            self.gave_up = True
            return Result(status("gave_up", f"{len(self.restart_times)} restarts in the last hour; not restarting again. {reason}"))
        if self.last_restart is not None and now - self.last_restart < cfg.cooldown:
            return Result(status("cooldown", f"waiting {cfg.cooldown - (now - self.last_restart):.0f}s. {reason}"))

        targets = [c for c in cfg.children if c in running_children]
        self.restart_times.append(now)
        self.last_restart = now
        self.settle_until = now + cfg.settle
        self.bad_since = None
        return Result(status("restarting", reason), Decision(targets, reason))
