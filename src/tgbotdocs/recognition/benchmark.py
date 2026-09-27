"""Sealed T01c benchmark preparation: plan, human-capture ingest and sealing.

Nothing here runs a model, contacts Telegram or reviews a case. `ingest` only records
files a human captured; `seal` only binds a corpus that humans already verified to a
frozen configuration. Errors carry fixed codes and content-free details (case IDs,
relative inbox paths, reason codes), never document values.
"""
from __future__ import annotations

import argparse
from collections import Counter
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import sys
from typing import Callable, Literal

from PIL import Image, UnidentifiedImageError
from pydantic import Field, StrictInt, StrictStr, ValidationError, model_validator

from .contracts import ContractModel, ExtractionProfile
from .corpus import (CATEGORIES, SCRIPTS, Artifact, Category, CorpusCase, CorpusError, CorpusManifest,
                     ExpectedOutcome, Origin, Quality, Script, declared_denominators, load_corpus,
                     validate_split_separation)

Condition = Literal["rotation", "perspective", "dim_lighting", "glare", "blur", "partial_crop"]
CONDITIONS = ("rotation", "perspective", "dim_lighting", "glare", "blur", "partial_crop")
NEGATIVE_SCENARIOS = frozenset({
    "not_document", "mixed_image_set", "mixed_pdf", "blank", "illegible", "equal_profiles",
    "conflicting_card_sides", "instruction_in_document", "protected_pdf", "no_suitable_profile"})
# Page layouts and table styles the tuning generator never produced.
NEW_LAYOUTS = frozenset({"two_column", "boxed_form", "inline", "boxed_table", "record_blocks"})
# Telegram stores a compressed photo at most this long on its longer side.
TELEGRAM_LONG_SIDE = {"standard": 1280, "hd": 2560}
# A camera original sent as a file is larger than any Telegram-compressed photo.
CAMERA_MIN_LONG_SIDE = TELEGRAM_LONG_SIDE["hd"] + 1
# A camera original travels as a file; the standard Bot API downloads files up to 20 MB
# (ADR-0002, OPERATIONS), so a larger original could never reach recognition.
BOT_API_FILE_LIMIT_BYTES = 20 * 1024 * 1024
PLACEHOLDER_SHA256 = "0" * 64
IGNORED_INBOX_NAMES = frozenset({"Thumbs.db", "desktop.ini", ".DS_Store"})
EXIF_GPS_TAG = 0x8825
SEALING_REASON = "benchmark_not_sealed_and_frozen"


class BenchmarkError(ValueError):
    """Fixed code plus content-free details (case IDs, relative paths, reason codes)."""

    def __init__(self, code: str, details: tuple[str, ...] | list[str] = ()):
        super().__init__(code)
        self.code = code
        self.details = tuple(details)


def canonical_json_bytes(value: object) -> bytes:
    """Sorted keys, compact separators, UTF-8: the byte form every hash here is taken over."""
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"),
                      allow_nan=False).encode("utf-8")


def file_sha256(path: Path) -> str:
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


class PendingInput(ContractModel):
    """The single input file a human still has to capture or receive for a case."""
    artifact_id: StrictStr = Field(min_length=1)
    source: Literal["camera", "telegram"]
    telegram_quality: Literal["standard", "hd"] | None = None
    condition: Condition | None = None
    instruction: StrictStr = Field(min_length=1)

    @model_validator(mode="after")
    def delivery(self):
        if (self.source == "telegram") != (self.telegram_quality is not None):
            raise ValueError("telegram_quality_required_exactly_for_telegram")
        return self

    def inbox_name(self, case_id: str) -> str:
        return f"{self.source}/{case_id}.jpg"


class PlannedCase(ContractModel):
    """Canonical case fields known before capture, plus composition metadata."""
    case_id: StrictStr = Field(pattern=r"^[a-z0-9]+(?:-[a-z0-9]+)*$")
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
    profiles: tuple[ExtractionProfile, ...]
    expected: ExpectedOutcome
    pending: PendingInput | None = None
    layout: StrictStr = Field(min_length=1)
    table_style: StrictStr | None = None
    printable_page: StrictInt | None = Field(default=None, ge=1)

    @model_validator(mode="after")
    def capture_plan(self):
        for artifact in self.artifacts:
            if artifact.kind == "photo" or artifact.delivery_simulated or artifact.physical_capture \
                    or artifact.telegram_delivery_verified:
                raise ValueError("generated_artifact_cannot_claim_capture_or_delivery")
        pending = self.pending
        if self.quality == "difficult":
            if pending is None or pending.condition is None or self.printable_page is None:
                raise ValueError("difficult_case_requires_physical_capture_plan")
        elif self.quality == "readable" and self.delivery_path == "photo":
            if pending is None or pending.source != "telegram" or pending.condition is not None:
                raise ValueError("readable_photo_requires_telegram_delivery_plan")
        elif pending is not None:
            raise ValueError("unexpected_pending_input")
        if pending is not None:
            if pending.source == "camera" and self.quality != "difficult":
                raise ValueError("camera_capture_only_for_difficult_cases")
            wanted = "photo" if pending.source == "telegram" else "image_file"
            if self.delivery_path != wanted or self.input_artifact_ids != (pending.artifact_id,):
                raise ValueError("pending_input_must_be_the_only_input")
        if self.quality != "difficult" and self.printable_page is not None:
            raise ValueError("only_difficult_cases_are_printed")
        # The placeholder capture proves ingest can only fail on the captured file itself.
        self.corpus_case(PLACEHOLDER_SHA256, "inbox")
        return self

    def corpus_case(self, capture_sha256: str | None = None, inbox: str = "inbox") -> CorpusCase:
        artifacts = self.artifacts
        if self.pending is not None:
            if capture_sha256 is None:
                raise ValueError("capture_required")
            artifacts += (Artifact(
                id=self.pending.artifact_id, path=f"{inbox}/{self.pending.inbox_name(self.case_id)}",
                sha256=capture_sha256, kind="photo" if self.pending.source == "telegram" else "image_file",
                physical_capture=self.quality == "difficult",
                telegram_delivery_verified=self.pending.source == "telegram"),)
        return CorpusCase(case_id=self.case_id, origin=self.origin, script=self.script, language=self.language,
                          category=self.category, quality=self.quality, scenario=self.scenario,
                          delivery_path=self.delivery_path, artifacts=artifacts,
                          input_artifact_ids=self.input_artifact_ids, page_ids=self.page_ids,
                          profiles=self.profiles, expected=self.expected)


class BenchmarkPlan(ContractModel):
    schema_version: Literal[1]
    split: Literal["benchmark"] = "benchmark"
    corpus_schema_version: Literal[1] = 1
    cases: tuple[PlannedCase, ...] = Field(min_length=1)
    shared_artifacts: tuple[Artifact, ...] = ()
    reproducibility: dict[StrictStr, StrictStr] = Field(default_factory=dict)

    @model_validator(mode="after")
    def plan_integrity(self):
        for label, values in (("case", [case.case_id for case in self.cases]),
                              ("family", [case.origin.family_id for case in self.cases]),
                              ("path", [a.path for a in self.shared_artifacts]
                               + [a.path for case in self.cases for a in case.artifacts])):
            if len(values) != len(set(values)):
                raise ValueError(f"duplicate_{label}_in_plan")
        if any(path.split("/", 1)[0] == "inbox" for case in self.cases for path in
               (artifact.path for artifact in case.artifacts)):
            raise ValueError("generated_artifact_inside_inbox")
        return self


def composition_problems(plan: BenchmarkPlan) -> tuple[str, ...]:
    """Content-free reasons the plan misses the accepted T01c composition (empty when met)."""
    problems = set()
    cases = plan.cases
    by_quality = {quality: [case for case in cases if case.quality == quality]
                  for quality in ("readable", "difficult", "negative")}
    readable, difficult, negative = by_quality["readable"], by_quality["difficult"], by_quality["negative"]
    if [len(by_quality[q]) for q in ("readable", "difficult", "negative")] != [40, 20, 10] \
            or len(cases) != 70:
        problems.add("quality_composition")
    scripts = Counter(case.script for case in readable)
    if any(scripts[script] < 6 for script in SCRIPTS):
        problems.add("readable_script_coverage")
    categories = Counter(case.category for case in readable)
    if any(categories[category] < 4 for category in CATEGORIES):
        problems.add("readable_category_coverage")
    paths = Counter(case.delivery_path for case in readable)
    if (paths["image_file"], paths["pdf"], paths["photo"]) != (24, 8, 8):
        problems.add("readable_delivery_split")
    lists_across = sum(case.delivery_path == "pdf" and _list_crosses_pages(case) for case in readable)
    if lists_across < 3:
        problems.add("readable_multipage_list_across_boundary")
    if not any(case.delivery_path == "pdf" and _record_split(case) for case in readable):
        problems.add("readable_record_split_across_boundary")
    telegram = Counter(case.pending.telegram_quality for case in readable if case.pending is not None)
    if (telegram["standard"], telegram["hd"]) != (4, 4):
        problems.add("readable_telegram_quality_split")
    two_sided = sum(case.delivery_path == "image_file" and len(case.input_artifact_ids) == 2
                    and case.scenario == "two_sided_card" for case in readable)
    if two_sided < 2:
        problems.add("readable_two_sided_cards")
    new_layouts = {value for case in readable for value in (case.layout, case.table_style)} & NEW_LAYOUTS
    if len(new_layouts) < 2 or len({case.layout for case in readable}) < 4:
        problems.add("readable_layout_variety")
    conditions = Counter(case.pending.condition for case in difficult if case.pending is not None)
    if any(conditions[condition] < 3 for condition in CONDITIONS):
        problems.add("difficult_condition_coverage")
    if sum(case.pending is not None and case.pending.source == "telegram" for case in difficult) < 10:
        problems.add("difficult_telegram_photo_count")
    if {case.script for case in difficult} != SCRIPTS:
        problems.add("difficult_script_coverage")
    if len({case.category for case in difficult}) < 6:
        problems.add("difficult_category_coverage")
    if sorted(case.printable_page for case in difficult) != list(range(1, len(difficult) + 1)):
        problems.add("printable_pages")
    if sorted(case.scenario for case in negative) != sorted(NEGATIVE_SCENARIOS):
        problems.add("negative_scenarios")
    owners = {profile.owner for case in cases for profile in case.profiles}
    if len(owners) != 1 or any(len(case.profiles) != 3 for case in cases):
        problems.add("profile_library")
    return tuple(sorted(problems))


def _list_crosses_pages(case: PlannedCase) -> bool:
    return any(len({page for row in value.rows for page in row.source_pages}) > 1
               for value in case.expected.lists)


def _record_split(case: PlannedCase) -> bool:
    return any(len(row.source_pages) > 1 for value in case.expected.lists for row in value.rows)


def load_plan(plan_path: Path) -> BenchmarkPlan:
    try:
        return BenchmarkPlan.model_validate_json(plan_path.read_bytes())
    except (OSError, ValueError, ValidationError):
        raise BenchmarkError("invalid_benchmark_plan") from None


def _write_new(path: Path, data: bytes) -> None:
    """Create `path` exclusively; never overwrite an existing manifest."""
    temporary = path.with_name(f".{path.name}.partial")
    temporary.unlink(missing_ok=True)  # only a crashed earlier write leaves this name behind
    try:
        with temporary.open("xb") as stream:
            stream.write(data)
            stream.flush()
            os.fsync(stream.fileno())
        if path.exists():
            raise BenchmarkError("output_exists")
        os.rename(temporary, path)
    except FileExistsError:
        raise BenchmarkError("output_exists") from None
    finally:
        temporary.unlink(missing_ok=True)


def _output_path(output: Path, root: Path) -> Path:
    output = output.resolve()
    if output.parent != root:
        raise BenchmarkError("manifest_must_be_written_next_to_its_artifacts")
    if output.exists():
        raise BenchmarkError("output_exists")
    return output


def _registry(paths: tuple[Path, ...]) -> tuple[CorpusManifest, ...]:
    # Declared hashes suffice for separation; the registry files may live elsewhere.
    try:
        return tuple(load_corpus(path, verify_files=False).manifest for path in paths)
    except CorpusError as error:
        raise BenchmarkError("invalid_registry_manifest", (str(error),)) from None


def _check_separation(registry: tuple[CorpusManifest, ...], manifest: CorpusManifest) -> None:
    try:
        validate_split_separation(*registry, manifest)
    except CorpusError as error:
        raise BenchmarkError(str(error)) from None


def _inspect_capture(path: Path, pending: PendingInput, quality: str) -> tuple[str, ...]:
    """Reason codes only; the image content is never reported."""
    try:
        with Image.open(path) as image:
            if image.format != "JPEG":
                return ("not_jpeg",)
            width, height = image.size
            if width * height > Image.MAX_IMAGE_PIXELS:
                return ("pixel_limit",)
            image.load()
            exif = image.getexif()
    except (OSError, UnidentifiedImageError, ValueError, Image.DecompressionBombError):
        return ("undecodable_image",)
    problems = []
    if EXIF_GPS_TAG in exif:
        problems.append("location_metadata_present")
    longer = max(width, height)
    if pending.source == "telegram":
        limit = TELEGRAM_LONG_SIDE[pending.telegram_quality]
        if longer > limit or pending.telegram_quality == "hd" and longer <= TELEGRAM_LONG_SIDE["standard"]:
            problems.append(f"telegram_{pending.telegram_quality}_size_mismatch")
    else:
        if longer < CAMERA_MIN_LONG_SIDE:
            problems.append("camera_original_too_small")
        if path.stat().st_size > BOT_API_FILE_LIMIT_BYTES:
            problems.append("exceeds_bot_api_file_limit")
    return tuple(problems)


def ingest(plan_path: Path, inbox_dir: Path, output_manifest_path: Path, *,
           registry: tuple[Path, ...] = ()) -> CorpusManifest:
    """Hash human-provided captures and write an unreviewed, unsealed benchmark manifest.

    Refuses when the plan misses the accepted composition, a generated file changed, the
    inbox lacks an expected capture or holds anything else, or a capture is not a
    decodable JPEG of the planned kind. Review stays pending for every case.
    """
    plan_path = plan_path.resolve()
    plan = load_plan(plan_path)
    problems = composition_problems(plan)
    if problems:
        raise BenchmarkError("benchmark_plan_composition_incomplete", problems)
    root = plan_path.parent
    output = _output_path(output_manifest_path, root)
    inbox = inbox_dir.resolve()
    if not inbox.is_relative_to(root) or inbox == root or not inbox.is_dir():
        raise BenchmarkError("inbox_must_be_a_directory_inside_the_plan_directory")
    inbox_relative = inbox.relative_to(root).as_posix()
    registry_manifests = _registry(registry)

    mismatched = []
    generated = [*plan.shared_artifacts, *(artifact for case in plan.cases for artifact in case.artifacts)]
    for artifact in generated:
        path = root / PurePosixPath(artifact.path)
        try:
            if file_sha256(path) != artifact.sha256:
                mismatched.append(f"hash_mismatch:{artifact.path}")
        except OSError:
            mismatched.append(f"missing:{artifact.path}")
    if mismatched:
        raise BenchmarkError("plan_artifact_mismatch", mismatched)

    expected = {case.pending.inbox_name(case.case_id): case for case in plan.cases if case.pending is not None}
    present = {path.relative_to(inbox).as_posix() for path in inbox.rglob("*")
               if path.is_file() and path.name not in IGNORED_INBOX_NAMES}
    differences = [f"missing:{name}" for name in sorted(set(expected) - present)]
    differences += [f"unexpected:{name}" for name in sorted(present - set(expected))]
    if differences:
        raise BenchmarkError("capture_inbox_mismatch", differences)

    invalid, hashes = [], {}
    known = {artifact.sha256 for artifact in generated}
    for name, case in sorted(expected.items()):
        path = inbox / PurePosixPath(name)
        invalid += [f"{name}:{code}" for code in _inspect_capture(path, case.pending, case.quality)]
        digest = file_sha256(path)
        if digest in known or digest in hashes.values():
            invalid.append(f"{name}:duplicate_of_another_file")
        hashes[case.case_id] = digest
    if invalid:
        raise BenchmarkError("capture_invalid", invalid)

    cases = tuple(case.corpus_case(hashes.get(case.case_id), inbox_relative) for case in plan.cases)
    try:
        manifest = CorpusManifest(schema_version=1, split="benchmark", purpose="review_preparation", cases=cases,
                                  denominators=declared_denominators(cases), sealed=False)
    except ValidationError:
        raise BenchmarkError("invalid_benchmark_manifest") from None
    _check_separation(registry_manifests, manifest)
    _write_new(output, canonical_json_bytes(manifest.model_dump(mode="json")))
    try:
        return load_corpus(output).manifest
    except CorpusError as error:
        raise BenchmarkError(str(error)) from None


# Required top-level fields of the runner's frozen configuration (design brief section 3).
# Interim shape guard only: it tolerates fields the runner may add, and the integrated seal
# should delegate to the runner's configuration loader, which validates the full schema.
FROZEN_CONFIGURATION_FIELDS = frozenset({
    "schema_version", "created_at", "runtime_artifacts", "runtime_profile", "core", "prompt", "policy",
    "corpus_manifest_schema_version", "calibration", "code_sha256"})


def frozen_configuration_sha256(path: Path) -> str:
    """SHA-256 over a frozen configuration file stored in its canonical JSON form.

    The file must already be canonical (sorted keys, compact separators, UTF-8, no
    duplicate keys, no trailing bytes), so the hash is the hash of the file itself and a
    hand-edited or re-serialized copy is refused rather than silently normalized. It must
    carry the required top-level fields of a frozen configuration, which refuses plans,
    calibration reports and manifests passed by mistake.
    """
    try:
        raw = path.read_bytes()
        value = json.loads(raw.decode("utf-8"), parse_constant=_reject_constant, object_pairs_hook=_unique_keys)
    except _DuplicateKey:
        raise BenchmarkError("invalid_frozen_configuration", ("duplicate_key",)) from None
    except (OSError, UnicodeDecodeError, ValueError):
        raise BenchmarkError("invalid_frozen_configuration") from None
    if not isinstance(value, dict) or not value:
        raise BenchmarkError("invalid_frozen_configuration")
    versions = (value.get("schema_version"), value.get("corpus_manifest_schema_version"))
    if not FROZEN_CONFIGURATION_FIELDS <= set(value) or any(type(v) is not int or v != 1 for v in versions):
        raise BenchmarkError("invalid_frozen_configuration", ("not_a_frozen_configuration",))
    canonical = canonical_json_bytes(value)
    if raw != canonical:
        raise BenchmarkError("invalid_frozen_configuration", ("not_canonical",))
    return hashlib.sha256(canonical).hexdigest()


class _DuplicateKey(ValueError):
    pass


def _unique_keys(pairs: list[tuple[str, object]]) -> dict[str, object]:
    value = dict(pairs)
    if len(value) != len(pairs):
        raise _DuplicateKey("duplicate_key")
    return value


def _reject_constant(_: str) -> None:
    raise ValueError("non_finite_number")


def seal(reviewed_manifest: Path, frozen_config_path: Path, output: Path, *,
         registry: tuple[Path, ...] = ()) -> CorpusManifest:
    """Bind a human-verified benchmark to one frozen configuration; never reviews anything."""
    reviewed_manifest = reviewed_manifest.resolve()
    try:
        corpus = load_corpus(reviewed_manifest)
    except CorpusError as error:
        raise BenchmarkError(str(error)) from None
    manifest = corpus.manifest
    if manifest.split != "benchmark":
        raise BenchmarkError("wrong_split")
    if manifest.sealed or manifest.frozen_configuration_sha256 is not None:
        raise BenchmarkError("benchmark_already_sealed")
    reasons = sorted(set(manifest.eligibility_reasons("benchmark")) - {SEALING_REASON})
    if reasons:
        raise BenchmarkError("benchmark_not_ready_for_sealing", reasons)
    digest = frozen_configuration_sha256(frozen_config_path)
    target = _output_path(output, corpus.root)
    _check_separation(_registry(registry), manifest)
    data = manifest.model_dump(mode="json")
    data.update(sealed=True, frozen_configuration_sha256=digest)
    sealed = CorpusManifest.model_validate_json(canonical_json_bytes(data))
    if sealed.eligibility_reasons("benchmark"):
        raise BenchmarkError("benchmark_not_ready_for_sealing", sealed.eligibility_reasons("benchmark"))
    _write_new(target, canonical_json_bytes(data))
    try:
        return load_corpus(target).manifest
    except CorpusError as error:
        raise BenchmarkError(str(error)) from None


def _summary(manifest: CorpusManifest, path: Path) -> str:
    counts = Counter(case.quality for case in manifest.cases)
    return (f"cases={len(manifest.cases)} readable={counts['readable']} difficult={counts['difficult']} "
            f"negative={counts['negative']} sealed={str(manifest.sealed).lower()} "
            f"review_pending={sum(case.review.status != 'verified' for case in manifest.cases)} "
            f"sha256={file_sha256(path)}")


def main(argv: list[str] | None = None, *, stdout: Callable[[str], None] = print) -> int:
    parser = argparse.ArgumentParser(prog="python -m tgbotdocs.recognition.benchmark", description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    ingest_parser = commands.add_parser("ingest", help="record human captures into an unreviewed manifest")
    ingest_parser.add_argument("--plan", required=True, type=Path)
    ingest_parser.add_argument("--inbox", type=Path, help="default: the plan directory's inbox/")
    ingest_parser.add_argument("--output", required=True, type=Path)
    ingest_parser.add_argument("--registry", action="append", type=Path, default=[],
                               help="historical development/tuning manifest to check separation against")
    seal_parser = commands.add_parser("seal", help="seal a human-verified benchmark to a frozen configuration")
    seal_parser.add_argument("--manifest", required=True, type=Path)
    seal_parser.add_argument("--config", required=True, type=Path)
    seal_parser.add_argument("--output", required=True, type=Path)
    seal_parser.add_argument("--registry", action="append", type=Path, default=[])
    args = parser.parse_args(argv)
    try:
        if args.command == "ingest":
            inbox = args.inbox if args.inbox is not None else args.plan.resolve().parent / "inbox"
            manifest = ingest(args.plan, inbox, args.output, registry=tuple(args.registry))
        else:
            manifest = seal(args.manifest, args.config, args.output, registry=tuple(args.registry))
    except BenchmarkError as error:
        print(f"error: {error.code}", file=sys.stderr)
        for detail in error.details:
            print(f"  {detail}", file=sys.stderr)
        return 2
    stdout(_summary(manifest, args.output.resolve()))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
