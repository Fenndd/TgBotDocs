"""Deterministic V4 merging in document order, without voting or content deduplication."""
from __future__ import annotations

from .contracts import (
    BatchResult, ExtractionProfile, FieldResult, ListField, ListResult, ListRow,
    RecognitionResult, ScalarField, job_outcome, normalize_value, validate_batch, validate_field_result,
)


class MixedDocumentError(ValueError):
    """A later page belongs to another document; no extraction may be presented."""


def _sources(results: tuple[FieldResult, ...]) -> tuple[int, ...]:
    return tuple(dict.fromkeys(page for result in results for page in result.source_pages))


def _reading(field: ScalarField, result: FieldResult):
    try:
        return normalize_value(field, result.raw_value)
    except ValueError:
        return result.raw_value


def merge_scalar(field: ScalarField, results: tuple[FieldResult, ...], *, traversal_complete: bool) -> FieldResult:
    if any(result.field_id != field.id for result in results):
        raise ValueError("cannot merge another field's readings")
    for result in results:
        validate_field_result(field, result, result.source_pages)
    sources = _sources(results)
    readings = tuple(result for result in results if result.status in ("extracted", "invalid") and result.raw_value is not None)
    values = tuple((type(_reading(field, result)), _reading(field, result)) for result in readings)
    if any(result.status == "ambiguous" for result in results) or len(set(values)) > 1:
        return FieldResult(field_id=field.id, status="ambiguous", source_pages=sources)
    extracted = next((result for result in results if result.status == "extracted"), None)
    if extracted is not None:
        updates = {"source_pages": sources}
        if field.type == "number":
            updates["normalized_value"] = normalize_value(field, extracted.raw_value)
        return extracted.model_copy(update=updates)
    invalid = next((result for result in results if result.status == "invalid"), None)
    if invalid is not None:
        return invalid.model_copy(update={"source_pages": sources})
    status = "unreadable" if not traversal_complete or not results or any(result.status == "unreadable" for result in results) else "missing"
    return FieldResult(field_id=field.id, status=status, source_pages=sources)


def _unresolved_row(row: ListRow) -> ListRow:
    return row.model_copy(update={"cells": tuple(
        FieldResult(field_id=cell.field_id, status="ambiguous", source_pages=cell.source_pages)
        for cell in row.cells), "continues_previous": False, "continues_next": False})


def _join_rows(field: ListField, left: ListRow, right: ListRow) -> tuple[ListRow, bool]:
    left_cells = {cell.field_id: cell for cell in left.cells}
    right_cells = {cell.field_id: cell for cell in right.cells}
    expected = {column.id for column in field.columns}
    if set(left_cells) != expected or set(right_cells) != expected:
        raise ValueError("continuation rows must cover requested columns")
    cells = tuple(merge_scalar(column, (left_cells[column.id], right_cells[column.id]), traversal_complete=True)
                  for column in field.columns)
    conflict = any(cell.status == "ambiguous" for cell in cells)
    return ListRow(cells=cells, source_pages=tuple(dict.fromkeys(left.source_pages + right.source_pages)),
                   source_key=left.source_key, continues_previous=left.continues_previous,
                   continues_next=right.continues_next), conflict


def merge_list(field: ListField, results: tuple[ListResult, ...], *, traversal_complete: bool) -> ListResult:
    if any(result.field_id != field.id for result in results):
        raise ValueError("cannot merge another list")
    enumeration_complete = traversal_complete and bool(results) and all(result.enumeration_complete for result in results)
    rows: list[ListRow] = []
    # A source identity describes an actual row occurrence, never just its content.
    seen: dict[tuple[str, tuple[int, ...]], tuple[ListRow, int]] = {}
    for result in results:
        if not result.rows and result.status != "complete" and result.reason != "missing":
            enumeration_complete = False
        columns = {column.id: column for column in field.columns}
        identities = tuple((row.source_key, row.source_pages) for row in result.rows)
        if len(set(identities)) != len(identities):
            raise ValueError("duplicate row source identities within one batch")
        for row_index, row in enumerate(result.rows):
            if {cell.field_id for cell in row.cells} != set(columns):
                raise ValueError("row must cover exactly the requested columns")
            for cell in row.cells:
                validate_field_result(columns[cell.field_id], cell, row.source_pages)
            if row.continues_previous and row_index != 0 or row.continues_next and row_index != len(result.rows) - 1:
                raise ValueError("continuation flags belong to boundary rows")
            original = row
            row = row.model_copy(update={"cells": tuple(
                merge_scalar(columns[cell.field_id], (cell,), traversal_complete=True) for cell in row.cells)})
            identity = (row.source_key, row.source_pages)
            previous = seen.get(identity)
            if previous is not None:
                first_reading, index = previous
                if first_reading == original:
                    continue
                enumeration_complete = False
                joined, _ = _join_rows(field, rows[index], row)
                rows[index] = joined.model_copy(update={"continues_previous": rows[index].continues_previous,
                                                       "continues_next": rows[index].continues_next})
                continue
            if rows and rows[-1].continues_next and row.continues_previous:
                seen[identity] = (original, len(rows) - 1)
                joined, conflict = _join_rows(field, rows[-1], row)
                rows[-1] = joined
                if conflict:
                    enumeration_complete = False
                continue
            if rows and rows[-1].continues_next:
                rows[-1] = _unresolved_row(rows[-1])
                enumeration_complete = False
            if row.continues_previous:
                row = _unresolved_row(row)
                enumeration_complete = False
            seen[identity] = (original, len(rows))
            rows.append(row)
        # A pending half cannot jump over an empty batch.
        if not result.rows and rows and rows[-1].continues_next:
            rows[-1] = _unresolved_row(rows[-1])
            enumeration_complete = False
    if rows and rows[-1].continues_next:
        rows[-1] = _unresolved_row(rows[-1])
        enumeration_complete = False
    if not traversal_complete:
        rows = [row.model_copy(update={"cells": tuple(
            cell.model_copy(update={"status": "unreadable"}) if cell.status == "missing" else cell
            for cell in row.cells)}) for row in rows]
    accepted = any(cell.status == "extracted" for row in rows for cell in row.cells)
    resolved = all(cell.status in ("extracted", "missing") for row in rows for cell in row.cells)
    confirmed_empty = not rows and all(result.status == "complete" for result in results)
    if enumeration_complete and resolved and (rows or confirmed_empty):
        status, reason = "complete", None
    elif accepted:
        status, reason = "partial", None
    else:
        status = "unresolved"
        statuses = {cell.status for row in rows for cell in row.cells}
        reasons = {result.reason for result in results}
        reason = next((candidate for candidate in ("ambiguous", "invalid", "unreadable", "missing")
                       if candidate in statuses or candidate in reasons), "unreadable")
        if not enumeration_complete and reason == "missing":
            reason = "unreadable"
    return ListResult(field_id=field.id, status=status, rows=tuple(rows),
                      enumeration_complete=enumeration_complete, reason=reason)


def merge_batches(profile: ExtractionProfile, batches: tuple[BatchResult, ...],
                  available_page_ids: tuple[int, ...], *, traversal_complete: bool) -> RecognitionResult:
    if not available_page_ids or len(set(available_page_ids)) != len(available_page_ids):
        raise ValueError("document pages must be nonempty and unique")
    unique_batches: list[BatchResult] = []
    seen_pages: set[int] = set()
    last_position = -1
    for batch in batches:
        validate_batch(batch, profile, available_page_ids)
        if any(item.status == "no" for item in batch.page_membership):
            raise MixedDocumentError("a page does not belong to the matched document")
        if batch in unique_batches:
            continue
        positions = tuple(available_page_ids.index(page) for page in batch.page_ids)
        if positions != tuple(range(positions[0], positions[0] + len(positions))) or positions[0] != last_position + 1:
            raise ValueError("batches must contain consecutive pages in document order as a contiguous document prefix")
        if seen_pages.intersection(batch.page_ids):
            raise ValueError("overlapping nonidentical batches")
        seen_pages.update(batch.page_ids)
        last_position = positions[-1]
        unique_batches.append(batch)
    if traversal_complete and seen_pages != set(available_page_ids):
        raise ValueError("complete traversal must cover every document page")
    scalars = tuple(merge_scalar(field, tuple(next(result for result in batch.fields if result.field_id == field.id)
                                              for batch in unique_batches), traversal_complete=traversal_complete)
                    for field in profile.fields if isinstance(field, ScalarField))
    lists = tuple(merge_list(field, tuple(next(result for result in batch.lists if result.field_id == field.id)
                                         for batch in unique_batches), traversal_complete=traversal_complete)
                  for field in profile.fields if isinstance(field, ListField))
    return RecognitionResult(fields=scalars, lists=lists, traversal_complete=traversal_complete,
                             outcome=job_outcome(scalars, lists, traversal_complete=traversal_complete))
