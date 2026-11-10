"""Ties engine, Docker client, checks and store together."""
from __future__ import annotations

import asyncio
import time

from .engine import CheckResult, Engine, GroupStatus
from .notify import notify
from .store import Store


class Runner:
    def __init__(self, settings, docker, store: Store, qbit_check=None, clock=time.time):
        self.s = settings
        self.docker = docker
        self.store = store
        self.qbit = qbit_check
        self.clock = clock
        self.engines = [Engine(g) for g in settings.groups]
        for e in self.engines:
            e.preload_restarts(store.restart_times(e.cfg.name, clock() - 3600))
        self.statuses: dict[str, GroupStatus] = {}
        self._last_state: dict[str, str] = {}

    async def tick(self) -> None:
        for eng in self.engines:
            cfg = eng.cfg
            try:
                parent = await self.docker.inspect(cfg.parent)
                children = {c: await self.docker.inspect(c) for c in cfg.children}
            except Exception as exc:  # Docker proxy unreachable etc.
                self._log_state(cfg.name, "error", f"cannot read Docker state: {exc}")
                continue
            checks: dict[str, CheckResult] = {}
            if self.qbit and self.s.qbit_container in cfg.children:
                checks[self.s.qbit_container] = await self.qbit.run()
            res = eng.evaluate(self.clock(), parent, children, checks)
            self.statuses[cfg.name] = res.status
            self._log_state(cfg.name, res.status.state, res.status.detail)
            if res.decision:
                await self._act(cfg.name, res.decision)

    async def _act(self, grp: str, decision) -> None:
        if self.s.dry_run:
            self.store.add(grp, "dry_run", f"would restart {decision.targets}: {decision.reason}")
            await notify(self.s.ntfy_url, "Watchdog (dry run)", f"{grp}: would restart {decision.targets}. {decision.reason}")
            return
        failed = []
        for name in decision.targets:
            try:
                await self.docker.restart(name)
            except Exception as exc:
                failed.append(f"{name}: {exc}")
        if failed:
            self.store.add(grp, "restart_failed", "; ".join(failed))
            await notify(self.s.ntfy_url, "Watchdog: restart FAILED", f"{grp}: {'; '.join(failed)}")
        else:
            self.store.add(grp, "restart", f"restarted {decision.targets}: {decision.reason}")
            await notify(self.s.ntfy_url, "Watchdog restarted containers", f"{grp}: {decision.targets}. {decision.reason}")

    def _log_state(self, grp: str, state: str, detail: str) -> None:
        # Only log state changes, not every tick.
        if self._last_state.get(grp) != state:
            self._last_state[grp] = state
            if state != "restarting":  # the restart itself is logged in _act
                self.store.add(grp, "state", f"{state}: {detail}" if detail else state)

    async def loop(self) -> None:
        while True:
            try:
                await self.tick()
            except Exception as exc:
                self.store.add("-", "error", f"tick failed: {exc}")
            await asyncio.sleep(self.s.interval)
