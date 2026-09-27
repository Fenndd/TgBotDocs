import asyncio
from contextlib import asynccontextmanager
import json
import math

from PIL import Image
import pytest

from tgbotdocs.recognition.adapter import ModelError, ModelReply, TokenScore
from tgbotdocs.recognition.contracts import ExtractionProfile, ScalarField, ListField, FormatValidator
from tgbotdocs.recognition.core import CoreSettings, ProcessingBudget, RecognitionCore, verify_batch
from tgbotdocs.recognition.prompts import parse_batch
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
        self.calls, self.counts = [], []
        self.image_tokens = image_tokens

    async def count_input_tokens(self, messages, schema, **_):
        image_count = sum(p["type"] == "image_url" for p in messages[1]["content"])
        self.counts.append(image_count)
        return 500 + image_count * self.image_tokens

    async def generate(self, messages, schema, **kwargs):
        self.calls.append(messages)
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
    checked = verify_batch(parse_batch(json.dumps(original), profile, (1, 2)), reply(original), profile,
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
    checked = verify_batch(parse_batch(json.dumps(data), profile, (1,)), reply(data), profile, VerificationPolicy(), None)
    assert checked.lists[0].status == "unresolved" and checked.lists[0].reason == "invalid"


async def test_deeply_nested_invalid_json_gets_one_controlled_retry(tmp_path, profile):
    files, scratch = images(tmp_path, 1)
    adapter = FakeAdapter(['[' * 1500 + ']' * 1500, batch((1,))])
    result = await RecognitionCore(adapter, settings()).recognize(files, (profile,), scratch=scratch, selected_profile=profile)
    assert result.metrics["contract_retries"] == 1 and result.recognition.outcome == "complete"
