"""Runner behavior with scripted cores; review attestations below are synthetic test data only."""
from contextlib import asynccontextmanager
from dataclasses import replace
from datetime import datetime, timezone
import hashlib
import json

from PIL import Image
import pytest

from test_config import make_frozen
from test_core import FakeAdapter, batch as wire_batch, matching_reply
from tgbotdocs.recognition import config, runner
from tgbotdocs.recognition.adapter import ModelError
from tgbotdocs.recognition.contracts import (BatchResult, ExtractionProfile, FieldResult, MatchingResponse,
                                             PageMembership, ScalarField)
from tgbotdocs.recognition.core import BatchTrace, CallRecord, JobTrace, RecognitionCore, decide
from tgbotdocs.recognition.corpus import (Artifact, CorpusCase, CorpusManifest, ExpectedOutcome, ExpectedValue,
                                          HumanReview, Origin, case_review_digest, declared_denominators)
from tgbotdocs.recognition.preparation import PreparationError
from tgbotdocs.recognition.verification import verify_matching

SCRIPTS = ("Latin", "Cyrillic", "Arabic", "Chinese", "Japanese", "Devanagari")
CATEGORIES = ("identity", "invoice", "receipt", "certificate", "contract", "application", "letter", "repeating_rows")
FIELD = ScalarField(id="code", label="Code", description="Printed code", type="text")
PROFILE_NAME = "Synthetic code card"


def write_png(path, seed):
    image = Image.new("RGB", (40, 50), "white")
    image.putpixel((seed % 40, seed // 40), (0, 0, 0))
    image.save(path)
    return hashlib.sha256(path.read_bytes()).hexdigest()


def make_case(root, identity, index, quality, *, split, delivery="image_file", reviewed=True):
    digest = write_png(root / f"{identity}.png", index + (0 if split == "tuning" else 500))
    profile = ExtractionProfile(id=f"profile-{identity}", owner="synthetic-user", version=1, name=PROFILE_NAME,
                                description="Card with a printed code", original_instruction="Read the code",
                                fields=(FIELD,))
    if quality == "negative":
        expected = ExpectedOutcome(matching="not_document", outcome="refused")
    else:
        expected = ExpectedOutcome(matching="matched", profile_id=profile.id, outcome="complete", fields=(
            ExpectedValue(field_id="code", status="extracted", present=True, value=f"VALUE-{identity}",
                          source_pages=(1,)),))
    benchmark = split == "benchmark"
    artifact = Artifact(id="input", path=f"{identity}.png", sha256=digest, kind=delivery,
                        telegram_delivery_verified=benchmark and delivery == "photo",
                        physical_capture=benchmark and quality == "difficult")
    case = CorpusCase(case_id=identity, origin=Origin(
        family_id=identity, kind="synthetic", permission_basis="synthetic test data",
        original_sha256=hashlib.sha256(f"{split}:{identity}".encode()).hexdigest()),
        script=SCRIPTS[index % 6], language="en", category=CATEGORIES[index % 8], quality=quality,
        scenario="synthetic_runner_test", delivery_path=delivery, artifacts=(artifact,), input_artifact_ids=("input",),
        page_ids=(1,), profiles=(profile,), expected=expected)
    if reviewed:
        data = case.model_dump()
        data["review"] = HumanReview(status="verified", reviewer="Synthetic test fixture", method="script_reading",
                                     reviewed_at=datetime(2026, 9, 27, tzinfo=timezone.utc),
                                     subject_sha256=case_review_digest(case), reviewer_kind="human")
        case = CorpusCase.model_validate(data)
    return case


def write_manifest(root, cases, *, split, reviewed=True, **kwargs):
    manifest = CorpusManifest(schema_version=1, split=split,
                              purpose="quality_measurement" if reviewed else "review_preparation",
                              cases=tuple(cases), denominators=declared_denominators(tuple(cases)), **kwargs)
    path = root / "manifest.json"
    path.write_text(manifest.model_dump_json(), encoding="utf-8")
    return path


def tuning_corpus(tmp_path, *, reviewed=True):
    root = tmp_path / "tuning"
    root.mkdir()
    qualities = ["readable"] * 16 + ["difficult"] * 4 + ["negative"] * 4
    cases = [make_case(root, f"tune-{i:02d}", i, quality, split="tuning", reviewed=reviewed)
             for i, quality in enumerate(qualities)]
    return write_manifest(root, cases, split="tuning", reviewed=reviewed)


def benchmark_corpus(tmp_path, config_sha, *, name="bench"):
    root = tmp_path / name
    root.mkdir()
    cases = []
    for i in range(70):
        quality = "readable" if i < 40 else "difficult" if i < 60 else "negative"
        photo = (quality == "readable" and i % 5 == 0) or (quality == "difficult" and i < 50)
        cases.append(make_case(root, f"bench-{i:02d}", i, quality, split="benchmark",
                               delivery="photo" if photo else "image_file"))
    return write_manifest(root, cases, split="benchmark", sealed=True, frozen_configuration_sha256=config_sha)


def scalar_batch(value):
    return BatchResult(page_ids=(1,), fields=(FieldResult(field_id="code", status="extracted", raw_value=value,
                                                          source_pages=(1,)),),
                       page_membership=(PageMembership(page_id=1, status="yes"),))


class ScriptedCore:
    """Produces the trace a real core would record for a one-page, one-field case."""

    def __init__(self, settings, scenarios):
        self.settings, self.scenarios, self.seen = settings, scenarios, []

    async def recognize(self, files, snapshots, *, scratch, observer):
        case_id = files[0].stem
        self.seen.append(case_id)
        scenario = self.scenarios.get(case_id, {})
        observer.page_kinds = ("png",)
        observer.preparation_s += 0.25
        if scenario.get("leave_file"):
            (scratch / "leftover.png").write_bytes(b"derived")
        if "raise" in scenario:
            raise scenario["raise"]

        def call(kind, stage, index, seconds):
            observer.calls.append(CallRecord(kind=kind, stage=stage, batch=index, duration_s=seconds, pages=(1,)))

        call("token_count", "matching", None, 0.5)
        call("matching", "matching", None, 1.0)
        if scenario.get("matching", "matched") == "matched":
            raw, candidates = MatchingResponse(status="matched", profile_index=1), scenario.get("candidates", (0.95,))
        else:
            raw, candidates = MatchingResponse(status=scenario["matching"]), None
        verified = verify_matching(raw, snapshots, candidate_probabilities=candidates,
                                   minimum_margin=self.settings.matching_margin)
        batches = ()
        if verified.status == "matched":
            value = scenario.get("value", f"VALUE-{case_id}")
            call("token_count", "extraction", 0, 0.5)
            call("extraction", "extraction", 0, 2.0)
            alternate = None
            if self.settings.compute_alternate_view:
                call("token_count", "alternate", 0, 0.5)
                call("alternate", "alternate", 0, 4.0)
                alternate = scalar_batch(scenario.get("alternate", value))
            probabilities = {("fields", "code", "v"): (scenario.get("probability", 0.99),)}
            batches = (BatchTrace(scalar_batch(value), probabilities, alternate, self.settings.compute_alternate_view),)
        trace = JobTrace(page_ids=(1,), page_kinds=("png",), matching=raw, candidate_probabilities=candidates,
                         manual_profile=None, batches=batches, calls=tuple(observer.calls),
                         preparation_s=observer.preparation_s)
        if self.settings.keep_trace:
            observer.trace = trace
        result = decide(trace, snapshots, policy=self.settings.verification,
                        matching_margin=self.settings.matching_margin,
                        alternate_calls=self.settings.compute_alternate_view)
        return replace(result, trace=trace if self.settings.keep_trace else None)


@pytest.fixture
def scripted(monkeypatch):
    state = {"scenarios": {}, "cores": [], "settings": []}

    @asynccontextmanager
    async def opener(data_root, settings):
        state["settings"].append(settings)
        core = state.get("factory", ScriptedCore)(settings, state["scenarios"])
        state["cores"].append(core)
        yield core, lambda: None

    monkeypatch.setattr(runner, "open_core", opener)
    monkeypatch.setattr(runner, "query_gpu_memory_mib", lambda: 1234)
    return state


TRAPS = {
    # A wrong reading the model is unsure about, which a second view also contradicts.
    "tune-03": {"value": "WRONG-VALUE", "probability": 0.6, "alternate": "OTHER-VALUE"},
    # A non-document the model confidently-enough matches to the only profile.
    "tune-21": {"candidates": (0.15,)},
    **{f"tune-{i}": {"matching": "not_document"} for i in (20, 22, 23)},
}


def test_grid_and_collection_settings_follow_the_documented_design():
    assert len(runner.calibration_grid(True)) == 192 and len(runner.calibration_grid(False)) == 96
    assert not any(point.v2_alternate_view for point in runner.calibration_grid(False))
    assert all(point.v3_declared_format for point in runner.calibration_grid(True))
    settings = runner.collection_settings(compute_alternate_view=True)
    assert settings.verification.min_token_probability is None and not settings.verification.check_alternate_view
    assert settings.verification.check_declared_format and settings.matching_margin == 0.0 and settings.keep_trace


def test_calibration_replays_every_point_and_auto_freeze_selects_the_documented_point(tmp_path, scripted, capsys):
    manifest = tuning_corpus(tmp_path)
    scripted["scenarios"].update(TRAPS)
    data, report_path = tmp_path / "data", tmp_path / "out" / "calibration.json"
    assert runner.main(["run", "--manifest", str(manifest), "--mode", "calibration", "--data-root", str(data),
                        "--output", str(report_path)]) == 0
    text = report_path.read_text(encoding="utf-8")
    for private in ("VALUE-", "WRONG", "OTHER-VALUE", PROFILE_NAME, "synthetic-user", "printed code"):
        assert private not in text
    report = json.loads(text)
    assert report["quality_measurement_eligible"] and report["selected_all_cases"]
    assert report["collection"]["compute_alternate_view"] and len(report["points"]) == 192
    assert report["resources"]["peak_gpu_memory_used_mib"] == 1234
    assert not any((data / "tmp").iterdir())
    permissive = report["points"][0]
    assert permissive["thresholds"] == {"v1_min_token_probability": None, "v2_alternate_view": False,
                                        "v3_declared_format": True, "matching_margin": 0.0}
    # The misread value and the value extracted from the wrongly matched non-document.
    assert permissive["aggregate"]["incorrect_accepted_values"] == 2
    assert permissive["aggregate"]["incorrect_automatic_profile_selections"] == 1
    curves = report["curves"]
    assert [entry["value"] for entry in curves["v1_with_v2_off_margin_0"]] == list(runner.V1_GRID)
    assert [entry["incorrect_accepted_values"] for entry in curves["v1_with_v2_off_margin_0"]][:4] == [2, 2, 2, 1]
    assert [entry["incorrect_accepted_values"] for entry in curves["v2_with_v1_off_margin_0"]] == [2, 1]
    assert [entry["incorrect_automatic_profile_selections"] for entry in curves["margin_with_v1_off_v2_off"]] == [
        1, 1, 1, 0, 0, 0, 0, 0]
    assert len(report["cases"]) == 24 and report["cases"][0]["calls"][0]["kind"] == "token_count"

    capsys.readouterr()
    frozen_path = tmp_path / "frozen.json"
    assert runner.main(["freeze", "--calibration", str(report_path), "--output", str(frozen_path), "--auto"]) == 0
    frozen, digest = config.load_frozen(frozen_path)
    assert digest in capsys.readouterr().out
    assert frozen.policy == config.FrozenPolicy(min_token_probability=0.99, check_alternate_view=False,
                                                check_declared_format=True, matching_margin=0.9)
    # 16 readable + 4 difficult cases traverse every page at the frozen point; per page:
    # preparation 0.25 + counts 0.5 + 0.5 + matching 1.0 + extraction 2.0; no V2 calls.
    assert frozen.page_times == (config.PageTimes(kind="png", count=20, p5=4.25, p50=4.25, p95=4.25),)
    assert frozen.calibration.calibration_report_sha256 == hashlib.sha256(report_path.read_bytes()).hexdigest()
    assert frozen.calibration.tuning_manifest_sha256 == hashlib.sha256(manifest.read_bytes()).hexdigest()
    assert frozen.calibration.selection_rule == runner.SELECTION_RULE
    assert frozen.code_sha256 == config.current_code_hash()


def point(index, *, errors=0, profiles=0, completeness=0.95, v1=None, v2=False, margin=0.0, decisions=(),
          unreplayable=0):
    return {"index": index, "thresholds": {"v1_min_token_probability": v1, "v2_alternate_view": v2,
                                           "v3_declared_format": True, "matching_margin": margin},
            "aggregate": {"incorrect_accepted_values": errors, "incorrect_automatic_profile_selections": profiles,
                          "rates": {"readable_completeness": completeness}},
            "unreplayable_cases": unreplayable, "case_decisions": list(decisions)}


def test_auto_selection_prefers_completeness_then_v2_off_then_higher_thresholds():
    points = [point(0, errors=1, completeness=1.0), point(1, v1=0.9, v2=True), point(2, v1=0.5),
              point(3, v1=0.9, margin=0.1), point(4, v1=0.9, margin=0.3), point(5, v1=0.99, completeness=0.9),
              point(6, profiles=1, completeness=0.99)]
    assert runner.select_point(points) == 4
    points.append(point(7, v1=None, v2=True, completeness=0.97))
    assert runner.select_point(points) == 7
    with pytest.raises(runner.RunnerError, match="calibration_no_zero_error_point"):
        runner.select_point([point(0, errors=1), point(1, profiles=2)])
    # A case whose outcome at a point is unknown may hide an error there.
    with pytest.raises(runner.RunnerError, match="calibration_no_zero_error_point"):
        runner.select_point([point(0, unreplayable=1)])


def calibration_report(tmp_path, points, **overrides):
    report = {"schema_version": runner.REPORT_SCHEMA_VERSION, "mode": "calibration", "quality_measurement_eligible": True,
              "selected_all_cases": True, "environment": config.current_environment().model_dump(mode="json"),
              "manifest_sha256": "c" * 64, "manifest_schema_version": 1, "points": points, "cases": [], **overrides}
    path = tmp_path / f"report-{len(list(tmp_path.iterdir()))}.json"
    path.write_text(json.dumps(report), encoding="utf-8")
    return path


def test_freeze_refuses_unsafe_or_mismatched_calibration(tmp_path, monkeypatch, capsys):
    reports = tmp_path / "reports"
    reports.mkdir()
    good = [point(0, v1=0.9, margin=0.2), point(1, errors=2)]

    def freeze(path, *extra):
        output = tmp_path / f"frozen-{len(list(tmp_path.glob('frozen-*')))}.json"
        code = runner.main(["freeze", "--calibration", str(path), "--output", str(output), *extra])
        return code, capsys.readouterr().err

    assert freeze(calibration_report(reports, good, mode="diagnostics", quality_measurement_eligible=False),
                  "--auto") == (2, "error: calibration_report_required\n")
    assert freeze(calibration_report(reports, good, selected_all_cases=False), "--auto")[1] == (
        "error: calibration_incomplete_case_selection\n")
    assert freeze(calibration_report(reports, good), "--point", "1")[1] == "error: calibration_point_has_errors\n"
    assert freeze(calibration_report(reports, good), "--point", "7")[1] == "error: unknown_calibration_point\n"
    low = [point(0, completeness=0.8)]
    assert freeze(calibration_report(reports, low), "--auto")[1] == "error: calibration_completeness_below_target\n"
    assert freeze(calibration_report(reports, low), "--auto", "--accept-below-target")[0] == 0
    assert freeze(calibration_report(reports, [point(0, errors=1)]), "--auto")[1] == (
        "error: calibration_no_zero_error_point\n")
    (reports / "broken.json").write_text("{", encoding="utf-8")
    assert freeze(reports / "broken.json", "--auto")[1] == "error: invalid_calibration_report\n"
    assert freeze(calibration_report(reports, good), "--point", "0")[0] == 0
    stale = calibration_report(reports, good)
    monkeypatch.setattr(config, "current_code_hash", lambda directory=None: "0" * 64)
    assert freeze(stale, "--auto")[1] == "error: code_hash_mismatch\n"


def test_diagnostics_run_records_states_cleans_scratch_and_keeps_values_out_of_files(tmp_path, scripted, capsys):
    manifest = tuning_corpus(tmp_path, reviewed=False)
    scripted["scenarios"].update({
        "tune-01": {"raise": ModelError("runtime_timeout")},
        "tune-02": {"raise": PreparationError("encrypted_pdf")},
        "tune-04": {"raise": ModelError("recognition_contract_violation")},
        "tune-05": {"leave_file": True},
        "tune-06": {"raise": RuntimeError("private detail VALUE-tune-06")},
        "tune-07": {"value": "MISREAD-VALUE"},
    })
    data, output = tmp_path / "data", tmp_path / "diagnostics.json"
    selection = ",".join(f"tune-{i:02d}" for i in range(8))
    assert runner.main(["run", "--manifest", str(manifest), "--mode", "diagnostics", "--data-root", str(data),
                        "--output", str(output), "--cases", selection, "--no-alternate", "--show-mismatches"]) == 0
    captured = capsys.readouterr()
    assert "MISREAD-VALUE" in captured.err and "VALUE-tune-07" in captured.err
    assert "VALUE" not in captured.out
    text = output.read_text(encoding="utf-8")
    assert "VALUE" not in text and "private detail" not in text
    report = json.loads(text)
    assert not report["quality_measurement_eligible"] and not report["selected_all_cases"]
    assert "human_review_or_ground_truth_pending" in report["eligibility_reasons"]["calibration"]
    assert len(report["points"]) == 96 and scripted["settings"][0].compute_alternate_view is False
    rows = {row["case_id"]: row for row in report["cases"]}
    assert [(rows[f"tune-{i:02d}"]["execution_state"], rows[f"tune-{i:02d}"]["error_code"]) for i in range(8)] == [
        ("completed", None), ("timeout", "runtime_timeout"), ("input_refused", "encrypted_pdf"),
        ("completed", None), ("failed", "recognition_contract_violation"), ("failed", "scratch_not_empty"),
        ("failed", "unexpected_error"), ("completed", None)]
    assert report["failures_by_code"] == {"encrypted_pdf": 1, "recognition_contract_violation": 1,
                                          "runtime_timeout": 1, "scratch_not_empty": 1, "unexpected_error": 1}
    aggregate = report["points"][0]["aggregate"]
    assert aggregate["cases"] == 24 and aggregate["not_run_cases"] == 16 and aggregate["timeout_cases"] == 1
    assert rows["tune-00"]["pages_by_kind"] == {"png": 1} and rows["tune-00"]["model_calls"] == 2
    assert not any((data / "tmp").iterdir())


def test_run_refusals_happen_before_the_runtime_starts(tmp_path, scripted, capsys):
    pending = tuning_corpus(tmp_path, reviewed=False)
    data, output = tmp_path / "data", tmp_path / "report.json"

    def run(manifest, mode, *extra):
        code = runner.main(["run", "--manifest", str(manifest), "--mode", mode, "--data-root", str(data),
                            "--output", str(output), *extra])
        return code, capsys.readouterr().err

    assert run(pending, "calibration") == (2, "error: corpus_ineligible_for_quality_measurement\n")
    assert run(pending, "diagnostics", "--cases", "tune-00,unknown")[1] == "error: unknown_or_duplicate_case_id\n"
    bench = benchmark_corpus(tmp_path, "d" * 64)
    assert run(bench, "diagnostics")[1] == "error: benchmark_split_refused\n"
    (tmp_path / "tuning" / "tune-00.png").write_bytes(b"tampered")
    assert run(pending, "diagnostics")[1] == "error: artifact_hash_mismatch\n"
    assert scripted["cores"] == [] and not output.exists()


def frozen_file(tmp_path, registry, *, name="frozen.json", **values):
    """A frozen configuration calibrated on the tuning manifest file ``registry``."""
    path = tmp_path / name
    tuning = hashlib.sha256(registry.read_bytes()).hexdigest()
    return path, config.write_frozen(make_frozen(tuning_manifest_sha256=tuning, **values), path)


def benchmark_args(tmp_path, manifest, frozen, registry, output, *extra):
    return ["benchmark", "--manifest", str(manifest), "--config", str(frozen), "--registry", str(registry),
            "--data-root", str(tmp_path / "data"), "--output", str(output), *extra]


def test_benchmark_runs_once_per_frozen_configuration(tmp_path, scripted, capsys):
    registry = tuning_corpus(tmp_path)
    frozen, digest = frozen_file(tmp_path, registry, min_token_probability=0.9, matching_margin=0.2)
    manifest = benchmark_corpus(tmp_path, digest)
    scripted["scenarios"].update({f"bench-{i}": {"matching": "not_document"} for i in range(60, 70)})
    output = tmp_path / "benchmark.json"
    assert runner.main(benchmark_args(tmp_path, manifest, frozen, registry, output)) == 0
    settings = scripted["settings"][0]
    assert settings.verification.min_token_probability == 0.9 and settings.matching_margin == 0.2
    assert not settings.compute_alternate_view and not settings.keep_trace
    text = output.read_text(encoding="utf-8")
    assert "VALUE" not in text and PROFILE_NAME not in text
    report = json.loads(text)
    assert report["aggregate"]["cases"] == 70 and report["aggregate"]["incorrect_accepted_values"] == 0
    assert report["aggregate"]["correct_accepted_values"] == 60 and report["quality_measurement_eligible"]
    assert report["page_times"] == [{"kind": "png", "count": 60, "p5": 4.25, "p50": 4.25, "p95": 4.25}]
    assert report["frozen_configuration_sha256"] == digest and "points" not in report
    ledger = [json.loads(line) for line in (tmp_path / "data" / "ledger" / "benchmark-runs.jsonl").read_text().splitlines()]
    assert [entry["event"] for entry in ledger] == ["started", "completed"]
    assert {entry["run_id"] for entry in ledger} == {report["run_id"]}
    assert report["prior_completed_runs_on_case_set"] == [] and not report["environment_changed_during_run"]
    capsys.readouterr()
    assert runner.main(benchmark_args(tmp_path, manifest, frozen, registry, tmp_path / "again.json")) == 2
    assert capsys.readouterr().err == "error: benchmark_already_run\n"
    assert len(scripted["cores"]) == 1 and not (tmp_path / "again.json").exists()

    # Freezing the same point again gives a new file hash but the same behavior: refused.
    refrozen, refrozen_digest = frozen_file(tmp_path, registry, name="refrozen.json", min_token_probability=0.9,
                                            matching_margin=0.2, created_at=datetime(2026, 9, 28, tzinfo=timezone.utc))
    assert refrozen_digest != digest
    resealed = benchmark_corpus(tmp_path, refrozen_digest, name="resealed")
    assert runner.main(benchmark_args(tmp_path, resealed, refrozen, registry, tmp_path / "again.json")) == 2
    assert capsys.readouterr().err == "error: benchmark_already_run\n"
    assert len(scripted["cores"]) == 1

    # A different configuration may run on the same cases (remediation); the report shows the earlier run.
    other, other_digest = frozen_file(tmp_path, registry, name="other.json", min_token_probability=0.95,
                                      matching_margin=0.2)
    remediated = benchmark_corpus(tmp_path, other_digest, name="remediated")
    assert runner.main(benchmark_args(tmp_path, remediated, other, registry, tmp_path / "second.json")) == 0
    second = json.loads((tmp_path / "second.json").read_text(encoding="utf-8"))
    assert second["prior_completed_runs_on_case_set"] == [report["run_id"]]
    assert second["behavior_sha256"] != report["behavior_sha256"]


def test_benchmark_refuses_mismatches_and_requires_acknowledging_incomplete_runs(
        tmp_path, scripted, capsys, monkeypatch):
    registry = tuning_corpus(tmp_path)
    frozen, digest = frozen_file(tmp_path, registry)
    output = tmp_path / "benchmark.json"
    other = benchmark_corpus(tmp_path, "e" * 64, name="other")
    assert runner.main(benchmark_args(tmp_path, other, frozen, registry, output)) == 2
    assert capsys.readouterr().err == "error: frozen_configuration_mismatch\n"
    manifest = benchmark_corpus(tmp_path, digest)
    assert runner.main(benchmark_args(tmp_path, manifest, frozen, manifest, output)) == 2
    assert capsys.readouterr().err == "error: benchmark_registry_requires_tuning_manifest\n"
    # A tuning registry that is not the manifest the configuration was calibrated on.
    stale = tmp_path / "stale.json"
    stale_digest = config.write_frozen(make_frozen(tuning_manifest_sha256="a" * 64), stale)
    stale_bench = benchmark_corpus(tmp_path, stale_digest, name="stale-bench")
    assert runner.main(benchmark_args(tmp_path, stale_bench, stale, registry, output)) == 2
    assert capsys.readouterr().err == "error: benchmark_registry_missing_calibration_manifest\n"
    with monkeypatch.context() as patch:
        patch.setattr(config, "current_code_hash", lambda directory=None: "0" * 64)
        assert runner.main(benchmark_args(tmp_path, manifest, frozen, registry, output)) == 2
        assert capsys.readouterr().err == "error: code_hash_mismatch\n"
    ledger = tmp_path / "data" / "ledger" / "benchmark-runs.jsonl"
    ledger.parent.mkdir(parents=True)
    ledger.write_text(json.dumps({"event": "started", "run_id": "crashed-run", "config_sha256": digest}) + "\n")
    assert runner.main(benchmark_args(tmp_path, manifest, frozen, registry, output)) == 2
    assert capsys.readouterr().err == "error: benchmark_incomplete_run_requires_acknowledgement\n"
    assert runner.main(benchmark_args(tmp_path, manifest, frozen, registry, output,
                                      "--acknowledge-incomplete-run", "another-run")) == 2
    assert scripted["cores"] == []
    assert runner.main(benchmark_args(tmp_path, manifest, frozen, registry, output,
                                      "--acknowledge-incomplete-run", "crashed-run")) == 0
    events = [json.loads(line)["event"] for line in ledger.read_text().splitlines()]
    assert events == ["started", "acknowledged", "started", "completed"]


def test_ledger_rules():
    started = {"event": "started", "run_id": "r1", "config_sha256": "x", "behavior_sha256": "bx"}
    assert runner.check_ledger([], "x", "bx", None) is None
    assert runner.check_ledger([started], "y", "by", None) is None
    with pytest.raises(runner.RunnerError, match="unknown_incomplete_run"):
        runner.check_ledger([], "x", "bx", "r1")
    assert runner.check_ledger([started], "x", "bx", "r1") == "r1"
    # An incomplete run of the same behavior under another file hash also needs acknowledging.
    with pytest.raises(runner.RunnerError, match="benchmark_incomplete_run_requires_acknowledgement"):
        runner.check_ledger([started], "y", "bx", None)
    acknowledged = {**started, "event": "acknowledged"}
    completed = [started, acknowledged, {**started, "run_id": "r2"}, {**started, "run_id": "r2", "event": "completed"}]
    for config_sha, behavior_sha in (("x", "bx"), ("y", "bx"), ("x", "by")):
        with pytest.raises(runner.RunnerError, match="benchmark_already_run"):
            runner.check_ledger(completed, config_sha, behavior_sha, None)



async def test_real_core_run_records_traces_and_removes_renders(tmp_path, monkeypatch):
    """Wiring with the production core and preparation workers; only the model is fake."""
    root = tmp_path / "tuning"
    root.mkdir()
    cases = [make_case(root, f"tune-{i:02d}", i, "readable", split="tuning", reviewed=False) for i in range(2)]
    manifest = write_manifest(root, cases, split="tuning", reviewed=False)
    matched = {"status": "matched", "profile_index": 1, "type_description": None}

    def answer(identity):
        data = wire_batch((1,), f"VALUE-{identity}")
        data["fields"] = {"code": data["fields"]["identifier"]}
        return data

    answers = [matched, answer("tune-00"), answer("tune-00"), matched, answer("tune-01"), {**answer("tune-01"),
               "fields": {"code": {"s": "extracted", "v": "DIFFERENT", "p": [1]}}}]
    adapters = []

    @asynccontextmanager
    async def opener(data_root, settings):
        adapters.append(FakeAdapter(answers, image_tokens=500))
        yield RecognitionCore(adapters[-1], settings), lambda: None

    monkeypatch.setattr(runner, "open_core", opener)
    monkeypatch.setattr(runner, "query_gpu_memory_mib", lambda: None)
    output = tmp_path / "report.json"
    parser = runner.build_parser()
    report = await runner.run_command(parser.parse_args([
        "run", "--manifest", str(manifest), "--mode", "diagnostics", "--data-root", str(tmp_path / "data"),
        "--output", str(output)]))
    assert len(adapters[0].calls) == 6 and not any((tmp_path / "data" / "tmp").iterdir())
    kinds = [call["kind"] for call in report["cases"][0]["calls"]]
    assert kinds == ["token_count", "matching", "token_count", "extraction", "token_count", "alternate"]
    by_v2 = {entry["value"]: entry for entry in report["curves"]["v2_with_v1_off_margin_0"]}
    assert by_v2[False]["accepted_values"] == 2 and by_v2[True]["accepted_values"] == 1
    assert report["resources"]["peak_gpu_memory_used_mib"] is None


def point_at(report, v1, v2, margin):
    return next(item for item in report["points"] if item["thresholds"] == {
        "v1_min_token_probability": v1, "v2_alternate_view": v2, "v3_declared_format": True,
        "matching_margin": margin})


async def test_replay_reports_call_failures_only_at_points_that_make_the_failing_call(tmp_path, monkeypatch):
    """Real core; only the model is fake. A failed alternate or a failure after a weak match
    must not hide what a point that never makes that call would have accepted."""
    root = tmp_path / "tuning"
    root.mkdir()
    cases = [make_case(root, f"tune-{i:02d}", i, "readable", split="tuning") for i in range(2)]
    manifest = write_manifest(root, cases, split="tuning")
    matched = {"status": "matched", "profile_index": 1, "type_description": None}
    misread = {"fields": {"code": {"s": "extracted", "v": "WRONG-00", "p": [1]}}, "lists": {},
               "membership": {"1": "yes"}}
    answers = [matched, misread, "invalid alternate", "invalid alternate again",
               # A match whose probability margin is 0.6, then an extraction contract violation.
               matching_reply(1, (0.6,)), "invalid extraction", "invalid extraction again"]
    adapters = []

    @asynccontextmanager
    async def opener(data_root, settings):
        adapters.append(FakeAdapter(answers, image_tokens=500))
        yield RecognitionCore(adapters[-1], settings), lambda: None

    monkeypatch.setattr(runner, "open_core", opener)
    monkeypatch.setattr(runner, "query_gpu_memory_mib", lambda: None)
    report = await runner.run_command(runner.build_parser().parse_args([
        "run", "--manifest", str(manifest), "--mode", "diagnostics", "--data-root", str(tmp_path / "data"),
        "--output", str(tmp_path / "report.json")]))
    assert not adapters[0].answers and not any((tmp_path / "data" / "tmp").iterdir())
    rows = {row["case_id"]: row for row in report["cases"]}
    # The collecting job survives its own alternate failure but not the extraction failure.
    assert (rows["tune-00"]["execution_state"], rows["tune-00"]["error_code"]) == ("completed", None)
    assert (rows["tune-01"]["execution_state"], rows["tune-01"]["error_code"]) == (
        "failed", "recognition_contract_violation")
    assert all(item["unreplayable_cases"] == 0 for item in report["points"])

    def summary(v1, v2, margin):
        aggregate = point_at(report, v1, v2, margin)["aggregate"]
        return (aggregate["incorrect_accepted_values"], aggregate["completed_cases"], aggregate["failed_cases"])

    # Without V2 the misread value is accepted: an error, not a failed case.
    assert summary(None, False, 0.0) == (1, 1, 1)
    # A margin above 0.6 stops at "uncertain" before the failing extraction call.
    assert summary(None, False, 0.7) == (1, 2, 0)
    # With V2 the failing alternate call is made, so the case fails there.
    assert summary(None, True, 0.0) == (0, 0, 2)
    assert summary(None, True, 0.7) == (0, 1, 1)


def test_page_samples_attribute_only_the_calls_a_decision_makes():
    def call(kind, stage, batch, pages, seconds):
        return {"kind": kind, "stage": stage, "batch": batch, "pages": pages, "duration_s": seconds}

    calls = [call("token_count", "matching", None, [1, 2, 3], 0.3), call("matching", "matching", None, [1, 2, 3], 0.6),
             call("token_count", "extraction", 0, [1], 0.1), call("token_count", "extraction", 0, [1, 2], 0.2),
             # Rejected lookahead of page 3 while packing batch 0.
             call("token_count", "extraction", 0, [1, 2, 3], 0.3), call("extraction", "extraction", 0, [1, 2], 1.0),
             call("token_count", "alternate", 0, [1, 2], 0.2), call("alternate", "alternate", 0, [1, 2], 0.8),
             call("token_count", "extraction", 1, [3], 0.1), call("extraction", "extraction", 1, [3], 0.5),
             call("token_count", "alternate", 1, [3], 0.1), call("alternate", "alternate", 1, [3], 0.4)]
    row = {"execution_state": "failed", "page_kinds": ["pdf", "pdf", "png"], "preparation_s": 0.3,
           "alternate_preparation_s": 0.6, "calls": calls}
    rows = [{**row, "case_id": "full"}, {**row, "case_id": "stopped"}, {**row, "case_id": "no-decision"}]
    decisions = {"full": (2, True), "stopped": (1, False)}
    without = runner.page_samples(rows, decisions, alternate=False)
    assert without.keys() == {"pdf", "png"}
    assert without["pdf"] == pytest.approx([1.2, 1.1]) and without["png"] == pytest.approx([1.1])
    with_v2 = runner.page_samples(rows, decisions, alternate=True)
    assert with_v2["pdf"] == pytest.approx([1.9, 1.8]) and with_v2["png"] == pytest.approx([1.8])
    assert runner.page_samples(rows, {"stopped": (1, False)}, alternate=True) == {}


def test_calibration_report_is_ineligible_when_the_code_changes_during_the_run(tmp_path, scripted, capsys,
                                                                               monkeypatch):
    manifest = tuning_corpus(tmp_path)
    real, calls = config.current_code_hash, []

    def drifting(directory=None):
        calls.append(directory)
        return real(directory) if len(calls) == 1 else "0" * 64

    monkeypatch.setattr(config, "current_code_hash", drifting)
    report_path = tmp_path / "calibration.json"
    assert runner.main(["run", "--manifest", str(manifest), "--mode", "calibration", "--data-root",
                        str(tmp_path / "data"), "--output", str(report_path)]) == 2
    assert capsys.readouterr().err == "error: environment_changed_during_run\n"
    report = json.loads(report_path.read_text(encoding="utf-8"))
    assert report["environment_changed_during_run"] and not report["quality_measurement_eligible"]
    assert report["environment"]["code_sha256"] == real()
    monkeypatch.setattr(config, "current_code_hash", real)
    assert runner.main(["freeze", "--calibration", str(report_path), "--output", str(tmp_path / "frozen.json"),
                        "--auto"]) == 2
    assert capsys.readouterr().err == "error: calibration_report_required\n"


def test_benchmark_records_its_run_but_is_ineligible_when_the_code_changes_during_it(tmp_path, scripted, capsys,
                                                                                    monkeypatch):
    registry = tuning_corpus(tmp_path)
    frozen, digest = frozen_file(tmp_path, registry)
    manifest = benchmark_corpus(tmp_path, digest)
    real, calls = config.current_code_hash, []

    def drifting(directory=None):
        calls.append(directory)
        return real(directory) if len(calls) == 1 else "0" * 64

    monkeypatch.setattr(config, "current_code_hash", drifting)
    output = tmp_path / "benchmark.json"
    assert runner.main(benchmark_args(tmp_path, manifest, frozen, registry, output)) == 2
    assert capsys.readouterr().err == "error: environment_changed_during_run\n"
    report = json.loads(output.read_text(encoding="utf-8"))
    assert report["environment_changed_during_run"] and not report["quality_measurement_eligible"]
    ledger = (tmp_path / "data" / "ledger" / "benchmark-runs.jsonl").read_text().splitlines()
    assert [json.loads(line)["event"] for line in ledger] == ["started", "completed"]
