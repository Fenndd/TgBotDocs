"""Local-only streaming llama.cpp client with explicit release and token evidence.

No request, response, image, token, or exception body is logged. A successful HTTP
response is not a successful contract or recognition result.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
import json
import math
from typing import Awaitable, Callable
from urllib.parse import urlsplit

import httpx


class ModelError(Exception):
    """Content-free failure suitable for a technical event code."""

    def __init__(self, code: str):
        self.code = code
        super().__init__(code)


@dataclass(frozen=True, repr=False)
class TokenScore:
    data: bytes
    logprob: float
    alternatives: tuple[tuple[bytes, float], ...] = ()


@dataclass(frozen=True, repr=False)
class ModelReply:
    text: str
    tokens: tuple[TokenScore, ...]
    probabilities_aligned: bool
    prompt_tokens: int | None
    generated_tokens: int | None
    duration_s: float

    def probabilities(self, pointer: tuple[str | int, ...]) -> tuple[float, ...] | None:
        """Raw probabilities of all generated tokens overlapping a JSON value.

        JSON pointers, rather than substring search, distinguish repeated values,
        escaped Unicode, table cells, and field names containing the same text.
        Missing or unaligned metadata fails closed for V1.
        """
        if not self.probabilities_aligned:
            return None
        try:
            _, spans = parse_json_with_spans(self.text)
            left, right = spans[pointer]
        except ValueError, KeyError:
            return None
        offset, scores = 0, []
        for token in self.tokens:
            end = offset + len(token.data)
            if offset < right and end > left:
                scores.append(math.exp(token.logprob))
            offset = end
        return tuple(scores) if scores else None

    def candidate_probabilities(self, pointer: tuple[str | int, ...], count: int) -> tuple[float, ...] | None:
        """Exact single-token candidate-index evidence, or no usable margin.

        Never infer missing alternatives, use self-reported confidence, or replace
        a multi-token index by a probability for only its first token.
        """
        if not self.probabilities_aligned or count < 1:
            return None
        try:
            _, spans = parse_json_with_spans(self.text)
            left, right = spans[pointer]
        except ValueError, KeyError:
            return None
        offset = 0
        for token in self.tokens:
            end = offset + len(token.data)
            if offset <= left < right <= end:
                selected = self.text.encode("utf-8")[left:right]
                prefix, suffix = token.data[: left - offset], token.data[right - offset :]
                distribution = dict(token.alternatives)
                distribution[token.data] = token.logprob
                keys = [prefix + str(index).encode("ascii") + suffix for index in range(1, count + 1)]
                if any(key not in distribution for key in keys) or selected not in [
                    str(n).encode() for n in range(1, count + 1)
                ]:
                    return None
                return tuple(math.exp(distribution[key]) for key in keys)
            offset = end
        return None


def parse_json_with_spans(text: str) -> tuple[object, dict[tuple, tuple[int, int]]]:
    """Strict JSON decoder retaining value spans in UTF-8 bytes; reject duplicates."""
    decoder = json.JSONDecoder(parse_constant=lambda _: (_ for _ in ()).throw(ValueError("nonfinite_json")))
    spans: dict[tuple, tuple[int, int]] = {}

    def whitespace(index):
        while index < len(text) and text[index] in " \t\r\n":
            index += 1
        return index

    def parse(index, pointer):
        if len(pointer) > 32:
            raise ValueError("json_nesting_limit")
        index = whitespace(index)
        start = index
        if index >= len(text):
            raise ValueError("incomplete_json")
        if text[index] == "{":
            result = {}
            index = whitespace(index + 1)
            if index < len(text) and text[index] == "}":
                index += 1
            else:
                while True:
                    key, index = decoder.raw_decode(text, index)
                    if not isinstance(key, str) or key in result:
                        raise ValueError("invalid_or_duplicate_key")
                    index = whitespace(index)
                    if index >= len(text) or text[index] != ":":
                        raise ValueError("invalid_object")
                    result[key], index = parse(index + 1, pointer + (key,))
                    index = whitespace(index)
                    if index < len(text) and text[index] == "}":
                        index += 1
                        break
                    if index >= len(text) or text[index] != ",":
                        raise ValueError("invalid_object")
                    index = whitespace(index + 1)
        elif text[index] == "[":
            result = []
            index = whitespace(index + 1)
            if index < len(text) and text[index] == "]":
                index += 1
            else:
                while True:
                    value, index = parse(index, pointer + (len(result),))
                    result.append(value)
                    index = whitespace(index)
                    if index < len(text) and text[index] == "]":
                        index += 1
                        break
                    if index >= len(text) or text[index] != ",":
                        raise ValueError("invalid_array")
                    index = whitespace(index + 1)
        else:
            result, index = decoder.raw_decode(text, index)
        spans[pointer] = (len(text[:start].encode("utf-8")), len(text[:index].encode("utf-8")))
        return result, index

    result, end = parse(0, ())
    if whitespace(end) != len(text):
        raise ValueError("trailing_json_content")
    return result, spans


def _token_bytes(token: dict) -> bytes:
    raw = token.get("bytes")
    if isinstance(raw, list) and all(type(value) is int and 0 <= value <= 255 for value in raw):
        return bytes(raw)
    text = token.get("token")
    if isinstance(text, str):
        return text.encode("utf-8")
    raise ValueError("invalid_token_metadata")


def _logprob(value):
    if type(value) not in (float, int) or not math.isfinite(value) or value > 0:
        raise ValueError("invalid_probability_metadata")
    return float(value)


async def _bounded_lines(response: httpx.Response, limit: int):
    buffer = bytearray()
    wire_bytes = 0
    async for chunk in response.aiter_bytes():
        wire_bytes += len(chunk)
        if wire_bytes > limit * 20:
            raise ModelError("runtime_response_limit")
        buffer.extend(chunk)
        while b"\n" in buffer:
            line, _, remainder = buffer.partition(b"\n")
            buffer = bytearray(remainder)
            if len(line) > limit:
                raise ModelError("runtime_response_limit")
            try:
                yield line.rstrip(b"\r").decode("utf-8")
            except UnicodeDecodeError:
                raise ModelError("runtime_invalid_stream") from None
        if len(buffer) > limit:
            raise ModelError("runtime_response_limit")
    if buffer:
        try:
            yield buffer.decode("utf-8")
        except UnicodeDecodeError:
            raise ModelError("runtime_invalid_stream") from None


@dataclass(frozen=True)
class AdapterSettings:
    endpoint: str = "http://127.0.0.1:18081"
    api_key: str = field(default="", repr=False)
    call_timeout_s: float = 300.0
    release_timeout_s: float = 10.0
    maximum_response_bytes: int = 2 * 1024 * 1024
    top_logprobs: int = 20

    def __post_init__(self):
        address = urlsplit(self.endpoint)
        if (
            address.scheme != "http"
            or address.hostname not in ("127.0.0.1", "::1")
            or address.username
            or address.password
            or address.path not in ("", "/")
            or address.query
            or address.fragment
        ):
            raise ValueError("Only a numeric loopback HTTP runtime endpoint is permitted")
        if not self.api_key or any(
            not math.isfinite(t) or t <= 0 for t in (self.call_timeout_s, self.release_timeout_s)
        ):
            raise ValueError("Runtime key and positive deadlines are required")
        if self.maximum_response_bytes < 1 or not 1 <= self.top_logprobs <= 100:
            raise ValueError("Invalid response/probability bounds")


class ModelAdapter:
    """One in-flight call; release is confirmed before the lock permits another."""

    def __init__(
        self,
        settings: AdapterSettings,
        *,
        restart: Callable[[], Awaitable[None]] | None = None,
        transport: httpx.AsyncBaseTransport | None = None,
    ):
        self.settings = settings
        self.restart = restart
        self._lock = asyncio.Lock()
        self._available = True
        self._client = httpx.AsyncClient(
            base_url=settings.endpoint,
            trust_env=False,
            follow_redirects=False,
            headers={"Authorization": f"Bearer {settings.api_key}"},
            timeout=None,
            transport=transport,
        )

    async def close(self):
        await self._client.aclose()

    def request_body(self, messages: list[dict], schema: dict, output_tokens: int) -> dict:
        return {
            "messages": messages,
            "response_format": {
                "type": "json_schema",
                "json_schema": {"name": "recognition", "strict": True, "schema": schema},
            },
            "stream": True,
            "temperature": 0,
            "seed": 42,
            "max_tokens": output_tokens,
            "logprobs": True,
            "top_logprobs": self.settings.top_logprobs,
            "post_sampling_probs": False,
            "cache_prompt": False,
        }

    async def count_input_tokens(
        self, messages: list[dict], schema: dict, *, output_tokens: int, remaining_budget_s: float
    ) -> int:
        """Pinned b11221 placeholder path: same template/images, no model inference.

        Accept only prepared, pixel-bounded images. The runtime decodes them for
        dimensions, even though this endpoint does not run the vision encoder.
        """
        if not math.isfinite(remaining_budget_s) or remaining_budget_s <= 0:
            raise ModelError("processing_budget_exhausted")
        async with self._lock:
            if not self._available:
                raise ModelError("runtime_unavailable")
            try:
                async with asyncio.timeout(min(self.settings.call_timeout_s, remaining_budget_s)):
                    response = await self._client.post(
                        "/v1/chat/completions/input_tokens",
                        json=self.request_body(messages, schema, output_tokens),
                    )
                    if response.status_code != 200 or len(response.content) > 65536:
                        raise ModelError("runtime_token_count_failed")
                    data = response.json()
                    count = data.get("input_tokens") if isinstance(data, dict) else None
                    if type(count) is not int or count < 1:
                        raise ModelError("runtime_token_count_failed")
                    return count
            except TimeoutError:
                raise ModelError("runtime_timeout") from None
            except httpx.HTTPError, ValueError:
                raise ModelError("runtime_token_count_failed") from None

    async def _idle(self) -> bool:
        try:
            async with asyncio.timeout(self.settings.release_timeout_s):
                while True:
                    try:
                        response = await self._client.get("/slots", timeout=1)
                        if response.status_code == 200 and len(response.content) <= 65536:
                            slots = response.json()
                            if (
                                isinstance(slots, list)
                                and len(slots) == 1
                                and isinstance(slots[0], dict)
                                and slots[0].get("is_processing") is False
                            ):
                                return True
                    except httpx.HTTPError, ValueError:
                        pass
                    await asyncio.sleep(min(0.05, self.settings.release_timeout_s))
        except TimeoutError:
            return False
        return False

    async def _release(self):
        self._available = False
        if await self._idle():
            self._available = True
            return
        if self.restart is not None:
            try:
                await self.restart()
            except Exception:
                raise ModelError("runtime_restart_failed") from None
            if await self._idle():
                self._available = True
                return
        raise ModelError("runtime_release_failed")

    async def _finish_release(self):
        # Repeated cancellation cannot release the call lock while cleanup still
        # owns the server slot. Preserve cancellation after the cleanup finishes.
        task = asyncio.create_task(self._release())
        cancelled = False
        while not task.done():
            try:
                await asyncio.shield(task)
            except asyncio.CancelledError:
                cancelled = True
        task.result()
        if cancelled:
            raise asyncio.CancelledError

    async def generate(
        self, messages: list[dict], schema: dict, *, output_tokens: int, remaining_budget_s: float
    ) -> ModelReply:
        if (
            type(output_tokens) is not int
            or output_tokens < 1
            or not math.isfinite(remaining_budget_s)
            or remaining_budget_s <= 0
        ):
            raise ModelError("processing_budget_exhausted")
        async with self._lock:
            if not self._available:
                raise ModelError("runtime_unavailable")
            begin = asyncio.get_running_loop().time()
            request = self.request_body(messages, schema, output_tokens)
            # The child task owns the response context and its closure. A parent
            # cancellation is forwarded exactly once, then drained under shield;
            # repeated cancellation must not interrupt HTTPX response.aclose().
            call = asyncio.create_task(self._consume(request, begin))
            try:
                async with asyncio.timeout(min(self.settings.call_timeout_s, remaining_budget_s)):
                    return await asyncio.shield(call)
            except TimeoutError:
                raise ModelError("runtime_timeout") from None
            finally:
                if not call.done():
                    call.cancel()
                    while not call.done():
                        try:
                            await asyncio.shield(call)
                        except asyncio.CancelledError:
                            pass
                        except Exception:
                            break
                if not call.cancelled():
                    call.exception()  # retrieve an error if cancellation raced completion
                await self._finish_release()

    async def _consume(self, request: dict, begin: float) -> ModelReply:
        pieces: list[str] = []
        tokens: list[TokenScore] = []
        finish, timings, content_bytes = None, {}, 0
        metadata_valid = True
        try:
            async with self._client.stream("POST", "/v1/chat/completions", json=request) as response:
                if response.status_code != 200:
                    raise ModelError("runtime_http_error")
                async for line in _bounded_lines(response, self.settings.maximum_response_bytes):
                    if len(line.encode("utf-8")) > self.settings.maximum_response_bytes:
                        raise ModelError("runtime_response_limit")
                    if not line.startswith("data: ") or line == "data: [DONE]":
                        continue
                    try:
                        event = json.loads(line[6:])
                        if not isinstance(event, dict) or "error" in event:
                            raise ValueError("runtime_error_event")
                        if event.get("timings") is not None:
                            timing_data = event["timings"]
                            if not isinstance(timing_data, dict):
                                raise ValueError("invalid_timings")
                            if any(
                                type(timing_data.get(key)) is not int or timing_data[key] < 0
                                for key in ("prompt_n", "predicted_n")
                                if key in timing_data
                            ):
                                raise ValueError("invalid_timings")
                            timings = timing_data
                        choices = event.get("choices", [])
                        if len(choices) > 1:
                            raise ValueError("multiple_choices")
                        for choice in choices:
                            delta = choice.get("delta", {})
                            if delta.get("tool_calls") or delta.get("function_call"):
                                raise ValueError("unexpected_tool_call")
                            content = delta.get("content")
                            if content:
                                if not isinstance(content, str):
                                    raise ValueError("invalid_content")
                                content_bytes += len(content.encode("utf-8"))
                                if content_bytes > self.settings.maximum_response_bytes:
                                    raise ModelError("runtime_response_limit")
                                pieces.append(content)
                            for token in (choice.get("logprobs") or {}).get("content", []):
                                try:
                                    alternatives = tuple(
                                        (_token_bytes(t), _logprob(t.get("logprob")))
                                        for t in token.get("top_logprobs", [])
                                    )
                                    tokens.append(
                                        TokenScore(
                                            _token_bytes(token), _logprob(token.get("logprob")), alternatives
                                        )
                                    )
                                except ValueError, TypeError, AttributeError:
                                    metadata_valid = False
                            finish = choice.get("finish_reason") or finish
                    except ValueError, TypeError, AttributeError:
                        raise ModelError("runtime_invalid_stream") from None
            if finish != "stop":
                raise ModelError("runtime_incomplete_output")
            text = "".join(pieces)
            aligned = (
                bool(tokens)
                and metadata_valid
                and b"".join(token.data for token in tokens) == text.encode("utf-8")
            )
            return ModelReply(
                text,
                tuple(tokens),
                aligned,
                timings.get("prompt_n"),
                timings.get("predicted_n"),
                asyncio.get_running_loop().time() - begin,
            )
        except httpx.HTTPError:
            raise ModelError("runtime_transport_error") from None
