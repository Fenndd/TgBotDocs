"""Strict, immutable recognition contracts. Candidates are internal job data."""
from __future__ import annotations

from datetime import datetime
from decimal import Decimal
import re
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, StrictBool, StrictInt, StrictStr, field_validator, model_validator

ScalarType = Literal["text", "date", "number", "boolean"]
FieldStatus = Literal["extracted", "missing", "unreadable", "ambiguous", "invalid"]
Value = StrictStr | StrictBool


class ContractModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)


class FormatValidator(ContractModel):
    kind: Literal["calendar_date", "iban", "luhn", "iso_code"]
    date_formats: tuple[StrictStr, ...] = ()
    allowlist: tuple[StrictStr, ...] = ()

    @model_validator(mode="after")
    def declared_parameters(self):
        if self.kind == "iso_code" and not self.allowlist:
            raise ValueError("ISO validation requires a dependable declared allowlist")
        if self.kind != "iso_code" and self.allowlist:
            raise ValueError("allowlist belongs only to ISO validation")
        if self.kind != "calendar_date" and self.date_formats:
            raise ValueError("date formats belong only to calendar validation")
        if len(set(self.date_formats)) != len(self.date_formats):
            raise ValueError("duplicate declared date format")
        for pattern in self.date_formats:
            if sorted(re.findall(r"%.", pattern)) != ["%Y", "%d", "%m"]:
                raise ValueError("declared date formats require one full year, numeric month and day")
        if any(not code or code.strip() != code for code in self.allowlist):
            raise ValueError("allowlist codes must be nonempty exact strings")
        if len(set(self.allowlist)) != len(self.allowlist):
            raise ValueError("duplicate allowlist code")
        return self


class ScalarField(ContractModel):
    id: StrictStr = Field(min_length=1)
    label: StrictStr = Field(min_length=1)
    description: StrictStr = Field(min_length=1)
    type: ScalarType
    validator: FormatValidator | None = None


class ListField(ContractModel):
    id: StrictStr = Field(min_length=1)
    label: StrictStr = Field(min_length=1)
    description: StrictStr = Field(min_length=1)
    type: Literal["list"] = "list"
    columns: tuple[ScalarField, ...] = Field(min_length=1)

    @model_validator(mode="after")
    def unique_columns(self):
        _unique(tuple(column.id for column in self.columns), "column IDs")
        return self


ProfileField = Annotated[ScalarField | ListField, Field(discriminator="type")]


class ExtractionProfile(ContractModel):
    id: StrictStr = Field(min_length=1)
    owner: StrictStr = Field(min_length=1)
    version: StrictInt = Field(ge=1)
    name: StrictStr = Field(min_length=1)
    description: StrictStr = Field(min_length=1)
    original_instruction: StrictStr = Field(min_length=1)
    fields: tuple[ProfileField, ...] = Field(min_length=1)
    guidance: StrictStr = ""

    @model_validator(mode="after")
    def unique_fields(self):
        _unique(tuple(field.id for field in self.fields), "field IDs")
        return self


class FieldResult(ContractModel):
    field_id: StrictStr = Field(min_length=1)
    status: FieldStatus
    raw_value: Value | None = None
    normalized_value: Value | None = None
    source_pages: tuple[StrictInt, ...] = ()

    @model_validator(mode="after")
    def value_and_sources(self):
        _pages(self.source_pages)
        if self.status == "extracted" and self.raw_value is None:
            raise ValueError("extracted requires a raw value")
        if self.status not in ("extracted", "invalid") and self.raw_value is not None:
            raise ValueError("only extracted or internal invalid candidates may contain raw values")
        if self.status != "extracted" and self.normalized_value is not None:
            raise ValueError("unaccepted results cannot contain normalized values")
        if self.raw_value is not None and not self.source_pages:
            raise ValueError("a reading requires source pages")
        return self

    @property
    def accepted_value(self) -> Value | None:
        if self.status != "extracted":
            return None
        return self.normalized_value if self.normalized_value is not None else self.raw_value

    def external(self) -> dict:
        """Only accepted values; internal raw candidates never leave this projection."""
        return {"field_id": self.field_id, "status": self.status, "value": self.accepted_value}


class ListRow(ContractModel):
    cells: tuple[FieldResult, ...] = Field(min_length=1)
    source_pages: tuple[StrictInt, ...] = Field(min_length=1)
    source_key: StrictStr = Field(min_length=1)
    continues_previous: StrictBool = False
    continues_next: StrictBool = False

    @model_validator(mode="after")
    def sources(self):
        _pages(self.source_pages)
        _unique(tuple(cell.field_id for cell in self.cells), "cell IDs")
        if any(not set(cell.source_pages).issubset(self.source_pages) for cell in self.cells):
            raise ValueError("cell sources must belong to row sources")
        return self


class ListResult(ContractModel):
    field_id: StrictStr = Field(min_length=1)
    status: Literal["complete", "partial", "unresolved"]
    rows: tuple[ListRow, ...] = ()
    enumeration_complete: StrictBool
    reason: Literal["missing", "unreadable", "ambiguous", "invalid"] | None = None

    @model_validator(mode="after")
    def state(self):
        accepted = any(cell.status == "extracted" for row in self.rows for cell in row.cells)
        resolved = all(cell.status in ("extracted", "missing") for row in self.rows for cell in row.cells)
        if self.status == "complete" and (not self.enumeration_complete or not resolved):
            raise ValueError("complete list requires full enumeration and resolved cells")
        if self.status == "partial" and not accepted:
            raise ValueError("partial list requires an accepted cell")
        if self.status == "unresolved" and (accepted or self.reason is None):
            raise ValueError("unresolved list has no accepted cells and needs a reason")
        if self.status != "unresolved" and self.reason is not None:
            raise ValueError("reason belongs only to unresolved lists")
        if self.status == "partial" and self.enumeration_complete and resolved:
            raise ValueError("fully resolved and enumerated list is complete")
        return self

    def external(self) -> dict:
        return {"field_id": self.field_id, "status": self.status,
                "enumeration_complete": self.enumeration_complete, "reason": self.reason,
                "rows": [[cell.external() for cell in row.cells] for row in self.rows]}


class PageMembership(ContractModel):
    page_id: StrictInt = Field(ge=1)
    status: Literal["yes", "no", "unclear"]


class BatchResult(ContractModel):
    page_ids: tuple[StrictInt, ...] = Field(min_length=1)
    fields: tuple[FieldResult, ...] = ()
    lists: tuple[ListResult, ...] = ()
    page_membership: tuple[PageMembership, ...] = ()

    @model_validator(mode="after")
    def batch_ids(self):
        _pages(self.page_ids)
        _unique(tuple(result.field_id for result in self.fields + self.lists), "result IDs")
        if self.page_membership:
            ids = tuple(item.page_id for item in self.page_membership)
            if set(ids) != set(self.page_ids) or len(ids) != len(self.page_ids):
                raise ValueError("membership must cover each batch page once")
        return self


class RecognitionResult(ContractModel):
    fields: tuple[FieldResult, ...]
    lists: tuple[ListResult, ...]
    outcome: Literal["failed", "complete", "partial"]
    traversal_complete: StrictBool = True

    @model_validator(mode="after")
    def consistent_outcome(self):
        if self.outcome != job_outcome(self.fields, self.lists, traversal_complete=self.traversal_complete):
            raise ValueError("outcome disagrees with accepted values and resolution")
        if not self.traversal_complete and (any(field.status == "missing" for field in self.fields)
                                            or any(result.status == "complete" or result.reason == "missing"
                                                   for result in self.lists)
                                            or any(cell.status == "missing" for result in self.lists
                                                   for row in result.rows for cell in row.cells)):
            raise ValueError("incomplete traversal cannot justify missing fields, lists, cells or complete lists")
        return self

    def external(self) -> dict:
        return {"outcome": self.outcome, "traversal_complete": self.traversal_complete,
                "fields": [field.external() for field in self.fields],
                "lists": [result.external() for result in self.lists]}


class MatchingResponse(ContractModel):
    status: Literal["matched", "no_profile", "uncertain", "unreadable", "mixed", "not_document"]
    profile_index: StrictInt | None = None
    type_description: StrictStr | None = None

    @model_validator(mode="after")
    def matching_state(self):
        if self.status == "matched":
            if self.profile_index is None or self.profile_index < 1:
                raise ValueError("matched requires a positive per-call index")
        elif self.profile_index is not None:
            raise ValueError("only matched may select a profile")
        if self.status == "no_profile" and not (self.type_description and self.type_description.strip()):
            raise ValueError("no_profile requires a meaningful type description")
        return self


def resolve_matching(response: MatchingResponse, snapshots: tuple[ExtractionProfile, ...]) -> ExtractionProfile | None:
    """Bind only to this call's immutable snapshots; never fetch a newer profile."""
    if len({snapshot.owner for snapshot in snapshots}) > 1:
        raise ValueError("matching snapshots must belong to one user")
    _unique(tuple(snapshot.id for snapshot in snapshots), "profile IDs")
    if response.status != "matched":
        return None
    if response.profile_index is None or response.profile_index > len(snapshots):
        raise ValueError("profile index is outside the supplied snapshots")
    return snapshots[response.profile_index - 1]


def _unique(values: tuple, label: str) -> None:
    if len(set(values)) != len(values):
        raise ValueError(f"duplicate {label}")


def _pages(pages: tuple[int, ...]) -> None:
    _unique(pages, "source pages")
    if any(page < 1 for page in pages):
        raise ValueError("source page IDs must be positive")


def normalize_value(field: ScalarField, value: Value) -> Value:
    """Permitted deterministic normalization, never transliteration or guessing."""
    if field.type == "boolean":
        if type(value) is not bool:
            raise ValueError("boolean fields require JSON booleans")
        return value
    if not isinstance(value, str):
        raise ValueError("text, date and exact decimal values require strings")
    if field.type == "number":
        if not re.fullmatch(r"[+-]?[0-9]+(?:\.[0-9]+)?", value):
            raise ValueError("decimal must be an unambiguous exact decimal string")
        decimal = Decimal(value)
        if decimal == 0:
            return "0"
        return format(decimal, "f").rstrip("0").rstrip(".") if "." in value else str(decimal)
    if field.type == "date":
        formats = ("%Y-%m-%d",)
        if field.validator and field.validator.kind == "calendar_date":
            formats += field.validator.date_formats
        readings = set()
        for date_format in formats:
            try:
                readings.add(datetime.strptime(value, date_format).date().isoformat())
            except ValueError:
                pass
        if len(readings) == 1:
            return next(iter(readings))
        if len(readings) > 1:
            raise ValueError("declared date interpretations disagree")
        return value
    return value


def validate_field_result(field: ScalarField, result: FieldResult, available_page_ids: tuple[int, ...]) -> None:
    if result.field_id != field.id:
        raise ValueError("result is not a requested field")
    if not set(result.source_pages).issubset(available_page_ids):
        raise ValueError("result references unavailable source pages")
    if result.status == "extracted":
        if field.type in ("text", "date") and not isinstance(result.raw_value, str):
            raise ValueError("text and date fields require strings")
        # A raw date may remain unnormalized. Parsing an ambiguous date is never mandatory.
        expected = normalize_value(field, result.raw_value) if result.normalized_value is not None or field.type in ("number", "boolean") else result.raw_value
        if result.normalized_value is not None:
            if type(result.normalized_value) is not type(expected) or result.normalized_value != expected:
                raise ValueError("normalization is not justified by the raw value")
            if field.type == "date" and not re.fullmatch(r"[0-9]{4}-[0-9]{2}-[0-9]{2}", str(expected)):
                raise ValueError("a normalized date must be unambiguously parsed")
            if field.type == "date":
                try:
                    datetime.strptime(expected, "%Y-%m-%d")
                except ValueError as error:
                    raise ValueError("normalized date is not calendar-valid") from error


def validate_batch(batch: BatchResult, profile: ExtractionProfile, available_page_ids: tuple[int, ...]) -> None:
    _pages(available_page_ids)
    if not set(batch.page_ids).issubset(available_page_ids):
        raise ValueError("batch references unavailable pages")
    expected_scalars = {field.id: field for field in profile.fields if isinstance(field, ScalarField)}
    expected_lists = {field.id: field for field in profile.fields if isinstance(field, ListField)}
    if set(expected_scalars) != {result.field_id for result in batch.fields}:
        raise ValueError("scalar results must cover exactly the requested IDs")
    if set(expected_lists) != {result.field_id for result in batch.lists}:
        raise ValueError("list results must cover exactly the requested IDs")
    for result in batch.fields:
        validate_field_result(expected_scalars[result.field_id], result, batch.page_ids)
    for result in batch.lists:
        field = expected_lists[result.field_id]
        _unique(tuple((row.source_key, row.source_pages) for row in result.rows), "row source identities")
        for index, row in enumerate(result.rows):
            if not set(row.source_pages).issubset(batch.page_ids):
                raise ValueError("row references pages outside its batch")
            if {cell.field_id for cell in row.cells} != {column.id for column in field.columns}:
                raise ValueError("row must cover exactly the requested columns")
            if row.continues_previous and index != 0 or row.continues_next and index != len(result.rows) - 1:
                raise ValueError("continuation flags belong to boundary rows")
            columns = {column.id: column for column in field.columns}
            for cell in row.cells:
                validate_field_result(columns[cell.field_id], cell, row.source_pages)


def job_outcome(fields: tuple[FieldResult, ...], lists: tuple[ListResult, ...], *,
                traversal_complete: bool = True) -> Literal["failed", "complete", "partial"]:
    any_accepted = any(field.status == "extracted" for field in fields)
    any_accepted |= any(cell.status == "extracted" for result in lists for row in result.rows for cell in row.cells)
    any_accepted |= any(result.status == "complete" and not result.rows for result in lists)
    if not any_accepted:
        return "failed"
    if traversal_complete and all(field.status in ("extracted", "missing") for field in fields) and all(result.status == "complete" for result in lists):
        return "complete"
    return "partial"
