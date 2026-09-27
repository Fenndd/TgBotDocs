"""Convert the legacy T01b tuning review package into a canonical, review-pending corpus manifest.

Usage (from the repository root, in the project environment):

    python tools/t01/canonicalize_tuning.py --legacy <package>/manifest.json --output <package>/canonical-manifest.json

The output is written next to the legacy manifest, so artifact paths stay relative to that directory.
Nothing in the legacy package is modified and an existing output is never overwritten. Every artifact in
the legacy inventory is hash-verified before conversion; the written manifest is loaded again with
``corpus.load_corpus`` so every canonical artifact hash is verified too. No model is run.

Mapping (the canonical schema forbids extra keys, so the rules live here, not in the manifest):

- Case: ``case_id`` = legacy ``id``; split ``tuning``, purpose ``review_preparation``; every review is pending.
- Origin: ``family_id`` = ``source_family``; kind ``synthetic``; ``permission_basis`` = legacy ``permission``;
  ``original_sha256`` = the first page's ``source_original`` (the image-file PNG for imported development
  cases, which have no separate original); ``ancestor_sha256`` = the other pages' originals and the source
  PDF; ``prior_splits`` = ``("development",)`` for imported frozen development cases.
- Delivery: ``image_file`` -> ``image_file``; ``pdf`` -> ``pdf``; ``simulated_telegram_photo_*`` -> ``photo``.
  Simulated photo JPEGs are ``kind="photo"`` with ``delivery_simulated=True`` whether or not they are the
  input. Other variants keep their kinds (``source_original`` -> ``original``, ``pdf_render``, ``image_file``);
  review sheets are ``reference`` aids, never inputs. Artifact IDs are file-name stems.
- Pages: ``page_ids`` = 1..N in document order (legacy page order: file order, then pages within a file);
  legacy page IDs such as ``dev-08-p02`` map to these integers.
- Profiles: legacy candidate profiles become ``ExtractionProfile`` objects owned by ``synthetic-user``.
  Profile library: every case also receives two distractor profiles, one from each of the two categories
  following the case's category in the cyclic order ``identity, invoice, receipt, certificate, contract,
  application, letter, repeating_rows``; each distractor is the expected profile of the first readable matched
  case of that category (legacy case order). A distractor whose ID is already present is skipped. The rule is
  applied uniformly, including negative cases (a ``no_profile`` case therefore only receives profiles of other
  categories). Profiles within a case are ordered by ID so the correct profile has no fixed position.
- Expected outcome: matching drafts ``matched``, ``no_profile``, ``uncertain``, ``unreadable``, ``mixed``,
  ``not_document`` map directly and ``not_run_input_refused`` maps to ``input_refused``; non-matched cases
  carry no values. Scalar ``extracted`` drafts keep the recorded value and its source pages; ``ambiguous``
  drafts (conflicting card sides) have no value. Difficult-case values with a pending draft status default
  to ``extracted`` with the single recorded value: the human confirms or changes their visibility in the
  review form. Lists get rows ``row-1..`` in legacy row order with status ``complete``. The outcome is
  recomputed from the values.
"""
from __future__ import annotations

import argparse
from collections import defaultdict
import hashlib
import json
from pathlib import Path, PurePosixPath
import sys

from pydantic import ValidationError

from tgbotdocs.recognition.contracts import ExtractionProfile, FormatValidator, ListField, ScalarField
from tgbotdocs.recognition.corpus import (Artifact, CorpusCase, CorpusError, CorpusManifest, ExpectedList,
                                          ExpectedOutcome, ExpectedRow, ExpectedValue, Origin, declared_denominators,
                                          load_corpus, validate_split_separation)
from tgbotdocs.recognition.review import (ReviewError, expected_outcome_status, manifest_bytes, sha256_bytes,
                                          write_new_file)

OWNER = "synthetic-user"
CATEGORY_ORDER = ("identity", "invoice", "receipt", "certificate", "contract", "application", "letter",
                  "repeating_rows")
MATCHING = {"matched": "matched", "no_profile": "no_profile", "uncertain": "uncertain", "unreadable": "unreadable",
            "mixed": "mixed", "not_document": "not_document", "not_run_input_refused": "input_refused"}
IMAGE_KINDS = {"source_original": "original", "image_file": "image_file", "pdf_render": "pdf_render",
               "simulated_telegram_photo_1280": "photo", "simulated_telegram_photo_2560": "photo"}


class CanonicalizationError(ValueError):
    """Fixed, content-free code; ``detail`` names a case ID at most."""

    def __init__(self, code: str, detail: str = ""):
        super().__init__(code)
        self.code = code
        self.detail = detail


def _sha256(path: Path) -> str:
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def verify_inventory(legacy: dict, root: Path) -> dict[str, str]:
    """Hash-verify every legacy artifact; returns path -> sha256."""
    hashes: dict[str, str] = {}
    root = root.resolve()
    for asset in legacy["artifacts"]:
        path = asset["path"]
        try:
            Artifact(id="inventory", path=path, sha256=asset["sha256"], kind="reference")
        except ValidationError:
            raise CanonicalizationError("legacy_artifact_path_or_hash_invalid") from None
        resolved = (root / path).resolve()
        if path in hashes or not resolved.is_relative_to(root):
            raise CanonicalizationError("legacy_artifact_inventory_invalid")
        try:
            actual, size = _sha256(resolved), resolved.stat().st_size
        except OSError:
            raise CanonicalizationError("legacy_artifact_unavailable") from None
        if actual != asset["sha256"] or size != asset["bytes"]:
            raise CanonicalizationError("legacy_artifact_hash_mismatch")
        hashes[path] = actual
    return hashes


def _profile(raw: dict) -> ExtractionProfile:
    def scalar(field: dict) -> ScalarField:
        validator = field.get("validator")
        return ScalarField(id=field["id"], label=field["label"], description=field["description"], type=field["type"],
                           validator=None if validator is None else FormatValidator.model_validate(validator))

    fields = []
    for field in raw["fields"]:
        if field["type"] == "list":
            fields.append(ListField(id=field["id"], label=field["label"], description=field["description"],
                                    columns=tuple(scalar(column) for column in field["columns"])))
        else:
            fields.append(scalar(field))
    return ExtractionProfile(id=raw["id"], owner=OWNER, version=raw["version"], name=raw["name"],
                             description=raw["description"], original_instruction=raw["original_instruction"],
                             fields=tuple(fields), guidance=raw.get("guidance") or "")


def _artifacts(case: dict, hashes: dict[str, str]) -> tuple[list[Artifact], str, tuple[str, ...]]:
    """Artifacts, the origin hash and the ancestor hashes of one legacy case."""
    artifacts: dict[str, Artifact] = {}

    def add(path: str, kind: str, recorded: str | None = None) -> Artifact:
        if path not in hashes:
            raise CanonicalizationError("legacy_artifact_not_inventoried", case["id"])
        if recorded is not None and recorded != hashes[path]:
            raise CanonicalizationError("legacy_artifact_hash_mismatch", case["id"])
        if path in artifacts:
            if artifacts[path].kind != kind:
                raise CanonicalizationError("legacy_artifact_kind_conflict", case["id"])
            return artifacts[path]
        artifacts[path] = Artifact(id=PurePosixPath(path).stem, path=path, sha256=hashes[path], kind=kind,
                                   delivery_simulated=kind == "photo")
        return artifacts[path]

    originals = []
    for page in case["pages"]:
        page_originals = []
        for image in page["images"]:
            kind = IMAGE_KINDS.get(image["kind"])
            if kind is None:
                raise CanonicalizationError("legacy_artifact_kind_unknown", case["id"])
            if (kind == "photo") != bool(image["delivery_simulated"]):
                raise CanonicalizationError("legacy_simulation_flag_inconsistent", case["id"])
            artifact = add(image["path"], kind, image["sha256"])
            if image["kind"] == "source_original":
                page_originals.insert(0, artifact.sha256)
            elif image["kind"] == "image_file":
                page_originals.append(artifact.sha256)
        if not page_originals:
            raise CanonicalizationError("legacy_page_original_missing", case["id"])
        originals.append(page_originals[0])
    ancestors = list(originals[1:])
    if case.get("pdf"):
        ancestors.append(add(case["pdf"]["path"], "pdf", case["pdf"]["sha256"]).sha256)
    if case.get("review_sheet"):
        add(case["review_sheet"], "reference")
    ancestors = tuple(dict.fromkeys(value for value in ancestors if value != originals[0]))
    return list(artifacts.values()), originals[0], ancestors


def _expected(case: dict, profiles: tuple[ExtractionProfile, ...], pages: dict[str, int]) -> ExpectedOutcome:
    draft = case["expected_result"]
    matching = MATCHING.get(draft["matching"]["status_draft"])
    if matching is None:
        raise CanonicalizationError("legacy_matching_status_unsupported", case["id"])
    if matching != "matched":
        return ExpectedOutcome(matching=matching, outcome="refused")
    profile_id = draft["matching"]["selected_profile_id_draft"]
    profile = next((item for item in profiles if item.id == profile_id), None)
    if profile is None:
        raise CanonicalizationError("legacy_expected_profile_missing", case["id"])

    def page_numbers(page_ids) -> tuple[int, ...]:
        try:
            return tuple(sorted({pages[page_id] for page_id in page_ids}))
        except KeyError:
            raise CanonicalizationError("legacy_page_unknown", case["id"]) from None

    fields = []
    for scalar in draft["scalar_fields"]:
        sources = scalar["source_values"]
        source_pages = page_numbers(value["page_id"] for value in sources)
        recorded = {value["value"] for value in sources}
        status = scalar["status_draft"]
        if status == "extracted":
            value = scalar["accepted_value_draft"]
            if value is None or value not in recorded:
                raise CanonicalizationError("legacy_value_inconsistent", case["id"])
            fields.append(ExpectedValue(field_id=scalar["field_id"], status="extracted", present=True, value=value,
                                        source_pages=source_pages))
        elif status == "ambiguous":
            fields.append(ExpectedValue(field_id=scalar["field_id"], status="ambiguous", present=True,
                                        source_pages=source_pages))
        elif status is None and case["quality_class"] == "difficult" and len(recorded) == 1:
            fields.append(ExpectedValue(field_id=scalar["field_id"], status="extracted", present=True,
                                        value=recorded.pop(), source_pages=source_pages))
        else:
            raise CanonicalizationError("legacy_value_status_unsupported", case["id"])
    cells: dict[str, dict[int, dict[str, dict]]] = defaultdict(lambda: defaultdict(dict))
    for cell in draft["list_cells"]:
        pending = cell["status_draft"] is None and case["quality_class"] == "difficult"
        if cell["status_draft"] != "extracted" and not pending:
            raise CanonicalizationError("legacy_value_status_unsupported", case["id"])
        row = cells[cell["field_id"]][cell["row_index"]]
        if cell["column"] in row:
            raise CanonicalizationError("legacy_list_cell_duplicate", case["id"])
        row[cell["column"]] = cell
    lists = []
    for field in profile.fields:
        if not isinstance(field, ListField):
            continue
        rows = []
        for number, (_, row) in enumerate(sorted(cells.pop(field.id, {}).items()), 1):
            row_cells = tuple(ExpectedValue(field_id=column.id, status="extracted", present=True,
                                            value=row[column.id]["source"]["value"],
                                            source_pages=page_numbers((row[column.id]["source"]["page_id"],)))
                              for column in field.columns if column.id in row)
            if len(row_cells) != len(row):
                raise CanonicalizationError("legacy_list_column_unknown", case["id"])
            row_pages = tuple(sorted({page for cell in row_cells for page in cell.source_pages}))
            rows.append(ExpectedRow(source_key=f"row-{number}", source_pages=row_pages, cells=row_cells))
        lists.append(ExpectedList(field_id=field.id, status="complete", enumeration_complete=True, rows=tuple(rows)))
    if cells:
        raise CanonicalizationError("legacy_list_not_in_profile", case["id"])
    fields, lists = tuple(fields), tuple(lists)
    return ExpectedOutcome(matching="matched", profile_id=profile_id, outcome=expected_outcome_status(fields, lists),
                           fields=fields, lists=lists)


def _case(case: dict, hashes: dict[str, str]) -> CorpusCase:
    pages = {page["page_id"]: number for number, page in enumerate(case["pages"], 1)}
    if len(pages) != len(case["pages"]):
        raise CanonicalizationError("legacy_page_duplicate", case["id"])
    artifacts, original, ancestors = _artifacts(case, hashes)
    by_path = {artifact.path: artifact for artifact in artifacts}
    if any(path not in by_path for path in case["inputs"]):
        raise CanonicalizationError("legacy_input_unknown", case["id"])
    delivery = case["delivery_path"]
    delivery = "photo" if delivery.startswith("simulated_telegram_photo_") else delivery
    profiles = tuple(_profile(profile) for profile in case["candidate_profiles"])
    origin = Origin(family_id=case["source_family"], kind="synthetic", permission_basis=case["permission"],
                    original_sha256=original, ancestor_sha256=ancestors,
                    prior_splits=("development",) if case.get("imported_frozen_development_case") else ())
    return CorpusCase(case_id=case["id"], origin=origin, script=case["script"], language=case["language"],
                      category=case["category"], quality=case["quality_class"], scenario=case["scenario"],
                      delivery_path=delivery, artifacts=tuple(artifacts),
                      input_artifact_ids=tuple(by_path[path].id for path in case["inputs"]),
                      page_ids=tuple(range(1, len(pages) + 1)), profiles=profiles,
                      expected=_expected(case, profiles, pages))


def _with_distractors(cases: list[CorpusCase]) -> list[CorpusCase]:
    library: dict[str, ExtractionProfile] = {}
    for case in cases:
        if case.quality == "readable" and case.expected and case.expected.matching == "matched":
            library.setdefault(case.category, next(p for p in case.profiles if p.id == case.expected.profile_id))
    result = []
    for case in cases:
        profiles = {profile.id: profile for profile in case.profiles}
        position = CATEGORY_ORDER.index(case.category)
        for step in (1, 2):
            category = CATEGORY_ORDER[(position + step) % len(CATEGORY_ORDER)]
            if category not in library:
                raise CanonicalizationError("distractor_category_unavailable", case.case_id)
            profiles.setdefault(library[category].id, library[category])
        ordered = tuple(profile for _, profile in sorted(profiles.items()))
        result.append(CorpusCase.model_validate({**case.model_dump(exclude={"profiles"}), "profiles": ordered}))
    return result


def canonicalize(legacy_path: Path) -> CorpusManifest:
    """Verify the legacy package and return its canonical, review-pending manifest (nothing is written)."""
    try:
        legacy = json.loads(legacy_path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        raise CanonicalizationError("legacy_manifest_unreadable") from None
    try:
        if legacy.get("schema_version") != 1 or not isinstance(legacy.get("cases"), list):
            raise CanonicalizationError("legacy_manifest_invalid")
        hashes = verify_inventory(legacy, legacy_path.parent)
        cases = []
        for case in legacy["cases"]:
            try:
                cases.append(_case(case, hashes))
            except ValidationError:
                raise CanonicalizationError("canonical_validation_failed", str(case.get("id"))) from None
        cases = _with_distractors(cases)
        manifest = CorpusManifest(schema_version=1, split="tuning", purpose="review_preparation", cases=tuple(cases),
                                  denominators=declared_denominators(tuple(cases)))
        validate_split_separation(manifest)
    except (KeyError, TypeError, AttributeError):
        raise CanonicalizationError("legacy_manifest_invalid") from None
    except ValidationError:
        raise CanonicalizationError("canonical_validation_failed") from None
    return manifest


def write_canonical(legacy_path: Path, output: Path) -> tuple[CorpusManifest, str]:
    if output.resolve().parent != legacy_path.resolve().parent:
        raise CanonicalizationError("canonical_manifest_must_be_next_to_legacy_manifest")
    if output.exists():
        raise CanonicalizationError("output_exists")
    manifest = canonicalize(legacy_path)
    data = manifest_bytes(manifest)
    try:
        write_new_file(output, data)
    except ReviewError as error:
        raise CanonicalizationError(error.code) from None
    load_corpus(output)  # verifies every canonical artifact hash against the files on disk
    return manifest, sha256_bytes(data)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Convert the legacy T01b tuning package to a canonical manifest.")
    parser.add_argument("--legacy", type=Path, required=True, help="legacy tuning package manifest.json")
    parser.add_argument("--output", type=Path, required=True, help="new canonical manifest next to the legacy one")
    args = parser.parse_args(argv)
    try:
        manifest, digest = write_canonical(args.legacy, args.output)
    except CanonicalizationError as error:
        detail = f" ({error.detail})" if error.detail else ""
        print(f"error: {error.code}{detail}", file=sys.stderr)
        return 2
    except CorpusError as error:
        print(f"error: {error}", file=sys.stderr)
        return 2
    print(json.dumps({"canonical_manifest": str(args.output), "sha256": digest, "cases": len(manifest.cases),
                      "pending_reviews": sum(case.review.status == "pending" for case in manifest.cases)}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
