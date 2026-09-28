"""Dependency health and intake gating (STATE_MACHINE, Dependency Unavailability).

While PostgreSQL or the model runtime is unhealthy, new jobs are refused as
temporarily unavailable before any download; admitted jobs keep their own
deadlines. A runtime whose process ended, whose slot could not be released, or
whose health endpoint keeps failing is restarted inside the GPU scheduler's
slot, so no model call runs during the restart. Every
transition produces one content-free operator alert. While the runtime stays
unavailable, health checks continue and a restart is retried at a low rate.
"""

import asyncio
from contextlib import suppress
import time

import httpx

RESTART_AFTER_FAILURES = 3
# While the runtime stays unavailable, a new restart is attempted this rarely.
RETRY_EVERY_FAILURES = 10


class HealthMonitor:
    def __init__(self, storage, runtime, adapter, scheduler, alert, *, interval_s=30.0, timeout_s=10.0,
                 clock=time.monotonic):
        self.storage, self.runtime, self.adapter, self.scheduler = storage, runtime, adapter, scheduler
        self.alert, self.interval_s, self.timeout_s, self.clock = alert, interval_s, timeout_s, clock
        self.database = self.model = True
        self.failures = 0
        self.attempted = None

    def healthy(self):
        return self.database and self.model

    async def _database_ok(self):
        try:
            async with asyncio.timeout(self.timeout_s):
                await self.storage.health()
            return True
        except Exception:
            return False

    async def _runtime_ok(self):
        # Private attributes of the frozen runtime/adapter are read, never changed here.
        process = getattr(self.runtime, "_process", None)
        if process is None or process.returncode is not None or not getattr(self.adapter, "_available", True):
            return False
        try:
            async with httpx.AsyncClient(trust_env=False, timeout=self.timeout_s) as client:
                response = await client.get(f"http://127.0.0.1:{self.runtime.port}/health")
            return response.status_code == 200 and response.json().get("status") == "ok"
        except (httpx.HTTPError, ValueError, AttributeError):
            return False

    async def _restart(self):
        """Runs in the scheduler slot: no call streams while the server restarts."""
        await self.runtime.restart()
        if not await self.adapter._idle():
            raise RuntimeError("runtime_not_idle_after_restart")
        self.adapter._available = True

    async def check(self):
        database = await self._database_ok()
        if database != self.database:
            self.database = database
            self.alert("database_available" if database else "database_unavailable")
        model = await self._runtime_ok()
        if model:
            self.failures, self.attempted = 0, None
        else:
            self.failures += 1
            process = getattr(self.runtime, "_process", None)
            dead = process is None or process.returncode is not None or not getattr(self.adapter, "_available", True)
            due = self.attempted is None or self.failures - self.attempted >= RETRY_EVERY_FAILURES
            if due and (dead or self.failures >= RESTART_AFTER_FAILURES):
                self.attempted = self.failures
                try:
                    await self.scheduler.run("health-runtime-restart", self._restart, interactive=True)
                    model = await self._runtime_ok()
                    if model:
                        self.failures = 0
                        self.alert("runtime_restarted")
                except Exception:
                    model = False
                finally:
                    with suppress(RuntimeError):
                        self.scheduler.forget("health-runtime-restart")
        if model != self.model:
            self.model = model
            self.alert("runtime_available" if model else "runtime_unavailable")
        return self.healthy()

    async def run(self):
        while True:
            await asyncio.sleep(self.interval_s)
            try:
                await self.check()
            except Exception:
                # A failed check must not stop later checks.
                self.database = self.model = False
