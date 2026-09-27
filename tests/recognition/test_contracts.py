import json

import pytest
from pydantic import ValidationError

from tgbotdocs.recognition.contracts import (
    BatchResult, ExtractionProfile, FieldResult, FormatValidator, ListField, ListResult, ListRow,
    MatchingResponse, PageMembership, RecognitionResult, ScalarField, job_outcome,
    normalize_value, resolve_matching, validate_batch,
)


def scalar(id="name", type="text", validator=None):
    return ScalarField(id=id, label=id, description="Requested value", type=type, validator=validator)


def profile(fields=None, **updates):
    data = dict(id="p1", owner="u1", version=1, name="Custom document", description="Description",
                original_instruction="Read requested values", fields=fields or (scalar(),))
    data.update(updates)
    return ExtractionProfile(**data)


def test_json_schema_accepts_arrays_but_python_contracts_require_immutable_tuples():
    fixture = {"id": "p1", "owner": "u1", "version": 1, "name": "Certificate", "description": "Custom",
               "original_instruction": "Read values", "fields": [
                   {"id": "n", "label": "Name", "description": "Name", "type": "text"},
                   {"id": "items", "label": "Items", "description": "Records", "type": "list", "columns": [
                       {"id": "amount", "label": "Amount", "description": "Amount", "type": "number"}]}]}
    parsed = ExtractionProfile.model_validate_json(json.dumps(fixture))
    assert isinstance(parsed.fields, tuple) and isinstance(parsed.fields[1].columns, tuple)
    with pytest.raises(ValidationError):
        ExtractionProfile.model_validate(fixture)
    with pytest.raises(ValidationError):
        parsed.fields[0].label = "Changed"
    fixture["fields"][0]["label"] = "Changed outside"
    assert parsed.fields[0].label == "Name"


@pytest.mark.parametrize("mutation", [
    {"unexpected": "value"}, {"version": True}, {"fields": (scalar(), scalar())},
])
def test_profile_rejects_extra_coercion_and_duplicate_ids(mutation):
    with pytest.raises(ValidationError):
        profile(**mutation)


def test_nested_lists_and_undeclared_iso_allowlist_are_rejected():
    nested = ListField(id="items", label="Items", description="Rows", columns=(scalar(),))
    with pytest.raises(ValidationError):
        ListField(id="outer", label="Outer", description="Rows", columns=(nested,))
    with pytest.raises(ValidationError):
        FormatValidator(kind="iso_code")
    with pytest.raises(ValidationError, match="full year"):
        FormatValidator(kind="calendar_date", date_formats=("%d/%m/%y",))


@pytest.mark.parametrize("payload", [
    dict(field_id="name", status="extracted"),
    dict(field_id="name", status="missing", raw_value="guess", source_pages=(1,)),
    dict(field_id="name", status="invalid", raw_value="guess", normalized_value="guess", source_pages=(1,)),
    dict(field_id="name", status="extracted", raw_value=1, source_pages=(1,)),
    dict(field_id="name", status="extracted", raw_value="value", source_pages=(True,)),
    dict(field_id="name", status="extracted", raw_value="value", source_pages=(1, 1)),
])
def test_result_status_value_and_source_invariants(payload):
    with pytest.raises(ValidationError):
        FieldResult(**payload)


def test_invalid_candidate_is_internal_and_external_result_withholds_it():
    invalid = FieldResult(field_id="name", status="invalid", raw_value="unverified", source_pages=(1,))
    result = RecognitionResult(fields=(invalid,), lists=(), outcome="failed")
    assert invalid.raw_value == "unverified" and invalid.accepted_value is None
    assert "unverified" not in json.dumps(result.external())
    with pytest.raises(ValidationError):
        RecognitionResult(fields=(invalid,), lists=(), outcome="complete")


def test_validate_batch_requires_all_requested_ids_and_real_sources():
    requested = profile()
    with pytest.raises(ValueError, match="exactly"):
        validate_batch(BatchResult(page_ids=(1,)), requested, (1,))
    with pytest.raises(ValueError, match="outside|unavailable"):
        validate_batch(BatchResult(page_ids=(1,), fields=(FieldResult(field_id="name", status="extracted", raw_value="a", source_pages=(2,)),)), requested, (1, 2))
    with pytest.raises(ValueError, match="exactly"):
        validate_batch(BatchResult(page_ids=(1,), fields=(FieldResult(field_id="extra", status="missing"),)), requested, (1,))
    with pytest.raises(ValidationError, match="membership"):
        BatchResult(page_ids=(1, 2), page_membership=(PageMembership(page_id=1, status="yes"),))


def test_normalization_is_exact_and_does_not_correct_unicode_or_document_numbers():
    text = "00012 Прізвище العربية 漢字 @name <b>"
    assert normalize_value(scalar(), text) == text
    assert normalize_value(scalar(type="number"), "+0010.2300") == "10.23"
    assert normalize_value(scalar(type="number"), "900719925474099312345.000000000000001") == "900719925474099312345.000000000000001"
    assert normalize_value(scalar(type="number"), "-0.00") == "0"
    for value in ("1,234", "1e2", "NaN", "１２"):
        with pytest.raises(ValueError):
            normalize_value(scalar(type="number"), value)
    with pytest.raises(ValueError):
        normalize_value(scalar(type="boolean"), "true")


def test_date_normalization_requires_a_single_unambiguous_declared_interpretation():
    date_field = scalar(type="date")
    assert normalize_value(date_field, "01/02/2026") == "01/02/2026"
    read = FieldResult(field_id="name", status="extracted", raw_value="01/02/2026", normalized_value="2026-02-01", source_pages=(1,))
    with pytest.raises(ValueError, match="normalization"):
        validate_batch(BatchResult(page_ids=(1,), fields=(read,)), profile((date_field,)), (1,))
    declared = scalar(type="date", validator=FormatValidator(kind="calendar_date", date_formats=("%d/%m/%Y",)))
    assert normalize_value(declared, "01/02/2026") == "2026-02-01"
    conflicting = scalar(type="date", validator=FormatValidator(kind="calendar_date", date_formats=("%d/%m/%Y", "%m/%d/%Y")))
    with pytest.raises(ValueError, match="disagree"):
        normalize_value(conflicting, "01/02/2026")
    invalid = FieldResult(field_id="name", status="extracted", raw_value="2023-02-29", normalized_value="2023-02-29", source_pages=(1,))
    with pytest.raises(ValueError, match="calendar-valid"):
        validate_batch(BatchResult(page_ids=(1,), fields=(invalid,)), profile((date_field,)), (1,))


def test_row_cells_are_exact_requested_columns_and_sources():
    field = ListField(id="items", label="Items", description="Rows", columns=(scalar("name"), scalar("amount", "number")))
    row = ListRow(cells=(FieldResult(field_id="name", status="extracted", raw_value="item", source_pages=(1,)),), source_pages=(1,), source_key="page1:row1")
    result = ListResult(field_id="items", status="complete", rows=(row,), enumeration_complete=True)
    with pytest.raises(ValueError, match="columns"):
        validate_batch(BatchResult(page_ids=(1,), lists=(result,)), profile((field,)), (1,))
    with pytest.raises(ValidationError, match="row sources"):
        ListRow(cells=(FieldResult(field_id="name", status="extracted", raw_value="item", source_pages=(2,)),), source_pages=(1,), source_key="row1")


def test_matching_indices_bind_to_snapshots_and_enforce_status_and_owner():
    snapshots = (profile(), profile(id="p2", version=2))
    assert resolve_matching(MatchingResponse(status="matched", profile_index=2), snapshots) is snapshots[1]
    for index in (0, True):
        with pytest.raises(ValidationError):
            MatchingResponse(status="matched", profile_index=index)
    with pytest.raises(ValueError, match="outside"):
        resolve_matching(MatchingResponse(status="matched", profile_index=3), snapshots)
    with pytest.raises(ValueError, match="one user"):
        resolve_matching(MatchingResponse(status="matched", profile_index=1), (profile(), profile(id="p2", owner="u2")))
    with pytest.raises(ValidationError):
        MatchingResponse(status="uncertain", profile_index=1)
    with pytest.raises(ValidationError):
        MatchingResponse(status="no_profile", type_description=" ")
    with pytest.raises(ValidationError):
        MatchingResponse(status="matched", profile_index=1, confidence=0.99)


def test_outcome_failed_precedes_resolution_and_partial_table_counts_as_success():
    assert job_outcome((FieldResult(field_id="name", status="missing"),), ()) == "failed"
    empty = ListResult(field_id="items", status="complete", rows=(), enumeration_complete=True)
    assert job_outcome((), (empty,)) == "complete"
    row = ListRow(cells=(FieldResult(field_id="name", status="extracted", raw_value="a", source_pages=(1,)),), source_pages=(1,), source_key="row")
    partial = ListResult(field_id="items", status="partial", rows=(row,), enumeration_complete=False)
    assert job_outcome((), (partial,)) == "partial"


def test_final_incomplete_result_cannot_justify_a_missing_list():
    missing = ListResult(field_id="items", status="unresolved", reason="missing", enumeration_complete=True)
    with pytest.raises(ValidationError, match="incomplete traversal"):
        RecognitionResult(fields=(), lists=(missing,), outcome="failed", traversal_complete=False)
    complete = RecognitionResult(fields=(), lists=(missing,), outcome="failed", traversal_complete=True)
    assert complete.lists[0].reason == "missing"


def test_final_incomplete_result_cannot_justify_a_missing_cell_in_a_partial_list():
    row = ListRow(cells=(
        FieldResult(field_id="name", status="extracted", raw_value="Known", source_pages=(1,)),
        FieldResult(field_id="amount", status="missing", source_pages=(1,))),
        source_pages=(1,), source_key="row1")
    partial = ListResult(field_id="items", status="partial", rows=(row,), enumeration_complete=False)
    with pytest.raises(ValidationError, match="incomplete traversal"):
        RecognitionResult(fields=(), lists=(partial,), outcome="partial", traversal_complete=False)
    complete = RecognitionResult(fields=(), lists=(partial,), outcome="partial", traversal_complete=True)
    assert complete.lists[0].rows[0].cells[1].status == "missing"
