"""Production recognition orchestration, independent of Telegram and persistence.

All images, candidates and token evidence remain job-scoped. The caller owns
originals, a private scratch root and scheduling. Queue wait is outside the
processing budget; preparation, matching, extraction and verification are inside.
"""

from __future__ import annotations

import asyncio
from contextlib import AsyncExitStack, asynccontextmanager, contextmanager
from dataclasses import dataclass, field
import hashlib
import math
from pathlib import Path
from typing import Callable

from .adapter import ModelAdapter, ModelError, ModelReply
from .contracts import (
    BatchResult,
    ExtractionProfile,
    ListResult,
    MatchingResponse,
    RecognitionResult,
    resolve_matching,
    validate_batch,
)
from .merge import MixedDocumentError, merge_batches
from .preparation import PreparationLimits, inspect_document, render_batch
from . import prompts
from .runtime import RuntimeProfile
from .verification import VerificationPolicy, verify_field, verify_matching


@dataclass(frozen=True)
class CoreSettings:
    runtime: RuntimeProfile
    verification: VerificationPolicy
    matching_margin: float
    processing_budget_s: float = 1800.0
    image_long_side: int = 2560
    matching_long_side: int = 1280
    preparation: PreparationLimits = PreparationLimits()

    def __post_init__(self):
        if not math.isfinite(self.matching_margin) or not 0 <= self.matching_margin <= 1:
            raise ValueError("An explicit finite matching margin is required")
        if not math.isfinite(self.processing_budget_s) or self.processing_budget_s <= 0:
            raise ValueError("A positive processing budget is required")
        if any(type(x) is not int or x <= 0 for x in (self.image_long_side, self.matching_long_side)):
            raise ValueError("Invalid image resolution")


@dataclass(frozen=True, repr=False)
class CoreResult:
    matching: MatchingResponse
    profile: ExtractionProfile | None
    recognition: RecognitionResult | None
    user_selected: bool
    metrics: dict = field(default_factory=dict)


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


def verify_batch(
    batch: BatchResult,
    reply: ModelReply,
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
            raw_token_probabilities=reply.probabilities(("fields", f.field_id, "v")),
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
                    raw_token_probabilities=reply.probabilities(
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


class RecognitionCore:
    def __init__(self, adapter: ModelAdapter, settings: CoreSettings, *, turn: Callable | None = None):
        self.adapter, self.settings = adapter, settings
        self._turn_lock = asyncio.Lock()
        self.turn = turn or self._local_turn

    @asynccontextmanager
    async def _local_turn(self):
        async with self._turn_lock:
            yield

    async def _count(self, text, pages, schema, budget, *, retry=True):
        # Reserve the clarified-contract retry prompt too; a later retry must not
        # silently eat the output budget of a previously admitted batch.
        return await self.adapter.count_input_tokens(
            prompts.messages(text, pages, retry=retry),
            schema,
            output_tokens=self.settings.runtime.output_tokens,
            remaining_budget_s=budget.remaining,
        )

    @asynccontextmanager
    async def _batch(self, document, start, text_for, schema_for, scratch, budget, *, matching=False):
        """Greedily pack consecutive pages using the runtime's exact token count.

        Only the current batch and one lookahead page are rendered. A rejected
        lookahead is removed immediately; accepted renders survive through V2.
        """
        async with AsyncExitStack() as stack:
            pages = []
            for info in document.pages[start:]:
                candidate_context = render_batch(
                    document,
                    (info.page_id,),
                    self.settings.runtime.pdf_dpi,
                    self.settings.matching_long_side if matching else self.settings.image_long_side,
                    scratch=scratch,
                    timeout_s=budget.remaining,
                )
                prepared = await candidate_context.__aenter__()
                candidate = tuple(pages) + prepared
                ids = tuple(p.page_id for p in candidate)
                try:
                    count = await self._count(text_for(ids), candidate, schema_for(ids), budget)
                except BaseException:
                    await candidate_context.__aexit__(None, None, None)
                    raise
                if count + self.settings.runtime.output_tokens > self.settings.runtime.context_tokens:
                    await candidate_context.__aexit__(None, None, None)
                    if not pages:
                        raise ModelError("profile_or_page_exceeds_context")
                    break
                stack.push_async_exit(candidate_context)
                pages.extend(prepared)
            if not pages:
                raise ModelError("empty_document")
            yield tuple(pages)

    async def _call(self, text, pages, schema, parse, budget, metrics):
        for attempt in range(2):
            reply = await self.adapter.generate(
                prompts.messages(text, pages, retry=bool(attempt)),
                schema,
                output_tokens=self.settings.runtime.output_tokens,
                remaining_budget_s=budget.remaining,
            )
            metrics["model_calls"] += 1
            if (
                reply.prompt_tokens is not None
                and reply.prompt_tokens + self.settings.runtime.output_tokens
                > self.settings.runtime.context_tokens
            ):
                raise ModelError("runtime_context_accounting_mismatch")
            try:
                return parse(reply.text), reply
            except ValueError, TypeError, KeyError:
                if attempt:
                    raise ModelError("recognition_contract_violation") from None
                metrics["contract_retries"] += 1
        raise AssertionError("unreachable")

    async def recognize(
        self,
        files: tuple[Path, ...],
        snapshots: tuple[ExtractionProfile, ...],
        *,
        scratch: Path,
        selected_profile: ExtractionProfile | None = None,
    ) -> CoreResult:
        # Validate ownership and uniqueness even when the model refuses or the
        # caller manually selects a profile. No later database fetch is involved.
        resolve_matching(MatchingResponse(status="uncertain"), snapshots)
        if selected_profile is not None and selected_profile not in snapshots:
            raise ValueError("manual choice must be one immutable supplied snapshot")
        budget = ProcessingBudget(self.settings.processing_budget_s)
        metrics = {"model_calls": 0, "contract_retries": 0, "pages": 0, "batches": 0}
        with budget.charge():
            document = await inspect_document(files, scratch, self.settings.preparation, budget.remaining)
        metrics["pages"] = len(document.pages)
        if selected_profile is None:
            async with self.turn():
                with budget.charge():

                    def text_for(ids):
                        return prompts.matching_text(snapshots, ids)

                    def schema_for(_):
                        return prompts.matching_schema(len(snapshots))

                    async with self._batch(
                        document, 0, text_for, schema_for, scratch, budget, matching=True
                    ) as pages:
                        ids = tuple(p.page_id for p in pages)
                        matching, reply = await self._call(
                            text_for(ids),
                            pages,
                            schema_for(ids),
                            lambda text: prompts.parse_matching(text, snapshots),
                            budget,
                            metrics,
                        )
                        matching = verify_matching(
                            matching,
                            snapshots,
                            candidate_probabilities=reply.candidate_probabilities(
                                ("profile_index",), len(snapshots)
                            ),
                            minimum_margin=self.settings.matching_margin,
                        )
            profile = resolve_matching(matching, snapshots)
            if profile is None:
                metrics["processing_s"] = budget.used
                return CoreResult(matching, None, None, False, metrics)
        else:
            profile = selected_profile
            matching = MatchingResponse(status="matched", profile_index=snapshots.index(profile) + 1)
        batches, previous, start = [], {}, 0
        while start < len(document.pages):
            async with self.turn():
                with budget.charge():

                    def text_for(ids, boundary=previous):
                        return prompts.extraction_text(profile, ids, boundary)

                    def schema_for(ids):
                        return prompts.extraction_schema(profile, ids)

                    async with self._batch(document, start, text_for, schema_for, scratch, budget) as pages:
                        ids = tuple(p.page_id for p in pages)

                        def parse(text, batch_ids=ids):
                            return prompts.parse_batch(text, profile, batch_ids)

                        batch, reply = await self._call(
                            text_for(ids), pages, schema_for(ids), parse, budget, metrics
                        )
                        if any(p.status == "no" for p in batch.page_membership):
                            metrics["processing_s"] = budget.used + (
                                self.settings.processing_budget_s - budget.used - budget.remaining
                            )
                            return CoreResult(
                                MatchingResponse(status="mixed"),
                                None,
                                None,
                                selected_profile is not None,
                                metrics,
                            )
                        alternate = None
                        if self.settings.verification.check_alternate_view:
                            # T01a did not validate tight field localization. Read
                            # whole pages at a genuinely different resolution.
                            long_side = max(1, int(min(max(p.width, p.height) for p in pages) * 0.75))
                            async with render_batch(
                                document,
                                ids,
                                self.settings.runtime.alternative_pdf_dpi,
                                long_side,
                                scratch=scratch,
                                timeout_s=budget.remaining,
                            ) as other:
                                different = all(
                                    hashlib.sha256(p.path.read_bytes()).digest()
                                    != hashlib.sha256(q.path.read_bytes()).digest()
                                    for p, q in zip(pages, other, strict=True)
                                )
                                if different:
                                    count = await self._count(text_for(ids), other, schema_for(ids), budget)
                                    if (
                                        count + self.settings.runtime.output_tokens
                                        <= self.settings.runtime.context_tokens
                                    ):
                                        alternate, _ = await self._call(
                                            text_for(ids), other, schema_for(ids), parse, budget, metrics
                                        )
                                        if any(p.status == "no" for p in alternate.page_membership):
                                            return CoreResult(
                                                MatchingResponse(status="mixed"),
                                                None,
                                                None,
                                                selected_profile is not None,
                                                metrics,
                                            )
                        batches.append(
                            verify_batch(batch, reply, profile, self.settings.verification, alternate)
                        )
                        metrics["batches"] += 1
                        previous = {
                            r.field_id: r.rows[-1].model_dump(mode="json")
                            for r in batches[-1].lists
                            if r.rows and r.rows[-1].continues_next
                        }
                        start += len(pages)
        with budget.charge():
            _ = budget.remaining
            try:
                result = merge_batches(
                    profile, tuple(batches), tuple(p.page_id for p in document.pages), traversal_complete=True
                )
            except MixedDocumentError:
                return CoreResult(
                    MatchingResponse(status="mixed"), None, None, selected_profile is not None, metrics
                )
        metrics["processing_s"] = budget.used
        return CoreResult(matching, profile, result, selected_profile is not None, metrics)
