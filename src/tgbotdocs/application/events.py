"""RAM-only events and per-user mailboxes."""

import asyncio
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any


@dataclass(frozen=True, repr=False)
class ButtonClick:
    data: str
    query_id: str


@dataclass(frozen=True, repr=False)
class Event:
    kind: str
    owner: int
    update_id: int | None = None
    message_id: int | None = None
    created_at: datetime | None = None
    job_id: str | None = None
    generation: int = 0
    payload: Any = field(default=None, repr=False)


class UserActor:
    """Apply transitions sequentially; blocking work returns completion events."""

    def __init__(self, owner, transition):
        self.owner, self.transition = owner, transition
        self.mailbox = asyncio.Queue()
        self.busy = False
        self.task = asyncio.create_task(self._run())

    @property
    def idle(self):
        """No queued event and no transition in progress."""
        return self.mailbox.empty() and not self.busy

    def enqueue(self, event):
        if event.owner != self.owner:
            raise ValueError("event_owner_mismatch")
        self.mailbox.put_nowait(event)

    async def _run(self):
        while True:
            event = await self.mailbox.get()
            self.busy = True
            try:
                if event is None:
                    return
                await self.transition(event)
            finally:
                self.busy = False
                self.mailbox.task_done()

    async def close(self):
        self.mailbox.put_nowait(None)
        await self.task
