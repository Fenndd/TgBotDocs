"""Ordered delivery: explicit retry only, window, cancellation and uncertainty."""

import asyncio

from aiogram.exceptions import TelegramBadRequest, TelegramRetryAfter
from aiogram.methods import SendMessage
import pytest

from tgbotdocs.application.delivery import CANCELLED, COMPLETE, FAILED, UNCERTAIN, deliver
from tgbotdocs.application.rendering import MessagePart

METHOD = SendMessage(chat_id=1, text="x")
PARTS = tuple(MessagePart(f"Part {i}") for i in range(1, 4))


class Transport:
    def __init__(self, behaviour=None):
        self.sent, self.attempts, self.behaviour = [], [], behaviour or {}

    async def send(self, owner, text, **kwargs):
        self.attempts.append(text)
        action = self.behaviour.get(text)
        if isinstance(action, list):
            action = action.pop(0) if action else None
        if isinstance(action, Exception):
            raise action
        if isinstance(action, asyncio.Event):
            await action.wait()
        self.sent.append(text)


async def test_parts_in_order_and_retry_after_is_retried_without_duplicates():
    transport = Transport({"Part 2": [TelegramRetryAfter(METHOD, "flood", 0), None]})
    assert await deliver(transport, 1, PARTS, window_s=5, attempts=3, current=lambda: True) == COMPLETE
    assert transport.sent == ["Part 1", "Part 2", "Part 3"]
    assert transport.attempts == ["Part 1", "Part 2", "Part 2", "Part 3"]


async def test_retry_limit_refusal_and_window_end_are_not_success():
    exhausted = Transport({"Part 1": [TelegramRetryAfter(METHOD, "flood", 0)] * 3})
    assert await deliver(exhausted, 1, PARTS, window_s=5, attempts=3, current=lambda: True) == FAILED
    assert exhausted.sent == []
    too_long = Transport({"Part 1": [TelegramRetryAfter(METHOD, "flood", 10)]})
    assert await deliver(too_long, 1, PARTS, window_s=5, attempts=3, current=lambda: True) == FAILED
    refused = Transport({"Part 2": TelegramBadRequest(METHOD, "bad")})
    assert await deliver(refused, 1, PARTS, window_s=5, attempts=3, current=lambda: True) == FAILED
    assert refused.sent == ["Part 1"]
    hanging = Transport({"Part 1": asyncio.Event()})
    assert await deliver(hanging, 1, PARTS, window_s=0.05, attempts=3, current=lambda: True) == UNCERTAIN


async def test_cancellation_stops_new_parts_and_lets_a_started_send_finish():
    gate = asyncio.Event()
    transport = Transport({"Part 2": gate})
    task = asyncio.create_task(deliver(transport, 1, PARTS, window_s=5, attempts=3, current=lambda: True))
    async with asyncio.timeout(2):
        while transport.attempts[-1:] != ["Part 2"]:  # noqa: ASYNC110 - bounded observation
            await asyncio.sleep(0.001)
    task.cancel()
    await asyncio.sleep(0.01)
    assert not task.done()
    gate.set()
    with pytest.raises(asyncio.CancelledError):
        await task
    assert transport.sent == ["Part 1", "Part 2"]
    committed = Transport()
    assert await deliver(committed, 1, PARTS, window_s=5, attempts=3, current=lambda: False) == CANCELLED
    assert committed.attempts == []
