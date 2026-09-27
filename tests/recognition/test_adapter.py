import asyncio
import json
import math

import httpx
import pytest

from tgbotdocs.recognition.adapter import (
    AdapterSettings,
    ModelAdapter,
    ModelError,
    ModelReply,
    TokenScore,
    parse_json_with_spans,
)


def settings(**values):
    return AdapterSettings(api_key="synthetic-test-key", release_timeout_s=0.05, **values)


def sse(content, *, finish="stop", tokens=None):
    event = {
        "choices": [
            {"delta": {"content": content}, "finish_reason": finish, "logprobs": {"content": tokens or []}}
        ]
    }
    return ("data: " + json.dumps(event) + "\n\ndata: [DONE]\n\n").encode()


class Stream(httpx.AsyncByteStream):
    def __init__(self, payload, delay=0):
        self.payload, self.delay = payload, delay
        self.closed = False

    async def __aiter__(self):
        if self.delay:
            await asyncio.sleep(self.delay)
        yield self.payload

    async def aclose(self):
        self.closed = True


def transport(stream, *, idle=True, requests=None):
    async def handle(request):
        if requests is not None:
            requests.append(request)
        if request.url.path == "/slots":
            return httpx.Response(200, json=[{"is_processing": not idle}])
        return httpx.Response(200, stream=stream)

    return httpx.MockTransport(handle)


@pytest.mark.parametrize(
    "endpoint",
    [
        "https://example.com",
        "http://localhost:8080",
        "http://127.0.0.1.evil/",
        "http://user:password@127.0.0.1",
        "http://127.0.0.1/path",
        "http://0.0.0.0",
    ],
)
def test_endpoint_cannot_send_documents_outside_numeric_loopback(endpoint):
    with pytest.raises(ValueError):
        AdapterSettings(endpoint=endpoint, api_key="test")


def test_spans_distinguish_duplicate_values_and_escaped_unicode():
    text = '{"a":"same","b":["same","\\u0627"]}'
    parsed, spans = parse_json_with_spans(text)
    assert parsed == {"a": "same", "b": ["same", "ا"]}
    assert spans[("a",)] != spans[("b", 0)]
    left, right = spans[("b", 1)]
    assert text.encode()[left:right] == b'"\\u0627"'


@pytest.mark.parametrize(
    "text", ['{"a":1,"a":2}', '{"a":NaN}', '{"a":Infinity}', "{} trailing", "[1,]", '{"a":1,}']
)
def test_invalid_json_never_becomes_evidence(text):
    with pytest.raises(ValueError):
        parse_json_with_spans(text)


def test_weakest_value_token_can_be_found_without_matching_another_equal_value():
    segments = [('{"a":', 1), ('"same"', 0.8), (',"b":', 1), ('"same"', 0.1), ("}", 1)]
    text = "".join(token for token, _ in segments)
    tokens = tuple(TokenScore(token.encode(), math.log(p)) for token, p in segments)
    result = ModelReply(text, tokens, True, 20, 5, 1)
    assert result.probabilities(("a",)) == pytest.approx((0.8,))
    assert result.probabilities(("b",)) == pytest.approx((0.1,))
    assert ModelReply(text, tokens, False, None, None, 1).probabilities(("a",)) is None


def test_matching_margin_requires_complete_candidate_token_evidence():
    token = TokenScore(b"1", math.log(0.8), ((b"1", math.log(0.8)), (b"2", math.log(0.1))))
    reply = ModelReply(
        '{"profile_index":1}',
        (TokenScore(b'{"profile_index":', 0), token, TokenScore(b"}", 0)),
        True,
        0,
        0,
        0,
    )
    assert reply.candidate_probabilities(("profile_index",), 2) == pytest.approx((0.8, 0.1))
    assert reply.candidate_probabilities(("profile_index",), 3) is None


async def test_stream_success_closes_before_idle_and_never_sends_resumable_header():
    requests = []
    stream = Stream(sse('{"value":"ok"}'))
    client = ModelAdapter(settings(), transport=transport(stream, requests=requests))
    try:
        reply = await client.generate([], {}, output_tokens=50, remaining_budget_s=1)
        assert reply.text == '{"value":"ok"}' and stream.closed
        assert [r.url.path for r in requests] == ["/v1/chat/completions", "/slots"]
        body = json.loads(requests[0].content)
        assert body["post_sampling_probs"] is False and body["stream"] is True
        assert "x-conversation-id" not in requests[0].headers
        assert not reply.probabilities_aligned
    finally:
        await client.close()


async def test_deadline_closes_stream_then_checks_idle():
    stream = Stream(sse("{}"), delay=1)
    client = ModelAdapter(settings(), transport=transport(stream))
    try:
        with pytest.raises(ModelError, match="runtime_timeout"):
            await client.generate([], {}, output_tokens=50, remaining_budget_s=0.02)
        assert stream.closed
    finally:
        await client.close()


async def test_cancellation_closes_stream_and_preserves_cancelled_error():
    stream = Stream(sse("{}"), delay=1)
    requests = []
    client = ModelAdapter(settings(), transport=transport(stream, requests=requests))
    task = asyncio.create_task(client.generate([], {}, output_tokens=50, remaining_budget_s=3))
    await asyncio.sleep(0.01)
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    assert stream.closed and requests[-1].url.path == "/slots"
    await client.close()


async def test_unconfirmed_release_blocks_next_call():
    client = ModelAdapter(settings(), transport=transport(Stream(sse("{}")), idle=False))
    try:
        with pytest.raises(ModelError, match="runtime_release_failed"):
            await client.generate([], {}, output_tokens=50, remaining_budget_s=1)
        with pytest.raises(ModelError, match="runtime_unavailable"):
            await client.generate([], {}, output_tokens=50, remaining_budget_s=1)
    finally:
        await client.close()


async def test_repeated_cancel_cannot_interrupt_stream_close_or_release_lock_early():
    closing, allow_close = asyncio.Event(), asyncio.Event()

    class SlowClose(Stream):
        async def aclose(self):
            closing.set()
            await allow_close.wait()
            self.closed = True

    stream = SlowClose(sse("{}"), delay=60)
    requests = []
    client = ModelAdapter(settings(), transport=transport(stream, requests=requests))
    try:
        task = asyncio.create_task(client.generate([], {}, output_tokens=50, remaining_budget_s=3))
        await asyncio.sleep(0.01)
        task.cancel()
        await closing.wait()
        task.cancel()
        await asyncio.sleep(0)
        assert not task.done() and not stream.closed
        assert all(r.url.path != "/slots" for r in requests)
        allow_close.set()
        with pytest.raises(asyncio.CancelledError):
            await task
        assert stream.closed and requests[-1].url.path == "/slots"
    finally:
        await client.close()


async def test_release_deadline_is_absolute_and_restart_is_required():
    restarted = False

    async def restart():
        nonlocal restarted
        restarted = True

    async def handle(request):
        if request.url.path == "/slots":
            if not restarted:
                await asyncio.sleep(0.2)
            return httpx.Response(200, json=[{"is_processing": False}])
        return httpx.Response(200, stream=Stream(sse("{}")))

    client = ModelAdapter(settings(), restart=restart, transport=httpx.MockTransport(handle))
    try:
        await client.generate([], {}, output_tokens=50, remaining_budget_s=1)
        assert restarted
    finally:
        await client.close()


async def test_malformed_slot_metadata_fails_closed_then_restarts():
    restarted = False

    async def restart():
        nonlocal restarted
        restarted = True

    async def handle(request):
        if request.url.path == "/slots":
            return httpx.Response(200, json=[{"is_processing": False}] if restarted else [None])
        return httpx.Response(200, stream=Stream(sse("{}")))

    client = ModelAdapter(settings(), restart=restart, transport=httpx.MockTransport(handle))
    try:
        await client.generate([], {}, output_tokens=50, remaining_budget_s=1)
        assert restarted
    finally:
        await client.close()


async def test_malformed_timings_are_fixed_error_without_leaking_body():
    payload = b'data: {"timings":"private text"}\n\n'
    client = ModelAdapter(settings(), transport=transport(Stream(payload)))
    try:
        with pytest.raises(ModelError, match="^runtime_invalid_stream$"):
            await client.generate([], {}, output_tokens=50, remaining_budget_s=1)
    finally:
        await client.close()


@pytest.mark.parametrize(
    "payload,code",
    [
        (sse("{}", finish="length"), "runtime_incomplete_output"),
        (b"x" * 2048, "runtime_response_limit"),
        (b"data: invalid\n\n", "runtime_invalid_stream"),
    ],
)
async def test_stream_failures_are_content_free_and_release_slot(payload, code):
    client = ModelAdapter(settings(maximum_response_bytes=1024), transport=transport(Stream(payload)))
    try:
        with pytest.raises(ModelError) as failure:
            await client.generate([], {}, output_tokens=50, remaining_budget_s=1)
        assert failure.value.code == code and str(failure.value) == code
    finally:
        await client.close()
