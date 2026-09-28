import asyncio
from contextlib import suppress
import json
import math
from types import SimpleNamespace

import pytest
from PIL import Image

from tgbotdocs.application.scheduler import GpuScheduler, ScheduledRecognitionCore
from tgbotdocs.recognition.adapter import ModelError, ModelReply, TokenScore
from tgbotdocs.recognition.contracts import ExtractionProfile, ScalarField
from tgbotdocs.recognition.core import CoreSettings, JobObserver, ProcessingBudget, RecognitionCore
from tgbotdocs.recognition.runtime import RuntimeProfile
from tgbotdocs.recognition.verification import VerificationPolicy


async def spin_until(predicate):
    async with asyncio.timeout(2):
        while not predicate():  # noqa: ASYNC110 - bounded observation of the scheduler's private queue
            await asyncio.sleep(0)


async def test_compiler_priority_and_document_admission_ring():
    scheduler = GpuScheduler()
    gate, started = asyncio.Event(), asyncio.Event()
    calls, concurrent = [], 0
    peak = 0

    async def call(label, blocked=False):
        nonlocal concurrent, peak
        concurrent += 1
        peak = max(peak, concurrent)
        calls.append(label)
        try:
            if blocked:
                started.set()
                await gate.wait()
            await asyncio.sleep(0)
            return label
        finally:
            concurrent -= 1

    first = asyncio.create_task(scheduler.run("a", lambda: call("a1", True), admission_order=0))
    await started.wait()
    # a's retry cannot jump over b, even if it was enqueued first.
    a2 = asyncio.create_task(scheduler.run("a", lambda: call("a2"), admission_order=0))
    b = asyncio.create_task(scheduler.run("b", lambda: call("b"), admission_order=1))
    compile_task = asyncio.create_task(scheduler.run("settings", lambda: call("compile"), interactive=True))
    await spin_until(lambda: len(scheduler._pending) == 3)
    gate.set()
    assert await asyncio.gather(first, a2, b, compile_task) == ["a1", "a2", "b", "compile"]
    assert calls == ["a1", "compile", "b", "a2"]
    assert peak == 1
    await scheduler.close()


async def test_cancel_queued_job_never_invokes_factory_or_late_call():
    scheduler = GpuScheduler()
    gate, started = asyncio.Event(), asyncio.Event()
    calls = []

    async def first():
        started.set()
        await gate.wait()

    async def forbidden():
        calls.append("forbidden")

    task = asyncio.create_task(scheduler.run("a", first))
    await started.wait()
    queued = asyncio.create_task(scheduler.run("b", forbidden))
    await spin_until(lambda: len(scheduler._pending) == 1)
    await scheduler.cancel("b")
    with pytest.raises(asyncio.CancelledError):
        await queued
    with pytest.raises(asyncio.CancelledError):
        await scheduler.run("b", forbidden)
    gate.set()
    await task
    assert not calls
    await scheduler.close()


async def test_cancel_running_call_waits_for_release_before_next_operation():
    scheduler = GpuScheduler()
    started, releasing, idle = asyncio.Event(), asyncio.Event(), asyncio.Event()
    order = []

    async def stream():
        started.set()
        try:
            await asyncio.Event().wait()
        finally:
            order.append("closing")
            releasing.set()
            await idle.wait()
            order.append("idle")

    async def next_call():
        order.append("next")

    active = asyncio.create_task(scheduler.run("a", stream))
    await started.wait()
    waiting = asyncio.create_task(scheduler.run("b", next_call))
    cancelling = asyncio.create_task(scheduler.cancel("a"))
    await releasing.wait()
    assert order == ["closing"] and not waiting.done()
    idle.set()
    await cancelling
    with pytest.raises(asyncio.CancelledError):
        await active
    await waiting
    assert order == ["closing", "idle", "next"]
    await scheduler.close()


async def test_queue_timeout_does_not_execute_and_error_does_not_stop_next_job():
    scheduler = GpuScheduler(queue_timeout_s=0.015)
    started, gate = asyncio.Event(), asyncio.Event()
    calls = []

    async def blocked():
        started.set()
        await gate.wait()
        raise ModelError("synthetic_failure")

    async def queued_call():
        calls.append("called")
        return 7

    active = asyncio.create_task(scheduler.run("a", blocked))
    await started.wait()
    with pytest.raises(ModelError, match="queue_wait_expired"):
        await scheduler.run("b", queued_call)
    gate.set()
    with pytest.raises(ModelError, match="synthetic_failure"):
        await active
    assert calls == []
    assert await scheduler.run("c", queued_call) == 7
    def invalid_factory():
        raise ValueError("synthetic_factory_error")

    with pytest.raises(ValueError, match="synthetic_factory_error"):
        await scheduler.run("d", invalid_factory)
    assert await scheduler.run("e", queued_call) == 7
    await scheduler.close()


async def test_queue_wait_is_not_charged_and_remaining_budget_is_recomputed(tmp_path):
    scheduler = GpuScheduler()
    started, gate = asyncio.Event(), asyncio.Event()

    async def blocker():
        started.set()
        await gate.wait()

    active = asyncio.create_task(scheduler.run("blocker", blocker))
    await started.wait()
    observed = []

    class Adapter:
        async def generate(self, *args, **kwargs):
            observed.append(kwargs["remaining_budget_s"])
            await asyncio.sleep(0.005)
            return ModelReply("{}", (), False, 1, 1, 0.005)

    settings = CoreSettings(runtime=RuntimeProfile(), verification=VerificationPolicy(), matching_margin=0.1)
    core = ScheduledRecognitionCore(Adapter(), settings, scheduler=scheduler, job_id="job")
    budget = ProcessingBudget(0.15)
    job = SimpleNamespace(budget=budget, observer=JobObserver())
    path = tmp_path / "page.png"
    path.write_bytes(b"synthetic")
    pages = (SimpleNamespace(page_id=1, path=path),)

    async def call():
        with budget.charge():
            return await core._call(job, "instruction", pages, {}, json.loads, kind="extraction", batch=0)

    waiting = asyncio.create_task(call())
    await spin_until(lambda: len(scheduler._pending) == 1)
    await asyncio.sleep(0.2)  # intentionally exceeds this job's processing budget
    gate.set()
    await active
    assert (await waiting)[0] == {}
    assert 0.1 < observed[0] <= 0.15
    assert 0.003 < budget.used < 0.15
    await scheduler.close()


async def test_scheduled_count_and_contract_retry_share_per_call_turns(tmp_path):
    scheduler = GpuScheduler()
    started, gate = asyncio.Event(), asyncio.Event()
    events = []

    class Adapter:
        calls = 0

        async def count_input_tokens(self, *args, **kwargs):
            events.append("a-count")
            return 100

        async def generate(self, *args, **kwargs):
            self.calls += 1
            events.append(f"a-{self.calls}")
            if self.calls == 1:
                started.set()
                await gate.wait()
            text = "bad-json" if self.calls == 1 else "{}"
            return ModelReply(text, (), False, 100, 1, 0.001)

    settings = CoreSettings(runtime=RuntimeProfile(), verification=VerificationPolicy(), matching_margin=0.1)
    core = ScheduledRecognitionCore(Adapter(), settings, scheduler=scheduler, job_id="a", admission_order=0)
    job = SimpleNamespace(budget=ProcessingBudget(10), observer=JobObserver())
    path = tmp_path / "page.png"
    path.write_bytes(b"synthetic")
    pages = (SimpleNamespace(page_id=1, path=path),)

    async def a():
        with job.budget.charge():
            assert await core._count(job, "x", pages, {}, stage="extraction", batch=0) == 100
            return await core._call(job, "x", pages, {}, json.loads, kind="extraction", batch=0)

    async def b():
        events.append("b")

    first = asyncio.create_task(a())
    await started.wait()
    second = asyncio.create_task(scheduler.run("b", b, admission_order=1))
    await spin_until(lambda: len(scheduler._pending) == 1)
    gate.set()
    await asyncio.gather(first, second)
    assert events == ["a-count", "a-1", "b", "a-2"]
    assert job.observer.contract_retries == 1
    await scheduler.close()


async def test_caller_cancellation_and_close_drain_without_pending_tasks():
    scheduler = GpuScheduler()
    started = asyncio.Event()

    async def call():
        started.set()
        await asyncio.Event().wait()

    task = asyncio.create_task(scheduler.run("a", call))
    await started.wait()
    task.cancel()
    with suppress(asyncio.CancelledError):
        await task
    await scheduler.close()
    with pytest.raises(ModelError, match="scheduler_closed"):
        await scheduler.run("b", call)


async def test_full_core_parity_including_retry_and_alternate_view(tmp_path):
    """Real image preparation, scripted model; no inference or Telegram."""
    image = tmp_path / "source.png"
    Image.new("RGB", (100, 120), "white").save(image)
    profile = ExtractionProfile(id="profile", owner="1", version=1, name="Synthetic",
                                description="Synthetic test", original_instruction="Read identifier",
                                fields=(ScalarField(id="identifier", label="Identifier", type="text",
                                                    description="Printed identifier"),))
    output = {"fields": {"identifier": {"s": "extracted", "v": "SYNTHETIC-1", "p": [1]}},
              "lists": {}, "membership": {"1": "yes"}}

    class Adapter:
        def __init__(self):
            self.messages, self.count_messages, self.calls = [], [], 0

        async def count_input_tokens(self, messages, schema, **kwargs):
            self.count_messages.append((messages, schema))
            return 500

        async def generate(self, messages, schema, **kwargs):
            self.messages.append((messages, schema))
            self.calls += 1
            text = "invalid-json" if self.calls == 1 else json.dumps(output)
            tokens = tuple(TokenScore(c.encode(), math.log(0.99)) for c in text)
            return ModelReply(text, tokens, True, 500, len(tokens), 0.001)

    config = CoreSettings(runtime=RuntimeProfile(), verification=VerificationPolicy(check_alternate_view=True),
                          matching_margin=0.1, compute_alternate_view=True)
    plain_adapter, scheduled_adapter = Adapter(), Adapter()
    plain_scratch, scheduled_scratch = tmp_path / "plain", tmp_path / "scheduled"
    plain_scratch.mkdir()
    scheduled_scratch.mkdir()
    plain = await RecognitionCore(plain_adapter, config).recognize(
        (image,), (profile,), scratch=plain_scratch, selected_profile=profile)
    scheduler = GpuScheduler()
    scheduled = await ScheduledRecognitionCore(scheduled_adapter, config, scheduler=scheduler,
                                               job_id="job").recognize(
        (image,), (profile,), scratch=scheduled_scratch, selected_profile=profile)
    assert plain.recognition == scheduled.recognition
    assert plain.matching == scheduled.matching and plain.user_selected == scheduled.user_selected
    assert plain_adapter.messages == scheduled_adapter.messages
    assert plain_adapter.count_messages == scheduled_adapter.count_messages
    assert scheduled_adapter.calls == 3
    assert not list(plain_scratch.iterdir()) and not list(scheduled_scratch.iterdir())
    assert image.exists()
    await scheduler.close()
