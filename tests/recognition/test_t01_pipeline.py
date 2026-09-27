"""End-to-end T01 tooling chain across package seams, with a scripted core and no model or GPU.

Tuning review -> calibration -> freeze -> benchmark ingest -> benchmark review -> seal ->
benchmark run, each step through its command-line entry point, so the files one command
writes are exactly the files the next command reads.

Everything here is synthetic test data. The review decisions below are shaped exactly like
the review form's export, but they are produced by this test to exercise the tooling; they are
not a human review, and no real document, value or profile is involved. The benchmark uses
the real 70-case plan from ``tools/t01/benchmark-cases.json`` with placeholder generated files
and tiny generated JPEG captures (as in ``test_benchmark.py``), so the 40/20/10 composition
gate and every other gate run unmodified; nothing is monkeypatched except ``runner.open_core``
(a scripted core instead of the pinned runtime) and the GPU memory query.
"""
from contextlib import asynccontextmanager
import hashlib
import importlib.util
import io
import json
from pathlib import Path

from PIL import Image
import pytest

from test_runner import TRAPS, ScriptedCore, make_case as make_tuning_case
from tgbotdocs.recognition import benchmark, config, corpus_cli, runner
from tgbotdocs.recognition.benchmark import canonical_json_bytes
from tgbotdocs.recognition.corpus import CorpusManifest, declared_denominators, load_corpus
from tgbotdocs.recognition.review import manifest_bytes, reviewable_values

TOOLS = Path(__file__).resolve().parents[2] / "tools" / "t01"
CAPTURE_SIZE = {"standard": (1280, 960), "hd": (2560, 1920), "camera": (2600, 1950)}
REJECTED_TUNING_CASE = "tune-05"
SYNTHETIC_REVIEWER = "Synthetic pipeline test reviewer"


def jpeg(size, color) -> bytes:
    stream = io.BytesIO()
    Image.new("RGB", size, color).save(stream, "JPEG", quality=80)
    return stream.getvalue()


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def form_export(manifest: CorpusManifest, manifest_path: Path, *, method: str, rejected=(), not_legible=()) -> dict:
    """Synthetic decisions in the exact shape the review form exports (``review._SCRIPT``)."""
    cases = []
    for case in manifest.cases:
        if case.case_id in rejected:
            cases.append({"case_id": case.case_id, "decision": "rejected", "method": None, "values": [],
                          "notes": ""})
            continue
        values = [{"field_id": key[0], "row_key": key[1], "column_id": key[2],
                   "visibility": "not_legible" if (case.case_id, key) in not_legible else "legible"}
                  for key, _ in reviewable_values(case)]
        cases.append({"case_id": case.case_id, "decision": "verified", "method": method, "values": values,
                      "notes": ""})
    return {"schema_version": 1, "manifest_sha256": sha256(manifest_path), "reviewer": SYNTHETIC_REVIEWER,
            "reviewer_attests_human_inspection": True, "reviewed_at": "2026-09-28T10:15:00+03:00", "cases": cases}


def write_json(path: Path, value: dict) -> Path:
    # The form writes JSON.stringify(data, null, 2) plus a newline.
    path.write_text(json.dumps(value, indent=2) + "\n", encoding="utf-8")
    return path


def cli(main, argv, capsys):
    code = main([str(item) for item in argv])
    captured = capsys.readouterr()
    return code, captured.out, captured.err


@pytest.fixture
def core_state(monkeypatch):
    state = {"scenarios": {}, "cores": [], "settings": []}

    @asynccontextmanager
    async def opener(data_root, settings):
        state["settings"].append(settings)
        core = ScriptedCore(settings, state["scenarios"])
        state["cores"].append(core)
        yield core, lambda: None

    monkeypatch.setattr(runner, "open_core", opener)
    monkeypatch.setattr(runner, "query_gpu_memory_mib", lambda: None)
    return state


def canonical_tuning_manifest(tmp_path: Path) -> tuple[Path, CorpusManifest]:
    """24 synthetic cases (16/4/4), diverse and review-pending: calibration-eligible except for review."""
    root = tmp_path / "tuning"
    root.mkdir()
    qualities = ["readable"] * 16 + ["difficult"] * 4 + ["negative"] * 4
    cases = tuple(make_tuning_case(root, f"tune-{i:02d}", i, quality, split="tuning", reviewed=False)
                  for i, quality in enumerate(qualities))
    manifest = CorpusManifest(schema_version=1, split="tuning", purpose="review_preparation", cases=cases,
                              denominators=declared_denominators(cases))
    path = root / "canonical-manifest.json"
    path.write_bytes(manifest_bytes(manifest))
    return path, manifest


def benchmark_package(tmp_path: Path) -> Path:
    """The real 70-case plan with placeholder generated files and one generated capture per pending input."""
    spec_module = importlib.util.spec_from_file_location("create_benchmark_set", TOOLS / "create_benchmark_set.py")
    generator = importlib.util.module_from_spec(spec_module)
    spec_module.loader.exec_module(generator)
    spec = json.loads((TOOLS / "benchmark-cases.json").read_text(encoding="utf-8"))
    root = tmp_path / "benchmark"
    root.mkdir()
    paths = ["printable-originals.pdf"] + [path for case in spec["cases"] for _, path, _ in generator.artifact_specs(case)]
    for path in paths:
        (root / path).parent.mkdir(parents=True, exist_ok=True)
        (root / path).write_bytes(f"synthetic placeholder {path}".encode())
    plan = generator.build_plan(spec, lambda path: benchmark.file_sha256(root / path), {"fixture": "pipeline"})
    (root / "plan.json").write_bytes(canonical_json_bytes(plan.model_dump(mode="json")))
    for number, case in enumerate(case for case in plan.cases if case.pending is not None):
        target = root / "inbox" / case.pending.inbox_name(case.case_id)
        target.parent.mkdir(parents=True, exist_ok=True)
        size = CAPTURE_SIZE[case.pending.telegram_quality or "camera"]
        target.write_bytes(jpeg(size, (number * 9 % 256, 90, 200 - number)))
    return root


def test_t01_pipeline_from_tuning_review_to_a_single_benchmark_run(tmp_path, core_state, capsys):
    data_root = tmp_path / "data"

    # ---- Stage 2: tuning review -------------------------------------------------------------
    canonical, pending = canonical_tuning_manifest(tmp_path)
    assert set(pending.eligibility_reasons("calibration")) == {"review_preparation_only",
                                                               "human_review_or_ground_truth_pending"}
    decisions = write_json(tmp_path / "tuning-review-decisions.json",
                           form_export(pending, canonical, method="script_reading",
                                       rejected=(REJECTED_TUNING_CASE,)))
    reviewed = canonical.parent / "reviewed-manifest.json"
    code, out, err = cli(corpus_cli.main, ["review-apply", "--manifest", canonical, "--decisions", decisions,
                                           "--output", reviewed], capsys)
    assert code == 0, err
    applied = json.loads(out)
    assert applied["removed_rejected_case_ids"] == [REJECTED_TUNING_CASE]
    assert applied["sha256"] == sha256(reviewed) and applied["purpose"] == "quality_measurement"
    code, out, err = cli(corpus_cli.main, ["status", "--manifest", reviewed], capsys)
    assert code == 0, err
    status = json.loads(out)
    assert status["eligibility"]["calibration"] == [] and status["reviews"] == {"verified": 23}
    assert status["files_verified"] is True and "VALUE" not in out

    # ---- Stage 3: calibration and freeze ------------------------------------------------------
    core_state["scenarios"].update(TRAPS)
    calibration = data_root / "measurements" / "calibration.json"
    code, out, err = cli(runner.main, ["run", "--mode", "calibration", "--manifest", reviewed, "--data-root",
                                       data_root, "--output", calibration], capsys)
    assert code == 0, err
    report = json.loads(calibration.read_text(encoding="utf-8"))
    assert report["quality_measurement_eligible"] and report["selected_all_cases"] and report["case_count"] == 23
    assert report["manifest_sha256"] == sha256(reviewed)
    assert report["eligibility_reasons"]["calibration"] == []
    assert REJECTED_TUNING_CASE not in core_state["cores"][0].seen

    frozen_path = data_root / "frozen" / "frozen-t01b.json"
    code, out, err = cli(runner.main, ["freeze", "--auto", "--calibration", calibration, "--output", frozen_path],
                         capsys)
    assert code == 0, err
    frozen, runner_digest = config.load_frozen(frozen_path)
    assert json.loads(out)["sha256"] == runner_digest == sha256(frozen_path)
    assert frozen.calibration.tuning_manifest_sha256 == sha256(reviewed)
    assert frozen.calibration.calibration_report_sha256 == sha256(calibration)
    assert frozen.policy == config.FrozenPolicy(min_token_probability=0.99, check_alternate_view=False,
                                                check_declared_format=True, matching_margin=0.9)

    # ---- Stage 4: sealed benchmark preparation -------------------------------------------------
    package = benchmark_package(tmp_path)
    ingested = package / "benchmark-manifest.json"
    lines = []
    assert benchmark.main(["ingest", "--plan", str(package / "plan.json"), "--output", str(ingested),
                           "--registry", str(canonical)], stdout=lines.append) == 0, capsys.readouterr().err
    assert lines[0].startswith("cases=70 readable=40 difficult=20 negative=10 sealed=false review_pending=70")
    unreviewed = load_corpus(ingested).manifest
    difficult = next(case for case in unreviewed.cases if case.quality == "difficult" and reviewable_values(case))
    hidden = {(difficult.case_id, reviewable_values(difficult)[0][0])}
    decisions = write_json(package / "review-decisions.json",
                           form_export(unreviewed, ingested, method="glyph_sequence_comparison", not_legible=hidden))
    reviewed_benchmark = package / "reviewed-manifest.json"
    code, out, err = cli(corpus_cli.main, ["review-apply", "--manifest", ingested, "--decisions", decisions,
                                           "--output", reviewed_benchmark], capsys)
    assert code == 0, err
    assert json.loads(out)["verified_cases"] == 70
    code, out, err = cli(corpus_cli.main, ["status", "--manifest", reviewed_benchmark], capsys)
    assert json.loads(out)["eligibility"]["benchmark"] == ["benchmark_not_sealed_and_frozen"]

    sealed = package / "sealed-manifest.json"
    lines.clear()
    assert benchmark.main(["seal", "--manifest", str(reviewed_benchmark), "--config", str(frozen_path),
                           "--output", str(sealed), "--registry", str(reviewed)],
                          stdout=lines.append) == 0, capsys.readouterr().err
    assert "sealed=true review_pending=0" in lines[0]
    sealed_manifest = load_corpus(sealed).manifest
    # The seal's hash of the file freeze wrote is the runner's identity of that configuration.
    assert sealed_manifest.frozen_configuration_sha256 == runner_digest
    assert sealed_manifest.eligibility_reasons("benchmark") == ()

    # ---- Stage 5: one benchmark run -----------------------------------------------------------
    loaded = load_corpus(sealed)
    core_state["scenarios"].update({case.files[0].stem: {"matching": "not_document"} for case in loaded.cases})
    cores_before = len(core_state["cores"])

    def run_benchmark(registry, output):
        return cli(runner.main, ["benchmark", "--manifest", sealed, "--config", frozen_path, "--registry", registry,
                                 "--data-root", data_root, "--output", output], capsys)

    # A tuning registry other than the manifest the configuration was calibrated on is refused.
    code, _, err = run_benchmark(canonical, data_root / "measurements" / "refused.json")
    assert (code, err) == (2, "error: benchmark_registry_missing_calibration_manifest\n")
    assert len(core_state["cores"]) == cores_before

    first = data_root / "measurements" / "benchmark.json"
    code, out, err = run_benchmark(reviewed, first)
    assert code == 0, err
    result = json.loads(first.read_text(encoding="utf-8"))
    assert result["frozen_configuration_sha256"] == runner_digest and result["manifest_sha256"] == sha256(sealed)
    assert result["aggregate"]["cases"] == 70 and result["registry_splits"] == ["tuning"]
    assert result["quality_measurement_eligible"] and not result["environment_changed_during_run"]
    assert len(core_state["cores"]) == cores_before + 1
    settings = core_state["settings"][-1]
    assert settings.verification.min_token_probability == 0.99 and settings.matching_margin == 0.9

    code, _, err = run_benchmark(reviewed, data_root / "measurements" / "again.json")
    assert (code, err) == (2, "error: benchmark_already_run\n")
    assert len(core_state["cores"]) == cores_before + 1
    assert not (data_root / "measurements" / "again.json").exists()
    ledger = (data_root / "ledger" / "benchmark-runs.jsonl").read_text(encoding="utf-8").splitlines()
    assert [json.loads(line)["event"] for line in ledger] == ["started", "completed"]
    assert not any((data_root / "tmp").iterdir())
