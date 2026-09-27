"""Benchmark preparation: plan composition, capture ingest and sealing.

Captures below are tiny generated JPEGs and review attestations are synthetic test data
only; no model, Telegram or camera is involved.
"""
from datetime import datetime, timezone
import hashlib
import importlib.util
import io
import json
from pathlib import Path
import shutil

import pytest
from PIL import ExifTags, Image, features
from pydantic import ValidationError

from tgbotdocs.recognition import benchmark
from tgbotdocs.recognition.benchmark import (BenchmarkError, canonical_json_bytes, composition_problems,
                                             frozen_configuration_sha256, ingest, seal)
from tgbotdocs.recognition.corpus import (CorpusCase, CorpusManifest, HumanReview, case_review_digest,
                                          declared_denominators, load_corpus)

TOOLS = Path(__file__).resolve().parents[2] / "tools" / "t01"
FONTS = Path("C:/Windows/Fonts")
CAPTURE_SIZE = {"standard": (1280, 960), "hd": (2560, 1920), "camera": (2600, 1950)}


@pytest.fixture(scope="module")
def generator():
    spec = importlib.util.spec_from_file_location("create_benchmark_set", TOOLS / "create_benchmark_set.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture(scope="module")
def spec():
    return json.loads((TOOLS / "benchmark-cases.json").read_text(encoding="utf-8"))


def fake_digest(path: str) -> str:
    return hashlib.sha256(path.encode()).hexdigest()


def jpeg(size, color, **save) -> bytes:
    stream = io.BytesIO()
    Image.new("RGB", size, color).save(stream, "JPEG", quality=80, **save)
    return stream.getvalue()


@pytest.fixture(scope="module")
def template(tmp_path_factory, generator, spec):
    """A plan directory with placeholder generated files and one valid capture per pending input."""
    root = tmp_path_factory.mktemp("benchmark-template")
    paths = ["printable-originals.pdf"] + [path for case in spec["cases"]
                                           for _, path, _ in generator.artifact_specs(case)]
    for path in paths:
        (root / path).parent.mkdir(parents=True, exist_ok=True)
        (root / path).write_bytes(f"synthetic placeholder {path}".encode())
    plan = generator.build_plan(spec, lambda path: benchmark.file_sha256(root / path), {"fixture": "tests"})
    (root / "plan.json").write_bytes(canonical_json_bytes(plan.model_dump(mode="json")))
    for number, case in enumerate(case for case in plan.cases if case.pending is not None):
        pending = case.pending
        target = root / "inbox" / pending.inbox_name(case.case_id)
        target.parent.mkdir(parents=True, exist_ok=True)
        size = CAPTURE_SIZE[pending.telegram_quality or "camera"]
        target.write_bytes(jpeg(size, (number * 9 % 256, 90, 200 - number)))
    return root


@pytest.fixture
def plan_dir(template, tmp_path):
    target = tmp_path / "benchmark"
    shutil.copytree(template, target)
    return target


def run_ingest(plan_dir, **kwargs):
    return ingest(plan_dir / "plan.json", plan_dir / "inbox", plan_dir / "benchmark-manifest.json", **kwargs)


def human_verified(manifest: CorpusManifest) -> CorpusManifest:
    """Synthetic test attestation standing in for a real human review record."""
    cases = []
    for case in manifest.cases:
        data = case.model_dump()
        data["review"] = HumanReview(status="verified", reviewer="Synthetic test reviewer",
                                     method="glyph_sequence_comparison",
                                     reviewed_at=datetime(2026, 9, 27, tzinfo=timezone.utc),
                                     subject_sha256=case_review_digest(case), reviewer_kind="human")
        cases.append(CorpusCase.model_validate(data))
    return CorpusManifest(schema_version=1, split="benchmark", purpose="quality_measurement", cases=tuple(cases),
                          denominators=declared_denominators(tuple(cases)))


def write_reviewed(plan_dir) -> Path:
    manifest = human_verified(run_ingest(plan_dir))
    path = plan_dir / "reviewed-manifest.json"
    path.write_bytes(canonical_json_bytes(manifest.model_dump(mode="json")))
    return path


def frozen_value() -> dict:
    """Synthetic stand-in shaped like the runner's FrozenConfiguration (top-level fields only matter here)."""
    return {"schema_version": 1, "created_at": "2026-09-27T12:00:00Z", "runtime_artifacts": {"build": "synthetic"},
            "runtime_profile": {"context": 4096}, "core": {"long_side": 1600}, "prompt": {"version": "t"},
            "policy": {"v1_threshold": 0.9, "v2": False, "v3": True}, "corpus_manifest_schema_version": 1,
            "calibration": {"selected_point": 0}, "code_sha256": "a" * 64, "page_times": []}


def write_config(path: Path, value=None) -> Path:
    """Write a configuration the way the runner's canonical writer does."""
    path.write_bytes(canonical_json_bytes(frozen_value() if value is None else value))
    return path


def error_of(call) -> BenchmarkError:
    with pytest.raises(BenchmarkError) as caught:
        call()
    return caught.value


# ---------------------------------------------------------------- plan and specification

def test_benchmark_specification_meets_accepted_composition(generator, spec):
    plan = generator.build_plan(spec, fake_digest, {})
    assert composition_problems(plan) == ()
    assert {profile.owner for case in plan.cases for profile in case.profiles} == {"benchmark-synthetic-user"}
    matched = [case for case in plan.cases if case.expected.profile_id]
    # The correct profile is not always offered first, so position cannot give it away.
    assert 0 < sum(case.profiles[0].id == case.expected.profile_id for case in matched) < len(matched)
    split = next(case for case in plan.cases if case.scenario == "multipage_pdf_record_split_across_boundary")
    assert any(len(row.source_pages) == 2 for value in split.expected.lists for row in value.rows)
    conflict = next(case for case in plan.cases if case.scenario == "conflicting_card_sides")
    card = next(value for value in conflict.expected.fields if value.field_id == "card_number")
    assert (card.status, card.value, conflict.expected.outcome) == ("ambiguous", None, "partial")


def test_benchmark_sources_are_independent_of_development_and_tuning(generator, spec):
    earlier = generator.earlier_specs()
    generator.check_independence(spec, earlier)
    reused_field = json.loads(json.dumps(spec))
    reused_field["profiles"]["invoice"]["fields"][0]["id"] = "reference"
    with pytest.raises(ValueError, match="field IDs"):
        generator.check_independence(reused_field, earlier)
    tuning_value = next(field["value"] for field in earlier[1]["cases"][0]["pages"][0]["fields"])
    reused_value = json.loads(json.dumps(spec))
    reused_value["cases"][0]["pages"][0]["fields"]["holder"] = tuning_value
    with pytest.raises(ValueError, match="bench-r01"):
        generator.check_independence(reused_value, earlier)


def test_composition_problems_name_each_missing_requirement(generator, spec):
    plan = generator.build_plan(spec, fake_digest, {})
    without_case = plan.model_copy(update={"cases": plan.cases[1:]})
    assert {"quality_composition", "readable_two_sided_cards"} <= set(composition_problems(without_case))
    standard_only = tuple(case.model_copy(update={"pending": case.pending.model_copy(update={"telegram_quality": "standard"})})
                          if case.quality == "readable" and case.pending else case for case in plan.cases)
    assert composition_problems(plan.model_copy(update={"cases": standard_only})) == ("readable_telegram_quality_split",)
    no_negatives = tuple(case for case in plan.cases if case.scenario != "protected_pdf")
    assert "negative_scenarios" in composition_problems(plan.model_copy(update={"cases": no_negatives}))


def test_planned_case_refuses_inconsistent_capture_plans(generator, spec):
    plan = generator.build_plan(spec, fake_digest, {})
    difficult = next(case for case in plan.cases if case.quality == "difficult").model_dump()
    readable = next(case for case in plan.cases if case.delivery_path == "image_file"
                    and case.quality == "readable").model_dump()
    with pytest.raises(ValidationError, match="difficult_case_requires_physical_capture_plan"):
        benchmark.PlannedCase.model_validate({**difficult, "pending": None})
    with pytest.raises(ValidationError, match="unexpected_pending_input"):
        benchmark.PlannedCase.model_validate({**readable, "pending": difficult["pending"]})
    photo = readable["artifacts"][0] | {"kind": "photo"}
    with pytest.raises(ValidationError, match="generated_artifact_cannot_claim_capture"):
        benchmark.PlannedCase.model_validate({**readable, "artifacts": (photo, *readable["artifacts"][1:])})
    with pytest.raises(ValidationError, match="telegram_quality_required"):
        benchmark.PendingInput(artifact_id="x", source="telegram", instruction="send")


# ---------------------------------------------------------------- ingest

def test_ingest_records_captures_but_never_reviews_or_seals(plan_dir):
    manifest = run_ingest(plan_dir)
    assert (manifest.split, manifest.purpose, manifest.sealed, manifest.frozen_configuration_sha256) == \
        ("benchmark", "review_preparation", False, None)
    assert len(manifest.cases) == 70 and all(case.review.status == "pending" for case in manifest.cases)
    captured = {case.case_id: next(a for a in case.artifacts if a.id in case.input_artifact_ids)
                for case in manifest.cases if case.quality == "difficult" or case.delivery_path == "photo"}
    assert len(captured) == 28
    for case in manifest.cases:
        if case.case_id not in captured:
            continue
        artifact = captured[case.case_id]
        telegram = artifact.path.startswith("inbox/telegram/")
        assert artifact.kind == ("photo" if telegram else "image_file")
        assert artifact.telegram_delivery_verified is telegram and not artifact.delivery_simulated
        assert artifact.physical_capture is (case.quality == "difficult")
    # Only human review and sealing remain; delivery and physical-capture coverage are complete.
    assert set(manifest.eligibility_reasons("benchmark")) == {
        "review_preparation_only", "human_review_or_ground_truth_pending", "benchmark_not_sealed_and_frozen"}
    written = (plan_dir / "benchmark-manifest.json").read_bytes()
    assert written == canonical_json_bytes(json.loads(written))
    assert load_corpus(plan_dir / "benchmark-manifest.json").files_verified


def test_ingest_refuses_missing_and_unexpected_captures(plan_dir):
    (plan_dir / "inbox" / "camera" / "bench-d01.jpg").rename(plan_dir / "inbox" / "telegram" / "bench-d01.jpg")
    (plan_dir / "inbox" / "camera" / "IMG_2044.jpg").write_bytes(b"extra")
    (plan_dir / "inbox" / "camera" / "Thumbs.db").write_bytes(b"operating system cache")
    error = error_of(lambda: run_ingest(plan_dir))
    assert error.code == "capture_inbox_mismatch"
    assert error.details == ("missing:camera/bench-d01.jpg", "unexpected:camera/IMG_2044.jpg",
                             "unexpected:telegram/bench-d01.jpg")
    assert not (plan_dir / "benchmark-manifest.json").exists()


def gps_jpeg(size) -> bytes:
    exif = Image.Exif()
    exif[ExifTags.IFD.GPSInfo] = {ExifTags.GPS.GPSLatitudeRef: "N"}
    return jpeg(size, "white", exif=exif)


def oversized_camera_jpeg(total: int) -> bytes:
    """A decodable camera-sized JPEG padded after its end marker to exactly `total` bytes."""
    content = jpeg(CAPTURE_SIZE["camera"], "white")
    return content + b"\0" * (total - len(content))


def png_bytes(size) -> bytes:
    stream = io.BytesIO()
    Image.new("RGB", size, "white").save(stream, "PNG")
    return stream.getvalue()


@pytest.mark.parametrize(("name", "content", "code"), [
    ("camera/bench-d01.jpg", lambda: png_bytes((2600, 100)), "not_jpeg"),
    ("camera/bench-d01.jpg", lambda: b"\xff\xd8 truncated", "undecodable_image"),
    ("camera/bench-d01.jpg", lambda: jpeg((1280, 960), "white"), "camera_original_too_small"),
    ("camera/bench-d01.jpg", lambda: gps_jpeg((2600, 100)), "location_metadata_present"),
    ("camera/bench-d01.jpg", lambda: oversized_camera_jpeg(benchmark.BOT_API_FILE_LIMIT_BYTES + 1),
     "exceeds_bot_api_file_limit"),
    ("telegram/bench-d02.jpg", lambda: jpeg((2000, 1500), "white"), "telegram_standard_size_mismatch"),
    ("telegram/bench-d04.jpg", lambda: jpeg((1280, 960), "white"), "telegram_hd_size_mismatch"),
])
def test_ingest_refuses_captures_that_do_not_match_their_delivery_path(plan_dir, name, content, code):
    (plan_dir / "inbox" / name).write_bytes(content())
    error = error_of(lambda: run_ingest(plan_dir))
    assert (error.code, error.details) == ("capture_invalid", (f"{name}:{code}",))


def test_ingest_accepts_a_camera_original_at_the_bot_api_file_limit(plan_dir):
    assert benchmark.BOT_API_FILE_LIMIT_BYTES == 20 * 1024 * 1024
    (plan_dir / "inbox" / "camera" / "bench-d01.jpg").write_bytes(oversized_camera_jpeg(benchmark.BOT_API_FILE_LIMIT_BYTES))
    assert run_ingest(plan_dir).split == "benchmark"


def test_ingest_refuses_a_capture_duplicating_another_file(plan_dir):
    shutil.copyfile(plan_dir / "inbox" / "camera" / "bench-d01.jpg", plan_dir / "inbox" / "camera" / "bench-d03.jpg")
    error = error_of(lambda: run_ingest(plan_dir))
    assert "camera/bench-d03.jpg:duplicate_of_another_file" in error.details


def test_ingest_refuses_changed_generated_files_and_incomplete_plans(plan_dir):
    (plan_dir / "bench-r01" / "bench-r01-p01.png").write_bytes(b"changed")
    error = error_of(lambda: run_ingest(plan_dir))
    assert (error.code, error.details) == ("plan_artifact_mismatch", ("hash_mismatch:bench-r01/bench-r01-p01.png",))
    plan = json.loads((plan_dir / "plan.json").read_bytes())
    plan["cases"] = [case for case in plan["cases"] if case["case_id"] != "bench-n04"]
    (plan_dir / "plan.json").write_bytes(canonical_json_bytes(plan))
    error = error_of(lambda: run_ingest(plan_dir))
    assert error.code == "benchmark_plan_composition_incomplete"
    assert {"quality_composition", "negative_scenarios"} <= set(error.details)
    (plan_dir / "plan.json").write_text("{}", encoding="utf-8")
    assert error_of(lambda: run_ingest(plan_dir)).code == "invalid_benchmark_plan"


def test_ingest_output_and_inbox_locations_are_fixed(plan_dir, tmp_path):
    outside = tmp_path / "elsewhere.json"
    assert error_of(lambda: ingest(plan_dir / "plan.json", plan_dir / "inbox", outside)).code \
        == "manifest_must_be_written_next_to_its_artifacts"
    assert error_of(lambda: ingest(plan_dir / "plan.json", tmp_path, plan_dir / "m.json")).code \
        == "inbox_must_be_a_directory_inside_the_plan_directory"
    run_ingest(plan_dir)
    assert error_of(lambda: run_ingest(plan_dir)).code == "output_exists"


def test_ingest_checks_separation_from_a_declared_registry(plan_dir, tmp_path):
    manifest = run_ingest(plan_dir)
    reused = manifest.cases[0].model_copy(update={"case_id": "tune-reused"})
    registry = CorpusManifest(schema_version=1, split="tuning", purpose="review_preparation", cases=(reused,),
                              denominators=declared_denominators((reused,)))
    registry_path = tmp_path / "tuning-manifest.json"
    registry_path.write_bytes(canonical_json_bytes(registry.model_dump(mode="json")))
    (plan_dir / "benchmark-manifest.json").unlink()
    error = error_of(lambda: run_ingest(plan_dir, registry=(registry_path,)))
    assert error.code == "benchmark_split_contamination"


# ---------------------------------------------------------------- seal

def test_seal_binds_a_human_verified_benchmark_to_the_frozen_configuration(plan_dir, tmp_path):
    reviewed = write_reviewed(plan_dir)
    config = write_config(tmp_path / "frozen.json")
    sealed = seal(reviewed, config, plan_dir / "sealed-manifest.json")
    assert sealed.sealed and sealed.frozen_configuration_sha256 == hashlib.sha256(config.read_bytes()).hexdigest()
    assert sealed.frozen_configuration_sha256 == frozen_configuration_sha256(config)
    assert sealed.eligibility_reasons("benchmark") == ()
    loaded = load_corpus(plan_dir / "sealed-manifest.json")
    loaded.manifest.require_eligible("benchmark")
    assert error_of(lambda: seal(plan_dir / "sealed-manifest.json", config, plan_dir / "again.json")).code \
        == "benchmark_already_sealed"


def test_seal_refuses_unreviewed_or_changed_benchmarks(plan_dir, tmp_path):
    config = write_config(tmp_path / "frozen.json")
    run_ingest(plan_dir)
    error = error_of(lambda: seal(plan_dir / "benchmark-manifest.json", config, plan_dir / "sealed.json"))
    assert error.code == "benchmark_not_ready_for_sealing"
    assert set(error.details) == {"human_review_or_ground_truth_pending", "review_preparation_only"}
    (plan_dir / "benchmark-manifest.json").unlink()
    reviewed = write_reviewed(plan_dir)
    (plan_dir / "inbox" / "camera" / "bench-d01.jpg").write_bytes(jpeg((2600, 1950), "black"))
    assert error_of(lambda: seal(reviewed, config, plan_dir / "sealed.json")).code == "artifact_hash_mismatch"
    assert not (plan_dir / "sealed.json").exists()


@pytest.mark.parametrize("content", ["[1, 2]", "{}", '{"threshold": NaN}', "not json"])
def test_frozen_configuration_hash_refuses_invalid_files(tmp_path, content):
    config = tmp_path / "frozen.json"
    config.write_text(content, encoding="utf-8")
    assert error_of(lambda: frozen_configuration_sha256(config)).code == "invalid_frozen_configuration"
    assert error_of(lambda: frozen_configuration_sha256(tmp_path / "absent.json")).code == "invalid_frozen_configuration"


def other_json(name: str) -> bytes:
    value = frozen_value()
    if name == "plan_or_report":
        return canonical_json_bytes({"cases": [1]})
    if name == "missing_field":
        del value["calibration"]
    elif name == "schema_version_true":
        value["schema_version"] = True
    elif name == "manifest_schema_2":
        value["corpus_manifest_schema_version"] = 2
    return canonical_json_bytes(value)


@pytest.mark.parametrize("name", ["plan_or_report", "missing_field", "schema_version_true",
                                  "manifest_schema_2"])
def test_frozen_configuration_hash_refuses_files_that_are_not_a_frozen_configuration(tmp_path, name):
    config = tmp_path / "frozen.json"
    config.write_bytes(other_json(name))
    error = error_of(lambda: frozen_configuration_sha256(config))
    assert (error.code, error.details) == ("invalid_frozen_configuration", ("not_a_frozen_configuration",))


def test_frozen_configuration_hash_refuses_duplicate_keys_and_non_canonical_bytes(tmp_path):
    canonical = canonical_json_bytes(frozen_value())
    duplicate = tmp_path / "duplicate.json"
    duplicate.write_bytes(canonical.replace(b'"v1_threshold":0.9', b'"v1_threshold":0.5,"v1_threshold":0.9'))
    assert error_of(lambda: frozen_configuration_sha256(duplicate)).details == ("duplicate_key",)
    variants = {"pretty": json.dumps(frozen_value(), indent=2, sort_keys=True).encode(),
                "unsorted": json.dumps(frozen_value(), separators=(",", ":")).encode(),
                "trailing_newline": canonical + b"\n",
                "bom": b"\xef\xbb\xbf" + canonical}
    assert variants["unsorted"] != canonical
    for name, content in variants.items():
        config = tmp_path / f"{name}.json"
        config.write_bytes(content)
        assert error_of(lambda path=config: frozen_configuration_sha256(path)).code \
            == "invalid_frozen_configuration", name
    exact = write_config(tmp_path / "exact.json")
    assert frozen_configuration_sha256(exact) == hashlib.sha256(canonical).hexdigest()


def test_seal_refuses_a_file_that_is_not_the_frozen_configuration(plan_dir, tmp_path):
    reviewed = write_reviewed(plan_dir)
    error = error_of(lambda: seal(reviewed, plan_dir / "plan.json", plan_dir / "sealed.json"))
    assert (error.code, error.details) == ("invalid_frozen_configuration", ("not_a_frozen_configuration",))
    pretty = tmp_path / "frozen.json"
    pretty.write_text(json.dumps(frozen_value(), indent=2), encoding="utf-8")
    assert error_of(lambda: seal(reviewed, pretty, plan_dir / "sealed.json")).details == ("not_canonical",)
    assert not (plan_dir / "sealed.json").exists()


# ---------------------------------------------------------------- command line

def test_cli_reports_only_counts_and_hashes(plan_dir, capsys):
    lines = []
    assert benchmark.main(["ingest", "--plan", str(plan_dir / "plan.json"),
                           "--output", str(plan_dir / "benchmark-manifest.json")], stdout=lines.append) == 0
    assert lines[0].startswith("cases=70 readable=40 difficult=20 negative=10 sealed=false review_pending=70 sha256=")
    assert benchmark.main(["ingest", "--plan", str(plan_dir / "plan.json"),
                           "--output", str(plan_dir / "benchmark-manifest.json")], stdout=lines.append) == 2
    assert capsys.readouterr().err == "error: output_exists\n"


# ---------------------------------------------------------------- generator smoke test

REQUIRED_FONTS = ("arial.ttf", "tahoma.ttf", "times.ttf", "msyh.ttc", "Nirmala.ttc", "msgothic.ttc")


@pytest.mark.skipif(not features.check_feature("raqm") or not all((FONTS / name).exists() for name in REQUIRED_FONTS),
                    reason="needs Pillow RAQM and the local Windows fonts used by the benchmark specification")
def test_generator_renders_representative_cases_deterministically(generator, spec, tmp_path):
    chosen = {"bench-r03", "bench-r27", "bench-d01", "bench-n05", "bench-n09"}
    cases = [case for case in spec["cases"] if case["id"] in chosen]
    fonts = {name: FONTS / name for name in {case["font"] for case in cases} | {"arial.ttf"}}
    hashes = []
    for run in ("first", "second"):
        output = tmp_path / run
        output.mkdir()
        for case in cases:
            generator.render_files(case, spec, fonts, output)
        hashes.append({path.relative_to(output).as_posix(): benchmark.file_sha256(path)
                       for path in sorted(output.rglob("*")) if path.is_file()})
    assert hashes[0] == hashes[1]
    assert set(hashes[0]) == {path for case in cases for _, path, _ in generator.artifact_specs(case)}
    with Image.open(tmp_path / "first" / "bench-r03" / "bench-r03-p01.png") as card:
        assert card.size == generator.CARD
    pdfium = pytest.importorskip("pypdfium2")
    with pytest.raises(pdfium.PdfiumError):
        pdfium.PdfDocument(str(tmp_path / "first" / "bench-n09" / "bench-n09.pdf"))
    with pdfium.PdfDocument(str(tmp_path / "first" / "bench-r27" / "bench-r27.pdf")) as document:
        assert len(document) == 2
