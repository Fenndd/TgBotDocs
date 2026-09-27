"""Frozen configuration identity: canonical bytes, code and prompt hashes, environment checks."""
from datetime import datetime, timedelta, timezone
import hashlib
import json

import pytest

from tgbotdocs.recognition import config, prompts


def make_frozen(*, tuning_manifest_sha256="a" * 64, created_at=datetime(2026, 9, 27, 12, tzinfo=timezone.utc),
                **policy):
    environment = config.current_environment()
    values = {"min_token_probability": 0.9, "check_alternate_view": False, "check_declared_format": True,
              "matching_margin": 0.2, **policy}
    return config.FrozenConfiguration(
        schema_version=1, created_at=created_at,
        runtime_artifacts=environment.runtime_artifacts, runtime_profile=environment.runtime_profile,
        core=environment.core, prompt=environment.prompt, policy=config.FrozenPolicy(**values),
        corpus_manifest_schema_version=1,
        calibration=config.CalibrationProvenance(tuning_manifest_sha256=tuning_manifest_sha256,
                                                 calibration_report_sha256="b" * 64,
                                                 point_index=3, selection_rule="test rule"),
        code_sha256=environment.code_sha256, dependencies=environment.dependencies,
        page_times=(config.PageTimes(kind="png", count=2, p5=1.0, p50=2.0, p95=3.0),),
    )


def test_canonical_bytes_identify_content_not_formatting(tmp_path):
    frozen = make_frozen()
    path = tmp_path / "frozen.json"
    digest = config.write_frozen(frozen, path)
    assert digest == hashlib.sha256(path.read_bytes()).hexdigest()
    data = json.loads(path.read_bytes())
    assert path.read_bytes() == json.dumps(data, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode()
    loaded, loaded_digest = config.load_frozen(path)
    assert loaded == frozen and loaded_digest == digest
    pretty = tmp_path / "pretty.json"
    pretty.write_text(json.dumps(data, indent=4), encoding="utf-8")
    assert config.load_frozen(pretty)[1] == digest
    changed = tmp_path / "changed.json"
    config.write_frozen(make_frozen(min_token_probability=0.95), changed)
    assert config.load_frozen(changed)[1] != digest
    with pytest.raises(config.ConfigError, match="frozen_configuration_exists"):
        config.write_frozen(make_frozen(min_token_probability=0.5), path)
    assert config.load_frozen(path)[1] == digest


@pytest.mark.parametrize("mutate", [
    lambda data: data.update(extra="value"),
    lambda data: data.update(created_at="2026-09-27T12:00:00"),
    lambda data: data.update(created_at="2026-09-27T12:00:00+02:00"),
    lambda data: data["policy"].update(matching_margin=1.5),
    lambda data: data.update(code_sha256="not-a-hash"),
    lambda data: data.update(page_times=[data["page_times"][0], data["page_times"][0]]),
])
def test_invalid_frozen_configuration_is_refused_with_a_fixed_code(tmp_path, mutate):
    data = make_frozen().model_dump(mode="json")
    mutate(data)
    path = tmp_path / "frozen.json"
    path.write_text(json.dumps(data), encoding="utf-8")
    with pytest.raises(config.ConfigError, match="^invalid_frozen_configuration$"):
        config.load_frozen(path)


def test_code_hash_is_line_ending_independent_and_covers_names_and_bytes(tmp_path):
    first, second = tmp_path / "one", tmp_path / "two"
    first.mkdir(), second.mkdir()
    (first / "a.py").write_bytes(b"x = 1\ny = 2\n")
    (first / "b.py").write_bytes(b"z = 3\n")
    (second / "a.py").write_bytes(b"x = 1\r\ny = 2\r\n")
    (second / "b.py").write_bytes(b"z = 3\r\n")
    (second / "notes.txt").write_bytes(b"not code")
    assert config.current_code_hash(first) == config.current_code_hash(second)
    (second / "b.py").write_bytes(b"z = 4\n")
    assert config.current_code_hash(first) != config.current_code_hash(second)
    (second / "b.py").write_bytes(b"z = 3\n")
    (second / "b.py").rename(second / "c.py")
    assert config.current_code_hash(first) != config.current_code_hash(second)
    assert config.current_code_hash() == config.current_code_hash(config.Path(config.__file__).parent)


def test_prompt_identity_tracks_constants_and_version(monkeypatch):
    original = config.prompt_identity()
    assert original.version == prompts.PROMPT_VERSION and original == config.prompt_identity()
    monkeypatch.setattr(prompts, "EXTRACTION", prompts.EXTRACTION + " Changed.")
    assert config.prompt_identity().sha256 != original.sha256
    monkeypatch.undo()
    monkeypatch.setattr(prompts, "PROMPT_VERSION", "other")
    assert config.prompt_identity().sha256 != original.sha256


def test_environment_comparison_names_each_difference():
    frozen = make_frozen()
    current = config.current_environment()
    assert config.environment_mismatches(frozen.environment(), current) == ()
    changed = frozen.environment().model_copy(update={
        "code_sha256": "0" * 64, "core": current.core.model_copy(update={"image_long_side": 1280})})
    assert config.environment_mismatches(changed, current) == ("code_hash_mismatch", "core_settings_mismatch")


def test_frozen_policy_builds_matching_core_settings():
    settings = make_frozen(check_alternate_view=True, min_token_probability=None).core_settings()
    assert settings.compute_alternate_view and settings.verification.check_alternate_view
    assert settings.verification.min_token_probability is None and settings.matching_margin == 0.2
    assert not settings.keep_trace
    defaults = config.default_core_values()
    assert (settings.image_long_side, settings.processing_budget_s) == (defaults.image_long_side,
                                                                         defaults.processing_budget_s)


def test_percentiles_and_page_time_summary():
    assert config.percentile([4.0, 1.0, 3.0, 2.0], 0.5) == 2.5
    assert config.percentile([7.0], 0.95) == 7.0
    with pytest.raises(ValueError):
        config.percentile([], 0.5)
    summary = config.page_time_summary({"pdf": [1.0, 2.0, 3.0], "png": [], "jpeg": [5.0]})
    assert [(item.kind, item.count, item.p50) for item in summary] == [("jpeg", 1, 5.0), ("pdf", 3, 2.0)]


def test_timestamps_must_be_utc():
    data = make_frozen().model_dump()
    for created in (datetime(2026, 1, 1, tzinfo=timezone(timedelta(hours=3))), datetime(2026, 1, 1)):
        with pytest.raises(ValueError, match="utc_timestamp_required"):
            config.FrozenConfiguration.model_validate({**data, "created_at": created})


def test_behavior_identity_ignores_creation_time_and_provenance_only():
    base = make_frozen()
    same = make_frozen(created_at=datetime(2027, 1, 1, tzinfo=timezone.utc), tuning_manifest_sha256="f" * 64)
    assert config.configuration_sha256(base) != config.configuration_sha256(same)
    assert config.behavior_sha256(base) == config.behavior_sha256(same)
    assert config.behavior_sha256(base) != config.behavior_sha256(make_frozen(matching_margin=0.3))
    changed = base.model_copy(update={"code_sha256": "0" * 64})
    assert config.behavior_sha256(base) != config.behavior_sha256(changed)


def test_dependency_versions_are_part_of_the_environment():
    current = config.current_environment()
    assert current.dependencies == config.dependency_versions() == make_frozen().dependencies
    assert current.dependencies.python.count(".") == 2 and current.dependencies.pillow != "not_installed"
    upgraded = current.model_copy(update={"dependencies": current.dependencies.model_copy(update={"pillow": "99.0"})})
    assert config.environment_mismatches(upgraded, current) == ("dependency_versions_mismatch",)
