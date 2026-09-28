"""T05: the frozen recognition core applied to one phase of an admitted job.

A job may need several recognition phases: matching with extraction, then
extraction again after the user chooses or creates a profile, or a new pass after
a late album fragment. Every phase continues the job's single processing budget
(ED-003): it receives only the remaining time, and the time it charged is reported
through ``charge`` even when the phase is cancelled. Derived renders hold a global
temporary-quota reservation sized for this document. Recognition source, prompts,
thresholds and policy stay exactly as frozen; only application seams are used.
"""

from __future__ import annotations

import asyncio
from contextlib import suppress
from dataclasses import dataclass, replace
import math

from tgbotdocs.recognition.adapter import ModelError
from tgbotdocs.recognition.core import CoreResult
from tgbotdocs.recognition.preparation import PreparationError, PreparationLimits

from .lifecycle import LifecycleError
from .scheduler import ScheduledRecognitionCore

# The preparation worker reserves this many bytes per rendered pixel and page.
_BYTES_PER_PIXEL, _PAGE_OVERHEAD = 5, 65536
# Qwen3-VL merges 16 px patches 2x2; a resize may halve each side before that.
_PIXELS_PER_TOKEN_LOWER_BOUND = 32 * 32 * 4


def _output(page, dpi, long_side):
    """The worker's rendered size for one page (see preparation_worker.render)."""
    if page.kind == "pdf":
        scale = min(dpi / 72, long_side / max(page.width, page.height))
        return math.ceil(page.width * scale), math.ceil(page.height * scale)
    scale = min(1, long_side / max(page.width, page.height))
    return max(1, round(page.width * scale)), max(1, round(page.height * scale))


def _bytes(size):
    return size[0] * size[1] * _BYTES_PER_PIXEL + _PAGE_OVERHEAD


def _bound(pages, runtime, dpi, long_side, *, alternate):
    """Upper bound of derived bytes one batch stage of the frozen core holds at once.

    A batch holds its pages and one rejected lookahead page, and then the
    alternate view of the batch at no more than 0.75 of the primary size. Pages
    in a batch are limited by the prompt's image tokens, so the batch bytes are
    at most the prompt tokens times the largest bytes-per-token ratio of the
    document, and never more than all pages together.
    """
    prompt = runtime.context_tokens - runtime.output_tokens
    ratios, totals, largest = [], 0, 0
    for page in pages:
        width, height = _output(page, dpi, long_side)
        primary = _bytes((width, height))
        second = _bytes((math.ceil(width * 0.75) + 1, math.ceil(height * 0.75) + 1)) if alternate else 0
        tokens = min(runtime.image_max_tokens,
                     max(runtime.image_min_tokens, width * height / _PIXELS_PER_TOKEN_LOWER_BOUND))
        ratios.append((primary + second) / tokens)
        totals += primary + second
        largest = max(largest, primary)
    return math.ceil(min(prompt * max(ratios), totals)) + largest


def render_reservation(pages, settings):
    """Bytes a phase may render for this document, as a hard per-job worker quota."""
    if not pages:
        raise ValueError("document_without_pages")
    runtime = settings.runtime
    extraction = _bound(pages, runtime, runtime.pdf_dpi, settings.image_long_side,
                        alternate=settings.compute_alternate_view)
    matching = _bound(pages, runtime, runtime.pdf_dpi, settings.matching_long_side, alternate=False)
    return max(extraction, matching)


@dataclass(frozen=True, repr=False)
class PhaseOutcome:
    """A core result, or a fixed content-free error code."""

    result: CoreResult | None = None
    error: str | None = None


class RecognitionService:
    def __init__(self, adapter, scheduler, settings, lifecycle):
        self.adapter, self.scheduler, self.settings, self.lifecycle = adapter, scheduler, settings, lifecycle

    async def run(self, *, key, admission_order, files, pages, scratch, snapshots, remaining_s, charge,
                  selected_profile=None, started=None) -> PhaseOutcome:
        """Run one phase; ``charge(seconds)`` always receives its own processing time.

        ``key`` identifies this phase in the GPU scheduler; ``admission_order`` is
        the job's stable place in the document ring.
        """
        if not math.isfinite(remaining_s) or remaining_s <= 0:
            charge(0.0)
            return PhaseOutcome(error="processing_budget_exhausted")
        loop = asyncio.get_running_loop()
        core, begin = None, loop.time()
        try:
            reserve = render_reservation(pages, self.settings)
            with self.lifecycle.reserve(reserve):
                limits = self.settings.preparation
                limits = PreparationLimits(limits.max_pixels, self.lifecycle.job_usage(scratch) + reserve,
                                           limits.free_reserve_bytes)
                settings = replace(self.settings, processing_budget_s=remaining_s, preparation=limits)
                core = ScheduledRecognitionCore(self.adapter, settings, scheduler=self.scheduler, job_id=key,
                                                admission_order=admission_order, started=started)
                begin = loop.time()
                result = await core.recognize(tuple(files), tuple(snapshots), scratch=scratch,
                                              selected_profile=selected_profile)
            return PhaseOutcome(result=result)
        except LifecycleError as error:
            return PhaseOutcome(error="storage_limit" if error.code == "storage_limit" else "temporarily_unavailable")
        except OSError:
            return PhaseOutcome(error="storage_limit")
        except (ModelError, PreparationError) as error:
            return PhaseOutcome(error=error.code)
        except ValueError:
            # A contract/trace inconsistency; never a raw exception or model text.
            return PhaseOutcome(error="recognition_failed")
        finally:
            charge(0.0 if core is None else core.charged_s(loop.time() - begin))
            with suppress(RuntimeError):
                self.scheduler.forget(key)
