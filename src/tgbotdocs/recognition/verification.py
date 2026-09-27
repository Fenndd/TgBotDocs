"""Configurable V1–V3 signals. These rules abstain; they do not certify accuracy."""
from __future__ import annotations

from datetime import datetime
import math
import re

from pydantic import Field, StrictFloat, model_validator

from .contracts import (
    ContractModel, ExtractionProfile, FieldResult, FormatValidator, MatchingResponse,
    ScalarField, normalize_value, resolve_matching, validate_field_result,
)


class VerificationPolicy(ContractModel):
    min_token_probability: StrictFloat | None = Field(default=None, ge=0, le=1)
    check_alternate_view: bool = False
    check_declared_format: bool = True

    @model_validator(mode="after")
    def finite_threshold(self):
        if self.min_token_probability is not None and not math.isfinite(self.min_token_probability):
            raise ValueError("probability threshold must be finite")
        return self


def _probabilities(values: tuple[float, ...]) -> None:
    if not values or any(type(value) not in (int, float) or isinstance(value, bool) or not math.isfinite(value)
                         or not 0 <= value <= 1 for value in values):
        raise ValueError("raw probabilities must be nonempty finite values in [0, 1]")


def format_valid(value: str | bool, validator: FormatValidator) -> bool:
    if not isinstance(value, str):
        return False
    if validator.kind == "calendar_date":
        interpretations = set()
        for pattern in ("%Y-%m-%d",) + validator.date_formats:
            try:
                interpretations.add(datetime.strptime(value, pattern).date())
            except ValueError:
                pass
        return len(interpretations) == 1
    if validator.kind == "iso_code":
        return value in validator.allowlist
    if validator.kind == "luhn":
        if not re.fullmatch(r"[0-9]{2,}", value):
            return False
        total = 0
        for index, digit in enumerate(reversed(value)):
            number = int(digit)
            if index % 2:
                number *= 2
                if number > 9:
                    number -= 9
            total += number
        return total % 10 == 0
    # IBAN's declared format admits presentation spaces, but not arbitrary punctuation.
    compact = value.replace(" ", "").upper()
    if not re.fullmatch(r"[A-Z]{2}[0-9]{2}[A-Z0-9]{11,30}", compact):
        return False
    remainder = 0
    for character in compact[4:] + compact[:4]:
        for digit in str(ord(character) - 55) if character.isalpha() else character:
            remainder = (remainder * 10 + int(digit)) % 97
    return remainder == 1


def _downgrade(result: FieldResult, status: str) -> FieldResult:
    return FieldResult(field_id=result.field_id, status=status,
                       raw_value=result.raw_value if status == "invalid" else None,
                       source_pages=result.source_pages)


def verify_field(field: ScalarField, result: FieldResult, *, policy: VerificationPolicy,
                 raw_token_probabilities: tuple[float, ...] | None = None,
                 alternate: FieldResult | None = None) -> FieldResult:
    validate_field_result(field, result, result.source_pages)
    if result.status != "extracted":
        return result
    if policy.check_declared_format and field.validator and not format_valid(result.raw_value, field.validator):
        return _downgrade(result, "invalid")
    if policy.min_token_probability is not None:
        if raw_token_probabilities is None:
            return _downgrade(result, "ambiguous")
        _probabilities(raw_token_probabilities)
        if min(raw_token_probabilities) < policy.min_token_probability:
            return _downgrade(result, "ambiguous")
    if policy.check_alternate_view:
        if alternate is None or alternate.status != "extracted":
            return _downgrade(result, "ambiguous")
        validate_field_result(field, alternate, result.source_pages)
        try:
            original_value, alternate_value = normalize_value(field, result.raw_value), normalize_value(field, alternate.raw_value)
        except ValueError:
            return _downgrade(result, "ambiguous")
        if type(original_value) is not type(alternate_value) or original_value != alternate_value:
            return _downgrade(result, "ambiguous")
    return result


def verify_matching(response: MatchingResponse, snapshots: tuple[ExtractionProfile, ...], *,
                    candidate_probabilities: tuple[float, ...] | None, minimum_margin: float) -> MatchingResponse:
    """Scores must be measured raw candidate probabilities from the adapter, in snapshot order."""
    selected = resolve_matching(response, snapshots)
    if type(minimum_margin) not in (float, int) or isinstance(minimum_margin, bool) or not math.isfinite(minimum_margin) or not 0 <= minimum_margin <= 1:
        raise ValueError("an explicit finite matching margin in [0, 1] is required")
    if selected is None:
        return response
    if candidate_probabilities is None:
        return MatchingResponse(status="uncertain", type_description=response.type_description)
    _probabilities(candidate_probabilities)
    if len(candidate_probabilities) != len(snapshots):
        raise ValueError("probabilities must correspond exactly to per-call profile indices")
    selected_score = candidate_probabilities[response.profile_index - 1]
    alternatives = candidate_probabilities[:response.profile_index - 1] + candidate_probabilities[response.profile_index:]
    runner_up = max(alternatives, default=0.0)
    if selected_score <= runner_up or selected_score - runner_up <= minimum_margin:
        return MatchingResponse(status="uncertain", type_description=response.type_description)
    return response
