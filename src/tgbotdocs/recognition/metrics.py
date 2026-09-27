"""Pure, content-free corpus aggregation; no model calls or acceptance verdicts.

Calibration replays the real production decision for every threshold point and
passes the resulting observations here; this module contains no threshold logic.
"""
from __future__ import annotations

from collections import Counter
from math import expm1, log
from typing import Literal

from pydantic import StrictBool, StrictStr

from .contracts import (ContractModel, FieldResult, ListResult, ListRow, MatchingResponse, RecognitionResult,
                        ScalarField, ListField, normalize_value, resolve_matching, validate_field_result)
from .corpus import (CorpusCase, CorpusError, CorpusManifest, ExpectedList, ExpectedValue, LoadedCorpus,
                     declared_denominators, validate_split_separation)

Mode = Literal["diagnostics", "calibration", "benchmark"]


class CaseObservation(ContractModel):
    """Private in-memory adapter input. Never serialize this model into diagnostics.

    Only a ``completed`` job delivers a result. Matching and recognition recorded for
    any other execution state are ignored (fail closed): an unfinished job contributes
    no accepted values or automatic selections but stays in every denominator.
    """
    case_id: StrictStr
    execution_state: Literal["completed", "failed", "cancelled", "timeout", "not_run", "input_refused"]
    matching: MatchingResponse | None = None
    selected_profile_id: StrictStr | None = None
    automatic_profile_selection: StrictBool = True
    recognition: RecognitionResult | None = None


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
    """An accepted value is correct only if exact (or a declared variant) with contained pages."""
    if result.status != "extracted" or not context or truth is None or field is None or truth.status != "extracted":
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


def _row_score(row: ListRow, truth_row, columns: dict[str, ScalarField], case: CorpusCase, context: bool) -> tuple[int, int, int]:
    """(exactly matching accepted cells, agreeing missing cells, 1) for one admissible pair, else zeros.

    A row with any accepted cell is admissible only through an exactly correct cell;
    agreeing ``missing`` cells then only break ties. A row without accepted cells is
    admissible through agreeing ``missing`` cells.
    """
    if not context or not set(row.source_pages).issubset(truth_row.source_pages):
        return 0, 0, 0
    cells = {cell.field_id: cell for cell in truth_row.cells}
    correct = sum(_matches(cell, cells.get(cell.field_id), columns.get(cell.field_id), case, True) for cell in row.cells)
    missing = sum(cell.status == "missing" and cell.field_id in cells and cells[cell.field_id].status == "missing"
                  for cell in row.cells)
    accepted = any(cell.status == "extracted" for cell in row.cells)
    return (correct, missing, 1) if correct or (missing and not accepted) else (0, 0, 0)


def _blank_row_pairs(result: ListResult, expected: ExpectedList | None, pairs: tuple[int | None, ...]) -> dict[int, int]:
    """Positional pairing, used only for ``false_missing_values``, of unmatched rows that
    carry no accepted cell to unmatched expected rows within the same alignment gap.

    Such rows cannot be aligned by content, so without this their absence claims for
    present values would go uncounted. It never changes accuracy or structure counts.
    """
    if expected is None:
        return {}
    found: dict[int, int] = {}
    gap_actual: list[int] = []
    previous = -1
    for i, index in enumerate((*pairs, len(expected.rows))):
        if i < len(pairs) and index is None:
            if not any(cell.status == "extracted" for cell in result.rows[i].cells):
                gap_actual.append(i)
            continue
        for a, e in zip(gap_actual, range(previous + 1, index), strict=False):
            if set(result.rows[a].source_pages).issubset(expected.rows[e].source_pages):
                found[a] = e
        gap_actual, previous = [], index
    return found


def _align_rows(result: ListResult, expected: ExpectedList | None, columns: dict[str, ScalarField],
               case: CorpusCase, context: bool) -> tuple[int | None, ...]:
    """Monotone alignment of actual rows to expected rows, both in document order.

    Actual ``source_key`` values are batch-derived and never used. The dynamic program
    maximizes, lexicographically, exactly matching accepted cells, then agreeing
    ``missing`` cells, then paired rows. A row with accepted cells needs an exactly
    correct cell to pair, so a row whose every accepted cell is wrong stays unmatched
    (an extra row) whether or not it also has blank columns. Ties prefer
    pairing, then skipping the actual row. Returns the expected index per actual row.
    """
    actual = result.rows
    truth = expected.rows if expected else ()
    n, m = len(actual), len(truth)
    zero = (0, 0, 0)
    weight = [[_row_score(actual[i], truth[j], columns, case, context) for j in range(m)] for i in range(n)]
    best = [[zero] * (m + 1) for _ in range(n + 1)]
    for i in range(n - 1, -1, -1):
        for j in range(m - 1, -1, -1):
            options = [best[i + 1][j], best[i][j + 1]]
            if weight[i][j] != zero:
                w, rest = weight[i][j], best[i + 1][j + 1]
                options.insert(0, (w[0] + rest[0], w[1] + rest[1], w[2] + rest[2]))
            best[i][j] = max(options)  # max returns the first maximal option: pair, skip actual, skip expected
    pairs: list[int | None] = [None] * n
    i = j = 0
    while i < n and j < m:
        w, rest = weight[i][j], best[i + 1][j + 1]
        if w != zero and best[i][j] == (w[0] + rest[0], w[1] + rest[1], w[2] + rest[2]):
            pairs[i] = j
            i, j = i + 1, j + 1
        elif best[i][j] == best[i + 1][j]:
            i += 1
        else:
            j += 1
    return tuple(pairs)


def _case_counts(case: CorpusCase, observation: CaseObservation | None) -> Counter:
    counts = Counter(cases=1, readable_cases=int(case.quality == "readable"))
    denominator = declared_denominators((case,))
    counts.update(denominator.model_dump(exclude={"cases", "readable_cases"}))
    truth = case.expected
    if truth:
        for kind, values in (("scalar", truth.fields), ("list_cell", tuple(cell for item in truth.lists for row in item.rows for cell in row.cells))):
            counts[kind + "_known_values"] += sum(v.status == "extracted" for v in values)
            counts[kind + "_readable_present_values"] += sum(v.present is True for v in values) if case.quality == "readable" else 0
    if observation is None:
        observation = CaseObservation(case_id=case.case_id, execution_state="not_run")
    counts[observation.execution_state + "_cases"] += 1
    delivered = observation.execution_state == "completed"
    matching = observation.matching if delivered else None
    recognition = observation.recognition if delivered else None
    automatic, context = _profile(case, observation) if delivered else (False, False)
    if automatic:
        counts["automatic_profile_selections"] += 1
        counts["incorrect_automatic_profile_selections"] += int(not context)
        counts["correct_automatic_profile_selections"] += int(context)
    actual_matching = "input_refused" if observation.execution_state == "input_refused" else (matching.status if matching else None)
    if truth:
        counts["matching_status_errors"] += int(actual_matching != truth.matching)
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

    def value(result, expected, field, identity, kind, valid_context):
        # Scalars in the correct profile context and cells of content-aligned rows; blank
        # unaligned rows are counted through ``_blank_row_pairs`` in the list loop.
        if valid_context and result.status == "missing" and expected is not None and expected.present is True:
            counts["false_missing_values"] += 1  # A present value was reported absent.
        if result.status != "extracted":
            return
        counts["accepted_values"] += 1
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
        value(result, expected_fields.get(result.field_id), fields.get(result.field_id), ("field", result.field_id), "scalar", context)
    list_ids = [r.field_id for r in recognition.lists]
    if set(list_ids) != set(expected_lists) or len(list_ids) != len(set(list_ids)):
        counts["schema_errors"] += 1
    for result in recognition.lists:
        expected = expected_lists.get(result.field_id)
        columns = {column.id: column for column in lists[result.field_id].columns} if result.field_id in lists else {}
        pairs = _align_rows(result, expected, columns, case, context)
        matched = {index for index in pairs if index is not None}
        extra_accepted = any(index is None and any(cell.status == "extracted" for cell in row.cells)
                             for row, index in zip(result.rows, pairs, strict=True))
        exact = expected is not None and None not in pairs and len(matched) == len(expected.rows)
        if (expected is None or extra_accepted
                or result.status == "complete" and not (exact and expected.status == "complete")):
            counts["list_structure_errors"] += 1
        if expected and not expected.rows and expected.status == "complete" and result.status == "complete" and not result.rows and context:
            counts["confirmed_empty_lists"] += 1
        blank = _blank_row_pairs(result, expected, pairs) if context else {}
        for position, (row, index) in enumerate(zip(result.rows, pairs, strict=True)):
            if set(columns) != {cell.field_id for cell in row.cells}:
                counts["schema_errors"] += 1
            if index is None and position in blank:
                # No accepted cells: only reported absence of present values is counted.
                blank_truth = {cell.field_id: cell for cell in expected.rows[blank[position]].cells}
                counts["false_missing_values"] += sum(cell.status == "missing" and cell.field_id in blank_truth
                                                      and blank_truth[cell.field_id].present is True for cell in row.cells)
            truth_row = expected.rows[index] if index is not None else None
            cells = {cell.field_id: cell for cell in truth_row.cells} if truth_row else {}
            for cell in row.cells:
                # Cells of an unmatched (extra) row have no truth and are therefore incorrect.
                value(cell, cells.get(cell.field_id), columns.get(cell.field_id),
                      ("cell", result.field_id, index, cell.field_id), "list_cell", context and truth_row is not None)
    return counts


def _report(counts: Counter) -> dict:
    # Fixed keys keep output independent of document, profile and prompt content.
    keys = ("cases", "readable_cases", "readable_present_values", "known_readable_values", "unambiguous_profiles",
            "accepted_values", "correct_accepted_values", "incorrect_accepted_values", "known_readable_values_recovered",
            "readable_present_values_recovered", "automatic_profile_selections", "incorrect_automatic_profile_selections",
            "correct_automatic_profile_selections", "matching_status_errors", "outcome_errors", "schema_errors", "list_structure_errors",
            "confirmed_empty_lists", "false_missing_values", "scalar_accepted_values", "scalar_incorrect_accepted_values",
            "list_cell_accepted_values", "list_cell_incorrect_accepted_values", "completed_cases", "failed_cases",
            "cancelled_cases", "timeout_cases", "not_run_cases", "input_refused_cases")
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
        "readable_completeness": rate(kind + "_readable_present_values_recovered", kind + "_readable_present_values"),
        "zero_error_bound": zero_error_bound(counts[kind + "_accepted_values"], counts[kind + "_incorrect_accepted_values"]),
    } for kind in ("scalar", "list_cell")}
    return result


def aggregate_metrics(corpus: CorpusManifest | LoadedCorpus, observations: tuple[CaseObservation, ...], *,
                      mode: Mode = "diagnostics", registry: tuple[CorpusManifest, ...] = ()) -> dict:
    """All declared cases remain in denominators. Result contains no case IDs or values."""
    manifest = _gate(corpus, mode, registry)
    ids = {case.case_id for case in manifest.cases}
    observed = {item.case_id: item for item in observations}
    if len(observed) != len(observations) or not set(observed).issubset(ids):
        raise CorpusError("duplicate_or_unknown_observation")
    total = Counter()
    groups: dict[tuple[str, str], Counter] = {}
    for case in manifest.cases:
        counts = _case_counts(case, observed.get(case.case_id))
        total.update(counts)
        for dimension in ("script", "language", "category", "quality", "delivery_path"):
            key = dimension, getattr(case, dimension)
            groups.setdefault(key, Counter()).update(counts)
    return {"mode": mode, "quality_measurement_eligible": mode != "diagnostics", "acceptance_decision": None,
            "ineligibility_reasons": ["diagnostics_only", *manifest.eligibility_reasons("benchmark" if manifest.split == "benchmark" else "calibration")] if mode == "diagnostics" else [],
            "aggregate": _report(total), "groups": [{"dimension": key[0], "label": key[1], **_report(counts)} for key, counts in sorted(groups.items())]}
