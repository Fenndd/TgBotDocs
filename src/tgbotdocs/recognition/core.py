"""Production recognition orchestration, independent of Telegram and persistence.

All images, candidates and token evidence remain job-scoped. The caller owns
originals, a private scratch root and scheduling. Queue wait is outside the
processing budget; preparation, matching, extraction and verification are inside.

Every model call is independent of the verification policy: the list continuation
context comes from parsed, pre-verification rows, alternate readings depend only on
``compute_alternate_view``, and the matching call is always made unless the user
chose a profile. A job therefore records one ``JobTrace`` and ``decide`` derives the
production decision from it. ``recognize`` returns ``decide`` with the configured
policy, so calibration replay and production share one decision path.
"""

from __future__ import annotations

import asyncio
from contextlib import AsyncExitStack, asynccontextmanager, contextmanager
from dataclasses import dataclass, field, replace
import hashlib
import math
from pathlib import Path
from typing import Callable, Literal, Mapping

from pydantic import Field, StrictFloat, StrictInt, model_validator

from .adapter import ModelAdapter, ModelError, ModelReply
from .contracts import (
    BatchResult,
    ContractModel,
    ExtractionProfile,
    ListResult,
    MatchingResponse,
    RecognitionResult,
    resolve_matching,
    validate_batch,
)
from .merge import MixedDocumentError, merge_batches
from .preparation import PreparationLimits, PreparedDocument, inspect_document, render_batch
from . import prompts
from .runtime import RuntimeProfile
from .verification import VerificationPolicy, verify_field, verify_matching

Pointer = tuple[str | int, ...]
CALL_KINDS = ("token_count", "matching", "extraction", "alternate")


@dataclass(frozen=True)
class CoreSettings:
    runtime: RuntimeProfile
    verification: VerificationPolicy
    matching_margin: float
    processing_budget_s: float = 1800.0
    image_long_side: int = 2560
    matching_long_side: int = 1280
    preparation: PreparationLimits = PreparationLimits()
    # Alternate (V2) readings are a model-call setting, separate from the policy
    # that decides whether they are enforced; enforcing requires computing them.
    compute_alternate_view: bool = False
    # A trace holds job-scoped candidates and evidence; keep it only for replay.
    keep_trace: bool = False

    def __post_init__(self):
        if not math.isfinite(self.matching_margin) or not 0 <= self.matching_margin <= 1:
            raise ValueError("An explicit finite matching margin is required")
        if not math.isfinite(self.processing_budget_s) or self.processing_budget_s <= 0:
            raise ValueError("A positive processing budget is required")
        if any(type(x) is not int or x <= 0 for x in (self.image_long_side, self.matching_long_side)):
            raise ValueError("Invalid image resolution")
        if type(self.compute_alternate_view) is not bool or type(self.keep_trace) is not bool:
            raise ValueError("Invalid trace settings")
        if self.verification.check_alternate_view and not self.compute_alternate_view:
            raise ValueError("The alternate-view signal requires computing alternate readings")


class CallRecord(ContractModel):
    """Content-free timing of one runtime request: never prompts, images or text.

    ``stage`` names the phase a token count belongs to; ``batch`` is the zero-based
    extraction batch index (None during matching). Pages are page IDs.
    """

    kind: Literal["token_count", "matching", "extraction", "alternate"]
    stage: Literal["matching", "extraction", "alternate"]
    batch: StrictInt | None = Field(default=None, ge=0)
    duration_s: StrictFloat = Field(ge=0, allow_inf_nan=False)
    prompt_tokens: StrictInt | None = Field(default=None, ge=0)
    generated_tokens: StrictInt | None = Field(default=None, ge=0)
    pages: tuple[StrictInt, ...] = Field(min_length=1)

    @model_validator(mode="after")
    def consistent_stage(self):
        if self.kind != "token_count" and self.kind != self.stage:
            raise ValueError("call_stage_mismatch")
        if (self.stage == "matching") != (self.batch is None):
            raise ValueError("call_batch_mismatch")
        return self


@dataclass(repr=False)
class JobObserver:
    """Mutable, content-free progress of one job; it survives a failed job for reports."""

    calls: list[CallRecord] = field(default_factory=list)
    page_kinds: tuple[str, ...] = ()
    preparation_s: float = 0.0
    alternate_preparation_s: float = 0.0
    contract_retries: int = 0


@dataclass(frozen=True, repr=False)
class BatchTrace:
    """Parsed primary batch before verification, its raw V1 evidence and alternate."""

    batch: BatchResult
    probabilities: Mapping[Pointer, tuple[float, ...] | None]
    alternate: BatchResult | None
    alternate_attempted: bool


@dataclass(frozen=True, repr=False)
class JobTrace:
    """Internal job data. Never serialize: batches and matching hold document content."""

    page_ids: tuple[int, ...]
    page_kinds: tuple[str, ...]
    matching: MatchingResponse | None
    candidate_probabilities: tuple[float, ...] | None
    manual_profile: ExtractionProfile | None
    batches: tuple[BatchTrace, ...]
    calls: tuple[CallRecord, ...]
    preparation_s: float
    alternate_preparation_s: float = 0.0
    contract_retries: int = 0
    processing_s: float = 0.0


@dataclass(frozen=True, repr=False)
class CoreResult:
    matching: MatchingResponse
    profile: ExtractionProfile | None
    recognition: RecognitionResult | None
    user_selected: bool
    metrics: dict = field(default_factory=dict)
    calls: tuple[CallRecord, ...] = ()
    trace: JobTrace | None = None


class ProcessingBudget:
    def __init__(self, seconds: float):
        self.seconds, self.used = seconds, 0.0
        self._start = None

    @property
    def remaining(self):
        active = 0 if self._start is None else asyncio.get_running_loop().time() - self._start
        remaining = self.seconds - self.used - active
        if remaining <= 0:
            raise ModelError("processing_budget_exhausted")
        return remaining

    @contextmanager
    def charge(self):
        if self._start is not None:
            raise RuntimeError("nested budget accounting")
        self._start = asyncio.get_running_loop().time()
        try:
            yield
        finally:
            self.used += asyncio.get_running_loop().time() - self._start
            self._start = None


def _list_with_cells(result: ListResult, rows, *, enumeration_complete: bool) -> ListResult:
    accepted = any(c.status == "extracted" for r in rows for c in r.cells)
    resolved = all(c.status in ("extracted", "missing") for r in rows for c in r.cells)
    if enumeration_complete and resolved and result.status == "complete":
        status, reason = "complete", None
    elif accepted:
        status, reason = "partial", None
    else:
        statuses = {c.status for row in rows for c in row.cells}
        status = "unresolved"
        reason = next((s for s in ("ambiguous", "invalid", "unreadable", "missing")
                       if s in statuses or s == result.reason), "ambiguous")
        if not enumeration_complete and reason == "missing":
            reason = "unreadable"
    return ListResult(
        field_id=result.field_id,
        status=status,
        reason=reason,
        rows=tuple(rows),
        enumeration_complete=enumeration_complete,
    )


def probability_map(reply: ModelReply, batch: BatchResult) -> dict[Pointer, tuple[float, ...] | None]:
    """Raw V1 evidence for every value pointer of a parsed batch (None when unusable)."""
    pointers = [("fields", f.field_id, "v") for f in batch.fields]
    pointers += [
        ("lists", result.field_id, "rows", index, "cells", cell.field_id, "v")
        for result in batch.lists
        for index, row in enumerate(result.rows)
        for cell in row.cells
    ]
    return {pointer: reply.probabilities(pointer) for pointer in pointers}


def verify_batch(
    batch: BatchResult,
    probabilities: Mapping[Pointer, tuple[float, ...] | None],
    profile: ExtractionProfile,
    policy: VerificationPolicy,
    alternate: BatchResult | None,
) -> BatchResult:
    specs = {f.id: f for f in profile.fields}
    other_fields = {f.field_id: f for f in alternate.fields} if alternate else {}
    def same_sources(primary, alternative):
        if alternative is not None and set(alternative.source_pages).issubset(primary.source_pages):
            return alternative
        return None
    fields = tuple(
        verify_field(
            specs[f.field_id],
            f,
            policy=policy,
            raw_token_probabilities=probabilities.get(("fields", f.field_id, "v")),
            alternate=same_sources(f, other_fields.get(f.field_id)),
        )
        for f in batch.fields
    )
    other_lists = {f.field_id: f for f in alternate.lists} if alternate else {}
    lists = []
    for result in batch.lists:
        specification = specs[result.field_id]
        alt = other_lists.get(result.field_id)
        aligned = (
            alt is not None
            and len(alt.rows) == len(result.rows)
            and all(
                a.source_pages == b.source_pages
                and a.continues_previous == b.continues_previous
                and a.continues_next == b.continues_next
                for a, b in zip(result.rows, alt.rows, strict=True)
            )
        )
        rows = []
        for index, row in enumerate(result.rows):
            alternate_cells = {c.field_id: c for c in alt.rows[index].cells} if aligned else {}
            columns = {f.id: f for f in specification.columns}
            cells = tuple(
                verify_field(
                    columns[c.field_id],
                    c,
                    policy=policy,
                    raw_token_probabilities=probabilities.get(
                        ("lists", result.field_id, "rows", index, "cells", c.field_id, "v")
                    ),
                    alternate=same_sources(c, alternate_cells.get(c.field_id)),
                )
                for c in row.cells
            )
            rows.append(row.model_copy(update={"cells": cells}))
        enumeration = result.enumeration_complete
        if policy.check_alternate_view and (
            not aligned or not alt.enumeration_complete or alt.status == "unresolved"
        ):
            enumeration = False
        lists.append(_list_with_cells(result, rows, enumeration_complete=enumeration))
    verified = BatchResult(
        page_ids=batch.page_ids, fields=fields, lists=tuple(lists), page_membership=batch.page_membership
    )
    validate_batch(verified, profile, batch.page_ids)
    return verified


def _rejects(batch: BatchResult) -> bool:
    return any(p.status == "no" for p in batch.page_membership)


def _metrics(trace: JobTrace, batches_used: int) -> dict:
    seconds = {kind: sum(c.duration_s for c in trace.calls if c.kind == kind) for kind in CALL_KINDS}
    return {
        "model_calls": sum(c.kind != "token_count" for c in trace.calls),
        "contract_retries": trace.contract_retries,
        "pages": len(trace.page_ids),
        "batches": batches_used,
        "processing_s": trace.processing_s,
        "preparation_s": trace.preparation_s,
        "alternate_preparation_s": trace.alternate_preparation_s,
        "call_seconds": seconds,
    }


def decide(
    trace: JobTrace,
    snapshots: tuple[ExtractionProfile, ...],
    *,
    policy: VerificationPolicy,
    matching_margin: float,
) -> CoreResult:
    """Pure production decision for one recorded job under a verification policy.

    Replay is exact when the trace was collected with a matching margin no higher
    than ``matching_margin``, with alternate readings computed whenever the policy
    enforces V2, and without V2 early termination when the policy does not enforce it.
    A trace that cannot support the policy raises ``ValueError`` with a fixed code.
    """
    if type(matching_margin) not in (float, int) or isinstance(matching_margin, bool) or not (
        math.isfinite(matching_margin) and 0 <= matching_margin <= 1
    ):
        raise ValueError("an explicit finite matching margin in [0, 1] is required")
    resolve_matching(MatchingResponse(status="uncertain"), snapshots)
    manual = trace.manual_profile is not None
    if manual:
        if trace.manual_profile not in snapshots:
            raise ValueError("manual choice must be one immutable supplied snapshot")
        profile = trace.manual_profile
        matching = MatchingResponse(status="matched", profile_index=snapshots.index(profile) + 1)
    else:
        if trace.matching is None:
            raise ValueError("trace_without_matching")
        matching = verify_matching(
            trace.matching,
            snapshots,
            candidate_probabilities=trace.candidate_probabilities,
            minimum_margin=matching_margin,
        )
        profile = resolve_matching(matching, snapshots)

    def result(status, selected, recognition, used):
        return CoreResult(status, selected, recognition, manual, _metrics(trace, used), trace.calls)

    if profile is None:
        return result(matching, None, None, 0)
    if not trace.batches:
        raise ValueError("trace_incomplete_for_policy")
    verified, covered = [], []
    for index, item in enumerate(trace.batches):
        if _rejects(item.batch):
            return result(MatchingResponse(status="mixed"), None, None, index + 1)
        if policy.check_alternate_view:
            if not item.alternate_attempted:
                raise ValueError("trace_lacks_alternate_view")
            if item.alternate is not None and _rejects(item.alternate):
                return result(MatchingResponse(status="mixed"), None, None, index + 1)
        verified.append(verify_batch(item.batch, item.probabilities, profile, policy, item.alternate))
        covered.extend(item.batch.page_ids)
    if tuple(covered) != trace.page_ids:
        raise ValueError("trace_incomplete_for_policy")
    try:
        recognition = merge_batches(profile, tuple(verified), trace.page_ids, traversal_complete=True)
    except MixedDocumentError:
        return result(MatchingResponse(status="mixed"), None, None, len(verified))
    return result(matching, profile, recognition, len(verified))


@dataclass(repr=False)
class _Job:
    budget: ProcessingBudget
    observer: JobObserver
    scratch: Path


class RecognitionCore:
    def __init__(self, adapter: ModelAdapter, settings: CoreSettings, *, turn: Callable | None = None):
        self.adapter, self.settings = adapter, settings
        self._turn_lock = asyncio.Lock()
        self.turn = turn or self._local_turn

    @asynccontextmanager
    async def _local_turn(self):
        async with self._turn_lock:
            yield

    async def _count(self, job, text, pages, schema, *, stage, batch, retry=True):
        # Reserve the clarified-contract retry prompt too; a later retry must not
        # silently eat the output budget of a previously admitted batch.
        begin = asyncio.get_running_loop().time()
        count = await self.adapter.count_input_tokens(
            prompts.messages(text, pages, retry=retry),
            schema,
            output_tokens=self.settings.runtime.output_tokens,
            remaining_budget_s=job.budget.remaining,
        )
        job.observer.calls.append(CallRecord(
            kind="token_count", stage=stage, batch=batch,
            duration_s=asyncio.get_running_loop().time() - begin,
            prompt_tokens=count, pages=tuple(p.page_id for p in pages),
        ))
        return count

    def _fits(self, count: int) -> bool:
        return count + self.settings.runtime.output_tokens <= self.settings.runtime.context_tokens

    @asynccontextmanager
    async def _batch(self, job, document, start, text_for, schema_for, *, stage, batch, matching=False):
        """Greedily pack consecutive pages using the runtime's exact token count.

        Only the current batch and one lookahead page are rendered. A rejected
        lookahead is removed immediately; accepted renders survive through V2.
        """
        loop = asyncio.get_running_loop()
        async with AsyncExitStack() as stack:
            pages = []
            for info in document.pages[start:]:
                candidate_context = render_batch(
                    document,
                    (info.page_id,),
                    self.settings.runtime.pdf_dpi,
                    self.settings.matching_long_side if matching else self.settings.image_long_side,
                    scratch=job.scratch,
                    timeout_s=job.budget.remaining,
                )
                begin = loop.time()
                prepared = await candidate_context.__aenter__()
                job.observer.preparation_s += loop.time() - begin
                candidate = tuple(pages) + prepared
                ids = tuple(p.page_id for p in candidate)
                try:
                    count = await self._count(
                        job, text_for(ids), candidate, schema_for(ids), stage=stage, batch=batch
                    )
                except BaseException:
                    await candidate_context.__aexit__(None, None, None)
                    raise
                if not self._fits(count):
                    await candidate_context.__aexit__(None, None, None)
                    if not pages:
                        raise ModelError("profile_or_page_exceeds_context")
                    break
                stack.push_async_exit(candidate_context)
                pages.extend(prepared)
            if not pages:
                raise ModelError("empty_document")
            yield tuple(pages)

    async def _call(self, job, text, pages, schema, parse, *, kind, batch):
        loop = asyncio.get_running_loop()
        for attempt in range(2):
            begin = loop.time()
            reply = await self.adapter.generate(
                prompts.messages(text, pages, retry=bool(attempt)),
                schema,
                output_tokens=self.settings.runtime.output_tokens,
                remaining_budget_s=job.budget.remaining,
            )
            job.observer.calls.append(CallRecord(
                kind=kind, stage=kind, batch=batch, duration_s=loop.time() - begin,
                prompt_tokens=reply.prompt_tokens, generated_tokens=reply.generated_tokens,
                pages=tuple(p.page_id for p in pages),
            ))
            if reply.prompt_tokens is not None and not self._fits(reply.prompt_tokens):
                raise ModelError("runtime_context_accounting_mismatch")
            try:
                return parse(reply.text), reply
            except ValueError, TypeError, KeyError:
                if attempt:
                    raise ModelError("recognition_contract_violation") from None
                job.observer.contract_retries += 1
        raise AssertionError("unreachable")

    async def _match(self, job, document, snapshots):
        async with self.turn():
            with job.budget.charge():

                def text_for(ids):
                    return prompts.matching_text(snapshots, ids)

                def schema_for(_):
                    return prompts.matching_schema(len(snapshots))

                async with self._batch(
                    job, document, 0, text_for, schema_for, stage="matching", batch=None, matching=True
                ) as pages:
                    ids = tuple(p.page_id for p in pages)
                    matching, reply = await self._call(
                        job,
                        text_for(ids),
                        pages,
                        schema_for(ids),
                        lambda text: prompts.parse_matching(text, snapshots),
                        kind="matching",
                        batch=None,
                    )
                    return matching, reply.candidate_probabilities(("profile_index",), len(snapshots))

    async def _alternate(self, job, document, pages, text_for, schema_for, parse, index):
        # T01a did not validate tight field localization. Read whole pages at a
        # genuinely different resolution.
        ids = tuple(p.page_id for p in pages)
        long_side = max(1, int(min(max(p.width, p.height) for p in pages) * 0.75))
        loop = asyncio.get_running_loop()
        async with AsyncExitStack() as stack:
            begin = loop.time()
            other = await stack.enter_async_context(render_batch(
                document,
                ids,
                self.settings.runtime.alternative_pdf_dpi,
                long_side,
                scratch=job.scratch,
                timeout_s=job.budget.remaining,
            ))
            job.observer.alternate_preparation_s += loop.time() - begin
            different = all(
                hashlib.sha256(p.path.read_bytes()).digest() != hashlib.sha256(q.path.read_bytes()).digest()
                for p, q in zip(pages, other, strict=True)
            )
            if not different:
                return None
            count = await self._count(job, text_for(ids), other, schema_for(ids), stage="alternate", batch=index)
            if not self._fits(count):
                return None
            alternate, _ = await self._call(
                job, text_for(ids), other, schema_for(ids), parse, kind="alternate", batch=index
            )
            return alternate

    async def _extract(self, job, document: PreparedDocument, profile, batches: list[BatchTrace]):
        previous, start, index = {}, 0, 0
        while start < len(document.pages):
            async with self.turn():
                with job.budget.charge():

                    def text_for(ids, boundary=previous):
                        return prompts.extraction_text(profile, ids, boundary)

                    def schema_for(ids):
                        return prompts.extraction_schema(profile, ids)

                    async with self._batch(
                        job, document, start, text_for, schema_for, stage="extraction", batch=index
                    ) as pages:
                        ids = tuple(p.page_id for p in pages)

                        def parse(text, batch_ids=ids):
                            return prompts.parse_batch(text, profile, batch_ids)

                        batch, reply = await self._call(
                            job, text_for(ids), pages, schema_for(ids), parse, kind="extraction", batch=index
                        )
                        stop = _rejects(batch)
                        alternate, attempted = None, False
                        if not stop and self.settings.compute_alternate_view:
                            attempted = True
                            alternate = await self._alternate(
                                job, document, pages, text_for, schema_for, parse, index
                            )
                            # Without V2 enforcement an alternate rejection is only
                            # recorded, so the trace also serves policies without V2.
                            stop = (
                                self.settings.verification.check_alternate_view
                                and alternate is not None
                                and _rejects(alternate)
                            )
                        batches.append(BatchTrace(batch, probability_map(reply, batch), alternate, attempted))
                        if stop:
                            return
                        # Continuation context comes from the parsed rows, never
                        # from policy-dependent verified rows.
                        previous = prompts.boundary_context(batch)
                        start += len(pages)
                        index += 1
        with job.budget.charge():
            _ = job.budget.remaining

    async def recognize(
        self,
        files: tuple[Path, ...],
        snapshots: tuple[ExtractionProfile, ...],
        *,
        scratch: Path,
        selected_profile: ExtractionProfile | None = None,
        observer: JobObserver | None = None,
    ) -> CoreResult:
        # Validate ownership and uniqueness even when the model refuses or the
        # caller manually selects a profile. No later database fetch is involved.
        resolve_matching(MatchingResponse(status="uncertain"), snapshots)
        if selected_profile is not None and selected_profile not in snapshots:
            raise ValueError("manual choice must be one immutable supplied snapshot")
        job = _Job(ProcessingBudget(self.settings.processing_budget_s),
                   JobObserver() if observer is None else observer, scratch)
        loop = asyncio.get_running_loop()
        with job.budget.charge():
            begin = loop.time()
            document = await inspect_document(files, scratch, self.settings.preparation, job.budget.remaining)
            job.observer.preparation_s += loop.time() - begin
        job.observer.page_kinds = tuple(p.kind for p in document.pages)
        raw, candidates, profile = None, None, selected_profile
        if selected_profile is None:
            raw, candidates = await self._match(job, document, snapshots)
            verified = verify_matching(
                raw,
                snapshots,
                candidate_probabilities=candidates,
                minimum_margin=self.settings.matching_margin,
            )
            profile = resolve_matching(verified, snapshots)
        batches: list[BatchTrace] = []
        if profile is not None:
            await self._extract(job, document, profile, batches)
        trace = JobTrace(
            page_ids=tuple(p.page_id for p in document.pages),
            page_kinds=job.observer.page_kinds,
            matching=raw,
            candidate_probabilities=candidates,
            manual_profile=selected_profile,
            batches=tuple(batches),
            calls=tuple(job.observer.calls),
            preparation_s=job.observer.preparation_s,
            alternate_preparation_s=job.observer.alternate_preparation_s,
            contract_retries=job.observer.contract_retries,
            processing_s=job.budget.used,
        )
        result = decide(
            trace, snapshots, policy=self.settings.verification, matching_margin=self.settings.matching_margin
        )
        return replace(result, trace=trace) if self.settings.keep_trace else result
