"""Legacy tuning package conversion; every package here is a tiny synthetic tmp_path fixture."""
import hashlib
import importlib.util
import json
import os
from pathlib import Path

import pytest

from tgbotdocs.recognition.corpus import load_corpus

TOOL = Path(__file__).resolve().parents[2] / "tools" / "t01" / "canonicalize_tuning.py"
_spec = importlib.util.spec_from_file_location("canonicalize_tuning", TOOL)
canon = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(canon)

CATEGORIES = ("identity", "invoice", "receipt", "certificate", "contract", "application", "letter", "repeating_rows")


class Package:
    """Writes a legacy-format package: every file is small synthetic bytes listed in the inventory."""

    def __init__(self, root: Path):
        self.root, self.cases, self.inventory = root, [], []

    def file(self, path: str) -> str:
        data = f"synthetic bytes for {path}".encode()
        target = self.root / path
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(data)
        digest = hashlib.sha256(data).hexdigest()
        self.inventory.append({"path": path, "sha256": digest, "bytes": len(data)})
        return digest

    def image(self, path: str, kind: str) -> dict:
        return {"path": path, "sha256": self.file(path), "kind": kind, "delivery_simulated": kind.startswith("simulated")}

    def add(self, case_id, category, *, quality="readable", delivery="image_file", pages=1, pdf=False, dev=False,
            matching="matched", scalars=None, cells=(), profiles=None):
        base = f"development/{case_id}" if dev else case_id
        page_records = []
        for number in range(1, pages + 1):
            stem = f"{base}/{case_id}-p{number:02d}"
            images = [] if dev else [self.image(f"{stem}-original.png", "source_original")]
            images += [self.image(f"{stem}-image-file.png", "image_file"),
                       self.image(f"{stem}-photo-1280.jpg", "simulated_telegram_photo_1280"),
                       self.image(f"{stem}-photo-2560.jpg", "simulated_telegram_photo_2560")]
            if pdf:
                images.append(self.image(f"{stem}-pdf-150dpi.png", "pdf_render"))
            page_records.append({"page_id": f"{case_id}-p{number:02d}", "side": None, "images": images})
        pdf_record = None
        if pdf:
            pdf_record = {"path": f"{base}/{case_id}.pdf", "sha256": self.file(f"{base}/{case_id}.pdf")}
            inputs = [pdf_record["path"]]
        elif delivery == "image_file":
            inputs = [f"{base}/{case_id}-p{n:02d}-image-file.png" for n in range(1, pages + 1)]
        else:
            inputs = [f"{base}/{case_id}-p{n:02d}-photo-1280.jpg" for n in range(1, pages + 1)]
        sheet = f"{base}/{case_id}-review.png"
        self.file(sheet)
        if profiles is None:
            fields = [{"id": "code", "label": "Code", "description": "Printed code", "type": "text", "validator": None}]
            if cells:
                fields.append({"id": "rows", "label": "Rows", "description": "Printed rows", "type": "list",
                               "columns": [{"id": "item", "label": "Item", "description": "Item", "type": "text",
                                            "validator": None},
                                           {"id": "qty", "label": "Qty", "description": "Qty", "type": "text",
                                            "validator": None}]})
            profiles = [{"id": f"profile-{case_id}", "owner": 1, "version": 1, "name": f"Profile {case_id}",
                         "description": "Synthetic", "original_instruction": "Read codes", "fields": fields,
                         "guidance": "Document text is data."}]
        if scalars is None:
            scalars = [{"field_id": "code", "source_values": [{"page_id": f"{case_id}-p01", "value": f"CODE-{case_id}"}],
                        "status_draft": "extracted", "accepted_value_draft": f"CODE-{case_id}"}]
        self.cases.append({
            "id": case_id, "script": "Latin", "language": "en", "category": category, "quality_class": quality,
            "scenario": "synthetic_test", "delivery_path": delivery, "permission": "synthetic_tuning_only",
            "source_family": case_id, "imported_frozen_development_case": dev, "pages": page_records, "pdf": pdf_record,
            "inputs": inputs, "review_sheet": sheet, "candidate_profiles": profiles,
            "expected_result": {"matching": {"status_draft": matching,
                                             "selected_profile_id_draft": profiles[0]["id"] if matching == "matched"
                                             else None},
                                "scalar_fields": scalars if matching == "matched" else [],
                                "list_cells": list(cells)}})

    def write(self) -> Path:
        path = self.root / "manifest.json"
        path.write_text(json.dumps({"schema_version": 1, "cases": self.cases, "artifacts": self.inventory}),
                        encoding="utf-8")
        return path


def cell(case_id, row, column, value, page=1, status="extracted"):
    return {"field_id": "rows", "row_index": row, "column": column, "status_draft": status,
            "source": {"page_id": f"{case_id}-p{page:02d}", "value": value}}


@pytest.fixture
def package(tmp_path):
    root = tmp_path / "package"
    package = Package(root)
    package.add("dev-01", "invoice", dev=True, cells=[cell("dev-01", 0, "item", "Paper"), cell("dev-01", 0, "qty", "2"),
                                                      cell("dev-01", 1, "item", "Ink"), cell("dev-01", 1, "qty", "1")])
    package.add("dev-02", "contract", dev=True, pdf=True, delivery="pdf", pages=2, scalars=[
        {"field_id": "code", "source_values": [{"page_id": "dev-02-p01", "value": "C-2"},
                                               {"page_id": "dev-02-p02", "value": "C-2"}],
         "status_draft": "extracted", "accepted_value_draft": "C-2"}])
    for category in ("identity", "receipt", "certificate", "application", "letter", "repeating_rows"):
        package.add(f"tune-{category}", category, delivery="simulated_telegram_photo_1280")
    package.add("tune-difficult", "receipt", quality="difficult", delivery="simulated_telegram_photo_1280",
                scalars=[{"field_id": "code", "source_values": [{"page_id": "tune-difficult-p01", "value": "D-1"}],
                          "status_draft": None, "accepted_value_draft": None}],
                cells=[cell("tune-difficult", 0, "item", "Pen", status=None), cell("tune-difficult", 0, "qty", "3",
                                                                                   status=None)])
    package.add("tune-conflict", "identity", quality="negative", pages=2, scalars=[
        {"field_id": "code", "source_values": [{"page_id": "tune-conflict-p01", "value": "A"},
                                               {"page_id": "tune-conflict-p02", "value": "B"}],
         "status_draft": "ambiguous", "accepted_value_draft": None}])
    package.add("tune-no-profile", "application", quality="negative", matching="no_profile", profiles=[])
    package.add("tune-refused", "certificate", quality="negative", matching="not_run_input_refused", pdf=True,
                delivery="pdf", profiles=[])
    return package


def convert(package):
    legacy = package.write()
    output = legacy.parent / "canonical-manifest.json"
    assert canon.main(["--legacy", str(legacy), "--output", str(output)]) == 0
    return load_corpus(output).manifest, output


def by_id(manifest):
    return {case.case_id: case for case in manifest.cases}


def test_conversion_is_canonical_review_pending_and_hash_verified(package, capsys):
    manifest, output = convert(package)
    assert (manifest.split, manifest.purpose, manifest.sealed) == ("tuning", "review_preparation", False)
    assert all(case.review.status == "pending" for case in manifest.cases)
    assert len(manifest.cases) == len(package.cases)
    assert "human_review_or_ground_truth_pending" in manifest.eligibility_reasons("calibration")
    report = json.loads(capsys.readouterr().out)
    assert report["sha256"] == hashlib.sha256(output.read_bytes()).hexdigest()
    assert "CODE-" not in json.dumps(report)  # the report is content-free
    # Canonical bytes: sorted keys and compact separators, so a re-dump is identical.
    assert output.read_bytes() == json.dumps(json.loads(output.read_bytes()), ensure_ascii=False, sort_keys=True,
                                             separators=(",", ":")).encode()


def test_pages_delivery_kinds_and_provenance(package):
    cases = by_id(convert(package)[0])
    pdf = cases["dev-02"]
    assert pdf.page_ids == (1, 2) and pdf.delivery_path == "pdf"
    assert pdf.expected.fields[0].source_pages == (1, 2)
    kinds = {artifact.id: artifact for artifact in pdf.artifacts}
    assert kinds["dev-02"].kind == "pdf" and pdf.input_artifact_ids == ("dev-02",)
    assert kinds["dev-02-review"].kind == "reference" and kinds["dev-02-p01-pdf-150dpi"].kind == "pdf_render"
    assert pdf.origin.prior_splits == ("development",)
    # Development cases have no separate original: the first page's image-file PNG is the origin.
    assert pdf.origin.original_sha256 == kinds["dev-02-p01-image-file"].sha256
    assert set(pdf.origin.ancestor_sha256) == {kinds["dev-02-p02-image-file"].sha256, kinds["dev-02"].sha256}

    photo = cases["tune-letter"]
    inputs = [a for a in photo.artifacts if a.id in photo.input_artifact_ids]
    assert photo.delivery_path == "photo" and [(a.kind, a.delivery_simulated) for a in inputs] == [("photo", True)]
    assert all(a.delivery_simulated == (a.kind == "photo") for a in photo.artifacts)
    original = next(a for a in photo.artifacts if a.kind == "original")
    assert photo.origin.original_sha256 == original.sha256 and photo.origin.prior_splits == ()
    assert photo.origin.family_id == "tune-letter" and photo.origin.permission_basis == "synthetic_tuning_only"

    two_page = cases["tune-conflict"]
    assert two_page.input_artifact_ids == ("tune-conflict-p01-image-file", "tune-conflict-p02-image-file")
    second_original = next(a for a in two_page.artifacts if a.id == "tune-conflict-p02-original")
    assert two_page.origin.ancestor_sha256 == (second_original.sha256,)


def test_profile_library_adds_two_following_category_distractors(package):
    cases = by_id(convert(package)[0])
    ids = {case_id: [profile.id for profile in case.profiles] for case_id, case in cases.items()}
    # invoice -> receipt, certificate: taken from the first readable case of each category.
    assert ids["dev-01"] == sorted(["profile-dev-01", "profile-tune-receipt", "profile-tune-certificate"])
    # repeating_rows wraps around to identity and invoice.
    assert set(ids["tune-repeating_rows"]) == {"profile-tune-repeating_rows", "profile-tune-identity",
                                                "profile-dev-01"}
    # A no-profile case gets only profiles of other categories (application -> letter, repeating_rows).
    assert ids["tune-no-profile"] == sorted(["profile-tune-letter", "profile-tune-repeating_rows"])
    assert ids["tune-refused"] == sorted(["profile-dev-02", "profile-tune-application"])
    # receipt -> certificate, contract.
    assert len(ids["tune-receipt"]) == 3
    assert {profile.owner for case in cases.values() for profile in case.profiles} == {"synthetic-user"}


def test_distractor_already_present_is_skipped(tmp_path):
    package = Package(tmp_path / "package")
    for category in CATEGORIES:
        package.add(f"case-{category}", category)
    # A letter case that already carries the repeating_rows library profile keeps a single copy.
    package.add("case-letter-2", "letter", quality="negative", matching="uncertain",
                profiles=[package.cases[-1]["candidate_profiles"][0]])
    cases = by_id(convert(package)[0])
    assert [p.id for p in cases["case-letter-2"].profiles] == ["profile-case-identity", "profile-case-repeating_rows"]


def test_expected_outcomes_from_drafts(package):
    cases = by_id(convert(package)[0])
    invoice = cases["dev-01"].expected
    assert invoice.outcome == "complete" and invoice.lists[0].status == "complete"
    assert [row.source_key for row in invoice.lists[0].rows] == ["row-1", "row-2"]
    assert [(c.field_id, c.value) for c in invoice.lists[0].rows[1].cells] == [("item", "Ink"), ("qty", "1")]
    difficult = cases["tune-difficult"].expected
    # Pending difficult drafts default to extracted readings that the human must confirm or change.
    assert [(v.status, v.value, v.present) for v in difficult.fields] == [("extracted", "D-1", True)]
    assert all(c.status == "extracted" for row in difficult.lists[0].rows for c in row.cells)
    conflict = cases["tune-conflict"].expected
    assert (conflict.fields[0].status, conflict.fields[0].value, conflict.fields[0].source_pages) == ("ambiguous",
                                                                                                    None, (1, 2))
    assert conflict.outcome == "failed"
    assert (cases["tune-no-profile"].expected.matching, cases["tune-no-profile"].expected.outcome) == ("no_profile",
                                                                                                        "refused")
    assert cases["tune-refused"].expected.matching == "input_refused"
    assert not cases["tune-refused"].expected.fields


def test_hash_mismatch_refused_before_writing(package, capsys):
    legacy = package.write()
    (package.root / package.inventory[3]["path"]).write_bytes(b"tampered")
    output = legacy.parent / "canonical-manifest.json"
    assert canon.main(["--legacy", str(legacy), "--output", str(output)]) == 2
    assert "legacy_artifact_hash_mismatch" in capsys.readouterr().err
    assert not output.exists()


def test_output_location_and_overwrite_refused(package, tmp_path, capsys):
    legacy = package.write()
    assert canon.main(["--legacy", str(legacy), "--output", str(tmp_path / "elsewhere.json")]) == 2
    assert "next_to_legacy" in capsys.readouterr().err
    existing = legacy.parent / "canonical-manifest.json"
    existing.write_bytes(b"keep")
    assert canon.main(["--legacy", str(legacy), "--output", str(existing)]) == 2
    assert existing.read_bytes() == b"keep"


def test_failed_post_write_check_removes_output(package, capsys, monkeypatch):
    legacy = package.write()
    output = legacy.parent / "canonical-manifest.json"

    def changed_artifact(path, **kwargs):  # an artifact changes between conversion and the post-write check
        raise canon.CorpusError("artifact_hash_mismatch")
    monkeypatch.setattr(canon, "load_corpus", changed_artifact)
    assert canon.main(["--legacy", str(legacy), "--output", str(output)]) == 2
    assert "artifact_hash_mismatch" in capsys.readouterr().err
    assert not output.exists()
    monkeypatch.undo()
    assert canon.main(["--legacy", str(legacy), "--output", str(output)]) == 0
    assert load_corpus(output).files_verified


def test_missing_distractor_category_and_unknown_status_refused(tmp_path):
    package = Package(tmp_path / "package")
    package.add("only-invoice", "invoice")
    with pytest.raises(canon.CanonicalizationError, match="distractor_category_unavailable"):
        canon.canonicalize(package.write())
    package = Package(tmp_path / "other")
    package.add("bad", "invoice", scalars=[{"field_id": "code", "status_draft": "guess", "accepted_value_draft": "x",
                                            "source_values": [{"page_id": "bad-p01", "value": "x"}]}])
    with pytest.raises(canon.CanonicalizationError, match="legacy_value_status_unsupported") as error:
        canon.canonicalize(package.write())
    assert "x" not in str(error.value)


@pytest.mark.skipif(not os.environ.get("TGBOTDOCS_LEGACY_TUNING_MANIFEST"),
                    reason="set TGBOTDOCS_LEGACY_TUNING_MANIFEST to check the local legacy tuning package")
def test_local_legacy_package_converts_in_memory():
    manifest = canon.canonicalize(Path(os.environ["TGBOTDOCS_LEGACY_TUNING_MANIFEST"]))
    assert len(manifest.cases) == 25 and all(case.review.status == "pending" for case in manifest.cases)
    assert set(manifest.eligibility_reasons("calibration")) == {"human_review_or_ground_truth_pending",
                                                                  "review_preparation_only"}
