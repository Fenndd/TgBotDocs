import asyncio
from contextlib import asynccontextmanager
import json
import math

from PIL import Image
import pytest

from tgbotdocs.recognition.adapter import ModelError, ModelReply, TokenScore
from tgbotdocs.recognition.contracts import ExtractionProfile, ScalarField, ListField, FormatValidator
from tgbotdocs.recognition.core import (BatchTrace, CoreSettings, JobObserver, JobTrace, ProcessingBudget,
                                        RecognitionCore, StageFailure, decide,
                                        probability_map, verify_batch)
from tgbotdocs.recognition.prompts import matching_schema, parse_batch
from tgbotdocs.recognition.runtime import RuntimeProfile
from tgbotdocs.recognition.verification import VerificationPolicy


@pytest.fixture
def profile():
    return ExtractionProfile(
        id="private-stored-id",
        owner="private-owner",
        version=1,
        name="Synthetic card",
        description="A fictional test card",
        original_instruction="Read the identifier",
        fields=(
            ScalarField(id="identifier", label="Identifier", description="Printed identifier", type="text"),
        ),
    )


def batch(ids, value="AB-001", status="extracted", membership="yes"):
    return {
        "fields": {"identifier": {"s": status, "v": value, "p": [ids[0]] if value is not None else []}},
        "lists": {},
        "membership": {str(p): membership for p in ids},
    }


def reply(data, *, probabilities=True):
    text = data if isinstance(data, str) else json.dumps(data)
    tokens = tuple(TokenScore(c.encode(), math.log(0.99)) for c in text) if probabilities else ()
    return ModelReply(text, tokens, probabilities, 100, len(tokens), 0.001)


class FakeAdapter:
    def __init__(self, answers, image_tokens=1000):
        self.answers = list(answers)
        self.calls, self.counts, self.schemas = [], [], []
        self.image_tokens = image_tokens

    async def count_input_tokens(self, messages, schema, **_):
        image_count = sum(p["type"] == "image_url" for p in messages[1]["content"])
        self.counts.append(image_count)
        return 500 + image_count * self.image_tokens

    async def generate(self, messages, schema, **kwargs):
        self.calls.append(messages)
        self.schemas.append(schema)
        answer = self.answers.pop(0)
        if isinstance(answer, Exception):
            raise answer
        return answer if isinstance(answer, ModelReply) else reply(answer)


def images(tmp_path, count):
    files = []
    for index in range(count):
        path = tmp_path / f"input-{index}.png"
        image = Image.new("RGB", (80, 100), "white")
        image.putpixel((index, index), (0, 0, 0))
        image.save(path)
        files.append(path)
    scratch = tmp_path / "scratch"
    scratch.mkdir()
    return tuple(files), scratch


def settings(**values):
    return CoreSettings(
        runtime=RuntimeProfile(), verification=VerificationPolicy(), matching_margin=0.1, **values
    )


async def test_all_pages_lazy_packed_merged_and_temporary_files_removed(tmp_path, profile):
    files, scratch = images(tmp_path, 3)
    adapter = FakeAdapter([batch((1, 2)), batch((3,))])
    core = RecognitionCore(adapter, settings())
    result = await core.recognize(files, (profile,), scratch=scratch, selected_profile=profile)
    assert result.recognition.outcome == "complete"
    assert result.recognition.fields[0].source_pages == (1, 3)
    assert result.metrics["batches"] == 2 and result.metrics["pages"] == 3
    assert adapter.counts == [1, 2, 3, 1]
    assert not list(scratch.iterdir()) and all(p.exists() for p in files)
    wire = json.dumps(adapter.calls)
    assert profile.id not in wire and profile.owner not in wire


async def test_late_mixed_document_discards_earlier_accepted_values(tmp_path, profile):
    files, scratch = images(tmp_path, 3)
    adapter = FakeAdapter([batch((1, 2)), batch((3,), membership="no")])
    result = await RecognitionCore(adapter, settings()).recognize(
        files, (profile,), scratch=scratch, selected_profile=profile
    )
    assert result.matching.status == "mixed" and result.recognition is None and result.profile is None
    assert not list(scratch.iterdir())


async def test_conflicting_batches_abstain_without_voting(tmp_path, profile):
    files, scratch = images(tmp_path, 3)
    adapter = FakeAdapter([batch((1, 2)), batch((3,), "AB-007")])
    result = await RecognitionCore(adapter, settings()).recognize(
        files, (profile,), scratch=scratch, selected_profile=profile
    )
    assert result.recognition.fields[0].status == "ambiguous"
    assert result.recognition.fields[0].accepted_value is None


async def test_matching_requires_probability_margin_and_uses_immutable_snapshot(tmp_path, profile):
    files, scratch = images(tmp_path, 1)
    matched = {"status": "matched", "profile_index": 1, "type_description": None}
    adapter = FakeAdapter([matched, batch((1,))])
    result = await RecognitionCore(adapter, settings()).recognize(files, (profile,), scratch=scratch)
    assert result.profile is profile and not result.user_selected
    assert result.recognition.outcome == "complete"
    adapter = FakeAdapter([reply(matched, probabilities=False)])
    result = await RecognitionCore(adapter, settings()).recognize(files, (profile,), scratch=scratch)
    assert result.matching.status == "uncertain" and result.recognition is None
    assert len(adapter.calls) == 1


async def test_one_contract_retry_does_not_expose_arbitrary_model_text(tmp_path, profile):
    files, scratch = images(tmp_path, 1)
    adapter = FakeAdapter(["private invalid text", batch((1,))])
    result = await RecognitionCore(adapter, settings()).recognize(
        files, (profile,), scratch=scratch, selected_profile=profile
    )
    assert result.metrics["contract_retries"] == 1
    assert "previous response violated" in adapter.calls[1][1]["content"][0]["text"]
    assert "private invalid text" not in json.dumps(adapter.calls)
    adapter = FakeAdapter(["private invalid text", "still invalid"])
    with pytest.raises(ModelError, match="^recognition_contract_violation$"):
        await RecognitionCore(adapter, settings()).recognize(
            files, (profile,), scratch=scratch, selected_profile=profile
        )
    assert len(adapter.calls) == 2 and not list(scratch.iterdir())


async def test_single_page_context_overflow_refuses_before_generation(tmp_path, profile):
    files, scratch = images(tmp_path, 1)
    adapter = FakeAdapter([], image_tokens=4000)
    with pytest.raises(ModelError, match="profile_or_page_exceeds_context"):
        await RecognitionCore(adapter, settings()).recognize(
            files, (profile,), scratch=scratch, selected_profile=profile
        )
    assert not adapter.calls and not list(scratch.iterdir())


async def test_different_view_disagreement_downgrades_and_cleans(tmp_path, profile):
    files, scratch = images(tmp_path, 1)
    adapter = FakeAdapter([batch((1,)), batch((1,), "AB-007")])
    config = CoreSettings(
        runtime=RuntimeProfile(),
        verification=VerificationPolicy(check_alternate_view=True),
        matching_margin=0.1,
        compute_alternate_view=True,
    )
    result = await RecognitionCore(adapter, config).recognize(
        files, (profile,), scratch=scratch, selected_profile=profile
    )
    assert result.recognition.fields[0].status == "ambiguous"
    primary = adapter.calls[0][1]["content"][-1]["image_url"]["url"]
    other = adapter.calls[1][1]["content"][-1]["image_url"]["url"]
    assert primary != other and not list(scratch.iterdir())


async def test_queue_wait_is_excluded_from_processing_budget(tmp_path, profile):
    files, scratch = images(tmp_path, 1)

    @asynccontextmanager
    async def slow_turn():
        await asyncio.sleep(0.1)
        yield

    adapter = FakeAdapter([batch((1,))])
    result = await RecognitionCore(adapter, settings(processing_budget_s=5), turn=slow_turn).recognize(
        files, (profile,), scratch=scratch, selected_profile=profile
    )
    assert result.recognition.outcome == "complete"
    budget = ProcessingBudget(0.02)
    await asyncio.sleep(0.03)
    assert budget.remaining == 0.02
    with budget.charge():
        await asyncio.sleep(0.03)
        with pytest.raises(ModelError, match="processing_budget_exhausted"):
            _ = budget.remaining


@pytest.mark.parametrize(
    "mutation",
    [
        lambda data: data.update(extra="unrequested"),
        lambda data: data["fields"].update(another={"s": "missing", "v": None, "p": []}),
        lambda data: data["fields"]["identifier"].update(p=[999]),
        lambda data: data["membership"].update({"999": "yes"}),
    ],
)
def test_wire_contract_rejects_extra_fields_and_impossible_sources(profile, mutation):
    data = batch((1,))
    mutation(data)
    with pytest.raises(ValueError):
        parse_batch(json.dumps(data), profile, (1,))


def test_alternate_page_disagreement_is_abstention_not_unhandled_error(profile):
    original, other = batch((1, 2)), batch((1, 2))
    other["fields"]["identifier"]["p"] = [2]
    parsed = parse_batch(json.dumps(original), profile, (1, 2))
    checked = verify_batch(parsed, probability_map(reply(original), parsed), profile,
                           VerificationPolicy(check_alternate_view=True), parse_batch(json.dumps(other), profile, (1, 2)))
    assert checked.fields[0].status == "ambiguous"


def table_profile(profile, columns):
    return profile.model_copy(update={"fields": (ListField(id="rows", label="Rows", description="Rows", columns=columns),)})


def table(cells):
    return {"fields": {}, "membership": {"1": "yes"}, "lists": {"rows": {"status": "complete",
        "enumeration_complete": True, "reason": None, "rows": [{"cells": cells, "pages": [1],
        "continues_previous": False, "continues_next": False}]}}}


def test_invalid_number_cell_downgrades_container_and_preserves_other_cell(profile):
    profile = table_profile(profile, (
        ScalarField(id="name", label="Name", description="Name", type="text"),
        ScalarField(id="amount", label="Amount", description="Amount", type="number")))
    data = table({"name": {"s": "extracted", "v": "Paper", "p": [1]},
                  "amount": {"s": "extracted", "v": "1,23", "p": [1]}})
    parsed = parse_batch(json.dumps(data), profile, (1,))
    assert parsed.lists[0].status == "partial"
    assert parsed.lists[0].rows[0].cells[0].accepted_value == "Paper"
    assert parsed.lists[0].rows[0].cells[1].status == "invalid"


def test_only_invalid_cell_uses_invalid_list_reason(profile):
    profile = table_profile(profile, (ScalarField(id="code", label="Code", description="Luhn code", type="text",
                                                  validator=FormatValidator(kind="luhn")),))
    data = table({"code": {"s": "extracted", "v": "79927398714", "p": [1]}})
    parsed = parse_batch(json.dumps(data), profile, (1,))
    checked = verify_batch(parsed, probability_map(reply(data), parsed), profile, VerificationPolicy(), None)
    assert checked.lists[0].status == "unresolved" and checked.lists[0].reason == "invalid"


async def test_deeply_nested_invalid_json_gets_one_controlled_retry(tmp_path, profile):
    files, scratch = images(tmp_path, 1)
    adapter = FakeAdapter(['[' * 1500 + ']' * 1500, batch((1,))])
    result = await RecognitionCore(adapter, settings()).recognize(files, (profile,), scratch=scratch, selected_profile=profile)
    assert result.metrics["contract_retries"] == 1 and result.recognition.outcome == "complete"


# --- Policy-independent model calls, traces and exact replay -------------------------------


def weak_reply(data, probability):
    text = json.dumps(data)
    tokens = tuple(TokenScore(c.encode(), math.log(probability)) for c in text)
    return ModelReply(text, tokens, True, 100, len(tokens), 0.001)


def matching_reply(index, probabilities):
    """Matching reply whose index token carries measured alternatives for every candidate."""
    text = json.dumps({"status": "matched", "profile_index": index, "type_description": None})
    position = text.index('"profile_index": ') + len('"profile_index": ')
    tokens = []
    for offset, character in enumerate(text):
        if offset == position:
            alternatives = tuple((str(n).encode(), math.log(p)) for n, p in enumerate(probabilities, 1) if n != index)
            tokens.append(TokenScore(character.encode(), math.log(probabilities[index - 1]), alternatives))
        else:
            tokens.append(TokenScore(character.encode(), math.log(0.99)))
    return ModelReply(text, tuple(tokens), True, 100, len(tokens), 0.001)


def second(profile):
    return profile.model_copy(update={"id": "private-other-id", "name": "Other synthetic card"})


def list_profile(profile):
    return table_profile(profile, (ScalarField(id="code", label="Code", description="Row code", type="text"),))


def list_batch(page, value, *, previous=False, following=False, membership="yes"):
    return {"fields": {}, "membership": {str(page): membership}, "lists": {"rows": {
        "status": "complete", "enumeration_complete": True, "reason": None,
        "rows": [{"cells": {"code": {"s": "extracted", "v": value, "p": [page]}}, "pages": [page],
                  "continues_previous": previous, "continues_next": following}]}}}


def test_alternate_enforcement_requires_computing_alternate_readings():
    with pytest.raises(ValueError, match="alternate"):
        CoreSettings(runtime=RuntimeProfile(), verification=VerificationPolicy(check_alternate_view=True),
                     matching_margin=0.1)


async def test_model_calls_are_identical_across_policies_and_continuation_uses_parsed_rows(tmp_path, profile):
    profile = list_profile(profile)
    files, scratch = images(tmp_path, 2)
    runs = {}
    for name, policy in (("permissive", VerificationPolicy()), ("strict", VerificationPolicy(min_token_probability=0.9))):
        adapter = FakeAdapter([weak_reply(list_batch(1, "ROW-7", following=True), 0.5),
                               reply(list_batch(2, "ROW-7", previous=True))], image_tokens=2000)
        core = RecognitionCore(adapter, CoreSettings(runtime=RuntimeProfile(), verification=policy, matching_margin=0.1))
        runs[name] = (await core.recognize(files, (profile,), scratch=scratch, selected_profile=profile), adapter)
    assert json.dumps(runs["permissive"][1].calls) == json.dumps(runs["strict"][1].calls)
    boundary = json.loads(runs["strict"][1].calls[1][1]["content"][0]["text"].split("\n", 1)[1])["previous_boundary"]
    assert boundary == {"rows": {"cells": {"code": {"s": "extracted", "v": "ROW-7", "p": [1]}}, "pages": [1],
                                 "continues_previous": False, "continues_next": True}}
    assert runs["permissive"][0].recognition.lists[0].rows[0].cells[0].accepted_value == "ROW-7"
    assert runs["strict"][0].recognition.lists[0].rows[0].cells[0].accepted_value is None
    assert not list(scratch.iterdir())


POLICIES = [VerificationPolicy(min_token_probability=v1, check_alternate_view=v2)
            for v1 in (None, 0.9) for v2 in (False, True)]


@pytest.mark.parametrize("margin", [0.0, 0.3, 0.6])
async def test_replayed_trace_reproduces_production_decision_for_every_point(tmp_path, profile, margin):
    snapshots = (profile, second(profile))
    files, scratch = images(tmp_path, 1)

    def answers(alternate=True):
        items = [matching_reply(1, (0.7, 0.2)), weak_reply(batch((1,)), 0.8)]
        return items + ([batch((1,), "AB-007")] if alternate else [])

    collector = RecognitionCore(FakeAdapter(answers()), CoreSettings(
        runtime=RuntimeProfile(), verification=VerificationPolicy(), matching_margin=0.0,
        compute_alternate_view=True, keep_trace=True))
    trace = (await collector.recognize(files, snapshots, scratch=scratch)).trace
    outcomes = set()
    for policy in POLICIES:
        replayed = decide(trace, snapshots, policy=policy, matching_margin=margin)
        for compute in {True, policy.check_alternate_view}:
            production = await RecognitionCore(FakeAdapter(answers(compute)), CoreSettings(
                runtime=RuntimeProfile(), verification=policy, matching_margin=margin,
                compute_alternate_view=compute)).recognize(files, snapshots, scratch=scratch)
            assert production.matching == replayed.matching and production.profile == replayed.profile
            assert production.recognition == replayed.recognition
        outcomes.add((replayed.matching.status, replayed.recognition and replayed.recognition.outcome))
    if margin < 0.5:
        # Only the permissive point accepts the weak, disagreeing reading.
        assert outcomes == {("matched", "complete"), ("matched", "failed")}
    else:
        assert outcomes == {("uncertain", None)}


async def test_alternate_rejection_stops_only_when_the_policy_enforces_it(tmp_path, profile):
    profile = list_profile(profile)
    files, scratch = images(tmp_path, 2)
    answers = [list_batch(1, "ROW-1"), list_batch(1, "ROW-1", membership="no"),
               list_batch(2, "ROW-2"), list_batch(2, "ROW-2")]
    enforced = FakeAdapter(list(answers), image_tokens=2000)
    result = await RecognitionCore(enforced, CoreSettings(
        runtime=RuntimeProfile(), verification=VerificationPolicy(check_alternate_view=True), matching_margin=0.1,
        compute_alternate_view=True, keep_trace=True)).recognize(files, (profile,), scratch=scratch,
                                                                 selected_profile=profile)
    assert result.matching.status == "mixed" and result.recognition is None and len(enforced.calls) == 2
    with pytest.raises(ValueError, match="trace_incomplete_for_policy"):
        decide(result.trace, (profile,), policy=VerificationPolicy(), matching_margin=0.1)
    collected = FakeAdapter(list(answers), image_tokens=2000)
    result = await RecognitionCore(collected, CoreSettings(
        runtime=RuntimeProfile(), verification=VerificationPolicy(), matching_margin=0.1,
        compute_alternate_view=True, keep_trace=True)).recognize(files, (profile,), scratch=scratch,
                                                                 selected_profile=profile)
    assert result.recognition.outcome == "complete" and len(collected.calls) == 4
    assert decide(result.trace, (profile,), policy=VerificationPolicy(check_alternate_view=True),
                  matching_margin=0.1).matching.status == "mixed"
    assert not list(scratch.iterdir())


async def test_replay_refuses_policies_the_trace_cannot_support(tmp_path, profile):
    snapshots = (profile, second(profile))
    files, scratch = images(tmp_path, 1)
    core = RecognitionCore(FakeAdapter([matching_reply(1, (0.7, 0.2)), batch((1,))]), CoreSettings(
        runtime=RuntimeProfile(), verification=VerificationPolicy(), matching_margin=0.0, keep_trace=True))
    trace = (await core.recognize(files, snapshots, scratch=scratch)).trace
    assert not trace.batches[0].alternate_attempted
    with pytest.raises(ValueError, match="trace_lacks_alternate_view"):
        decide(trace, snapshots, policy=VerificationPolicy(check_alternate_view=True), matching_margin=0.0)
    strict = RecognitionCore(FakeAdapter([matching_reply(1, (0.7, 0.2))]), CoreSettings(
        runtime=RuntimeProfile(), verification=VerificationPolicy(), matching_margin=0.6, keep_trace=True))
    result = await strict.recognize(files, snapshots, scratch=scratch)
    assert result.matching.status == "uncertain" and result.trace.matching.status == "matched"
    assert decide(result.trace, snapshots, policy=VerificationPolicy(), matching_margin=0.9).matching.status == "uncertain"
    with pytest.raises(ValueError, match="trace_incomplete_for_policy"):
        decide(result.trace, snapshots, policy=VerificationPolicy(), matching_margin=0.0)


async def test_zero_candidate_profiles_cannot_express_a_selection(tmp_path):
    schema = matching_schema(0)
    assert "matched" not in schema["properties"]["status"]["enum"]
    assert schema["properties"]["profile_index"] == {"type": "null"}
    assert matching_schema(2)["properties"]["profile_index"]["anyOf"][0]["maximum"] == 2
    files, scratch = images(tmp_path, 1)
    adapter = FakeAdapter([{"status": "no_profile", "profile_index": None, "type_description": "Synthetic form"}])
    result = await RecognitionCore(adapter, settings()).recognize(files, (), scratch=scratch)
    assert result.matching.status == "no_profile" and result.recognition is None
    assert adapter.schemas == [schema]


async def test_trace_is_opt_in_and_call_records_are_content_free(tmp_path, profile):
    files, scratch = images(tmp_path, 1)
    result = await RecognitionCore(FakeAdapter([batch((1,))]), settings()).recognize(
        files, (profile,), scratch=scratch, selected_profile=profile)
    assert result.trace is None
    assert [(c.kind, c.stage, c.batch, c.pages) for c in result.calls] == [
        ("token_count", "extraction", 0, (1,)), ("extraction", "extraction", 0, (1,))]
    assert result.metrics["model_calls"] == 1
    assert set(result.metrics["call_seconds"]) == {"token_count", "matching", "extraction", "alternate"}
    serialized = json.dumps([c.model_dump(mode="json") for c in result.calls]) + json.dumps(result.metrics)
    assert "AB-001" not in serialized and profile.name not in serialized
    kept = await RecognitionCore(FakeAdapter([batch((1,))]), settings(keep_trace=True)).recognize(
        files, (profile,), scratch=scratch, selected_profile=profile)
    assert kept.trace.page_kinds == ("png",) and kept.trace.manual_profile is profile
    assert kept.trace.batches[0].probabilities[("fields", "identifier", "v")]


async def test_observer_keeps_content_free_progress_of_a_failed_job(tmp_path, profile):
    files, scratch = images(tmp_path, 1)
    observer = JobObserver()
    with pytest.raises(ModelError, match="recognition_contract_violation"):
        await RecognitionCore(FakeAdapter(["private invalid text", "still invalid"]), settings()).recognize(
            files, (profile,), scratch=scratch, selected_profile=profile, observer=observer)
    assert [c.kind for c in observer.calls] == ["token_count", "extraction", "extraction"]
    assert observer.contract_retries == 1 and observer.page_kinds == ("png",) and observer.preparation_s > 0


async def test_failure_after_a_weak_match_is_raised_only_where_extraction_happens(tmp_path, profile):
    snapshots = (profile, second(profile))
    files, scratch = images(tmp_path, 1)
    observer = JobObserver()
    collector = RecognitionCore(FakeAdapter([matching_reply(1, (0.7, 0.2)), "invalid", "still invalid"]), CoreSettings(
        runtime=RuntimeProfile(), verification=VerificationPolicy(), matching_margin=0.0,
        compute_alternate_view=True, keep_trace=True))
    with pytest.raises(ModelError, match="^recognition_contract_violation$"):
        await collector.recognize(files, snapshots, scratch=scratch, observer=observer)
    trace = observer.trace
    assert not trace.batches and trace.failure.code == "recognition_contract_violation"
    # A margin above 0.5 stops at "uncertain" and never makes the failing call.
    assert decide(trace, snapshots, policy=VerificationPolicy(), matching_margin=0.6).matching.status == "uncertain"
    with pytest.raises(ModelError, match="^recognition_contract_violation$"):
        decide(trace, snapshots, policy=VerificationPolicy(), matching_margin=0.3)
    assert not list(scratch.iterdir())


def recorded(profile, *, pages=1, alternate_error=None, failure=None):
    """Trace of a manual-profile job: 100 s setup, batch 0 with 500 s primary and 1500 s alternate."""
    data = batch((1,))
    parsed = parse_batch(json.dumps(data), profile, (1,))
    item = BatchTrace(parsed, probability_map(reply(data), parsed), None if alternate_error else parsed, True,
                      primary_s=500.0, alternate_s=1500.0, alternate_error=alternate_error)
    return JobTrace(page_ids=tuple(range(1, pages + 1)), page_kinds=("png",) * pages, matching=None,
                    candidate_probabilities=None, manual_profile=profile, batches=(item,), calls=(),
                    preparation_s=0.0, setup_s=100.0, failure=failure)


V2_OFF, V2_ON = VerificationPolicy(), VerificationPolicy(check_alternate_view=True)


def replayed(trace, profile, policy, budget=1800.0):
    return decide(trace, (profile,), policy=policy, matching_margin=0.0, processing_budget_s=budget)


def test_replay_times_out_each_policy_on_its_own_calls(profile):
    trace = recorded(profile)
    assert replayed(trace, profile, V2_OFF).recognition.outcome == "complete"
    with pytest.raises(ModelError, match="^processing_budget_exhausted$"):
        replayed(trace, profile, V2_ON)
    assert replayed(trace, profile, V2_ON, budget=2500.0).recognition.outcome == "complete"
    # The recording job made the alternate calls, so their time counts for it.
    with pytest.raises(ModelError, match="^processing_budget_exhausted$"):
        decide(trace, (profile,), policy=V2_OFF, matching_margin=0.0, processing_budget_s=1800.0,
               alternate_calls=True)


def test_recorded_failures_apply_only_where_they_are_determined(profile):
    exhausted = StageFailure("model", "processing_budget_exhausted", 100.0, 2200.0)
    trace = recorded(profile, pages=2, failure=exhausted)
    # The recording job ran out of its extended budget partly on alternate calls V2-off skips.
    with pytest.raises(ValueError, match="trace_undetermined_for_policy"):
        replayed(trace, profile, V2_OFF)
    with pytest.raises(ModelError, match="^processing_budget_exhausted$"):
        replayed(trace, profile, V2_ON)
    violation = StageFailure("model", "recognition_contract_violation", 10.0, 2110.0)
    with pytest.raises(ModelError, match="^recognition_contract_violation$"):
        replayed(recorded(profile, pages=2, failure=violation), profile, V2_OFF)
    # A skipped alternate call that failed at runtime level may have caused the later failure.
    crashed = StageFailure("model", "runtime_unavailable", 1500.0, 2100.0)
    trace = recorded(profile, pages=2, alternate_error=crashed, failure=violation)
    with pytest.raises(ValueError, match="trace_undetermined_for_policy"):
        replayed(trace, profile, V2_OFF, budget=5000.0)
    with pytest.raises(ModelError, match="^runtime_unavailable$"):
        replayed(trace, profile, V2_ON, budget=5000.0)
    invalid = StageFailure("model", "recognition_contract_violation", 1500.0, 2100.0)
    with pytest.raises(ModelError, match="^recognition_contract_violation$"):
        replayed(recorded(profile, pages=2, alternate_error=invalid, failure=violation), profile, V2_OFF,
                 budget=5000.0)
    assert replayed(recorded(profile, alternate_error=crashed), profile, V2_OFF).recognition.outcome == "complete"


async def test_alternate_failure_is_recorded_and_fails_only_an_enforcing_job(tmp_path, profile):
    files, scratch = images(tmp_path, 1)
    answers = [batch((1,), "AB-001"), "invalid alternate", "invalid alternate again"]
    collected = await RecognitionCore(FakeAdapter(list(answers)), CoreSettings(
        runtime=RuntimeProfile(), verification=VerificationPolicy(), matching_margin=0.1,
        compute_alternate_view=True, keep_trace=True)).recognize(files, (profile,), scratch=scratch,
                                                                 selected_profile=profile)
    assert collected.recognition.fields[0].accepted_value == "AB-001"
    assert collected.trace.batches[0].alternate_error.code == "recognition_contract_violation"
    with pytest.raises(ModelError, match="^recognition_contract_violation$"):
        await RecognitionCore(FakeAdapter(list(answers)), CoreSettings(
            runtime=RuntimeProfile(), verification=VerificationPolicy(check_alternate_view=True),
            matching_margin=0.1, compute_alternate_view=True)).recognize(files, (profile,), scratch=scratch,
                                                                        selected_profile=profile)
    assert not list(scratch.iterdir())


def test_matching_describes_the_document_before_choosing_and_sees_field_labels(profile):
    from tgbotdocs.recognition import prompts

    schema = prompts.matching_schema(2)
    # Generation follows key order: the description grounds the status and index.
    assert list(schema["properties"]) == ["type_description", "status", "profile_index"]
    assert schema["properties"]["type_description"] == {"type": "string"}
    text = prompts.matching_text((profile,), (1,))
    assert '"fields":["Identifier"]' in text and "private-stored-id" not in text and "private-owner" not in text
