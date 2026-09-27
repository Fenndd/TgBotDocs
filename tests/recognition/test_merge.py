import pytest

from tgbotdocs.recognition.contracts import (
    BatchResult, ExtractionProfile, FieldResult, ListField, ListResult, ListRow, PageMembership, ScalarField,
)
from tgbotdocs.recognition.merge import MixedDocumentError, merge_batches, merge_list, merge_scalar


def field(id="name", type="text"):
    return ScalarField(id=id, label=id, description="Requested", type=type)


def reading(value=None, status="extracted", page=1, id="name"):
    return FieldResult(field_id=id, status=status, raw_value=value, source_pages=(page,))


def table():
    return ListField(id="items", label="Items", description="Rows", columns=(field(), field("amount", "number")))


def row(key, page, name="Item", amount="10", previous=False, next=False):
    cells = (reading(name, "extracted" if name is not None else "missing", page),
             reading(amount, "extracted" if amount is not None else "missing", page, "amount"))
    return ListRow(cells=cells, source_pages=(page,), source_key=key, continues_previous=previous, continues_next=next)


def listing(rows=(), complete=True, status="complete", reason=None):
    return ListResult(field_id="items", rows=rows, status=status, enumeration_complete=complete, reason=reason)


@pytest.mark.parametrize("statuses,complete,expected", [
    (("missing", "missing"), True, "missing"),
    (("missing", "missing"), False, "unreadable"),
    (("missing", "unreadable"), True, "unreadable"),
    (("missing", "ambiguous"), True, "ambiguous"),
    (("invalid", "missing"), True, "invalid"),
])
def test_scalar_merge_status_precedence(statuses, complete, expected):
    results = tuple(reading(status=status, page=index + 1) for index, status in enumerate(statuses))
    assert merge_scalar(field(), results, traversal_complete=complete).status == expected


def test_invalid_raw_participates_in_conflicts_without_exposing_a_guess():
    merged = merge_scalar(field(), (reading("00012"), reading("00013", "invalid", 2)), traversal_complete=True)
    assert merged.status == "ambiguous" and merged.accepted_value is None and merged.raw_value is None
    assert merged.source_pages == (1, 2)
    assert merge_scalar(field(), (reading("00012"), reading("00012", "invalid", 2)), traversal_complete=True).accepted_value == "00012"


def test_scalar_agreement_uses_only_permitted_normalization_not_voting():
    merged = merge_scalar(field(type="number"), (reading("0010.00"), reading("10", page=2)), traversal_complete=True)
    assert merged.status == "extracted"
    results = (reading("A"), reading("A", page=2), reading("B", page=3))
    assert merge_scalar(field(), results, traversal_complete=True).status == "ambiguous"
    assert merge_scalar(field(), (reading("é"), reading("e\u0301", page=2)), traversal_complete=True).status == "ambiguous"


def test_identical_actual_rows_remain_and_exact_same_source_replay_is_deduped():
    first, second = row("row1", 1), row("row2", 1)
    merged = merge_list(table(), (listing((first, second)), listing((first, second))), traversal_complete=True)
    assert tuple(row_.source_key for row_ in merged.rows) == ("row1", "row2")
    assert tuple(tuple(cell.accepted_value for cell in row_.cells) for row_ in merged.rows) == (("Item", "10"), ("Item", "10"))
    assert merged.status == "complete"


def test_individual_table_cells_normalize_exact_numbers_and_replay_does_not_change_completeness():
    actual = row("row1", 1, amount="0010.2300")
    merged = merge_list(table(), (listing((actual,)), listing((actual,))), traversal_complete=True)
    assert merged.status == "complete" and len(merged.rows) == 1
    assert merged.rows[0].cells[1].accepted_value == "10.23"


def test_continuation_halves_join_complementary_cells_in_document_order():
    first = row("page1:last", 1, name="Product", amount=None, next=True)
    second = row("page2:first", 2, name=None, amount="10.00", previous=True)
    last = row("page2:second", 2, name="Other", amount="20")
    merged = merge_list(table(), (listing((first,)), listing((second, last))), traversal_complete=True)
    assert len(merged.rows) == 2 and merged.status == "complete"
    assert tuple(cell.accepted_value for cell in merged.rows[0].cells) == ("Product", "10")
    assert merged.rows[0].source_pages == (1, 2)
    assert not merged.rows[0].continues_previous and not merged.rows[0].continues_next


def test_conflicting_continuation_cells_are_unresolved_but_other_cells_survive():
    merged = merge_list(table(), (listing((row("a", 1, next=True),)), listing((row("b", 2, name="Different", previous=True),))), traversal_complete=True)
    assert merged.status == "partial" and not merged.enumeration_complete
    assert merged.rows[0].cells[0].status == "ambiguous"
    assert merged.rows[0].cells[1].accepted_value == "10"


@pytest.mark.parametrize("results", [
    (listing((row("first", 1, previous=True),)),),
    (listing((row("last", 1, next=True),)),),
    (listing((row("left", 1, next=True),)), listing(), listing((row("right", 3, previous=True),))),
])
def test_missing_continuation_counterpart_withholds_affected_row(results):
    merged = merge_list(table(), results, traversal_complete=True)
    assert not merged.enumeration_complete and merged.status == "unresolved"
    assert all(cell.accepted_value is None for row_ in merged.rows for cell in row_.cells)


def test_incomplete_enumeration_preserves_read_cells_and_withholds_justified_missing():
    merged = merge_list(table(), (listing((row("a", 1, amount=None),)),), traversal_complete=False)
    assert merged.status == "partial" and not merged.enumeration_complete
    assert merged.rows[0].cells[1].status == "unreadable"
    empty = merge_list(table(), (listing(),), traversal_complete=False)
    assert empty.status == "unresolved" and empty.reason == "unreadable"


def test_empty_list_requires_justified_absence_in_every_batch():
    assert merge_list(table(), (listing(), listing()), traversal_complete=True).status == "complete"
    unreadable = listing(complete=True, status="unresolved", reason="unreadable")
    result = merge_list(table(), (listing(), unreadable), traversal_complete=True)
    assert result.status == "unresolved" and not result.enumeration_complete


def test_complete_traversal_cannot_skip_pages_and_later_foreign_page_aborts():
    profile = ExtractionProfile(id="p", owner="u", version=1, name="Custom", description="Custom", original_instruction="Read", fields=(field(),))
    first = BatchResult(page_ids=(1,), fields=(reading("a"),))
    with pytest.raises(ValueError, match="every document page"):
        merge_batches(profile, (first,), (1, 2), traversal_complete=True)
    second = BatchResult(page_ids=(2,), fields=(reading(status="missing", page=2),), page_membership=(PageMembership(page_id=2, status="no"),))
    with pytest.raises(MixedDocumentError):
        merge_batches(profile, (first, second), (1, 2), traversal_complete=True)
    unclear = second.model_copy(update={"page_membership": (PageMembership(page_id=2, status="unclear"),)})
    assert merge_batches(profile, (first, unclear), (1, 2), traversal_complete=True).outcome == "complete"
    assert merge_batches(profile, (first,), (1, 2), traversal_complete=False).outcome == "partial"
    assert merge_batches(profile, (first, first, unclear), (1, 2), traversal_complete=True).outcome == "complete"
    with pytest.raises(ValueError, match="document order"):
        merge_batches(profile, (unclear, first), (1, 2), traversal_complete=True)


def test_conflicting_same_source_replay_after_join_remains_a_conflict():
    left = row("left", 1, amount=None, next=True)
    right = row("right", 2, name=None, previous=True)
    changed = row("left", 1, name="Different", amount=None, next=True)
    merged = merge_list(table(), (listing((left,)), listing((right,)), listing((changed,))), traversal_complete=True)
    assert len(merged.rows) == 1 and not merged.enumeration_complete
    assert merged.rows[0].cells[0].status == "ambiguous"
    assert merged.rows[0].cells[1].accepted_value == "10"


def test_pure_merge_api_rejects_unrequested_columns_and_false_normalization():
    wrong = ListRow(cells=(reading("guess", id="extra"),), source_pages=(1,), source_key="row")
    with pytest.raises(ValueError, match="requested columns"):
        merge_list(table(), (listing((wrong,)),), traversal_complete=True)
    false = reading("raw").model_copy(update={"normalized_value": "corrected"})
    with pytest.raises(ValueError, match="normalization"):
        merge_scalar(field(), (false,), traversal_complete=True)
