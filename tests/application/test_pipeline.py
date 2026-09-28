"""T05 application seams around the frozen core: budget, queue wait and render quota."""

import asyncio
import json
import math
from types import SimpleNamespace

import pytest
from PIL import Image

from tgbotdocs.application.lifecycle import LifecycleError, TemporaryLifecycle
from tgbotdocs.application.pipeline import RecognitionService, render_reservation
from tgbotdocs.application.scheduler import GpuScheduler, ScheduledRecognitionCore
from tgbotdocs.recognition.adapter import ModelReply, TokenScore
from tgbotdocs.recognition.contracts import ExtractionProfile, ScalarField
from tgbotdocs.recognition.core import CoreSettings
from tgbotdocs.recognition.preparation import PageInfo
from tgbotdocs.recognition.runtime import RuntimeProfile
from tgbotdocs.recognition.verification import VerificationPolicy

PROFILE = ExtractionProfile(id="profile", owner="1", version=1, name="Synthetic", description="Synthetic test",
                            original_instruction="Read identifier", fields=(ScalarField(
                                id="identifier", label="Identifier", type="text", description="Printed identifier"),))
OUTPUT = {"fields": {"identifier": {"s": "extracted", "v": "SYNTHETIC-1", "p": [1]}},
          "lists": {}, "membership": {"1": "yes"}}


def reply(text):
    tokens = tuple(TokenScore(c.encode(), math.log(0.99)) for c in text)
    return ModelReply(text, tokens, True, 500, len(tokens), 0.001)


def settings(**kwargs):
    values = dict(runtime=RuntimeProfile(), verification=VerificationPolicy(check_alternate_view=True),
                  matching_margin=0.1, compute_alternate_view=True)
    values.update(kwargs)
    return CoreSettings(**values)


async def owned_job(tmp_path, **limits):
    lifecycle = TemporaryLifecycle(tmp_path / "owned", free_reserve_bytes=0, **limits)
    assert await lifecycle.initialize()
    job = lifecycle.create_job("job")
    image = job / "original"
    Image.new("RGB", (100, 120), "white").save(image, format="PNG")
    page = PageInfo(page_id=1, file_index=0, file_page_index=0, kind="png", width=100, height=120)
    return lifecycle, job, image, (page,)


async def test_queue_wait_is_removed_from_call_records_and_alternate_times(tmp_path):
    """Another job's call between the primary and the alternate view is not charged."""
    scheduler = GpuScheduler()
    image = tmp_path / "source.png"
    Image.new("RGB", (100, 120), "white").save(image)
    (tmp_path / "scratch").mkdir()
    blocker_s = 1.5
    blocked = []

    class Adapter:
        calls = 0

        async def count_input_tokens(self, *args, **kwargs):
            return 500

        async def generate(self, *args, **kwargs):
            self.calls += 1
            if self.calls == 1:
                # The primary call is done; an interactive compile now takes the GPU.
                async def other():
                    await asyncio.sleep(blocker_s)
                blocked.append(asyncio.create_task(scheduler.run("compile", other, interactive=True)))
                await asyncio.sleep(0)
            return reply(json.dumps(OUTPUT))

    core = ScheduledRecognitionCore(Adapter(), settings(keep_trace=True), scheduler=scheduler, job_id="job")
    result = await core.recognize((image,), (PROFILE,), scratch=tmp_path / "scratch", selected_profile=PROFILE)
    await asyncio.gather(*blocked)
    trace = result.trace
    assert result.recognition.outcome == "complete"
    # The alternate render overlaps the other call; the rest of it is queue wait.
    wait = core.waited_s
    assert wait > 0.5
    (batch,) = trace.batches
    assert batch.alternate_attempted and batch.alternate_s < wait
    assert all(call.duration_s < wait for call in trace.calls)
    # The phases add up to the budget's charged time, which excludes the wait.
    assert trace.setup_s + batch.primary_s + batch.alternate_s == pytest.approx(trace.processing_s, abs=1e-6)
    assert core.charged_s(10.0) == trace.processing_s
    await scheduler.close()


async def test_phase_charges_time_after_cancellation_and_releases_resources(tmp_path):
    lifecycle, job, image, pages = await owned_job(tmp_path)
    scheduler = GpuScheduler()
    started = asyncio.Event()
    charged, begun = [], []

    class Adapter:
        async def count_input_tokens(self, *args, **kwargs):
            return 500

        async def generate(self, *args, **kwargs):
            started.set()
            await asyncio.Event().wait()

    service = RecognitionService(Adapter(), scheduler, settings(), lifecycle)
    task = asyncio.create_task(service.run(key="job-1", admission_order=0, files=(image,), pages=pages,
        scratch=job, snapshots=(PROFILE,), remaining_s=60, charge=charged.append,
        selected_profile=PROFILE, started=lambda: begun.append(True)))
    await started.wait()
    assert lifecycle._reserved
    await asyncio.sleep(0.05)
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    assert len(charged) == 1 and charged[0] >= 0.05
    assert begun and not lifecycle._reserved and "job-1" not in scheduler._orders
    assert not [p for p in job.iterdir() if p.name.startswith("prep-")]
    await scheduler.close()


async def test_phase_continues_remaining_budget_and_reports_fixed_codes(tmp_path):
    lifecycle, job, image, pages = await owned_job(tmp_path)
    scheduler = GpuScheduler()
    charged = []

    class Slow:
        async def count_input_tokens(self, *args, **kwargs):
            return 500

        async def generate(self, *args, remaining_budget_s, **kwargs):
            await asyncio.sleep(remaining_budget_s + 0.05)
            return reply(json.dumps(OUTPUT))

    service = RecognitionService(Slow(), scheduler, settings(), lifecycle)
    common = dict(files=(image,), pages=pages, scratch=job, snapshots=(PROFILE,), charge=charged.append,
                  selected_profile=PROFILE)
    none = await service.run(key="none", admission_order=0, remaining_s=0, **common)
    assert none.error == "processing_budget_exhausted" and charged == [0.0]
    # A second phase receives only the remainder of the job's budget.
    short = await service.run(key="short", admission_order=0, remaining_s=0.4, **common)
    assert short.error == "processing_budget_exhausted" and 0 < charged[-1] <= 0.4 + 0.2

    class Fast(Slow):
        async def generate(self, *args, **kwargs):
            return reply(json.dumps(OUTPUT))

    done = await RecognitionService(Fast(), scheduler, settings(), lifecycle).run(
        key="fast", admission_order=0, remaining_s=60, **common)
    assert done.result.recognition.outcome == "complete" and done.result.user_selected
    assert not lifecycle._reserved
    await scheduler.close()


async def test_render_reservation_is_document_aware_and_bounded(tmp_path):
    runtime = RuntimeProfile()
    config = settings()
    photo = PageInfo(page_id=1, file_index=0, file_page_index=0, kind="jpeg", width=4000, height=3000)
    single = render_reservation((photo,), config)
    primary = 2560 * 1920 * 5 + 65536
    alternate = (1920 + 1) * (1440 + 1) * 5 + 65536
    assert single == primary + alternate + primary
    many = tuple(PageInfo(page_id=i, file_index=0, file_page_index=i - 1, kind="pdf", width=595, height=842)
                 for i in range(1, 201))
    large = render_reservation(many, config)
    # Bounded by the prompt's image tokens, not by the page count.
    prompt = runtime.context_tokens - runtime.output_tokens
    assert large < (prompt // runtime.image_max_tokens + 2) * 2 * primary
    assert large == render_reservation(many[:20], config)
    without_alternate = render_reservation((photo,), settings(verification=VerificationPolicy(),
                                                              compute_alternate_view=False))
    assert without_alternate == 2 * primary
    with pytest.raises(ValueError):
        render_reservation((), config)


async def test_reservations_count_against_downloads_and_fail_explicitly(tmp_path):
    lifecycle, job, image, pages = await owned_job(tmp_path, quota_bytes=10 * 1024**2)
    used = lifecycle.job_usage(job)
    assert used >= image.stat().st_size
    with lifecycle.reserve(8 * 1024**2):
        with pytest.raises(LifecycleError, match="storage_limit"):
            lifecycle.check_capacity(2 * 1024**2)
        with pytest.raises(LifecycleError, match="storage_limit"):
            with lifecycle.reserve(2 * 1024**2):
                pass
    lifecycle.check_capacity(2 * 1024**2)
    scheduler = GpuScheduler()
    charged = []
    outcome = await RecognitionService(SimpleNamespace(), scheduler, settings(), lifecycle).run(
        key="big", admission_order=0, files=(image,), pages=(PageInfo(
            page_id=1, file_index=0, file_page_index=0, kind="png", width=5000, height=5000),),
        scratch=job, snapshots=(PROFILE,), remaining_s=60, charge=charged.append, selected_profile=PROFILE)
    assert outcome.error == "storage_limit" and charged == [0.0] and not lifecycle._reserved
    await scheduler.close()
