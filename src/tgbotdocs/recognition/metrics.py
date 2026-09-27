"""Pure, content-free corpus aggregation; no model calls or acceptance verdicts."""
from __future__ import annotations

from collections import Counter
from math import expm1, log
from typing import Literal

from pydantic import Field, StrictBool, StrictFloat, StrictStr, model_validator

from .contracts import (ContractModel, FieldResult, MatchingResponse, RecognitionResult,
                        ScalarField, ListField, normalize_value, resolve_matching, validate_field_result)
from .corpus import (CorpusCase, CorpusError, CorpusManifest, ExpectedValue, LoadedCorpus,
                     declared_denominators, validate_split_separation)

Mode = Literal["diagnostics", "calibration", "benchmark"]
Signal = Literal["V1", "V2", "V3", "V4", "V5"]


class Evidence(ContractModel):
    signal: Signal
    score: StrictFloat = Field(ge=0, le=1, allow_inf_nan=False)


class ValueEvidence(ContractModel):
    field_id: StrictStr
    source_key: StrictStr | None = None
    column_id: StrictStr | None = None
    evidence: tuple[Evidence, ...]

    @model_validator(mode="after")
    def identity(self):
        if (self.source_key is None) != (self.column_id is None):
            raise ValueError("cell_evidence_requires_row_and_column")
        if len({item.signal for item in self.evidence}) != len(self.evidence):
            raise ValueError("duplicate_evidence_signal")
        return self


class CaseObservation(ContractModel):
    """Private in-memory adapter input. Never serialize this model into diagnostics."""
    case_id: StrictStr
    execution_state: Literal["completed", "failed", "cancelled", "timeout", "not_run", "input_refused"]
    matching: MatchingResponse | None = None
    selected_profile_id: StrictStr | None = None
    automatic_profile_selection: StrictBool = True
    recognition: RecognitionResult | None = None
    matching_margin: StrictFloat | None = Field(default=None, ge=0, le=1, allow_inf_nan=False)
    value_evidence: tuple[ValueEvidence, ...] = ()

    @model_validator(mode="after")
    def unique_evidence(self):
        identities = [(item.field_id, item.source_key, item.column_id) for item in self.value_evidence]
        if len(identities) != len(set(identities)):
            raise ValueError("duplicate_value_evidence")
        return self


class ThresholdPoint(ContractModel):
    """Caller-declared thresholds. No built-in calibration or model confidence."""
    signals: tuple[Evidence, ...] = ()
    matching_minimum_margin: StrictFloat | None = Field(default=None, ge=0, le=1, allow_inf_nan=False)

    @model_validator(mode="after")
    def unique_signals(self):
        if len({item.signal for item in self.signals}) != len(self.signals):
            raise ValueError("duplicate_threshold_signal")
        if not self.signals and self.matching_minimum_margin is None:
            raise ValueError("threshold_requires_explicit_evidence")
        return self


def zero_error_bound(samples: int, errors: int, *, confidence: float = 0.95) -> dict:
    """One-sided binomial bound only for zero observed errors; no independence claim."""
    if type(samples) is not int or type(errors) is not int or samples < 0 or not 0 <= errors <= samples:
        raise ValueError("invalid_error_counts")
    if not 0 < confidence < 1:
        raise ValueError("invalid_confidence")
    return {"samples": samples, "errors": errors, "confidence": confidence,
            "upper_exact": -expm1(log(1 - confidence) / samples) if samples and errors == 0 else None,
            "upper_approximate": min(1.0, -log(1 - confidence) / samples) if samples and errors == 0 else None}


def _gate(corpus: CorpusManifest | LoadedCorpus, mode: Mode, registry: tuple[CorpusManifest, ...]) -> CorpusManifest:
    manifest = corpus.manifest if isinstance(corpus, LoadedCorpus) else corpus
    if mode not in ("diagnostics", "calibration", "benchmark"):
        raise CorpusError("unknown_measurement_mode")
    validate_split_separation(manifest, *registry)
    if mode != "diagnostics":
        manifest.require_eligible(mode)
        if not isinstance(corpus, LoadedCorpus) or not corpus.files_verified:
            raise CorpusError("quality_measurement_requires_verified_files")
        if mode == "benchmark" and not registry:
            raise CorpusError("benchmark_requires_historical_registry")
    return manifest


def _profile(case: CorpusCase, observation: CaseObservation) -> tuple[bool, bool]:
    """Return accepted automatic selection and correct selection context."""
    selected = observation.selected_profile_id
    consistent = True
    if observation.automatic_profile_selection:
        if observation.matching is None or observation.matching.status != "matched":
            return False, False
        try:
            resolved = resolve_matching(observation.matching, case.profiles)
            consistent = resolved is not None and resolved.id == selected
        except ValueError:
            consistent = False
    truth = case.expected
    return observation.automatic_profile_selection, bool(consistent and truth and truth.matching == "matched" and selected == truth.profile_id)


def _matches(result: FieldResult, truth: ExpectedValue | None, field: ScalarField | None,
             case: CorpusCase, context: bool) -> bool:
    if not context or truth is None or field is None or truth.status != "extracted":
        return False
    try:
        validate_field_result(field, result, case.page_ids)
        value = result.accepted_value
        if truth.normalization == "profile":
            value = normalize_value(field, value)
        return (type(value) is type(truth.value) and value in (truth.value, *truth.allowed_values)
                and bool(result.source_pages) and set(result.source_pages).issubset(truth.source_pages))
    except (ValueError, TypeError):
        return False


def _accept(observation: CaseObservation, identity: tuple, point: ThresholdPoint | None) -> bool:
    if point is None or not point.signals:
        return True
    item = next((item for item in observation.value_evidence
                 if (item.field_id, item.source_key, item.column_id) == identity), None)
    scores = {e.signal: e.score for e in item.evidence} if item else {}
    return all(threshold.signal in scores and scores[threshold.signal] >= threshold.score for threshold in point.signals)


def _case_counts(case: CorpusCase, observation: CaseObservation | None, point: ThresholdPoint | None) -> Counter:
    counts = Counter(cases=1, readable_cases=int(case.quality == "readable"))
    denominator = declared_denominators((case,))
    counts.update(denominator.model_dump(exclude={"cases", "readable_cases"}))
    if case.expected:
        for kind, values in (("scalar", case.expected.fields), ("list_cell", tuple(cell for item in case.expected.lists for row in item.rows for cell in row.cells))):
            counts[kind + "_known_values"] += sum(v.status == "extracted" for v in values)
            counts[kind + "_readable_present_values"] += sum(v.present is True for v in values) if case.quality == "readable" else 0
    if observation is None:
        counts["not_run_cases"] += 1
        return counts
    counts[observation.execution_state + "_cases"] += 1
    automatic, context = _profile(case, observation)
    if point and point.matching_minimum_margin is not None:
        retained = observation.matching_margin is not None and observation.matching_margin >= point.matching_minimum_margin
        if not retained:
            return counts  # Fail closed: no extraction accepted after an uncertain selection.
    if automatic:
        counts["automatic_profile_selections"] += 1
        counts["incorrect_automatic_profile_selections"] += int(not context)
        counts["correct_automatic_profile_selections"] += int(context)
    truth = case.expected
    actual_matching = "input_refused" if observation.execution_state == "input_refused" else (observation.matching.status if observation.matching else None)
    if truth:
        counts["matching_status_errors"] += int(actual_matching != truth.matching)
    recognition = observation.recognition
    if recognition is None:
        if truth and truth.matching == "matched":
            counts["outcome_errors"] += 1
        return counts
    if truth:
        counts["outcome_errors"] += int(recognition.outcome != truth.outcome)
    profile = next((p for p in case.profiles if truth and p.id == truth.profile_id), None)
    fields = {f.id: f for f in profile.fields if isinstance(f, ScalarField)} if profile else {}
    lists = {f.id: f for f in profile.fields if isinstance(f, ListField)} if profile else {}
    expected_fields = {v.field_id: v for v in truth.fields} if truth else {}
    expected_lists = {v.field_id: v for v in truth.lists} if truth else {}
    credited = set()

    def value(result, expected, field, identity, valid_context):
        if result.status != "extracted" or not _accept(observation, identity, point):
            return
        counts["accepted_values"] += 1
        kind = "scalar" if identity[1] is None else "list_cell"
        counts[kind + "_accepted_values"] += 1
        correct = identity not in credited and _matches(result, expected, field, case, valid_context)
        counts["incorrect_accepted_values"] += int(not correct)
        counts[kind + "_incorrect_accepted_values"] += int(not correct)
        if correct:
            credited.add(identity)
            counts["correct_accepted_values"] += 1
            counts["known_readable_values_recovered"] += 1
            counts["readable_present_values_recovered"] += int(case.quality == "readable")
            counts[kind + "_known_values_recovered"] += 1
            counts[kind + "_readable_present_values_recovered"] += int(case.quality == "readable")

    scalar_ids = [r.field_id for r in recognition.fields]
    if set(scalar_ids) != set(expected_fields) or len(scalar_ids) != len(set(scalar_ids)):
        counts["schema_errors"] += 1
    for result in recognition.fields:
        value(result, expected_fields.get(result.field_id), fields.get(result.field_id), (result.field_id, None, None), context)
    list_ids = [r.field_id for r in recognition.lists]
    if set(list_ids) != set(expected_lists) or len(list_ids) != len(set(list_ids)):
        counts["schema_errors"] += 1
    for result in recognition.lists:
        expected = expected_lists.get(result.field_id)
        expected_rows = {row.source_key: row for row in expected.rows} if expected else {}
        order = {key: index for index, key in enumerate(expected_rows)}
        actual_keys = [row.source_key for row in result.rows]
        positions = [order[key] for key in actual_keys if key in order]
        ordered = all(a < b for a, b in zip(positions, positions[1:], strict=False))
        exact_rows = expected is not None and actual_keys == list(expected_rows)
        structural_error = (expected is None or not ordered or len(actual_keys) != len(set(actual_keys))
                            or any(key not in expected_rows for key in actual_keys)
                            or result.status == "complete" and (not exact_rows or expected.status != "complete"))
        if structural_error:
            counts["list_structure_errors"] += 1
        if expected and not expected.rows and expected.status == "complete" and result.status == "complete" and not result.rows and context:
            counts["confirmed_empty_lists"] += 1
        columns = {column.id: column for column in lists[result.field_id].columns} if result.field_id in lists else {}
        for row in result.rows:
            expected_row = expected_rows.get(row.source_key)
            row_context = context and ordered and expected_row is not None and set(row.source_pages).issubset(expected_row.source_pages)
            cells = {cell.field_id: cell for cell in expected_row.cells} if expected_row else {}
            if set(columns) != {cell.field_id for cell in row.cells}:
                counts["schema_errors"] += 1
            for cell in row.cells:
                value(cell, cells.get(cell.field_id), columns.get(cell.field_id), (result.field_id, row.source_key, cell.field_id), row_context)
    return counts


def _report(counts: Counter) -> dict:
    # Fixed keys keep output independent of document, profile and prompt content.
    keys = ("cases", "readable_cases", "readable_present_values", "known_readable_values", "unambiguous_profiles",
            "accepted_values", "correct_accepted_values", "incorrect_accepted_values", "known_readable_values_recovered",
            "readable_present_values_recovered", "automatic_profile_selections", "incorrect_automatic_profile_selections",
            "correct_automatic_profile_selections", "matching_status_errors", "outcome_errors", "schema_errors", "list_structure_errors",
            "confirmed_empty_lists", "scalar_accepted_values", "scalar_incorrect_accepted_values", "list_cell_accepted_values",
            "list_cell_incorrect_accepted_values", "completed_cases", "failed_cases", "cancelled_cases", "timeout_cases", "not_run_cases", "input_refused_cases")
    result = {key: counts[key] for key in keys}
    def rate(numerator, denominator):
        return counts[numerator] / counts[denominator] if counts[denominator] else None
    result["rates"] = {"accepted_value_error": rate("incorrect_accepted_values", "accepted_values"),
                       "automatic_profile_error": rate("incorrect_automatic_profile_selections", "automatic_profile_selections"),
                       "readable_completeness": rate("readable_present_values_recovered", "readable_present_values"),
                       "known_value_recall": rate("known_readable_values_recovered", "known_readable_values"),
                       "profile_selection_recall": rate("correct_automatic_profile_selections", "unambiguous_profiles")}
    result["zero_error_bounds"] = {"accepted_values": zero_error_bound(counts["accepted_values"], counts["incorrect_accepted_values"]),
                                   "automatic_profiles": zero_error_bound(counts["automatic_profile_selections"], counts["incorrect_automatic_profile_selections"])}
    result["value_kinds"] = {kind: {
        "accepted_values": counts[kind + "_accepted_values"], "incorrect_accepted_values": counts[kind + "_incorrect_accepted_values"],
        "known_values": counts[kind + "_known_values"], "known_values_recovered": counts[kind + "_known_values_recovered"],
        "readable_present_values": counts[kind + "_readable_present_values"],
        "readable_present_values_recovered": counts[kind + "_readable_present_values_recovered"],
        "error_rate": rate(kind + "_incorrect_accepted_values", kind + "_accepted_values"),
        "recall": rate(kind + "_known_values_recovered", kind + "_known_values"),
        "readable_completeness": rate(kind + "_readable_present_values_recovered", kind + "_readable_present_values")
    } for kind in ("scalar", "list_cell")}
    return result


def aggregate_metrics(corpus: CorpusManifest | LoadedCorpus, observations: tuple[CaseObservation, ...], *,
                      mode: Mode = "diagnostics", registry: tuple[CorpusManifest, ...] = (),
                      _point: ThresholdPoint | None = None) -> dict:
    """All declared cases remain in denominators. Result contains no case IDs or values."""
    manifest = _gate(corpus, mode, registry)
    ids = {case.case_id for case in manifest.cases}
    observed = {item.case_id: item for item in observations}
    if len(observed) != len(observations) or not set(observed).issubset(ids):
        raise CorpusError("duplicate_or_unknown_observation")
    total = Counter()
    groups: dict[tuple[str, str], Counter] = {}
    for case in manifest.cases:
        counts = _case_counts(case, observed.get(case.case_id), _point)
        total.update(counts)
        for dimension in ("script", "language", "category", "quality", "delivery_path"):
            key = dimension, getattr(case, dimension)
            groups.setdefault(key, Counter()).update(counts)
    return {"mode": mode, "quality_measurement_eligible": mode != "diagnostics", "acceptance_decision": None,
            "ineligibility_reasons": ["diagnostics_only", *manifest.eligibility_reasons("benchmark" if manifest.split == "benchmark" else "calibration")] if mode == "diagnostics" else [],
            "aggregate": _report(total), "groups": [{"dimension": key[0], "label": key[1], **_report(counts)} for key, counts in sorted(groups.items())]}


def risk_coverage_curve(corpus: CorpusManifest | LoadedCorpus, observations: tuple[CaseObservation, ...],
                        points: tuple[ThresholdPoint, ...], *, mode: Literal["diagnostics", "calibration"] = "diagnostics",
                        registry: tuple[CorpusManifest, ...] = ()) -> dict:
    """Diagnostic/tuning sweep only. Thresholds may withhold, never invent accepted values."""
    manifest = corpus.manifest if isinstance(corpus, LoadedCorpus) else corpus
    if manifest.split == "benchmark" or mode not in ("diagnostics", "calibration"):
        raise CorpusError("benchmark_threshold_sweep_forbidden")
    if not points:
        raise CorpusError("explicit_threshold_points_required")
    reports = [aggregate_metrics(corpus, observations, mode=mode, registry=registry, _point=point) for point in points]
    return {"mode": mode, "acceptance_decision": None, "points": [{"index": index, "thresholds": point.model_dump(mode="json"),
            "aggregate": report["aggregate"]} for index, (point, report) in enumerate(zip(points, reports, strict=True))]}
