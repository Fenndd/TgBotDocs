"""T01b/T01c command-line runner over canonical corpus manifests.

``run`` collects one policy-independent trace per case (diagnostics or calibration)
and replays the production decision for every calibration point; ``freeze`` selects a
point and writes the frozen configuration; ``benchmark`` runs a sealed benchmark once
per frozen configuration and once per behavior identity (environment and policy).

Collection runs with ``COLLECTION_BUDGET_FACTOR`` times the production processing
budget, so extra alternate-view calls cannot exhaust the budget of a point that never
makes them; replay applies the production budget to each point's own recorded phases.
A case whose outcome at a point cannot be determined from the trace is counted in that
point's ``unreplayable_cases``, and such a point is never a zero-error candidate.

The benchmark ledger lives at ``<data root>/ledger/benchmark-runs.jsonl``, beside the
pinned runtime and model files of that data root; use one data root per PC.
Reports are content-free: case IDs, counts, rates, durations,
fixed error codes and hashes, never document values, profile contents, prompts or model
text. ``--show-mismatches`` prints values to stderr only, for synthetic development or
tuning cases, and never writes them to a file.

Usage: ``python -m tgbotdocs.recognition.runner {run,freeze,benchmark} ...``
"""

from __future__ import annotations

import argparse
import asyncio
from collections import Counter, defaultdict
from contextlib import asynccontextmanager
from dataclasses import dataclass, field
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import time
import uuid

from pydantic import Field, StrictBool, StrictFloat

from .adapter import ModelAdapter, ModelError
from .contracts import ContractModel
from .core import CoreResult, JobObserver, JobTrace, RecognitionCore, decide
from .corpus import CorpusError, CorpusManifest, LoadedCase, LoadedCorpus, load_corpus, validate_split_separation
from . import config
from .metrics import CaseObservation, aggregate_metrics
from .preparation import PreparationError
from .runtime import LocalRuntime, RuntimeFiles
from .verification import VerificationPolicy

REPORT_SCHEMA_VERSION = 2
COLLECTION_BUDGET_FACTOR = 2.0
V1_GRID = (None, 0.3, 0.5, 0.7, 0.8, 0.85, 0.9, 0.95, 0.97, 0.99, 0.995, 0.999)
MARGIN_GRID = (0.0, 0.05, 0.1, 0.2, 0.3, 0.5, 0.7, 0.9)
COMPLETENESS_TARGET = 0.90
SELECTION_RULE = (
    "Candidates are calibration points with zero incorrect accepted values, zero incorrect automatic "
    "profile selections and zero unreplayable cases on the tuning set. Choose the maximum readable "
    "completeness (none counts as 0); ties prefer V2 off, then the higher V1 threshold (disabled ranks lowest), then the higher matching "
    "margin. No candidate: calibration_no_zero_error_point (ADR-0004 remediation applies). A selected "
    "completeness below 0.90 is refused unless explicitly accepted."
)
PAGE_TIME_BASIS = (
    "Per page: the case's preparation time divided evenly over its pages, plus each included runtime call's "
    "duration divided evenly over the pages of that call. Only completed cases whose decision traversed "
    "every page contribute. Alternate-view calls and renders are included only when V2 is enabled."
)
TIMEOUT_CODES = {"processing_budget_exhausted", "runtime_timeout"}
REFUSED_INPUT_CODES = {"unsupported_format", "damaged_input", "encrypted_pdf", "pixel_limit"}
RUNTIME_DIRECTORY, EXECUTABLE = "runtime-b11221", "llama-server.exe"
MODEL, PROJECTOR = "Qwen3VL-4B-Instruct-Q4_K_M.gguf", "mmproj-Qwen3VL-4B-Instruct-F16.gguf"
LEDGER = Path("ledger") / "benchmark-runs.jsonl"


class RunnerError(Exception):
    """Content-free refusal or failure code."""

    def __init__(self, code: str):
        self.code = code
        super().__init__(code)


class CalibrationPoint(ContractModel):
    v1_min_token_probability: StrictFloat | None = Field(ge=0, le=1, allow_inf_nan=False)
    v2_alternate_view: StrictBool
    v3_declared_format: StrictBool
    matching_margin: StrictFloat = Field(ge=0, le=1, allow_inf_nan=False)

    def policy(self) -> VerificationPolicy:
        return VerificationPolicy(min_token_probability=self.v1_min_token_probability,
                                  check_alternate_view=self.v2_alternate_view,
                                  check_declared_format=self.v3_declared_format)


def calibration_grid(alternates_collected: bool) -> tuple[CalibrationPoint, ...]:
    return tuple(
        CalibrationPoint(v1_min_token_probability=v1, v2_alternate_view=v2, v3_declared_format=True,
                         matching_margin=margin)
        for v2 in ((False, True) if alternates_collected else (False,))
        for v1 in V1_GRID
        for margin in MARGIN_GRID
    )


def production_budget_s() -> float:
    return config.default_core_values().processing_budget_s


def collection_settings(*, compute_alternate_view: bool):
    """Permissive collection: V1 off, V2 not enforced, V3 on, margin 0, trace kept, extended budget."""
    core = config.default_core_values().model_copy(
        update={"processing_budget_s": production_budget_s() * COLLECTION_BUDGET_FACTOR})
    return config.core_settings(VerificationPolicy(), 0.0, compute_alternate_view=compute_alternate_view,
                                keep_trace=True, core=core)


# --- Runtime and resource sampling ------------------------------------------------------------


def runtime_files(data_root: Path) -> RuntimeFiles:
    return RuntimeFiles(data_root / RUNTIME_DIRECTORY / EXECUTABLE, data_root / "models" / MODEL,
                        data_root / "models" / PROJECTOR)


@asynccontextmanager
async def open_core(data_root: Path, settings):
    """Start one pinned runtime and one adapter; yield the core and a runtime PID getter."""
    async with LocalRuntime(runtime_files(data_root), settings.runtime) as runtime:
        adapter = ModelAdapter(runtime.adapter_settings, restart=runtime.restart)
        try:
            # LocalRuntime exposes no public PID; read it for RSS sampling only.
            yield RecognitionCore(adapter, settings), lambda: getattr(getattr(runtime, "_process", None), "pid", None)
        finally:
            await adapter.close()


def query_gpu_memory_mib() -> int | None:
    """Device-wide used GPU memory from nvidia-smi, or None when unavailable."""
    try:
        completed = subprocess.run(
            ["nvidia-smi", "--query-gpu=memory.used", "--format=csv,noheader,nounits"],
            capture_output=True, text=True, timeout=5, check=False,
            creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0,
        )
        values = [int(line.strip()) for line in completed.stdout.splitlines() if line.strip()]
        return max(values) if completed.returncode == 0 and values else None
    except (OSError, ValueError, subprocess.SubprocessError):
        return None


def process_rss_mib(pid: int | None) -> float | None:
    if pid is None:
        return None
    try:
        import psutil

        return psutil.Process(pid).memory_info().rss / 2**20
    except Exception:
        return None


class ResourceSampler:
    """Background peak sampling at a fixed interval; peaks are lower bounds."""

    def __init__(self, pid, interval_s: float = 0.5):
        self.pid, self.interval_s = pid, interval_s
        self.gpu, self.rss, self.samples = None, None, 0
        self._task = None

    async def sample(self):
        gpu = await asyncio.to_thread(query_gpu_memory_mib)
        rss = process_rss_mib(self.pid())
        self.samples += 1
        if gpu is not None:
            self.gpu = gpu if self.gpu is None else max(self.gpu, gpu)
        if rss is not None:
            self.rss = rss if self.rss is None else max(self.rss, rss)

    async def _loop(self):
        while True:
            await asyncio.sleep(self.interval_s)
            await self.sample()

    async def __aenter__(self):
        await self.sample()
        self._task = asyncio.create_task(self._loop())
        return self

    async def __aexit__(self, *_):
        self._task.cancel()
        try:
            await self._task
        except asyncio.CancelledError:
            pass
        await self.sample()

    def report(self) -> dict:
        return {"peak_gpu_memory_used_mib": self.gpu, "peak_runtime_rss_mib": self.rss, "samples": self.samples,
                "interval_s": self.interval_s,
                "basis": "sampled lower bounds; GPU memory is device-wide (nvidia-smi), RSS is the runtime process"}


# --- Case execution -------------------------------------------------------------------------------


@dataclass(repr=False)
class CaseRun:
    """One executed case. ``result`` and ``trace`` hold job content in memory only; never serialize them.

    ``trace`` is kept also when the collecting job itself failed after matching, since
    other calibration points may not make the failing call.
    """

    case_id: str
    state: str
    error_code: str | None
    wall_s: float
    observer: JobObserver = field(default_factory=JobObserver)
    result: CoreResult | None = None
    trace: JobTrace | None = None


def failure_state(error: ModelError | PreparationError) -> str:
    if isinstance(error, ModelError):
        return "timeout" if error.code in TIMEOUT_CODES else "failed"
    return "input_refused" if error.code in REFUSED_INPUT_CODES else "failed"


def _cleanup(scratch: Path) -> str | None:
    try:
        leftovers = any(scratch.iterdir())
    except OSError:
        return "scratch_cleanup_failed"
    if leftovers:
        shutil.rmtree(scratch, ignore_errors=True)
    else:
        try:
            scratch.rmdir()
        except OSError:
            pass
    if scratch.exists():
        return "scratch_cleanup_failed"
    return "scratch_not_empty" if leftovers else None


async def execute_case(core, case: LoadedCase, tmp_root: Path) -> CaseRun:
    """Run one case in a fresh private scratch directory that is always removed."""
    observer = JobObserver()
    scratch = Path(tempfile.mkdtemp(prefix="case-", dir=tmp_root))
    state, code, result, usable = "completed", None, None, True
    begin = time.monotonic()
    try:
        result = await core.recognize(case.files, case.profiles, scratch=scratch, observer=observer)
    except (ModelError, PreparationError) as error:
        state, code = failure_state(error), error.code
    except Exception:
        # Exception text may quote document or model content; report only a fixed code.
        state, code, usable = "failed", "unexpected_error", False
    finally:
        wall = time.monotonic() - begin
        cleanup = _cleanup(scratch)
    if cleanup:
        state, code, result, usable = "failed", cleanup, None, False
    return CaseRun(case.case_id, state, code, wall, observer, result, observer.trace if usable else None)


def observation(case_id: str, state: str, result: CoreResult | None) -> CaseObservation:
    if state != "completed" or result is None:
        return CaseObservation(case_id=case_id, execution_state=state)
    return CaseObservation(case_id=case_id, execution_state="completed", matching=result.matching,
                           selected_profile_id=result.profile.id if result.profile else None,
                           automatic_profile_selection=not result.user_selected, recognition=result.recognition)


def replay(case: LoadedCase, run: CaseRun, point: CalibrationPoint, budget_s: float):
    """Production decision of one recorded case at one point, plus content-free usage.

    The decision entry is ``[case_id, batches_used, traversed_all_pages, unreplayable]``;
    a point whose production job fails gets that failure's execution state and no entry.
    """
    if run.trace is None:
        return observation(case.case_id, run.state, None), None
    try:
        result = decide(run.trace, case.profiles, policy=point.policy(), matching_margin=point.matching_margin,
                        processing_budget_s=budget_s)
    except (ModelError, PreparationError) as error:
        return CaseObservation(case_id=case.case_id, execution_state=failure_state(error)), None
    except ValueError:
        return CaseObservation(case_id=case.case_id, execution_state="failed"), [case.case_id, 0, False, True]
    return (observation(case.case_id, "completed", result),
            [case.case_id, result.metrics["batches"], result.recognition is not None, False])


# --- Report assembly -----------------------------------------------------------------------------


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _sha256_file(path: Path) -> str:
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def case_set_sha256(manifest: CorpusManifest) -> str:
    """Identity of a case set by its files only: the sorted artifact hashes of each case."""
    cases = sorted(sorted(artifact.sha256 for artifact in case.artifacts) for case in manifest.cases)
    return hashlib.sha256(config.canonical_json(cases)).hexdigest()


def case_row(run: CaseRun) -> dict:
    observer = run.observer

    def seconds(kind, stage=None):
        return sum(c.duration_s for c in observer.calls if c.kind == kind and stage in (None, c.stage))

    return {
        "case_id": run.case_id, "execution_state": run.state, "error_code": run.error_code, "wall_s": run.wall_s,
        "pages": len(observer.page_kinds), "pages_by_kind": dict(sorted(Counter(observer.page_kinds).items())),
        "page_kinds": list(observer.page_kinds), "preparation_s": observer.preparation_s,
        "alternate_preparation_s": observer.alternate_preparation_s, "matching_s": seconds("matching"),
        "extraction_s": seconds("extraction"), "alternate_s": seconds("alternate"),
        "token_count_s": seconds("token_count"), "model_calls": sum(c.kind != "token_count" for c in observer.calls),
        "contract_retries": observer.contract_retries, "calls": [c.model_dump(mode="json") for c in observer.calls],
    }


def page_samples(rows: list[dict], decisions: dict[str, tuple[int, bool]], *, alternate: bool) -> dict:
    """Per-page seconds by page kind for the calls a given decision actually needs.

    Only decisions that traversed every page count; the recording job's own execution
    state does not matter, since it may have made calls the decision does not.
    """
    samples: dict[str, list[float]] = defaultdict(list)
    for row in rows:
        used, full = decisions.get(row["case_id"], (0, False))
        if not full or not row["page_kinds"]:
            continue
        kinds = row["page_kinds"]
        preparation = row["preparation_s"] + (row["alternate_preparation_s"] if alternate else 0.0)
        per_page = [preparation / len(kinds)] * len(kinds)
        for call in row["calls"]:
            if call["stage"] == "alternate" and not alternate:
                continue
            if call["stage"] != "matching" and call["batch"] >= used:
                continue
            for page in call["pages"]:
                per_page[page - 1] += call["duration_s"] / len(call["pages"])
        for kind, value in zip(kinds, per_page, strict=True):
            samples[kind].append(value)
    return dict(samples)


def timing_summary(runs: list[CaseRun]) -> dict:
    walls = [run.wall_s for run in runs]
    later = walls[1:]
    return {
        "case_wall_s": {"count": len(walls), "p50": config.percentile(walls, .5) if walls else None,
                        "p95": config.percentile(walls, .95) if walls else None},
        "first_case_s": walls[0] if walls else None,
        "later_cases_p50_s": config.percentile(later, .5) if later else None, "later_cases_count": len(later),
    }


def _curve_entry(index: int, value, report: dict) -> dict:
    aggregate = report["aggregate"]
    return {"index": index, "value": value, "accepted_values": aggregate["accepted_values"],
            "incorrect_accepted_values": aggregate["incorrect_accepted_values"],
            "readable_completeness": aggregate["rates"]["readable_completeness"],
            "automatic_profile_selections": aggregate["automatic_profile_selections"],
            "incorrect_automatic_profile_selections": aggregate["incorrect_automatic_profile_selections"]}


def signal_curves(points: tuple[CalibrationPoint, ...], reports: list[dict]) -> dict:
    items = list(enumerate(points))
    return {
        "v1_with_v2_off_margin_0": [_curve_entry(i, p.v1_min_token_probability, reports[i]) for i, p in items
                                    if not p.v2_alternate_view and p.matching_margin == 0.0],
        "v2_with_v1_off_margin_0": [_curve_entry(i, p.v2_alternate_view, reports[i]) for i, p in items
                                    if p.v1_min_token_probability is None and p.matching_margin == 0.0],
        "margin_with_v1_off_v2_off": [_curve_entry(i, p.matching_margin, reports[i]) for i, p in items
                                      if p.v1_min_token_probability is None and not p.v2_alternate_view],
    }


def build_run_report(*, mode: str, loaded: LoadedCorpus, manifest_sha256: str, cases: tuple[LoadedCase, ...],
                     runs: list[CaseRun], settings, resources: dict, environment: config.Environment,
                     environment_changed: bool = False) -> dict:
    manifest = loaded.manifest
    points = calibration_grid(settings.compute_alternate_view)
    by_id = {run.case_id: run for run in runs}
    budget = production_budget_s()
    reports = []
    for index, point in enumerate(points):
        replayed = [replay(case, by_id[case.case_id], point, budget) for case in cases]
        aggregate = aggregate_metrics(loaded, tuple(item for item, _ in replayed), mode=mode)
        decisions = [decision for _, decision in replayed if decision is not None]
        reports.append({"index": index, "thresholds": point.model_dump(mode="json"),
                        "aggregate": aggregate["aggregate"], "groups": aggregate["groups"],
                        "unreplayable_cases": sum(1 for decision in decisions if decision[3]),
                        "case_decisions": decisions})
    policy = settings.verification
    return {
        "schema_version": REPORT_SCHEMA_VERSION, "mode": mode, "created_at": _now(),
        "quality_measurement_eligible": mode == "calibration" and not environment_changed,
        "environment_changed_during_run": environment_changed, "acceptance_decision": None,
        "manifest_sha256": manifest_sha256, "manifest_schema_version": manifest.schema_version,
        "split": manifest.split, "purpose": manifest.purpose,
        "eligibility_reasons": {"calibration": list(manifest.eligibility_reasons("calibration")),
                                "benchmark": list(manifest.eligibility_reasons("benchmark"))},
        "selected_all_cases": len(cases) == len(manifest.cases), "case_count": len(cases),
        "environment": environment.model_dump(mode="json"),
        "collection": {"policy": policy.model_dump(mode="json"), "matching_margin": settings.matching_margin,
                       "compute_alternate_view": settings.compute_alternate_view, "keep_trace": settings.keep_trace,
                       "processing_budget_s": settings.processing_budget_s},
        "replay_processing_budget_s": budget,
        "selection_rule": SELECTION_RULE, "page_time_basis": PAGE_TIME_BASIS,
        "points": reports, "curves": signal_curves(points, reports),
        "cases": [case_row(by_id[case.case_id]) for case in cases],
        "failures_by_code": dict(sorted(Counter(run.error_code for run in runs if run.error_code).items())),
        "timing": timing_summary(runs), "resources": resources,
    }


def _write_json(path: Path, value: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(json.dumps(value, ensure_ascii=False, sort_keys=True, indent=1).encode("utf-8") + b"\n")


def _show_mismatches(cases: tuple[LoadedCase, ...], runs: list[CaseRun]) -> None:
    """Value-level comparison for prompt development; stderr only, never a file."""
    by_id = {run.case_id: run for run in runs}
    for case in cases:
        run, expected = by_id[case.case_id], case.case.expected
        actual = run.result
        print(f"[{case.case_id}] state={run.state} code={run.error_code} matching expected="
              f"{expected.matching if expected else None} actual={actual.matching.status if actual else None}",
              file=sys.stderr)
        if not expected or not actual or actual.recognition is None:
            continue
        fields = {item.field_id: item for item in actual.recognition.fields}
        for truth in expected.fields:
            item = fields.get(truth.field_id)
            status, value = (item.status, item.accepted_value) if item else (None, None)
            if value != truth.value or status != truth.status:
                print(f"  {truth.field_id}: expected={truth.value!r} ({truth.status}) actual={value!r} ({status})",
                      file=sys.stderr)
        lists = {item.field_id: item for item in actual.recognition.lists}
        for truth in expected.lists:
            result = lists.get(truth.field_id)
            rows = result.rows if result else ()
            print(f"  {truth.field_id}: expected {len(truth.rows)} rows ({truth.status}), actual {len(rows)} rows "
                  f"({result.status if result else None})", file=sys.stderr)
            for index in range(max(len(truth.rows), len(rows))):
                want = {c.field_id: c.value for c in truth.rows[index].cells} if index < len(truth.rows) else {}
                got = {c.field_id: c.accepted_value for c in rows[index].cells} if index < len(rows) else {}
                if want != got:
                    print(f"    row {index + 1}: expected={want!r} actual={got!r}", file=sys.stderr)


# --- Subcommands -----------------------------------------------------------------------------------


def _load(path: Path) -> LoadedCorpus:
    return load_corpus(path)


async def run_command(args) -> dict:
    loaded = _load(args.manifest)
    manifest = loaded.manifest
    if manifest.split == "benchmark":
        raise RunnerError("benchmark_split_refused")
    if args.mode == "calibration":
        manifest.require_eligible("calibration")
    cases = loaded.cases
    if args.cases:
        wanted = tuple(item for item in args.cases.split(",") if item)
        known = {case.case_id: case for case in loaded.cases}
        if not wanted or len(set(wanted)) != len(wanted) or any(item not in known for item in wanted):
            raise RunnerError("unknown_or_duplicate_case_id")
        cases = tuple(case for case in loaded.cases if case.case_id in set(wanted))
    if args.show_mismatches and (manifest.split not in ("development", "tuning")
                                 or any(case.case.origin.kind != "synthetic" for case in cases)):
        raise RunnerError("mismatch_display_not_permitted")
    manifest_sha = _sha256_file(args.manifest)
    settings = collection_settings(compute_alternate_view=not args.no_alternate)
    # The identity of the code and prompts this run uses is taken before the runtime
    # starts; a change on disk during the run makes the report ineligible.
    environment = config.current_environment()
    tmp_root = args.data_root / "tmp"
    tmp_root.mkdir(parents=True, exist_ok=True)
    runs: list[CaseRun] = []
    async with open_core(args.data_root, settings) as (core, pid):
        async with ResourceSampler(pid) as sampler:
            for case in cases:
                runs.append(await execute_case(core, case, tmp_root))
    changed = config.current_environment() != environment
    report = build_run_report(mode=args.mode, loaded=loaded, manifest_sha256=manifest_sha, cases=cases,
                              runs=runs, settings=settings, resources=sampler.report(), environment=environment,
                              environment_changed=changed)
    if args.show_mismatches:
        _show_mismatches(cases, runs)
    _write_json(args.output, report)
    if changed:
        raise RunnerError("environment_changed_during_run")
    return report


def _zero_error(point: dict) -> bool:
    """Zero errors that the point is known to make; unreplayable cases may hide errors."""
    aggregate = point["aggregate"]
    return (aggregate["incorrect_accepted_values"] == 0 and aggregate["incorrect_automatic_profile_selections"] == 0
            and point["unreplayable_cases"] == 0)


def select_point(points: list[dict]) -> int:
    candidates = [point for point in points if _zero_error(point)]
    if not candidates:
        raise RunnerError("calibration_no_zero_error_point")

    def rank(point):
        thresholds = point["thresholds"]
        completeness = point["aggregate"]["rates"]["readable_completeness"] or 0.0
        v1 = thresholds["v1_min_token_probability"]
        return (completeness, not thresholds["v2_alternate_view"], -1.0 if v1 is None else v1,
                thresholds["matching_margin"])

    return max(candidates, key=rank)["index"]


def freeze(report_path: Path, output: Path, *, point_index: int | None, auto: bool,
           accept_below_target: bool) -> tuple[config.FrozenConfiguration, str]:
    try:
        data = report_path.read_bytes()
        report = json.loads(data)
        points = report["points"]
        if (report["schema_version"] != REPORT_SCHEMA_VERSION or report["mode"] != "calibration"
                or report["quality_measurement_eligible"] is not True):
            raise RunnerError("calibration_report_required")
        recorded = config.Environment.model_validate(report["environment"])
        if [point["index"] for point in points] != list(range(len(points))) or any(
                type(point["unreplayable_cases"]) is not int for point in points):
            raise RunnerError("invalid_calibration_report")
    except (OSError, ValueError, KeyError, TypeError):
        raise RunnerError("invalid_calibration_report") from None
    if report.get("selected_all_cases") is not True:
        raise RunnerError("calibration_incomplete_case_selection")
    current = config.current_environment()
    mismatches = config.environment_mismatches(recorded, current)
    if mismatches:
        raise RunnerError(mismatches[0])
    if auto:
        index, rule = select_point(points), SELECTION_RULE
    else:
        if point_index is None or not 0 <= point_index < len(points):
            raise RunnerError("unknown_calibration_point")
        if not _zero_error(points[point_index]):
            raise RunnerError("calibration_point_has_errors")
        index, rule = point_index, f"Developer-selected point {point_index}; zero tuning errors required."
    selected = points[index]
    completeness = selected["aggregate"]["rates"]["readable_completeness"]
    if (completeness is None or completeness < COMPLETENESS_TARGET) and not accept_below_target:
        raise RunnerError("calibration_completeness_below_target")
    point = CalibrationPoint.model_validate(selected["thresholds"])
    decisions = {case_id: (used, full) for case_id, used, full, _ in selected["case_decisions"]}
    samples = page_samples(report["cases"], decisions, alternate=point.v2_alternate_view)
    frozen = config.FrozenConfiguration(
        schema_version=1, created_at=datetime.now(timezone.utc), runtime_artifacts=current.runtime_artifacts,
        runtime_profile=current.runtime_profile, core=current.core, prompt=current.prompt,
        policy=config.FrozenPolicy(min_token_probability=point.v1_min_token_probability,
                                   check_alternate_view=point.v2_alternate_view,
                                   check_declared_format=point.v3_declared_format,
                                   matching_margin=point.matching_margin),
        corpus_manifest_schema_version=report["manifest_schema_version"],
        calibration=config.CalibrationProvenance(tuning_manifest_sha256=report["manifest_sha256"],
                                                 calibration_report_sha256=hashlib.sha256(data).hexdigest(),
                                                 point_index=index, selection_rule=rule),
        code_sha256=current.code_sha256, dependencies=current.dependencies,
        page_times=config.page_time_summary(samples),
    )
    return frozen, config.write_frozen(frozen, output)


def _ledger_entries(path: Path) -> list[dict]:
    if not path.exists():
        return []
    entries = []
    try:
        for line in path.read_text(encoding="utf-8").splitlines():
            if line.strip():
                entry = json.loads(line)
                if not isinstance(entry, dict) or entry.get("event") not in ("started", "completed", "acknowledged"):
                    raise ValueError
                entries.append(entry)
    except (OSError, ValueError):
        raise RunnerError("benchmark_ledger_invalid") from None
    return entries


def _ledger_append(path: Path, entry: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as stream:
        stream.write(json.dumps(entry, sort_keys=True) + "\n")
        stream.flush()
        os.fsync(stream.fileno())


def check_ledger(entries: list[dict], config_sha256: str, behavior_sha256: str, acknowledge: str | None) -> str | None:
    """Enforce one benchmark run per frozen configuration and per behavior identity.

    A configuration frozen again from the same calibration (a new file hash, the same
    environment and policy) is the same configuration. Returns an acknowledged run ID.
    """
    runs = [entry for entry in entries
            if entry.get("config_sha256") == config_sha256 or entry.get("behavior_sha256") == behavior_sha256]
    if any(entry["event"] == "completed" for entry in runs):
        raise RunnerError("benchmark_already_run")
    closed = {entry["run_id"] for entry in runs if entry["event"] == "acknowledged"}
    pending = [entry["run_id"] for entry in runs if entry["event"] == "started" and entry["run_id"] not in closed]
    if not pending:
        if acknowledge is not None:
            raise RunnerError("unknown_incomplete_run")
        return None
    if pending != [acknowledge]:
        raise RunnerError("benchmark_incomplete_run_requires_acknowledgement")
    return acknowledge


async def benchmark_command(args) -> dict:
    frozen, config_sha = config.load_frozen(args.config)
    loaded = _load(args.manifest)
    manifest = loaded.manifest
    if manifest.split != "benchmark":
        raise RunnerError("benchmark_split_required")
    if manifest.frozen_configuration_sha256 != config_sha:
        raise RunnerError("frozen_configuration_mismatch")
    manifest.require_eligible("benchmark")
    registry = tuple(load_corpus(path, verify_files=False).manifest for path in args.registry)
    if not any(item.split == "tuning" for item in registry):
        raise RunnerError("benchmark_registry_requires_tuning_manifest")
    # Separation must be checked against the tuning manifest the thresholds were calibrated on.
    if frozen.calibration.tuning_manifest_sha256 not in {_sha256_file(path) for path in args.registry}:
        raise RunnerError("benchmark_registry_missing_calibration_manifest")
    validate_split_separation(manifest, *registry)
    environment = config.current_environment()
    mismatches = config.environment_mismatches(frozen.environment(), environment)
    if mismatches:
        raise RunnerError(mismatches[0])
    ledger = args.data_root / LEDGER
    manifest_sha = _sha256_file(args.manifest)
    behavior_sha, case_set_sha = config.behavior_sha256(frozen), case_set_sha256(manifest)
    entries = _ledger_entries(ledger)
    acknowledged = check_ledger(entries, config_sha, behavior_sha, args.acknowledge_incomplete_run)
    # Another configuration may run on the same cases only after remediation; make that visible.
    prior = sorted({str(entry.get("run_id")) for entry in entries
                    if entry["event"] == "completed" and entry.get("case_set_sha256") == case_set_sha})
    identity = {"config_sha256": config_sha, "behavior_sha256": behavior_sha, "manifest_sha256": manifest_sha,
                "case_set_sha256": case_set_sha}
    if acknowledged:
        _ledger_append(ledger, {"event": "acknowledged", "run_id": acknowledged, **identity, "utc": _now()})
    run_id = uuid.uuid4().hex
    _ledger_append(ledger, {"event": "started", "run_id": run_id, **identity, "utc": _now()})
    settings = frozen.core_settings()
    tmp_root = args.data_root / "tmp"
    tmp_root.mkdir(parents=True, exist_ok=True)
    runs: list[CaseRun] = []
    async with open_core(args.data_root, settings) as (core, pid):
        async with ResourceSampler(pid) as sampler:
            for case in loaded.cases:
                runs.append(await execute_case(core, case, tmp_root))
    changed = config.current_environment() != environment
    observations = tuple(observation(run.case_id, run.state, run.result) for run in runs)
    metrics = aggregate_metrics(loaded, observations, mode="benchmark", registry=registry)
    rows = [case_row(run) for run in runs]
    decisions = {run.case_id: (run.result.metrics["batches"], run.result.recognition is not None)
                 for run in runs if run.result is not None}
    page_times = config.page_time_summary(page_samples(rows, decisions, alternate=frozen.policy.check_alternate_view))
    report = {
        "schema_version": REPORT_SCHEMA_VERSION, "mode": "benchmark", "run_id": run_id, "created_at": _now(),
        "manifest_sha256": manifest_sha, "frozen_configuration_sha256": config_sha,
        "behavior_sha256": behavior_sha, "case_set_sha256": case_set_sha,
        "prior_completed_runs_on_case_set": prior,
        "environment": environment.model_dump(mode="json"), "environment_changed_during_run": changed,
        "policy": frozen.policy.model_dump(mode="json"), "registry_splits": [item.split for item in registry],
        "quality_measurement_eligible": metrics["quality_measurement_eligible"] and not changed,
        "acceptance_decision": None,
        "aggregate": metrics["aggregate"], "groups": metrics["groups"],
        "page_times": [item.model_dump(mode="json") for item in page_times], "page_time_basis": PAGE_TIME_BASIS,
        "timing": timing_summary(runs), "resources": sampler.report(),
        "failures_by_code": dict(sorted(Counter(run.error_code for run in runs if run.error_code).items())),
        "cases": rows,
    }
    _write_json(args.output, report)
    # The run consumed the sealed set even when its environment changed underneath it.
    _ledger_append(ledger, {"event": "completed", "run_id": run_id, **identity,
                            "environment_changed_during_run": changed, "utc": _now()})
    if changed:
        raise RunnerError("environment_changed_during_run")
    return report


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="python -m tgbotdocs.recognition.runner", description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    commands = parser.add_subparsers(dest="command", required=True)
    run = commands.add_parser("run", help="collect traces and replay the calibration grid")
    run.add_argument("--manifest", type=Path, required=True)
    run.add_argument("--mode", choices=("diagnostics", "calibration"), required=True)
    run.add_argument("--data-root", type=Path, required=True)
    run.add_argument("--output", type=Path, required=True)
    run.add_argument("--cases", help="comma-separated case IDs")
    run.add_argument("--no-alternate", action="store_true", help="do not compute alternate-view readings")
    run.add_argument("--show-mismatches", action="store_true",
                     help="print value-level mismatches of synthetic development/tuning cases to stderr only")
    frozen = commands.add_parser("freeze", help="select a calibration point and write the frozen configuration")
    frozen.add_argument("--calibration", type=Path, required=True)
    frozen.add_argument("--output", type=Path, required=True)
    choice = frozen.add_mutually_exclusive_group(required=True)
    choice.add_argument("--point", type=int)
    choice.add_argument("--auto", action="store_true")
    frozen.add_argument("--accept-below-target", action="store_true")
    bench = commands.add_parser("benchmark", help="run the sealed benchmark once with the frozen configuration")
    bench.add_argument("--manifest", type=Path, required=True)
    bench.add_argument("--config", type=Path, required=True)
    bench.add_argument("--registry", type=Path, action="append", required=True)
    bench.add_argument("--data-root", type=Path, required=True)
    bench.add_argument("--output", type=Path, required=True)
    bench.add_argument("--acknowledge-incomplete-run", metavar="RUN_ID")
    return parser


def main(argv=None) -> int:
    args = build_parser().parse_args(argv)
    try:
        if args.command == "run":
            report = asyncio.run(run_command(args))
            states = Counter(row["execution_state"] for row in report["cases"])
            print(json.dumps({"report": str(args.output), "mode": report["mode"], "cases": report["case_count"],
                              "execution_states": dict(sorted(states.items()))}))
        elif args.command == "freeze":
            frozen, digest = freeze(args.calibration, args.output, point_index=args.point, auto=args.auto,
                                    accept_below_target=args.accept_below_target)
            print(json.dumps({"frozen_configuration": str(args.output), "sha256": digest,
                              "point_index": frozen.calibration.point_index}))
        else:
            report = asyncio.run(benchmark_command(args))
            print(json.dumps({"report": str(args.output), "run_id": report["run_id"],
                              "cases": report["aggregate"]["cases"]}))
    except RunnerError as error:
        print(f"error: {error.code}", file=sys.stderr)
        return 2
    except (CorpusError, config.ConfigError) as error:
        # Both carry fixed codes only.
        print(f"error: {error}", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
