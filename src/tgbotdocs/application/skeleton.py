"""T02 walking path through actors, local core, transport, and cleanup.

The injected fixed profile exists only for the T02 check. The production dialogue
adds personal profiles in T03; there is no built-in taxonomy in this foundation.
"""

import asyncio
from dataclasses import dataclass, field
from datetime import datetime, timezone
import hmac
from pathlib import Path
import secrets
from uuid import uuid4

from .events import Event, UserActor
from .rendering import render_result


@dataclass(repr=False)
class SkeletonSession:
    awaiting_password: bool = False
    signed_in: bool = False
    job_id: str | None = None
    generation: int = 0
    operation: asyncio.Task | None = None
    seen: set[int] = field(default_factory=set)
    restart_notified: bool = False


class WalkingSkeleton:
    def __init__(self, config, transport, lifecycle, core_factory, profile_factory):
        self.config, self.transport, self.lifecycle = config, transport, lifecycle
        self.core_factory, self.profile_factory = core_factory, profile_factory
        self.started_at = datetime.now(timezone.utc)
        self.nonce = secrets.token_hex(4)
        self.actors, self.sessions, self.tasks = {}, {}, set()
        self.closing = False

    def submit(self, event):
        if self.closing and event.kind != "terminal":
            return
        if event.owner not in self.actors:
            self.sessions[event.owner] = SkeletonSession()
            self.actors[event.owner] = UserActor(event.owner, self.transition)
        self.actors[event.owner].enqueue(event)

    def _background(self, coroutine):
        task = asyncio.create_task(coroutine)
        self.tasks.add(task)
        task.add_done_callback(self.tasks.discard)
        return task

    def say(self, owner, text):
        if self.closing:
            return
        async def send():
            try:
                await self.transport.send(owner, text)
            except Exception:
                pass  # Transport failures never expose a response/secret body.
        self._background(send())

    async def transition(self, event):
        if self.closing and event.kind != "terminal":
            return
        session = self.sessions[event.owner]
        if event.update_id is not None:
            if event.update_id in session.seen:
                return
            session.seen.add(event.update_id)
        if event.created_at is not None and event.created_at < self.started_at:
            if event.kind == "text" and hmac.compare_digest(str(event.payload).encode(), self.config.password.encode()):
                self._background(self.transport.delete(event.owner, event.message_id))
            if not session.restart_notified:
                session.restart_notified = True
                self.say(event.owner, "The bot restarted. Send /start to sign in and resend your document.")
            return
        if event.kind == "terminal":
            if event.job_id == session.job_id and event.generation == session.generation:
                session.job_id, session.operation = None, None
            return
        if event.kind == "text" and event.payload in ("/cancel", "Cancel", "/logout", "Logout"):
            session.generation += 1
            if session.operation and not session.operation.cancelling():
                session.operation.cancel()
            if event.payload in ("/logout", "Logout"):
                session.signed_in, session.awaiting_password = False, False
            self.say(event.owner, "Cancelled." if session.job_id else "No active document.")
            return
        if event.kind == "text" and event.payload == "/start":
            session.awaiting_password = not session.signed_in
            self.say(event.owner, "Send a document, or use Settings, Several pages, Cancel, Logout."
                     if session.signed_in else "Enter the shared password.")
            return
        if session.awaiting_password and event.kind == "text":
            correct = hmac.compare_digest(str(event.payload).encode(), self.config.password.encode())
            self._background(self.transport.delete(event.owner, event.message_id))
            session.signed_in = correct
            session.awaiting_password = not correct
            self.say(event.owner, "Signed in. Send one image." if correct else "Incorrect password.")
            return
        if not session.signed_in:
            self.say(event.owner, "Send /start to sign in.")
            return
        if event.kind != "file":
            self.say(event.owner, "Send an image.")
            return
        if session.job_id:
            self.say(event.owner, "A document is active. Wait or Cancel and resend.")
            return
        if not self.lifecycle.intake_available:
            self.say(event.owner, "Temporarily unavailable.")
            return
        if sum(s.job_id is not None for s in self.sessions.values()) >= self.config.admitted_jobs:
            self.say(event.owner, "Busy. Try again later.")
            return
        session.job_id = uuid4().hex
        session.generation += 1
        session.operation = self._background(self._process(event, session.job_id, session.generation))

    async def _process(self, event, job_id, generation):
        directory = None
        try:
            directory = self.lifecycle.create_job(job_id)
            original = directory / "original"
            await self.transport.download(event.payload, original)
            profile = self.profile_factory(event.owner)
            core = self.core_factory(job_id)
            result = await core.recognize((Path(original),), (profile,), scratch=directory,
                                          selected_profile=profile)
            if generation != self.sessions[event.owner].generation:
                return
            if result.recognition is None:
                await self.transport.send(event.owner, "The document could not be read reliably.")
            else:
                for part in render_result(profile, result.recognition):
                    if generation != self.sessions[event.owner].generation:
                        return
                    await self.transport.send(event.owner, part.text, entities=part.entities)
        except asyncio.CancelledError:
            pass
        except Exception:
            if generation == self.sessions[event.owner].generation:
                self.say(event.owner, "The document could not be processed. Please resend it.")
        finally:
            async def finalize():
                try:
                    if directory is not None:
                        await self.lifecycle.cleanup_job(directory)
                finally:
                    # Terminal after cancellation uses the current generation,
                    # while job ID prevents an old operation clearing a new job.
                    current = self.sessions[event.owner]
                    self.submit(Event("terminal", event.owner, job_id=job_id, generation=current.generation))
            finalizer = asyncio.create_task(finalize())
            while not finalizer.done():
                try:
                    await asyncio.shield(finalizer)
                except asyncio.CancelledError:
                    pass
            finalizer.result()

    async def close(self):
        self.closing = True
        # Stop admitting work from already queued inputs, but leave terminal
        # processing alive until every operation's finalizer has completed.
        for actor in self.actors.values():
            await actor.mailbox.join()
        for session in self.sessions.values():
            session.generation += 1
            if session.operation and not session.operation.cancelling():
                session.operation.cancel()
        for task in tuple(self.tasks):
            if not task.cancelling():
                task.cancel()
        await asyncio.gather(*tuple(self.tasks), return_exceptions=True)
        for actor in self.actors.values():
            await actor.close()
