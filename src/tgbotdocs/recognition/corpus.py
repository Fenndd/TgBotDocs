"""Strict corpus contracts and explicit human-review gates; never review a case."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
import hashlib
import json
from pathlib import Path, PurePosixPath
from typing import Literal

from pydantic import Field, StrictBool, StrictInt, StrictStr, ValidationError, field_validator, model_validator

from .contracts import ContractModel, ExtractionProfile, FieldStatus, ListField, ScalarField, Value, normalize_value

Split = Literal["development", "tuning", "benchmark"]
Quality = Literal["readable", "difficult", "negative"]
Script = Literal["Latin", "Cyrillic", "Arabic", "Chinese", "Japanese", "Devanagari"]
Category = Literal["identity", "invoice", "receipt", "certificate", "contract", "application", "letter", "repeating_rows"]
SHA256 = StrictStr
SCRIPTS = {"Latin", "Cyrillic", "Arabic", "Chinese", "Japanese", "Devanagari"}
CATEGORIES = {"identity", "invoice", "receipt", "certificate", "contract", "application", "letter", "repeating_rows"}


class CorpusError(ValueError):
    """Content-free error codes safe for a diagnostic runner to report."""


def _hash(value: str) -> str:
    if len(value) != 64 or any(character not in "0123456789abcdef" for character in value):
        raise ValueError("invalid_sha256")
    return value


def _unique(values: tuple) -> None:
    if len(values) != len(set(values)):
        raise ValueError("duplicate_identity")


class Artifact(ContractModel):
    id: StrictStr = Field(min_length=1)
    path: StrictStr = Field(min_length=1)
    sha256: SHA256
    # "reference" marks review aids such as contact sheets; never a model input.
    kind: Literal["original", "image_file", "photo", "pdf", "pdf_render", "reference"]
    delivery_simulated: StrictBool = False
    physical_capture: StrictBool = False
    telegram_delivery_verified: StrictBool = False

    _valid_hash = field_validator("sha256")(_hash)

    @field_validator("path")
    @classmethod
    def local_relative_path(cls, value: str) -> str:
        path = PurePosixPath(value)
        if "\\" in value or ":" in value or path.is_absolute() or ".." in path.parts or path.as_posix() != value or value == ".":
            raise ValueError("unsafe_artifact_path")
        return value

    @model_validator(mode="after")
    def simulation(self):
        if self.delivery_simulated and self.kind != "photo":
            raise ValueError("simulation_requires_photo_kind")
        if self.telegram_delivery_verified and (self.kind != "photo" or self.delivery_simulated):
            raise ValueError("telegram_delivery_requires_nonsimulated_photo")
        return self


class Origin(ContractModel):
    family_id: StrictStr = Field(min_length=1)
    kind: Literal["synthetic", "permitted_public", "separately_authorized"]
    permission_basis: StrictStr = Field(min_length=1)
    original_sha256: SHA256
    ancestor_sha256: tuple[SHA256, ...] = ()
    prior_splits: tuple[Split, ...] = ()

    _valid_hash = field_validator("original_sha256")(_hash)

    @model_validator(mode="after")
    def provenance(self):
        for value in self.ancestor_sha256:
            _hash(value)
        _unique(self.ancestor_sha256)
        _unique(self.prior_splits)
        return self


class HumanReview(ContractModel):
    status: Literal["pending", "verified", "rejected"] = "pending"
    reviewer: StrictStr | None = None
    method: Literal["script_reading", "glyph_sequence_comparison", "published_transcription"] | None = None
    reviewed_at: datetime | None = None
    subject_sha256: SHA256 | None = None
    reviewer_kind: Literal["human"] | None = None

    @model_validator(mode="after")
    def explicit_attestation(self):
        if self.status == "verified":
            if not (self.reviewer and self.reviewer.strip() and self.method and self.reviewed_at and self.subject_sha256 and self.reviewer_kind):
                raise ValueError("human_attestation_required")
            if self.reviewed_at.tzinfo is None:
                raise ValueError("review_timestamp_timezone_required")
            _hash(self.subject_sha256)
        elif any(value is not None for value in (self.reviewer, self.method, self.reviewed_at, self.subject_sha256, self.reviewer_kind)):
            raise ValueError("nonverified_review_has_no_attestation")
        return self


class ExpectedValue(ContractModel):
    field_id: StrictStr = Field(min_length=1)
    status: FieldStatus
    present: StrictBool | None
    value: Value | None = None
    allowed_values: tuple[Value, ...] = ()
    source_pages: tuple[StrictInt, ...] = ()
    normalization: Literal["none", "profile"] = "none"

    @model_validator(mode="after")
    def ground_truth_state(self):
        _unique(self.source_pages)
        if any(page < 1 for page in self.source_pages):
            raise ValueError("invalid_ground_truth_page")
        if self.status == "extracted":
            if self.value is None or self.present is not True or not self.source_pages:
                raise ValueError("readable_ground_truth_requires_value_presence_source")
        elif self.value is not None or self.allowed_values:
            raise ValueError("unaccepted_ground_truth_has_no_value")
        if self.status == "missing" and self.present is not False:
            raise ValueError("missing_requires_justified_absence")
        if self.present is False and self.status != "missing":
            raise ValueError("absence_requires_missing_status")
        identities = tuple((type(value), value) for value in self.allowed_values)
        _unique(identities)
        if any(type(value) is not type(self.value) or value == self.value for value in self.allowed_values):
            raise ValueError("invalid_or_redundant_allowed_value")
        return self


class ExpectedRow(ContractModel):
    source_key: StrictStr = Field(min_length=1)
    source_pages: tuple[StrictInt, ...] = Field(min_length=1)
    cells: tuple[ExpectedValue, ...] = Field(min_length=1)

    @model_validator(mode="after")
    def row_identity(self):
        _unique(self.source_pages)
        _unique(tuple(cell.field_id for cell in self.cells))
        if any(page < 1 for page in self.source_pages) or any(not set(cell.source_pages).issubset(self.source_pages) for cell in self.cells):
            raise ValueError("invalid_ground_truth_row_sources")
        return self


class ExpectedList(ContractModel):
    field_id: StrictStr = Field(min_length=1)
    status: Literal["complete", "partial", "unresolved"]
    enumeration_complete: StrictBool
    reason: Literal["missing", "unreadable", "ambiguous", "invalid"] | None = None
    rows: tuple[ExpectedRow, ...] = ()

    @model_validator(mode="after")
    def list_state(self):
        _unique(tuple(row.source_key for row in self.rows))
        readable = any(cell.status == "extracted" for row in self.rows for cell in row.cells)
        resolved = all(cell.status in ("extracted", "missing") for row in self.rows for cell in row.cells)
        if self.status == "complete" and (not self.enumeration_complete or not resolved):
            raise ValueError("complete_truth_requires_enumeration_resolution")
        if self.status == "partial" and (not readable or self.enumeration_complete and resolved):
            raise ValueError("partial_truth_requires_readable_and_unresolved_parts")
        if self.status == "unresolved" and (readable or self.reason is None):
            raise ValueError("unresolved_truth_requires_reason_and_no_read_values")
        if self.status != "unresolved" and self.reason is not None:
            raise ValueError("reason_requires_unresolved_truth")
        return self


class ExpectedOutcome(ContractModel):
    matching: Literal["matched", "no_profile", "uncertain", "unreadable", "mixed", "not_document", "input_refused"]
    profile_id: StrictStr | None = None
    outcome: Literal["complete", "partial", "failed", "refused"]
    fields: tuple[ExpectedValue, ...] = ()
    lists: tuple[ExpectedList, ...] = ()

    @model_validator(mode="after")
    def selection(self):
        _unique(tuple(value.field_id for value in self.fields + self.lists))
        if self.matching == "matched":
            if not self.profile_id or self.outcome == "refused":
                raise ValueError("matched_truth_requires_profile_and_extraction")
            accepted = any(value.status == "extracted" for value in self.fields)
            accepted |= any(cell.status == "extracted" for value in self.lists for row in value.rows for cell in row.cells)
            accepted |= any(value.status == "complete" and not value.rows for value in self.lists)
            complete = all(value.status in ("extracted", "missing") for value in self.fields) and all(value.status == "complete" for value in self.lists)
            expected = "failed" if not accepted else ("complete" if complete else "partial")
            if self.outcome != expected:
                raise ValueError("ground_truth_outcome_inconsistent")
        elif self.profile_id is not None or self.outcome != "refused" or self.fields or self.lists:
            raise ValueError("refusal_truth_cannot_contain_accepted_extraction")
        return self


class CorpusCase(ContractModel):
    case_id: StrictStr = Field(min_length=1)
    origin: Origin
    script: Script
    language: StrictStr = Field(pattern=r"^[a-z]{2,3}(?:-[A-Z]{2})?$")
    category: Category
    quality: Quality
    scenario: StrictStr = Field(min_length=1)
    delivery_path: Literal["image_file", "photo", "pdf"]
    artifacts: tuple[Artifact, ...] = Field(min_length=1)
    input_artifact_ids: tuple[StrictStr, ...] = Field(min_length=1)
    page_ids: tuple[StrictInt, ...] = Field(min_length=1)
    profiles: tuple[ExtractionProfile, ...] = ()
    expected: ExpectedOutcome | None = None
    review: HumanReview = Field(default_factory=HumanReview)

    @model_validator(mode="after")
    def consistent_case(self):
        _unique(tuple(artifact.id for artifact in self.artifacts))
        _unique(tuple(artifact.path for artifact in self.artifacts))
        _unique(self.input_artifact_ids)
        _unique(self.page_ids)
        _unique(tuple(profile.id for profile in self.profiles))
        if any(page < 1 for page in self.page_ids):
            raise ValueError("invalid_case_page")
        if len({profile.owner for profile in self.profiles}) > 1:
            raise ValueError("profile_owner_mismatch")
        artifacts = {artifact.id: artifact for artifact in self.artifacts}
        if not set(self.input_artifact_ids).issubset(artifacts):
            raise ValueError("unknown_input_artifact")
        if any(artifacts[identity].kind != self.delivery_path for identity in self.input_artifact_ids):
            raise ValueError("primary_delivery_kind_mismatch")
        if self.expected and self.expected.matching == "matched":
            profile = next((profile for profile in self.profiles if profile.id == self.expected.profile_id), None)
            if profile is None:
                raise ValueError("expected_profile_not_supplied")
            scalars = {field.id: field for field in profile.fields if isinstance(field, ScalarField)}
            lists = {field.id: field for field in profile.fields if isinstance(field, ListField)}
            if set(scalars) != {value.field_id for value in self.expected.fields} or set(lists) != {value.field_id for value in self.expected.lists}:
                raise ValueError("ground_truth_must_cover_exact_profile_schema")
            for value in self.expected.fields:
                self._value(value, scalars[value.field_id])
            for value in self.expected.lists:
                columns = {column.id: column for column in lists[value.field_id].columns}
                for row in value.rows:
                    if not set(row.source_pages).issubset(self.page_ids) or set(columns) != {cell.field_id for cell in row.cells}:
                        raise ValueError("ground_truth_row_schema_or_page_mismatch")
                    for cell in row.cells:
                        self._value(cell, columns[cell.field_id])
        if self.review.status == "verified":
            if self.expected is None or self.review.subject_sha256 != case_review_digest(self):
                raise ValueError("review_not_bound_to_current_case_and_ground_truth")
        return self

    def _value(self, value: ExpectedValue, field: ScalarField) -> None:
        if not set(value.source_pages).issubset(self.page_ids):
            raise ValueError("ground_truth_source_not_in_case")
        if value.status == "extracted":
            if field.type == "boolean" and type(value.value) is not bool or field.type != "boolean" and not isinstance(value.value, str):
                raise ValueError("ground_truth_value_type_mismatch")
            if value.normalization == "profile":
                for accepted in (value.value, *value.allowed_values):
                    normalized = normalize_value(field, accepted)
                    if type(normalized) is not type(accepted) or normalized != accepted:
                        raise ValueError("ground_truth_value_must_be_declared_canonical_form")
        if self.quality == "readable" and value.present is True and value.status != "extracted":
            raise ValueError("readable_present_ground_truth_requires_readable_value")


def case_review_digest(case: CorpusCase) -> str:
    """Digest to give a human reviewer; calling it does not attest or approve."""
    payload = case.model_dump(mode="json", exclude={"review"})
    encoded = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


class Denominators(ContractModel):
    cases: StrictInt = Field(ge=0)
    readable_cases: StrictInt = Field(ge=0)
    readable_present_values: StrictInt = Field(ge=0)
    known_readable_values: StrictInt = Field(ge=0)
    unambiguous_profiles: StrictInt = Field(ge=0)


def declared_denominators(cases: tuple[CorpusCase, ...]) -> Denominators:
    readable = known = profiles = 0
    for case in cases:
        if case.expected is None:
            continue
        values = list(case.expected.fields) + [cell for value in case.expected.lists for row in value.rows for cell in row.cells]
        known += sum(value.status == "extracted" for value in values)
        if case.quality == "readable":
            readable += sum(value.present is True for value in values)
        profiles += case.expected.matching == "matched"
    return Denominators(cases=len(cases), readable_cases=sum(case.quality == "readable" for case in cases),
                        readable_present_values=readable, known_readable_values=known, unambiguous_profiles=profiles)


class CorpusManifest(ContractModel):
    schema_version: Literal[1]
    split: Split
    purpose: Literal["review_preparation", "quality_measurement"]
    cases: tuple[CorpusCase, ...] = Field(min_length=1)
    denominators: Denominators
    sealed: StrictBool = False
    frozen_configuration_sha256: SHA256 | None = None

    @model_validator(mode="after")
    def corpus_integrity(self):
        _unique(tuple(case.case_id for case in self.cases))
        _unique(tuple(case.origin.family_id for case in self.cases))
        if self.denominators != declared_denominators(self.cases):
            raise ValueError("declared_denominators_do_not_match_all_cases")
        if self.frozen_configuration_sha256 is not None:
            _hash(self.frozen_configuration_sha256)
        if self.split == "benchmark" and any(set(case.origin.prior_splits) & {"development", "tuning"} for case in self.cases):
            raise ValueError("development_or_tuning_origin_cannot_be_benchmark")
        return self

    def eligibility_reasons(self, mode: Literal["calibration", "benchmark"]) -> tuple[str, ...]:
        reasons = []
        if self.purpose != "quality_measurement":
            reasons.append("review_preparation_only")
        if any(case.review.status != "verified" or case.expected is None for case in self.cases):
            reasons.append("human_review_or_ground_truth_pending")
        required_split = "tuning" if mode == "calibration" else "benchmark"
        if self.split != required_split:
            reasons.append("wrong_split")
        if {case.script for case in self.cases} != SCRIPTS or {case.category for case in self.cases} != CATEGORIES or {case.quality for case in self.cases} != {"readable", "difficult", "negative"}:
            reasons.append("diversity_incomplete")
        if mode == "calibration" and len(self.cases) < 20:
            reasons.append("tuning_case_count_below_twenty")
        if mode == "benchmark":
            counts = {quality: sum(case.quality == quality for case in self.cases) for quality in ("readable", "difficult", "negative")}
            if counts != {"readable": 40, "difficult": 20, "negative": 10}:
                reasons.append("benchmark_composition_incomplete")
            if not self.sealed or self.frozen_configuration_sha256 is None:
                reasons.append("benchmark_not_sealed_and_frozen")
            readable_paths = {case.delivery_path for case in self.cases if case.quality == "readable"}
            if not {"photo", "image_file"}.issubset(readable_paths):
                reasons.append("benchmark_image_delivery_paths_incomplete")
            difficult_photos = 0
            for case in self.cases:
                selected = [a for a in case.artifacts if a.id in case.input_artifact_ids]
                if case.delivery_path == "photo" and any(a.delivery_simulated or not a.telegram_delivery_verified for a in selected):
                    reasons.append("benchmark_telegram_photo_delivery_unverified")
                if case.quality == "difficult" and not all(a.physical_capture for a in selected):
                    reasons.append("benchmark_difficult_cases_require_physical_photographs")
                if case.quality == "difficult" and case.delivery_path == "photo" and all(a.physical_capture and not a.delivery_simulated for a in selected):
                    difficult_photos += 1
            if difficult_photos < 10:
                reasons.append("benchmark_physical_photo_coverage_incomplete")
        return tuple(sorted(set(reasons)))

    def require_eligible(self, mode: Literal["calibration", "benchmark"]) -> None:
        if self.eligibility_reasons(mode):
            raise CorpusError("corpus_ineligible_for_quality_measurement")


def validate_split_separation(*manifests: CorpusManifest) -> None:
    """Caller supplies the historical corpus registry too; undeclared history is unknowable."""
    seen: dict[tuple[str, str], set[str]] = {}
    for manifest in manifests:
        for case in manifest.cases:
            identities = [("family", case.origin.family_id)]
            identities += [("sha256", value) for value in (case.origin.original_sha256, *case.origin.ancestor_sha256, *(a.sha256 for a in case.artifacts))]
            for identity in identities:
                splits = seen.setdefault(identity, set())
                splits.update((manifest.split, *case.origin.prior_splits))
                if "benchmark" in splits and splits & {"development", "tuning"}:
                    raise CorpusError("benchmark_split_contamination")


@dataclass(frozen=True)
class LoadedCase:
    case: CorpusCase
    files: tuple[Path, ...]

    @property
    def case_id(self) -> str:
        return self.case.case_id

    @property
    def profiles(self) -> tuple[ExtractionProfile, ...]:
        return self.case.profiles


@dataclass(frozen=True)
class LoadedCorpus:
    manifest: CorpusManifest
    root: Path
    cases: tuple[LoadedCase, ...]
    files_verified: bool


def load_corpus(path: Path, *, verify_files: bool = True) -> LoadedCorpus:
    """Validate canonical JSON and every artifact. Prep generators require a separate adapter."""
    root = path.resolve().parent
    try:
        manifest = CorpusManifest.model_validate_json(path.read_text(encoding="utf-8"))
    except (OSError, ValueError, ValidationError):
        raise CorpusError("invalid_corpus_manifest") from None
    loaded = []
    for case in manifest.cases:
        artifacts = {}
        for artifact in case.artifacts:
            resolved = (root / artifact.path).resolve()
            if not resolved.is_relative_to(root):
                raise CorpusError("artifact_outside_corpus_root")
            if verify_files:
                try:
                    with resolved.open("rb") as stream:
                        actual = hashlib.file_digest(stream, "sha256").hexdigest()
                except OSError:
                    raise CorpusError("artifact_unavailable") from None
                if actual != artifact.sha256:
                    raise CorpusError("artifact_hash_mismatch")
            artifacts[artifact.id] = resolved
        loaded.append(LoadedCase(case, tuple(artifacts[identity] for identity in case.input_artifact_ids)))
    validate_split_separation(manifest)
    return LoadedCorpus(manifest, root, tuple(loaded), verify_files)
