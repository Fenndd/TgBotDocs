import pytest

from tgbotdocs.recognition.contracts import ExtractionProfile, FieldResult, FormatValidator, MatchingResponse, ScalarField
from tgbotdocs.recognition.verification import VerificationPolicy, format_valid, verify_field, verify_matching


def field(validator=None, type="text"):
    return ScalarField(id="value", label="Value", description="Requested", type=type, validator=validator)


def reading(value="Value", status="extracted"):
    return FieldResult(field_id="value", status=status, raw_value=value, source_pages=(1,))


def snapshots():
    return tuple(ExtractionProfile(id=f"p{i}", owner="u", version=i, name="Custom", description="Custom", original_instruction="Read", fields=(field(),)) for i in (1, 2))


def test_v1_uses_weakest_raw_probability_and_missing_signal_abstains():
    policy = VerificationPolicy(min_token_probability=0.8)
    assert verify_field(field(), reading(), policy=policy, raw_token_probabilities=(0.99, 0.79, 0.99)).status == "ambiguous"
    assert verify_field(field(), reading(), policy=policy, raw_token_probabilities=(0.8, 0.9)).status == "extracted"
    assert verify_field(field(), reading(), policy=policy).status == "ambiguous"
    for probabilities in ((), (float("nan"),), (1.1,), (True,)):
        with pytest.raises(ValueError, match="probabilities"):
            verify_field(field(), reading(), policy=policy, raw_token_probabilities=probabilities)


def test_v2_requires_alternate_view_reading_and_never_votes_or_corrects_unicode():
    policy = VerificationPolicy(check_alternate_view=True)
    assert verify_field(field(), reading("A"), policy=policy, alternate=reading("B")).status == "ambiguous"
    assert verify_field(field(), reading("é"), policy=policy, alternate=reading("e\u0301")).status == "ambiguous"
    assert verify_field(field(type="number"), reading("10.00"), policy=policy, alternate=reading("0010")).status == "extracted"
    assert verify_field(field(), reading(), policy=policy).status == "ambiguous"
    with pytest.raises(ValueError, match="requested"):
        verify_field(field(), reading(), policy=policy, alternate=FieldResult(field_id="other", status="extracted", raw_value="Value", source_pages=(1,)))


@pytest.mark.parametrize("validator,valid,invalid", [
    (FormatValidator(kind="calendar_date"), "2024-02-29", "2023-02-29"),
    (FormatValidator(kind="luhn"), "79927398713", "79927398714"),
    (FormatValidator(kind="iban"), "GB82 WEST 1234 5698 7654 32", "GB83 WEST 1234 5698 7654 32"),
    (FormatValidator(kind="iso_code", allowlist=("SK", "UA")), "SK", "XX"),
])
def test_v3_profile_declared_validation_only(validator, valid, invalid):
    assert format_valid(valid, validator) and not format_valid(invalid, validator)
    policy = VerificationPolicy()
    assert verify_field(field(validator), reading(valid), policy=policy).status == "extracted"
    failed = verify_field(field(validator), reading(invalid), policy=policy)
    assert failed.status == "invalid" and failed.raw_value == invalid and failed.accepted_value is None
    assert verify_field(field(), reading(invalid), policy=policy).status == "extracted"


def test_date_is_calendar_valid_without_expiration_or_ambiguous_order_guessing():
    validator = FormatValidator(kind="calendar_date", date_formats=("%d/%m/%Y", "%m/%d/%Y"))
    assert not format_valid("01/02/2026", validator)
    assert format_valid("2000-01-01", validator)
    assert not format_valid("2026-01-01 trailing", validator)
    assert verify_field(field(validator, "date"), reading("01/02/2026"), policy=VerificationPolicy()).status == "invalid"
    assert verify_field(field(validator, "date"), reading("01/02/2026"),
                        policy=VerificationPolicy(check_declared_format=False, check_alternate_view=True),
                        alternate=reading("01/02/2026")).status == "ambiguous"


@pytest.mark.parametrize("status", ["missing", "unreadable", "ambiguous", "invalid"])
def test_verification_never_upgrades_model_status(status):
    original = reading(None, status)
    assert verify_field(field(FormatValidator(kind="luhn")), original,
                        policy=VerificationPolicy(min_token_probability=0.99, check_alternate_view=True),
                        raw_token_probabilities=(1.0,), alternate=reading("79927398713")) is original


def test_matching_requires_measured_per_candidate_margin_and_is_strictly_downgrade_only():
    profiles = snapshots()
    matched = MatchingResponse(status="matched", profile_index=1)
    assert verify_matching(matched, profiles, candidate_probabilities=(0.9, 0.1), minimum_margin=0.2) is matched
    assert verify_matching(matched, profiles, candidate_probabilities=(0.5, 0.5), minimum_margin=0.0).status == "uncertain"
    assert verify_matching(matched, profiles, candidate_probabilities=(0.1, 0.9), minimum_margin=0.2).status == "uncertain"
    assert verify_matching(matched, profiles, candidate_probabilities=None, minimum_margin=0.2).status == "uncertain"
    uncertain = MatchingResponse(status="uncertain")
    assert verify_matching(uncertain, profiles, candidate_probabilities=(0.99, 0.01), minimum_margin=0.2) is uncertain
    with pytest.raises(ValueError, match="exactly"):
        verify_matching(matched, profiles, candidate_probabilities=(0.9,), minimum_margin=0.2)
    with pytest.raises(ValueError, match="explicit"):
        verify_matching(matched, profiles, candidate_probabilities=(0.9, 0.1), minimum_margin=float("nan"))
