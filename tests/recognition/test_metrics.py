"""Content-free aggregation, monotone row alignment and ACCEPTANCE_PLAN counting rules."""
import json

import pytest

from test_corpus import make_case, manifest
from tgbotdocs.recognition import metrics
from tgbotdocs.recognition.contracts import (ExtractionProfile, FieldResult, ListField, ListResult, ListRow,
                                             MatchingResponse, RecognitionResult, ScalarField)
from tgbotdocs.recognition.corpus import CorpusError, ExpectedOutcome, ExpectedRow, ExpectedValue
from tgbotdocs.recognition.metrics import CaseObservation, aggregate_metrics, zero_error_bound

CODE = ScalarField(id="code", label="Code", description="Printed code", type="text")
QTY = ScalarField(id="qty", label="Quantity", description="Printed quantity", type="text")


def observation(identity="case-1", *, value="PRIVATE-CODE", rows=None, status="complete", **kwargs):
    args = dict(case_id=identity, execution_state="completed", matching=MatchingResponse(status="matched", profile_index=1),
                selected_profile_id="profile")
    if rows is None:
        args["recognition"] = RecognitionResult(fields=(FieldResult(field_id="code", status="extracted", raw_value=value, source_pages=(1,)),), lists=(), outcome="complete")
    else:
        complete = status == "complete"
        args["recognition"] = RecognitionResult(fields=(), lists=(ListResult(field_id="items", status=status, enumeration_complete=complete, rows=rows),),
                                                outcome="complete" if complete else "partial")
    args.update(kwargs)
    return CaseObservation(**args)


def cell(column, value, pages=(1,)):
    if value is None:
        return FieldResult(field_id=column, status="missing")
    if value == "?":
        return FieldResult(field_id=column, status="ambiguous")
    return FieldResult(field_id=column, status="extracted", raw_value=value, source_pages=pages)


def row(index, *values, pages=(1,)):
    """Batch-derived keys, exactly as the merge layer produces them; never truth identifiers."""
    columns = ("code", "qty")[:len(values)]
    return ListRow(source_key=f"batch:{pages[0]}:row:{index}", source_pages=pages,
                   cells=tuple(cell(c, v, pages) for c, v in zip(columns, values, strict=True)))


def truth_cell(column, value, pages=(1,)):
    if value is None:
        return ExpectedValue(field_id=column, status="missing", present=False)
    return ExpectedValue(field_id=column, status="extracted", present=True, value=value, source_pages=pages)


def expected_row(key, *values, pages=(1,)):
    columns = ("code", "qty")[:len(values)]
    return ExpectedRow(source_key=key, source_pages=pages, cells=tuple(truth_cell(c, v, pages) for c, v in zip(columns, values, strict=True)))


def list_case(*rows, columns=(CODE,), page_ids=(1,)):
    profile = ExtractionProfile(id="profile", owner="test-owner", version=1, name="Test", description="Synthetic test",
                                original_instruction="Read printed rows",
                                fields=(ListField(id="items", label="Items", description="Printed rows", columns=columns),))
    return manifest(make_case(rows=rows, profiles=(profile,), page_ids=page_ids))


def counts_for(corpus, *observations):
    return aggregate_metrics(corpus, observations)["aggregate"]


def test_report_contains_only_counts_controlled_groups_and_no_document_content():
    report = aggregate_metrics(manifest(make_case()), (observation(),))
    assert report["aggregate"]["correct_accepted_values"] == 1
    assert report["aggregate"]["rates"]["readable_completeness"] == 1
    assert not report["quality_measurement_eligible"] and report["acceptance_decision"] is None
    serialized = json.dumps(report)
    assert "PRIVATE-CODE" not in serialized and "case-1" not in serialized and "test-owner" not in serialized
    assert len(report["groups"]) == 5


def test_evidence_threshold_path_is_removed_and_observation_fields_are_stable():
    for name in ("ThresholdPoint", "Evidence", "ValueEvidence", "risk_coverage_curve"):
        assert not hasattr(metrics, name)
    assert set(CaseObservation.model_fields) == {"case_id", "execution_state", "matching", "selected_profile_id",
                                                 "automatic_profile_selection", "recognition"}


def test_omitted_execution_retains_denominators_and_abstention_is_not_false_success():
    corpus = manifest(make_case(), make_case("case-2"))
    counts = counts_for(corpus, observation())
    assert counts["cases"] == 2 and counts["known_readable_values"] == 2
    assert counts["not_run_cases"] == 1 and counts["rates"]["known_value_recall"] == .5
    assert aggregate_metrics(corpus, ())["aggregate"]["rates"]["accepted_value_error"] is None


def test_missing_observation_counts_exactly_like_an_explicit_not_run():
    corpus = manifest(make_case(), make_case("negative", negative=True, quality="negative"))
    explicit = (CaseObservation(case_id="case-1", execution_state="not_run"), CaseObservation(case_id="negative", execution_state="not_run"))
    assert aggregate_metrics(corpus, ()) == aggregate_metrics(corpus, explicit)
    counts = counts_for(corpus)
    assert counts["matching_status_errors"] == 2 and counts["outcome_errors"] == 1 and counts["not_run_cases"] == 2


@pytest.mark.parametrize("state", ["failed", "cancelled", "timeout", "not_run"])
def test_unfinished_jobs_deliver_nothing_but_stay_in_denominators(state):
    corpus = manifest(make_case())
    counts = counts_for(corpus, observation(execution_state=state))
    assert counts[state + "_cases"] == 1
    assert counts["accepted_values"] == counts["automatic_profile_selections"] == 0
    assert counts["readable_present_values"] == 1 and counts["rates"]["readable_completeness"] == 0
    assert counts["matching_status_errors"] == counts["outcome_errors"] == 1


def test_negative_profile_selection_and_hallucinated_values_count_errors():
    corpus = manifest(make_case(negative=True, quality="negative"))
    counts = counts_for(corpus, observation())
    assert counts["incorrect_automatic_profile_selections"] == 1
    assert counts["incorrect_accepted_values"] == 1
    assert counts["known_readable_values"] == 0 and counts["rates"]["known_value_recall"] is None
    refusal = CaseObservation(case_id="case-1", execution_state="completed", matching=MatchingResponse(status="not_document"))
    counts = counts_for(corpus, refusal)
    assert counts["matching_status_errors"] == counts["accepted_values"] == 0


def test_input_refusal_is_a_correct_matching_status_only_when_expected():
    refused = ExpectedOutcome(matching="input_refused", outcome="refused")
    observed = CaseObservation(case_id="case-1", execution_state="input_refused")
    assert counts_for(manifest(make_case(expected=refused, quality="negative")), observed)["matching_status_errors"] == 0
    counts = counts_for(manifest(make_case()), observed)
    assert counts["matching_status_errors"] == counts["outcome_errors"] == 1 and counts["rates"]["readable_completeness"] == 0


def test_wrong_profile_context_makes_even_correct_text_incorrect():
    counts = counts_for(manifest(make_case()), observation(selected_profile_id="other"))
    assert counts["incorrect_accepted_values"] == counts["incorrect_automatic_profile_selections"] == 1


def test_unicode_exactness_and_explicit_variants():
    expected = ExpectedValue(field_id="code", status="extracted", present=True, value="北京", allowed_values=("北京市",), source_pages=(1,))
    corpus = manifest(make_case(values=(expected,)))
    assert counts_for(corpus, observation(value="北京市"))["correct_accepted_values"] == 1
    assert counts_for(corpus, observation(value="Beijing"))["incorrect_accepted_values"] == 1


def test_extra_field_and_unjustified_normalization_are_acceptance_errors():
    corpus = manifest(make_case())
    extra = RecognitionResult(fields=(cell("code", "PRIVATE-CODE"), cell("extra", "PRIVATE-CODE")), lists=(), outcome="complete")
    counts = counts_for(corpus, observation(recognition=extra))
    assert counts["correct_accepted_values"] == counts["incorrect_accepted_values"] == counts["schema_errors"] == 1
    renormalized = FieldResult(field_id="code", status="extracted", raw_value="PRIVATE-CODE", normalized_value="PRIVATE CODE", source_pages=(1,))
    counts = counts_for(corpus, observation(recognition=RecognitionResult(fields=(renormalized,), lists=(), outcome="complete")))
    assert counts["incorrect_accepted_values"] == 1 and counts["correct_accepted_values"] == 0


def test_reported_absence_of_a_present_value_is_counted_separately():
    missing = RecognitionResult(fields=(cell("code", None),), lists=(), outcome="failed")
    counts = counts_for(manifest(make_case()), observation(recognition=missing))
    assert counts["false_missing_values"] == 1 and counts["accepted_values"] == 0
    assert counts["rates"]["readable_completeness"] == 0


@pytest.mark.parametrize("actual,correct,errors,structure", [
    ((row(0, "A"), row(1, "B")), 2, 0, 0),
    ((row(0, "B"), row(1, "A")), 1, 1, 1),  # Order is document order: a swap cannot be fully aligned.
    ((row(0, "A"), row(1, "A")), 1, 1, 1),  # A duplicate is an extra row; B is missing.
    ((row(0, "A"), row(1, "B"), row(2, "C")), 2, 1, 1),
    ((row(0, "A"),), 1, 0, 1),  # A complete list with a missing row.
    ((row(0, "X"), row(1, "B")), 1, 1, 1),
    ((row(0, "A"), row(1, "?")), 1, 0, 0),  # An unreadable row in a partial list is abstention.
])
def test_rows_align_monotonically_by_content_not_by_keys(actual, correct, errors, structure):
    corpus = list_case(expected_row("r1", "A"), expected_row("r2", "B"))
    status = "complete" if all(c.status == "extracted" for r in actual for c in r.cells) else "partial"
    counts = counts_for(corpus, observation(rows=actual, status=status))
    assert (counts["correct_accepted_values"], counts["incorrect_accepted_values"], counts["list_structure_errors"]) == (correct, errors, structure)
    assert counts["known_readable_values"] == 2 and counts["readable_present_values"] == 2


def test_batch_keys_that_collide_with_truth_keys_do_not_decide_association():
    corpus = list_case(expected_row("r1", "A"), expected_row("r2", "B"))
    misleading = (ListRow(source_key="r2", source_pages=(1,), cells=(cell("code", "A"),)),
                  ListRow(source_key="r1", source_pages=(1,), cells=(cell("code", "B"),)))
    counts = counts_for(corpus, observation(rows=misleading))
    assert counts["correct_accepted_values"] == 2 and counts["incorrect_accepted_values"] == counts["list_structure_errors"] == 0


def test_identical_rows_are_distinct_by_position():
    corpus = list_case(expected_row("r1", "A"), expected_row("r2", "A"), expected_row("r3", "B"))
    exact = counts_for(corpus, observation(rows=(row(0, "A"), row(1, "A"), row(2, "B"))))
    assert exact["correct_accepted_values"] == 3 and exact["list_structure_errors"] == 0
    extra = counts_for(corpus, observation(rows=(row(0, "A"), row(1, "A"), row(2, "A"), row(3, "B"))))
    assert (extra["correct_accepted_values"], extra["incorrect_accepted_values"], extra["list_structure_errors"]) == (3, 1, 1)
    partial = counts_for(corpus, observation(rows=(row(0, "A"), row(1, "B")), status="partial"))
    assert (partial["correct_accepted_values"], partial["incorrect_accepted_values"], partial["list_structure_errors"]) == (2, 0, 0)


def test_alignment_maximizes_correct_cells_instead_of_taking_the_first_admissible_pair():
    corpus = list_case(expected_row("r1", "A", "1"), expected_row("r2", "B", "2"), columns=(CODE, QTY))
    # Greedy earliest pairing would bind the first row to r2 through its quantity and orphan the exact row.
    counts = counts_for(corpus, observation(rows=(row(0, "C", "2"), row(1, "B", "2")), status="partial"))
    assert (counts["correct_accepted_values"], counts["incorrect_accepted_values"]) == (2, 2)
    assert counts["list_structure_errors"] == 1 and counts["value_kinds"]["list_cell"]["recall"] == .5


def test_partly_wrong_row_keeps_its_association_and_wrong_cells_are_errors():
    corpus = list_case(expected_row("r1", "A", "1"), expected_row("r2", "B", "2"), columns=(CODE, QTY))
    counts = counts_for(corpus, observation(rows=(row(0, "A", "9"), row(1, "B", "2"))))
    assert (counts["correct_accepted_values"], counts["incorrect_accepted_values"], counts["list_structure_errors"]) == (3, 1, 0)


def test_agreeing_missing_cells_associate_rows_for_list_completeness():
    corpus = list_case(expected_row("r1", "A", "1"), expected_row("r2", None, None), columns=(CODE, QTY))
    counts = counts_for(corpus, observation(rows=(row(0, "A", "1"), row(1, None, None))))
    assert counts["correct_accepted_values"] == 2 and counts["list_structure_errors"] == counts["false_missing_values"] == 0


def test_hallucinated_row_with_a_blank_column_is_an_extra_row_like_one_without():
    blank = list_case(expected_row("r1", "A", None), expected_row("r2", "B", None), columns=(CODE, QTY))
    with_blank = counts_for(blank, observation(rows=(row(0, "A", None), row(1, "Z", None))))
    full = list_case(expected_row("r1", "A", "1"), expected_row("r2", "B", "2"), columns=(CODE, QTY))
    without_blank = counts_for(full, observation(rows=(row(0, "A", "1"), row(1, "Z", "9"))))
    assert (with_blank["correct_accepted_values"], with_blank["incorrect_accepted_values"], with_blank["list_structure_errors"]) == (1, 1, 1)
    assert (without_blank["correct_accepted_values"], without_blank["incorrect_accepted_values"], without_blank["list_structure_errors"]) == (2, 2, 1)


def test_blank_row_for_a_present_row_counts_false_missing_values():
    corpus = list_case(expected_row("r1", "A", "1"), expected_row("r2", "B", "2"), columns=(CODE, QTY))
    counts = counts_for(corpus, observation(rows=(row(0, "A", "1"), row(1, None, None)), status="partial"))
    assert counts["false_missing_values"] == 2 and counts["list_structure_errors"] == 0
    assert (counts["correct_accepted_values"], counts["incorrect_accepted_values"]) == (2, 0)
    # A blank row with no unmatched expected row left in its gap is not paired.
    extra = counts_for(corpus, observation(rows=(row(0, "A", "1"), row(1, "B", "2"), row(2, None, None)), status="partial"))
    assert extra["false_missing_values"] == 0 and extra["correct_accepted_values"] == 4


def test_rows_outside_expected_pages_are_not_associated():
    corpus = list_case(expected_row("r1", "A", pages=(1,)), page_ids=(1, 2))
    counts = counts_for(corpus, observation(rows=(row(0, "A", pages=(2,)),)))
    assert (counts["correct_accepted_values"], counts["incorrect_accepted_values"], counts["list_structure_errors"]) == (0, 1, 1)
    continued = list_case(expected_row("r1", "A", pages=(1, 2)), page_ids=(1, 2))
    assert counts_for(continued, observation(rows=(row(0, "A", pages=(1, 2)),)))["correct_accepted_values"] == 1


def test_duplicate_list_results_never_earn_credit_twice():
    corpus = list_case(expected_row("r1", "A"))
    result = ListResult(field_id="items", status="complete", enumeration_complete=True, rows=(row(0, "A"),))
    recognition = RecognitionResult(fields=(), lists=(result, result), outcome="complete")
    counts = counts_for(corpus, observation(recognition=recognition))
    assert (counts["correct_accepted_values"], counts["incorrect_accepted_values"], counts["schema_errors"]) == (1, 1, 1)


def test_empty_list_has_zero_value_denominator_and_no_fabricated_confidence():
    counts = counts_for(manifest(make_case(rows=())), observation(rows=()))
    assert counts["confirmed_empty_lists"] == 1
    assert counts["accepted_values"] == counts["known_readable_values"] == 0
    assert counts["zero_error_bounds"]["accepted_values"]["upper_exact"] is None
    wrong = counts_for(manifest(make_case(rows=(expected_row("r1", "A"),))), observation(rows=()))
    assert wrong["list_structure_errors"] == 1 and wrong["rates"]["known_value_recall"] == 0


def test_partial_list_does_not_change_declared_denominator():
    corpus = list_case(expected_row("r1", "A"), expected_row("r2", "B"))
    counts = counts_for(corpus, observation(rows=(row(0, "B"),), status="partial"))
    assert counts["correct_accepted_values"] == 1 and counts["rates"]["known_value_recall"] == .5
    assert counts["list_structure_errors"] == 0


def test_groups_and_value_kinds_report_their_own_sample_size_and_bound():
    corpus = manifest(make_case(), make_case("case-2", script="Arabic", language="ar"))
    report = aggregate_metrics(corpus, (observation(), observation("case-2", value="WRONG")))
    scripts = {group["label"]: group for group in report["groups"] if group["dimension"] == "script"}
    assert scripts["Latin"]["zero_error_bounds"]["accepted_values"]["samples"] == 1
    assert scripts["Latin"]["zero_error_bounds"]["accepted_values"]["upper_exact"] == pytest.approx(.95)
    assert scripts["Arabic"]["incorrect_accepted_values"] == 1
    assert scripts["Arabic"]["zero_error_bounds"]["accepted_values"]["upper_exact"] is None
    scalar = report["aggregate"]["value_kinds"]["scalar"]
    assert scalar["zero_error_bound"]["samples"] == 2 and scalar["zero_error_bound"]["errors"] == 1


def test_bounds_are_exact_and_no_zero_sample_claim():
    assert zero_error_bound(0, 0)["upper_exact"] is None
    assert zero_error_bound(70, 0)["upper_exact"] == pytest.approx(1 - .05 ** (1 / 70))
    assert zero_error_bound(70, 1)["upper_exact"] is None
    for counts in ((-1, 0), (2, 3), (True, 0)):
        with pytest.raises(ValueError):
            zero_error_bound(*counts)


def test_quality_gate_and_unknown_duplicate_observations():
    corpus = manifest(make_case())
    with pytest.raises(CorpusError, match="ineligible"):
        aggregate_metrics(corpus, (), mode="calibration")
    for observations in ((observation(), observation()), (observation("unknown"),)):
        with pytest.raises(CorpusError, match="duplicate_or_unknown"):
            aggregate_metrics(corpus, observations)
