"""Corpus invariants; test attestations below are synthetic test data only."""
from datetime import datetime, timezone
import hashlib
import json

import pytest
from pydantic import ValidationError

from tgbotdocs.recognition.contracts import ExtractionProfile, ScalarField, ListField
from tgbotdocs.recognition.corpus import (Artifact, Origin, HumanReview, ExpectedValue, ExpectedList,
    ExpectedOutcome, CorpusCase, CorpusManifest, CorpusError, case_review_digest, declared_denominators,
    load_corpus, validate_split_separation)


HASH = hashlib.sha256(b"synthetic test bytes").hexdigest()
FIELD = ScalarField(id="code", label="Code", description="Printed code", type="text")


def make_case(identity="case-1", *, values=None, rows=None, negative=False, quality="readable", **kwargs):
    fields = (FIELD,) if rows is None else (ListField(id="items", label="Items", description="Printed rows", columns=(FIELD,)),)
    profile = ExtractionProfile(id="profile", owner="test-owner", version=1, name="Test", description="Synthetic test",
                                original_instruction="Read printed codes", fields=fields)
    if negative:
        expected = ExpectedOutcome(matching="not_document", outcome="refused")
    elif rows is None:
        expected = ExpectedOutcome(matching="matched", profile_id="profile", outcome="complete", fields=values or (
            ExpectedValue(field_id="code", status="extracted", present=True, value="PRIVATE-CODE", source_pages=(1,)),))
    else:
        expected = ExpectedOutcome(matching="matched", profile_id="profile", outcome="complete",
                                   lists=(ExpectedList(field_id="items", status="complete", enumeration_complete=True, rows=rows),))
    args = dict(case_id=identity, origin=Origin(family_id=identity, kind="synthetic", permission_basis="synthetic only",
                       original_sha256=hashlib.sha256(identity.encode()).hexdigest()), script="Latin", language="en",
                category="letter", quality=quality, scenario="synthetic_test", delivery_path="image_file",
                artifacts=(Artifact(id="input", path=f"{identity}.png", sha256=HASH, kind="image_file"),),
                input_artifact_ids=("input",), page_ids=(1,), profiles=(profile,), expected=expected)
    args.update(kwargs)
    return CorpusCase(**args)


def manifest(*cases, split="tuning", purpose="review_preparation", **kwargs):
    return CorpusManifest(schema_version=1, split=split, purpose=purpose, cases=cases,
                          denominators=declared_denominators(cases), **kwargs)


def reviewed(case):
    data = case.model_dump()
    data["review"] = HumanReview(status="verified", reviewer="Synthetic test reviewer", method="script_reading",
        reviewed_at=datetime(2026, 9, 27, tzinfo=timezone.utc), subject_sha256=case_review_digest(case), reviewer_kind="human")
    return CorpusCase.model_validate(data)


def test_pending_review_never_eligible_and_denominators_include_all_cases():
    corpus = manifest(make_case(), make_case("negative", negative=True, quality="negative"))
    assert corpus.denominators.cases == 2
    assert corpus.denominators.readable_present_values == 1
    assert "human_review_or_ground_truth_pending" in corpus.eligibility_reasons("calibration")
    with pytest.raises(CorpusError, match="ineligible"):
        corpus.require_eligible("calibration")


def test_review_binds_profiles_truth_metadata_and_bytes():
    case = reviewed(make_case())
    assert case.review.subject_sha256 == case_review_digest(case)
    data = case.model_dump()
    data["language"] = "ru"
    with pytest.raises(ValidationError, match="review_not_bound"):
        CorpusCase.model_validate(data)
    with pytest.raises(ValidationError, match="attestation"):
        HumanReview(status="verified")
    with pytest.raises(ValidationError, match="timezone"):
        HumanReview(status="verified", reviewer="Human", method="script_reading", reviewed_at=datetime(2026, 1, 1),
                    subject_sha256=HASH, reviewer_kind="human")


@pytest.mark.parametrize("path", ["../outside.png", "C:/private.png", "a\\b.png", "/absolute.png", "a/./b.png", "."])
def test_unsafe_paths_rejected(path):
    with pytest.raises(ValidationError, match="unsafe_artifact_path"):
        Artifact(id="a", path=path, sha256=HASH, kind="image_file")


def test_loader_checks_hashes_and_preserves_input_order(tmp_path):
    case = make_case()
    path = tmp_path / "manifest.json"
    path.write_text(manifest(case).model_dump_json(), encoding="utf-8")
    (tmp_path / "case-1.png").write_bytes(b"synthetic test bytes")
    loaded = load_corpus(path)
    assert loaded.files_verified and loaded.cases[0].files == ((tmp_path / "case-1.png").resolve(),)
    assert loaded.cases[0].profiles == case.profiles
    (tmp_path / "case-1.png").write_bytes(b"changed")
    with pytest.raises(CorpusError, match="artifact_hash_mismatch"):
        load_corpus(path)
    assert not load_corpus(path, verify_files=False).files_verified


def test_loader_rejects_review_preparation_generator_format_safely(tmp_path):
    path = tmp_path / "manifest.json"
    path.write_text(json.dumps({"schema": "t01b-tuning-review-v3", "private": "secret text"}), encoding="utf-8")
    with pytest.raises(CorpusError) as error:
        load_corpus(path)
    assert str(error.value) == "invalid_corpus_manifest"
    assert "secret" not in str(error.value)


def test_denominator_and_schema_coercion_rejected():
    data = manifest(make_case()).model_dump()
    data["denominators"]["known_readable_values"] = 999
    with pytest.raises(ValidationError, match="denominators"):
        CorpusManifest.model_validate(data)
    with pytest.raises(ValidationError):
        ExpectedValue(field_id="code", status="extracted", present="true", value="x", source_pages=(1,))
    with pytest.raises(ValidationError, match="exact_profile_schema"):
        make_case(values=(ExpectedValue(field_id="unknown", status="extracted", present=True, value="x", source_pages=(1,)),))


def test_readable_ground_truth_cannot_hide_present_unknown_value():
    value = ExpectedValue(field_id="code", status="unreadable", present=True, source_pages=(1,))
    expected = ExpectedOutcome(matching="matched", profile_id="profile", outcome="failed", fields=(value,))
    with pytest.raises(ValidationError, match="readable_present"):
        make_case(expected=expected)
    assert make_case(quality="difficult", expected=expected).expected.fields[0].value is None


def test_frozen_development_and_tuning_may_overlap_but_never_benchmark():
    case = make_case()
    development = manifest(case, split="development")
    tuning = manifest(case)
    validate_split_separation(development, tuning)
    benchmark = manifest(case, split="benchmark")
    with pytest.raises(CorpusError, match="contamination"):
        validate_split_separation(development, benchmark)
    origin = case.origin.model_copy(update={"prior_splits": ("development",)})
    with pytest.raises(ValidationError, match="cannot_be_benchmark"):
        manifest(make_case(origin=origin), split="benchmark")
    # A renamed family still cannot hide an ancestor hash or duplicated artifact bytes.
    with pytest.raises(CorpusError, match="contamination"):
        validate_split_separation(development, manifest(make_case("renamed"), split="benchmark"))


def test_variants_are_artifacts_not_extra_logical_cases():
    case = make_case()
    origin = case.origin.model_copy()
    with pytest.raises(ValidationError, match="duplicate_identity"):
        manifest(case, make_case("variant", origin=origin))


def test_allowed_values_are_explicit_and_review_bound():
    value = ExpectedValue(field_id="code", status="extracted", present=True, value="A", allowed_values=("B",), source_pages=(1,))
    assert make_case(values=(value,)).expected.fields[0].allowed_values == ("B",)
    with pytest.raises(ValidationError, match="allowed_value"):
        ExpectedValue(field_id="code", status="extracted", present=True, value="A", allowed_values=(True,), source_pages=(1,))


def test_reference_review_aid_is_allowed_but_never_an_input():
    sheet = Artifact(id="sheet", path="case-1-review.png", sha256=HASH, kind="reference")
    case = make_case(artifacts=(Artifact(id="input", path="case-1.png", sha256=HASH, kind="image_file"), sheet))
    assert case.input_artifact_ids == ("input",)
    with pytest.raises(ValidationError, match="primary_delivery_kind_mismatch"):
        make_case(artifacts=(sheet,), input_artifact_ids=("sheet",))
