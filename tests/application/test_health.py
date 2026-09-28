"""Dependency health gates intake, restarts the runtime in the GPU slot and alerts."""

import asyncio
from types import SimpleNamespace

from tgbotdocs.application.health import RETRY_EVERY_FAILURES, HealthMonitor
from tgbotdocs.application.scheduler import GpuScheduler
from tgbotdocs.storage import StorageUnavailable


class Storage:
    def __init__(self):
        self.up = True

    async def health(self):
        if not self.up:
            raise StorageUnavailable("down")


class Runtime:
    def __init__(self):
        self._process = SimpleNamespace(returncode=None)
        self.port, self.restarts, self.restart_ok = 1, 0, True

    async def restart(self):
        self.restarts += 1
        if not self.restart_ok:
            raise RuntimeError("synthetic restart failure")
        self._process = SimpleNamespace(returncode=None)


class Adapter:
    def __init__(self):
        self._available = True

    async def _idle(self):
        return True


def monitor(scheduler=None):
    alerts = []
    health = HealthMonitor(Storage(), Runtime(), Adapter(), scheduler or GpuScheduler(), alerts.append)
    health.endpoint_ok = True

    async def endpoint():
        process = health.runtime._process
        return process.returncode is None and health.adapter._available and health.endpoint_ok
    health._runtime_ok = endpoint
    return health, alerts


async def test_database_and_runtime_transitions_gate_intake_and_alert_once():
    health, alerts = monitor()
    assert await health.check() and not alerts
    health.storage.up = False
    assert not await health.check() and not health.healthy()
    assert not await health.check()
    assert alerts == ["database_unavailable"]
    health.storage.up = True
    assert await health.check() and alerts[-1] == "database_available"
    await health.scheduler.close()


async def test_dead_runtime_is_restarted_after_the_running_call_and_recovers():
    scheduler = GpuScheduler()
    health, alerts = monitor(scheduler)
    started, release, order = asyncio.Event(), asyncio.Event(), []

    async def running_call():
        started.set()
        await release.wait()
        order.append("call finished")

    call = asyncio.create_task(scheduler.run("job", running_call, admission_order=0))
    await started.wait()
    health.runtime._process = SimpleNamespace(returncode=1)
    check = asyncio.create_task(health.check())
    await asyncio.sleep(0.05)
    assert health.runtime.restarts == 0  # waits for the slot
    release.set()
    await call
    order.append("restart")
    assert await check and health.runtime.restarts == 1
    assert order == ["call finished", "restart"] and alerts == ["runtime_restarted"]
    await scheduler.close()


async def test_failed_restart_closes_intake_retries_rarely_and_reopens():
    health, alerts = monitor()
    health.adapter._available = False
    health.runtime.restart_ok = False
    assert not await health.check() and alerts == ["runtime_unavailable"]
    for _ in range(RETRY_EVERY_FAILURES - 1):
        assert not await health.check()
    assert health.runtime.restarts == 1
    health.runtime.restart_ok = True
    assert await health.check() and health.runtime.restarts == 2
    assert health.adapter._available and alerts[-2:] == ["runtime_restarted", "runtime_available"]
    await health.scheduler.close()


async def test_a_live_process_with_a_failing_endpoint_restarts_only_after_repeated_failures():
    health, alerts = monitor()
    health.endpoint_ok = False
    assert not await health.check() and not await health.check()
    assert health.runtime.restarts == 0
    original = health.runtime.restart

    async def restart():
        await original()
        health.endpoint_ok = True
    health.runtime.restart = restart
    assert await health.check() and health.runtime.restarts == 1
    assert alerts == ["runtime_unavailable", "runtime_restarted", "runtime_available"]
    await health.scheduler.close()
