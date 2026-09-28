"""Ordered result delivery (OPERATIONS, Delivery and Retries; STATE_MACHINE delivering).

Parts are sent in order within one delivery window. Only an explicit Telegram
``retry_after`` refusal is retried, because such a message was not accepted; any
other failure ends delivery as failed (Telegram refused the part) or uncertain (the
part may have arrived). A part is never sent twice as though it had not arrived.
After cancellation no new part or retry starts; a send already in flight is allowed
to finish, and cancellation then propagates.
"""

import asyncio

from aiogram.exceptions import TelegramAPIError, TelegramForbiddenError, TelegramNetworkError, TelegramRetryAfter

from .transport import SendSkipped

COMPLETE, FAILED, UNCERTAIN, BLOCKED, CANCELLED = "complete", "failed", "uncertain", "blocked", "cancelled"


async def _finish_started(send):
    """Let an in-flight request settle even if cancellation repeats."""
    while not send.done():
        try:
            await asyncio.shield(send)
        except asyncio.CancelledError:
            continue
        except Exception:
            break
    if not send.cancelled():
        send.exception()


async def deliver(transport, owner, parts, *, window_s, attempts, current):
    """Return COMPLETE only when Telegram confirmed every part.

    ``current()`` is checked before every part and retry, so a committed Cancel
    stops delivery without starting another request.
    """
    loop = asyncio.get_running_loop()
    deadline = loop.time() + window_s
    for part in parts:
        for attempt in range(attempts):
            if not current():
                return CANCELLED
            remaining = deadline - loop.time()
            if remaining <= 0:
                return FAILED
            send = asyncio.ensure_future(transport.send(owner, part.text, entities=part.entities, guard=current))
            try:
                async with asyncio.timeout(remaining):
                    await asyncio.shield(send)
                break
            except SendSkipped:
                return CANCELLED
            except asyncio.CancelledError:
                await _finish_started(send)
                raise
            except TimeoutError:
                # The window expired while the request was in flight.
                send.cancel()
                await _finish_started(send)
                return UNCERTAIN
            except TelegramRetryAfter as error:
                if attempt + 1 >= attempts or loop.time() + error.retry_after >= deadline:
                    return FAILED
                await asyncio.sleep(error.retry_after)
            except TelegramForbiddenError:
                return BLOCKED
            except TelegramNetworkError:
                return UNCERTAIN
            except TelegramAPIError:
                return FAILED
            except Exception:
                return UNCERTAIN
        else:
            return FAILED
    return COMPLETE
