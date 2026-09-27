"""Content-free aggregation and fail-closed threshold edge cases."""
import json
import math

import pytest
from pydantic import ValidationError

from test_corpus import make_case, manifest
from tgbotdocs.recognition.contracts import FieldResult, ListRow, ListResult, MatchingResponse, RecognitionResult
from tgbotdocs.recognition.corpus import ExpectedRow, ExpectedValue, CorpusError
from tgbotdocs.recognition.metrics import (CaseObservation, Evidence, ValueEvidence, ThresholdPoint,
                                         aggregate_metrics, risk_coverage_curve, zero_error_bound)


def observation(identity="case-1", *, value="PRIVATE-CODE", rows=None, **kwargs):
    args = dict(case_id=identity, execution_state="completed", matching=MatchingResponse(status="matched", profile_index=1),
                selected_profile_id="profile")
    if rows is None:
        args["recognition"] = RecognitionResult(fields=(FieldResult(field_id="code", status="extracted", raw_value=value, source_pages=(1,)),), lists=(), outcome="complete")
    else:
        args["recognition"] = RecognitionResult(fields=(), lists=(ListResult(field_id="items", status="complete", enumeration_complete=True, rows=rows),), outcome="complete")
    args.update(kwargs)
    return CaseObservation(**args)


def row(key, value):
    return ListRow(source_key=key, source_pages=(1,), cells=(FieldResult(field_id="code", status="extracted", raw_value=value, source_pages=(1,)),))


def expected_row(key, value):
    return ExpectedRow(source_key=key, source_pages=(1,), cells=(ExpectedValue(field_id="code", status="extracted", present=True, value=value, source_pages=(1,)),))


def test_report_contains_only_counts_controlled_groups_and_no_document_content():
    report = aggregate_metrics(manifest(make_case()), (observation(),))
    assert report["aggregate"]["correct_accepted_values"] == 1
    assert report["aggregate"]["rates"]["readable_completeness"] == 1
    assert not report["quality_measurement_eligible"] and report["acceptance_decision"] is None
    serialized = json.dumps(report)
    assert "PRIVATE-CODE" not in serialized and "case-1" not in serialized and "test-owner" not in serialized
    assert len(report["groups"]) == 5


def test_omitted_execution_retains_denominators_and_abstention_is_not_false_success():
    corpus = manifest(make_case(), make_case("case-2"))
    counts = aggregate_metrics(corpus, (observation(),))["aggregate"]
    assert counts["cases"] == 2 and counts["known_readable_values"] == 2
    assert counts["not_run_cases"] == 1 and counts["rates"]["known_value_recall"] == .5
    assert aggregate_metrics(corpus, ())["aggregate"]["rates"]["accepted_value_error"] is None


def test_negative_profile_selection_and_hallucinated_values_count_errors():
    corpus = manifest(make_case(negative=True, quality="negative"))
    counts = aggregate_metrics(corpus, (observation(),))["aggregate"]
    assert counts["incorrect_automatic_profile_selections"] == 1
    assert counts["incorrect_accepted_values"] == 1
    assert counts["known_readable_values"] == 0 and counts["rates"]["known_value_recall"] is None
    refusal = CaseObservation(case_id="case-1", execution_state="completed", matching=MatchingResponse(status="not_document"))
    counts = aggregate_metrics(corpus, (refusal,))["aggregate"]
    assert counts["matching_status_errors"] == counts["accepted_values"] == 0


def test_wrong_profile_context_makes_even_correct_text_incorrect():
    counts = aggregate_metrics(manifest(make_case()), (observation(selected_profile_id="other"),))["aggregate"]
    assert counts["incorrect_accepted_values"] == counts["incorrect_automatic_profile_selections"] == 1


def test_unicode_exactness_and_explicit_variants():
    expected = ExpectedValue(field_id="code", status="extracted", present=True, value="北京", allowed_values=("北京市",), source_pages=(1,))
    corpus = manifest(make_case(values=(expected,)))
    assert aggregate_metrics(corpus, (observation(value="北京市"),))["aggregate"]["correct_accepted_values"] == 1
    assert aggregate_metrics(corpus, (observation(value="Beijing"),))["aggregate"]["incorrect_accepted_values"] == 1


@pytest.mark.parametrize("actual,correct,errors", [
    ((row("r1", "A"), row("r2", "B")), 2, 0),
    ((row("r1", "B"), row("r2", "A")), 0, 2),
    ((row("r2", "B"), row("r1", "A")), 0, 2),
    ((row("r1", "A"), row("r1", "A")), 0, 2),
    ((row("r1", "A"), row("r2", "B"), row("extra", "C")), 2, 1),
])
def test_list_row_association_order_duplicates_and_extra_cells(actual, correct, errors):
    corpus = manifest(make_case(rows=(expected_row("r1", "A"), expected_row("r2", "B"))))
    counts = aggregate_metrics(corpus, (observation(rows=actual),))["aggregate"]
    assert counts["correct_accepted_values"] == correct
    assert counts["incorrect_accepted_values"] == errors
    assert counts["known_readable_values"] == 2
    if errors:
        assert counts["rates"]["known_value_recall"] <= 1


def test_empty_list_has_zero_value_denominator_and_no_fabricated_confidence():
    counts = aggregate_metrics(manifest(make_case(rows=())), (observation(rows=()),))["aggregate"]
    assert counts["confirmed_empty_lists"] == 1
    assert counts["accepted_values"] == counts["known_readable_values"] == 0
    assert counts["zero_error_bounds"]["accepted_values"]["upper_exact"] is None
    wrong = aggregate_metrics(manifest(make_case(rows=(expected_row("r1", "A"),))), (observation(rows=()),))["aggregate"]
    assert wrong["list_structure_errors"] == 1 and wrong["rates"]["known_value_recall"] == 0


def test_partial_list_does_not_change_declared_denominator():
    result = RecognitionResult(fields=(), lists=(ListResult(field_id="items", status="partial", enumeration_complete=False, rows=(row("r2", "B"),)),), outcome="partial")
    corpus = manifest(make_case(rows=(expected_row("r1", "A"), expected_row("r2", "B"))))
    counts = aggregate_metrics(corpus, (observation(recognition=result),))["aggregate"]
    assert counts["correct_accepted_values"] == 1 and counts["rates"]["known_value_recall"] == .5


def test_bounds_are_exact_and_no_zero_sample_claim():
    assert zero_error_bound(0, 0)["upper_exact"] is None
    assert zero_error_bound(70, 0)["upper_exact"] == pytest.approx(1 - .05 ** (1 / 70))
    assert zero_error_bound(70, 1)["upper_exact"] is None
    for counts in ((-1, 0), (2, 3), (True, 0)):
        with pytest.raises(ValueError):
            zero_error_bound(*counts)


def test_thresholds_fail_closed_and_do_not_upgrade_uncertain_values():
    corpus = manifest(make_case())
    points = (ThresholdPoint(signals=(Evidence(signal="V1", score=.5),)), ThresholdPoint(signals=(Evidence(signal="V1", score=.9),)))
    item = observation(value_evidence=(ValueEvidence(field_id="code", evidence=(Evidence(signal="V1", score=.8),)),))
    curve = risk_coverage_curve(corpus, (item,), points)
    assert [point["aggregate"]["accepted_values"] for point in curve["points"]] == [1, 0]
    assert [point["aggregate"]["known_readable_values"] for point in curve["points"]] == [1, 1]
    assert risk_coverage_curve(corpus, (observation(),), points)["points"][0]["aggregate"]["accepted_values"] == 0
    uncertain = RecognitionResult(fields=(FieldResult(field_id="code", status="ambiguous"),), lists=(), outcome="failed")
    assert risk_coverage_curve(corpus, (observation(recognition=uncertain),), points)["points"][0]["aggregate"]["accepted_values"] == 0
    margin = (ThresholdPoint(matching_minimum_margin=.7),)
    assert risk_coverage_curve(corpus, (observation(matching_margin=.5),), margin)["points"][0]["aggregate"]["accepted_values"] == 0


def test_threshold_input_errors_and_benchmark_sweeps_forbidden():
    for score in (math.nan, math.inf, -.1, 1.1):
        with pytest.raises(ValidationError):
            Evidence(signal="V1", score=score)
    with pytest.raises(ValidationError):
        ThresholdPoint(signals=(Evidence(signal="V1", score=.1), Evidence(signal="V1", score=.2)))
    with pytest.raises(CorpusError, match="benchmark_threshold_sweep"):
        risk_coverage_curve(manifest(make_case(), split="benchmark"), (), (ThresholdPoint(matching_minimum_margin=.5),))


def test_quality_gate_and_unknown_duplicate_observations():
    corpus = manifest(make_case())
    with pytest.raises(CorpusError, match="ineligible"):
        aggregate_metrics(corpus, (), mode="calibration")
    for observations in ((observation(), observation()), (observation("unknown"),)):
        with pytest.raises(CorpusError, match="duplicate_or_unknown"):
            aggregate_metrics(corpus, observations)
