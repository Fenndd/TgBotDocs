"""Single runtime-call scheduler and a seam around the frozen recognition core.

The core's original turn covers a whole batch, including retries and V2. This
subclass replaces that turn with a no-op and schedules each adapter call instead.
Queue time advances the active ProcessingBudget start, so only actual work is
charged. Neither prompts, verification policy nor recognition results change.
"""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
from contextlib import asynccontextmanager
from contextvars import ContextVar
from dataclasses import dataclass, replace
import math
from typing import Any

from tgbotdocs.recognition.adapter import ModelError
from tgbotdocs.recognition.core import RecognitionCore


@dataclass(eq=False)
class _Request:
    job_id: str
    operation: Callable[[], Awaitable[Any]]
    interactive: bool
    order: int
    started: asyncio.Future
    result: asyncio.Future
    budget: Any = None
    begin: float = 0.0
    cancelled: bool = False
    task: asyncio.Task | None = None
    uncharged: bool = False

    def exclude_wait(self):
        if not self.uncharged:
            if self.budget is not None and self.budget._start is not None:
                self.budget._start += asyncio.get_running_loop().time() - self.begin
            self.uncharged = True


async def _drain(task):
    while not task.done():
        try:
            await asyncio.shield(task)
        except asyncio.CancelledError:
            continue
        except Exception:
            break
    if not task.cancelled():
        task.exception()


class GpuScheduler:
    """Interactive FIFO first; documents rotate by stable admission order.

    Operations are factories, so cancellation of a queued request cannot start
    HTTP work. A running operation is drained before any next request starts;
    ModelAdapter owns slot-release/restart confirmation during that drain.
    """

    def __init__(self, queue_timeout_s: float = 900):
        if not math.isfinite(queue_timeout_s) or queue_timeout_s <= 0:
            raise ValueError("invalid_queue_timeout")
        self.queue_timeout_s = queue_timeout_s
        self._pending: list[_Request] = []
        self._orders: dict[str, int] = {}
        self._last_order: int | None = None
        self._driver: asyncio.Task | None = None
        self._active: _Request | None = None
        self._closed = False
        self._cancelled_jobs: set[str] = set()

    async def run(self, job_id, operation, *, interactive=False, admission_order=None, budget=None):
        if self._closed:
            raise ModelError("scheduler_closed")
        if job_id in self._cancelled_jobs:
            raise asyncio.CancelledError
        if not isinstance(job_id, str) or not job_id:
            raise ValueError("invalid_job_id")
        if admission_order is not None and (type(admission_order) is not int or admission_order < 0):
            raise ValueError("invalid_admission_order")
        order = self._orders.setdefault(job_id, admission_order if admission_order is not None
                                        else max(self._orders.values(), default=-1) + 1)
        loop = asyncio.get_running_loop()
        request = _Request(job_id, operation, interactive, order, loop.create_future(),
                           loop.create_future(), budget, loop.time())
        self._pending.append(request)
        if self._driver is None or self._driver.done():
            self._driver = asyncio.create_task(self._dispatch())
        try:
            try:
                async with asyncio.timeout(self.queue_timeout_s):
                    await asyncio.shield(request.started)
            except TimeoutError:
                self._cancel_request(request)
                raise ModelError("queue_wait_expired") from None
            return await asyncio.shield(request.result)
        except asyncio.CancelledError:
            self._cancel_request(request)
            if request.task is not None:
                await _drain(request.task)
            raise
        finally:
            # Retrieve a completion racing cancellation to prevent noisy logs.
            if request.result.done() and not request.result.cancelled():
                request.result.exception()

    def _cancel_request(self, request):
        if request.cancelled:
            return
        request.cancelled = True
        if request.task is not None:
            request.task.cancel()
        else:
            request.exclude_wait()
        if not request.started.done():
            request.started.cancel()
        if not request.result.done():
            request.result.cancel()

    async def cancel(self, job_id):
        """Invalidate this job ID permanently and drain its active call."""
        self._cancelled_jobs.add(job_id)
        for request in self._pending:
            if request.job_id == job_id:
                self._cancel_request(request)
        if self._active is not None and self._active.job_id == job_id:
            self._cancel_request(self._active)
            if self._active.task is not None:
                await _drain(self._active.task)

    def forget(self, job_id):
        """Release terminal metadata; call only after all job operations drained."""
        if any(r.job_id == job_id and not r.cancelled for r in self._pending) or (
            self._active is not None and self._active.job_id == job_id
        ):
            raise RuntimeError("job_still_scheduled")
        self._orders.pop(job_id, None)
        self._cancelled_jobs.discard(job_id)

    async def _dispatch(self):
        while True:
            self._pending = [r for r in self._pending if not r.cancelled]
            if not self._pending:
                return
            interactive = next((r for r in self._pending if r.interactive), None)
            if interactive is None:
                ordered = sorted(self._pending, key=lambda r: r.order)
                request = next((r for r in ordered if self._last_order is None
                                or r.order > self._last_order), ordered[0])
                self._last_order = request.order
            else:
                request = interactive
            self._pending.remove(request)
            if asyncio.get_running_loop().time() - request.begin >= self.queue_timeout_s:
                request.exclude_wait()
                request.started.set_result(None)
                request.result.set_exception(ModelError("queue_wait_expired"))
                continue
            self._active = request
            request.exclude_wait()
            request.started.set_result(None)
            try:
                request.task = asyncio.create_task(request.operation())
                result = await request.task
                if not request.result.done():
                    request.result.set_result(result)
            except asyncio.CancelledError:
                if not request.result.done():
                    request.result.cancel()
            except Exception as error:
                if not request.result.done():
                    request.result.set_exception(error)
            finally:
                self._active = None
            # Let the completed caller enqueue its next call before selection.
            await asyncio.sleep(0)

    async def close(self):
        self._closed = True
        for request in self._pending:
            self._cancel_request(request)
        if self._active is not None:
            self._cancel_request(self._active)
        if self._driver is not None:
            await _drain(self._driver)


class _ScheduledAdapter:
    def __init__(self, adapter, scheduler, job_id, admission_order, budget, waited, started=None):
        self.adapter, self.scheduler = adapter, scheduler
        self.job_id, self.admission_order, self.budget = job_id, admission_order, budget
        self.waited, self.started = waited, started

    def __getattr__(self, name):
        return getattr(self.adapter, name)

    async def _invoke(self, name, args, kwargs):
        budget = self.budget.get()
        loop = asyncio.get_running_loop()
        queued_at, began = loop.time(), None

        async def operation():
            nonlocal began
            began = loop.time()
            if self.started is not None:
                self.started()
            if budget is not None:
                kwargs["remaining_budget_s"] = budget.remaining
            return await getattr(self.adapter, name)(*args, **kwargs)

        try:
            return await self.scheduler.run(self.job_id, operation, admission_order=self.admission_order,
                                            budget=budget)
        finally:
            # Reported before the core appends this call's record, in call order.
            self.waited((loop.time() if began is None else began) - queued_at)

    async def generate(self, *args, **kwargs):
        return await self._invoke("generate", args, kwargs)

    async def count_input_tokens(self, *args, **kwargs):
        return await self._invoke("count_input_tokens", args, kwargs)


@asynccontextmanager
async def _unlocked_turn():
    yield


class _BatchLedger:
    """Receives the core's batch traces and removes GPU queue wait from their times.

    The frozen core measures an alternate view with the wall clock, so a turn given
    to another job between the primary and the alternate call would be charged to
    this job. ``block`` is the budget's charged time of the whole batch, which the
    scheduler already keeps free of queue wait.
    """

    def __init__(self, target, budget, alternate_waits):
        self.target, self.budget, self.alternate_waits = target, budget, alternate_waits
        self.mark = budget.used

    def append(self, trace):
        block, self.mark = self.budget.used - self.mark, self.budget.used
        wait = self.alternate_waits.pop(len(self.target), 0.0)
        alternate_s = max(0.0, trace.alternate_s - wait)
        failure = trace.alternate_error
        if failure is not None:
            failure = replace(failure, phase_s=alternate_s)
        self.target.append(replace(trace, primary_s=max(0.0, block - alternate_s), alternate_s=alternate_s,
                                   alternate_error=failure))


class ScheduledRecognitionCore(RecognitionCore):
    """One instance per job phase; unchanged core work with scheduled adapter calls.

    The private override signatures and budget accounting are deliberately small
    compatibility seams. Regression tests cover them; repeat those checks when
    the frozen core changes. Calls queued during rendering do not charge wait, and
    queue wait is removed from every recorded call and batch duration.
    """

    def __init__(self, adapter, settings, *, scheduler, job_id, admission_order=None, started=None):
        self._budget = ContextVar("recognition_budget", default=None)
        self._waits: list[float] = []
        self._alternate_waits: dict[int, float] = {}
        self._charged = None
        self.waited_s = 0.0
        proxy = _ScheduledAdapter(adapter, scheduler, job_id, admission_order, self._budget, self._waited,
                                  started)
        super().__init__(proxy, settings, turn=_unlocked_turn)

    def _waited(self, seconds):
        self._waits.append(seconds)
        self.waited_s += seconds

    def charged_s(self, elapsed_s):
        """The job's own processing time of this phase, even after cancellation."""
        if self._charged is not None:
            return self._charged.used
        return max(0.0, elapsed_s - self.waited_s)

    def _exclude_waits(self, job, records, waits):
        calls, new = job.observer.calls, self._waits[waits:]
        for offset, index in enumerate(range(records, len(calls))):
            if offset < len(new):
                record = calls[index]
                calls[index] = record.model_copy(update={"duration_s": max(0.0, record.duration_s - new[offset])})

    async def _count(self, job, *args, **kwargs):
        self._charged = job.budget
        token = self._budget.set(job.budget)
        records, waits = len(job.observer.calls), len(self._waits)
        try:
            return await super()._count(job, *args, **kwargs)
        finally:
            self._budget.reset(token)
            self._exclude_waits(job, records, waits)

    async def _call(self, job, *args, **kwargs):
        self._charged = job.budget
        token = self._budget.set(job.budget)
        records, waits = len(job.observer.calls), len(self._waits)
        try:
            return await super()._call(job, *args, **kwargs)
        finally:
            self._budget.reset(token)
            self._exclude_waits(job, records, waits)

    async def _alternate(self, job, document, pages, text_for, schema_for, parse, index):
        before = self.waited_s
        try:
            return await super()._alternate(job, document, pages, text_for, schema_for, parse, index)
        finally:
            self._alternate_waits[index] = self._alternate_waits.get(index, 0.0) + self.waited_s - before

    async def _extract(self, job, document, profile, batches):
        await super()._extract(job, document, profile, _BatchLedger(batches, job.budget, self._alternate_waits))
