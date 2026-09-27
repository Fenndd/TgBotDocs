"""Frozen recognition configuration: the canonical identity a benchmark run depends on.

The canonical form is JSON with sorted keys, compact separators and UTF-8; its
SHA-256 identifies the configuration. The file holds versions, hashes, parameters,
thresholds and timing statistics only, never document values or profile content.
"""

from __future__ import annotations

from dataclasses import MISSING, asdict, fields
from datetime import datetime
import hashlib
from importlib import metadata
import inspect
import json
import math
from pathlib import Path
import sys
from typing import Literal

from pydantic import Field, StrictBool, StrictFloat, StrictInt, StrictStr, ValidationError, field_validator

from .adapter import AdapterSettings
from .contracts import ContractModel
from .core import CoreSettings
from .preparation import PreparationLimits
from . import prompts
from .runtime import RuntimeFiles, RuntimeProfile
from .verification import VerificationPolicy

LLAMA_CPP_BUILD = "b11221"
PROMPT_CONSTANTS = ("PROMPT_VERSION", "SYSTEM", "EXTRACTION", "MATCHING")
# Everything that turns constants and a profile into model input or a grammar.
PROMPT_BUILDERS = (
    "_json", "profile_view", "matching_text", "extraction_text", "boundary_context", "messages",
    "_object", "matching_schema", "_pages_schema", "_cell_schema", "extraction_schema",
)


class ConfigError(ValueError):
    """Content-free configuration error code."""


def _sha256(value: str) -> str:
    if len(value) != 64 or any(character not in "0123456789abcdef" for character in value):
        raise ValueError("invalid_sha256")
    return value


def canonical_json(value) -> bytes:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")


def percentile(values, fraction: float) -> float:
    """Linear interpolation between order statistics; deterministic for small samples."""
    ordered = sorted(values)
    if not ordered or not 0 <= fraction <= 1:
        raise ValueError("invalid_percentile_request")
    position = fraction * (len(ordered) - 1)
    lower = math.floor(position)
    upper = min(lower + 1, len(ordered) - 1)
    return float(ordered[lower] + (ordered[upper] - ordered[lower]) * (position - lower))


class RuntimeArtifacts(ContractModel):
    llama_cpp_build: Literal["b11221"]
    executable_sha256: StrictStr
    model_sha256: StrictStr
    projector_sha256: StrictStr

    _hashes = field_validator("executable_sha256", "model_sha256", "projector_sha256")(_sha256)


class RuntimeValues(ContractModel):
    context_tokens: StrictInt
    image_min_tokens: StrictInt
    image_max_tokens: StrictInt
    output_tokens: StrictInt
    pdf_dpi: StrictInt
    alternative_pdf_dpi: StrictInt
    vision_gpu: StrictBool
    cache_type: StrictStr

    def profile(self) -> RuntimeProfile:
        return RuntimeProfile(**self.model_dump())


class CoreValues(ContractModel):
    processing_budget_s: StrictFloat
    image_long_side: StrictInt
    matching_long_side: StrictInt
    call_timeout_s: StrictFloat
    release_timeout_s: StrictFloat
    maximum_response_bytes: StrictInt
    top_logprobs: StrictInt
    max_pixels: StrictInt
    quota_bytes: StrictInt
    free_reserve_bytes: StrictInt


class PromptIdentity(ContractModel):
    version: StrictStr = Field(min_length=1)
    sha256: StrictStr

    _hash = field_validator("sha256")(_sha256)


class Dependencies(ContractModel):
    """Interpreter and installed distributions that render pages, parse replies or reach the runtime."""

    python: StrictStr
    httpx: StrictStr
    pillow: StrictStr
    pypdfium2: StrictStr
    pydantic: StrictStr
    pydantic_core: StrictStr


class Environment(ContractModel):
    """What the checkout, installed dependencies and pinned runtime determine; compared before freeze and benchmark."""

    code_sha256: StrictStr
    prompt: PromptIdentity
    runtime_artifacts: RuntimeArtifacts
    runtime_profile: RuntimeValues
    core: CoreValues
    dependencies: Dependencies

    _hash = field_validator("code_sha256")(_sha256)


class FrozenPolicy(ContractModel):
    min_token_probability: StrictFloat | None = Field(ge=0, le=1, allow_inf_nan=False)
    check_alternate_view: StrictBool
    check_declared_format: StrictBool
    matching_margin: StrictFloat = Field(ge=0, le=1, allow_inf_nan=False)

    def verification(self) -> VerificationPolicy:
        return VerificationPolicy(
            min_token_probability=self.min_token_probability,
            check_alternate_view=self.check_alternate_view,
            check_declared_format=self.check_declared_format,
        )


class CalibrationProvenance(ContractModel):
    tuning_manifest_sha256: StrictStr
    calibration_report_sha256: StrictStr
    point_index: StrictInt = Field(ge=0)
    selection_rule: StrictStr = Field(min_length=1)

    _hashes = field_validator("tuning_manifest_sha256", "calibration_report_sha256")(_sha256)


class PageTimes(ContractModel):
    """Seconds per page of one page kind for admission control; measured, not an SLA."""

    kind: Literal["png", "jpeg", "pdf"]
    count: StrictInt = Field(ge=1)
    p5: StrictFloat = Field(ge=0, allow_inf_nan=False)
    p50: StrictFloat = Field(ge=0, allow_inf_nan=False)
    p95: StrictFloat = Field(ge=0, allow_inf_nan=False)


class FrozenConfiguration(ContractModel):
    schema_version: Literal[1]
    created_at: datetime
    runtime_artifacts: RuntimeArtifacts
    runtime_profile: RuntimeValues
    core: CoreValues
    prompt: PromptIdentity
    policy: FrozenPolicy
    corpus_manifest_schema_version: Literal[1]
    calibration: CalibrationProvenance
    code_sha256: StrictStr
    dependencies: Dependencies
    page_times: tuple[PageTimes, ...] = ()

    _hash = field_validator("code_sha256")(_sha256)

    @field_validator("created_at")
    @classmethod
    def utc(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset().total_seconds() != 0:
            raise ValueError("utc_timestamp_required")
        return value

    @field_validator("page_times")
    @classmethod
    def unique_kinds(cls, value):
        if len({item.kind for item in value}) != len(value):
            raise ValueError("duplicate_page_kind")
        return value

    def environment(self) -> Environment:
        return Environment(code_sha256=self.code_sha256, prompt=self.prompt, runtime_artifacts=self.runtime_artifacts,
                           runtime_profile=self.runtime_profile, core=self.core, dependencies=self.dependencies)

    def core_settings(self, *, keep_trace: bool = False) -> CoreSettings:
        return core_settings(self.policy.verification(), self.policy.matching_margin,
                             compute_alternate_view=self.policy.check_alternate_view, keep_trace=keep_trace,
                             runtime=self.runtime_profile.profile(), core=self.core)


def _defaults(kind) -> dict:
    return {item.name: item.default for item in fields(kind) if item.default is not MISSING}


def runtime_artifacts() -> RuntimeArtifacts:
    defaults = _defaults(RuntimeFiles)
    return RuntimeArtifacts(llama_cpp_build=LLAMA_CPP_BUILD, executable_sha256=defaults["executable_sha256"],
                            model_sha256=defaults["model_sha256"], projector_sha256=defaults["projector_sha256"])


def default_core_values() -> CoreValues:
    """Pinned CoreSettings, AdapterSettings and PreparationLimits defaults of this checkout."""
    core, adapter = _defaults(CoreSettings), _defaults(AdapterSettings)
    limits = asdict(core["preparation"])
    return CoreValues(processing_budget_s=float(core["processing_budget_s"]), image_long_side=core["image_long_side"],
                      matching_long_side=core["matching_long_side"], call_timeout_s=float(adapter["call_timeout_s"]),
                      release_timeout_s=float(adapter["release_timeout_s"]),
                      maximum_response_bytes=adapter["maximum_response_bytes"], top_logprobs=adapter["top_logprobs"],
                      **limits)


def core_settings(policy: VerificationPolicy, matching_margin: float, *, compute_alternate_view: bool,
                  keep_trace: bool, runtime: RuntimeProfile | None = None,
                  core: CoreValues | None = None) -> CoreSettings:
    """The only way the runner builds core settings, so they match the recorded values."""
    core = core or default_core_values()
    return CoreSettings(
        runtime=runtime or RuntimeProfile(), verification=policy, matching_margin=float(matching_margin),
        processing_budget_s=core.processing_budget_s, image_long_side=core.image_long_side,
        matching_long_side=core.matching_long_side,
        preparation=PreparationLimits(max_pixels=core.max_pixels, quota_bytes=core.quota_bytes,
                                      free_reserve_bytes=core.free_reserve_bytes),
        compute_alternate_view=compute_alternate_view, keep_trace=keep_trace,
    )


def current_code_hash(directory: Path | None = None) -> str:
    """SHA-256 over the LF-normalized bytes of recognition/*.py, sorted by file name.

    Each file contributes its length-prefixed name and length-prefixed bytes, so
    renaming or moving bytes between files changes the hash.
    """
    directory = directory or Path(__file__).resolve().parent
    digest = hashlib.sha256()
    for path in sorted(directory.glob("*.py"), key=lambda item: item.name):
        data = path.read_bytes().replace(b"\r\n", b"\n")
        name = path.name.encode("utf-8")
        digest.update(len(name).to_bytes(4, "big") + name + len(data).to_bytes(8, "big") + data)
    return digest.hexdigest()


def prompt_identity() -> PromptIdentity:
    """Version and SHA-256 over the prompt constants and the prompt/schema builder source."""
    payload = {
        "constants": {name: getattr(prompts, name) for name in PROMPT_CONSTANTS},
        "sources": {name: inspect.getsource(getattr(prompts, name)).replace("\r\n", "\n")
                    for name in PROMPT_BUILDERS},
    }
    return PromptIdentity(version=prompts.PROMPT_VERSION, sha256=hashlib.sha256(canonical_json(payload)).hexdigest())


def dependency_versions() -> Dependencies:
    """Python version and installed versions of the distributions that shape model input or decisions."""

    def version(name: str) -> str:
        try:
            return metadata.version(name)
        except metadata.PackageNotFoundError:
            return "not_installed"

    return Dependencies(python=".".join(str(part) for part in sys.version_info[:3]), httpx=version("httpx"),
                        pillow=version("Pillow"), pypdfium2=version("pypdfium2"), pydantic=version("pydantic"),
                        pydantic_core=version("pydantic-core"))


def current_environment() -> Environment:
    return Environment(code_sha256=current_code_hash(), prompt=prompt_identity(),
                       runtime_artifacts=runtime_artifacts(),
                       runtime_profile=RuntimeValues(**asdict(RuntimeProfile())), core=default_core_values(),
                       dependencies=dependency_versions())


def environment_mismatches(expected: Environment, actual: Environment) -> tuple[str, ...]:
    checks = (("code_sha256", "code_hash_mismatch"), ("prompt", "prompt_mismatch"),
              ("runtime_artifacts", "runtime_artifacts_mismatch"), ("runtime_profile", "runtime_profile_mismatch"),
              ("core", "core_settings_mismatch"), ("dependencies", "dependency_versions_mismatch"))
    return tuple(code for name, code in checks if getattr(expected, name) != getattr(actual, name))


def behavior_sha256(config: FrozenConfiguration) -> str:
    """Identity of what a benchmark run measures: environment and policy.

    Unlike the file hash it excludes the creation time, calibration provenance and
    admission page times, so freezing the same point again yields the same identity.
    """
    payload = {"environment": config.environment().model_dump(mode="json"),
               "policy": config.policy.model_dump(mode="json")}
    return hashlib.sha256(canonical_json(payload)).hexdigest()


def page_time_summary(samples: dict[str, list[float]]) -> tuple[PageTimes, ...]:
    return tuple(
        PageTimes(kind=kind, count=len(values), p5=percentile(values, 0.05), p50=percentile(values, 0.5),
                  p95=percentile(values, 0.95))
        for kind, values in sorted(samples.items()) if values
    )


def configuration_bytes(config: FrozenConfiguration) -> bytes:
    return canonical_json(config.model_dump(mode="json"))


def configuration_sha256(config: FrozenConfiguration) -> str:
    return hashlib.sha256(configuration_bytes(config)).hexdigest()


def write_frozen(config: FrozenConfiguration, path: Path) -> str:
    """Write canonical bytes; never overwrite an existing frozen configuration."""
    path.parent.mkdir(parents=True, exist_ok=True)
    try:
        with path.open("xb") as stream:
            stream.write(configuration_bytes(config))
    except FileExistsError:
        raise ConfigError("frozen_configuration_exists") from None
    return configuration_sha256(config)


def load_frozen(path: Path) -> tuple[FrozenConfiguration, str]:
    """Validate a frozen configuration and return it with its canonical SHA-256."""
    try:
        config = FrozenConfiguration.model_validate_json(path.read_bytes())
    except (OSError, ValueError, ValidationError):
        raise ConfigError("invalid_frozen_configuration") from None
    return config, configuration_sha256(config)
