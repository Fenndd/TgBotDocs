"""Private-chat access and personal Settings connected by per-user actors."""

import asyncio
from dataclasses import dataclass, field
from datetime import datetime, timezone
import hmac
import logging
import time

from aiogram.types import KeyboardButton, ReplyKeyboardMarkup, ReplyKeyboardRemove

from .access import AccessGuard
from .events import ButtonClick, Event, UserActor
from .profiles import PreviewService
from .settings import SettingsFlow


@dataclass(repr=False)
class Session:
    signed_in: bool = False
    awaiting_password: bool = False
    seen: set = field(default_factory=set)
    restart_notified: bool = False
    reminder_at: float = float("-inf")
    active_at: float = 0.0


# A signed-out user's idle actor is released after this; sign-in state is unaffected.
IDLE_ACTOR_S = 3600.0
# Duplicate update IDs arrive close together; older IDs need not be remembered forever.
SEEN_LIMIT = 2000


MENU = ReplyKeyboardMarkup(keyboard=[
    [KeyboardButton(text="Several pages"), KeyboardButton(text="Settings")],
    [KeyboardButton(text="Cancel"), KeyboardButton(text="Logout")],
], resize_keyboard=True)


class ProductApplication:
    """A document flow is attached after T04/T05; no network is needed to construct it.

    Document transitions must follow the same short, nonblocking mailbox contract.
    The parent owns access and routes one accepted text input to exactly one flow.
    """

    def __init__(self, config, transport, store, compiler, *, documents=None, clock=time.monotonic):
        self.config, self.transport, self.store, self.clock = config, transport, store, clock
        # Telegram message dates have whole seconds; a message sent in the start
        # second is not treated as stale (ED-005).
        self.started_at = datetime.now(timezone.utc).replace(microsecond=0)
        self.guard = AccessGuard(config.password, clock=clock)
        self.sessions, self.actors, self.tasks = {}, {}, set()
        self.groups = {}
        self.closing = False
        self.settings = SettingsFlow(store, compiler,
            PreviewService(store, ttl_s=config.inactivity_s, clock=clock), transport,
            self.submit, ttl_s=config.inactivity_s, clock=clock)
        self.documents = None
        if documents is not None:
            self.attach(documents)

    def attach(self, documents):
        """Route document input to the job flow and share the Settings overlap rule."""
        self.documents = documents
        documents.settings_waiting = self.settings.waiting
        documents.alert = self.alert

    def session(self, owner):
        return self.sessions.setdefault(owner, Session())

    def submit(self, event):
        if self.closing and event.kind not in ("settings_result", "document_terminal"):
            return
        if event.owner not in self.actors:
            self.session(event.owner)
            self.actors[event.owner] = UserActor(event.owner, self.transition)
        self.actors[event.owner].enqueue(event)

    def task(self, coroutine):
        task = asyncio.create_task(coroutine)
        self.tasks.add(task)
        def finished(task):
            self.tasks.discard(task)
            if not task.cancelled():
                task.exception()
        task.add_done_callback(finished)
        return task

    def say(self, owner, text, *, menu=False, remove_menu=False):
        if self.closing:
            return
        self.task(self.transport.send(owner, text, reply_markup=
            MENU if menu else ReplyKeyboardRemove() if remove_menu else None))

    def alert(self, code, job_id=None):
        logging.getLogger("tgbotdocs.events").info("%s", code)
        text = code + " " + datetime.now(timezone.utc).isoformat()
        if job_id is not None:
            text += " " + job_id
        for owner in self.config.operator_ids:
            self.say(owner, text)

    def nonprivate(self, chat_id):
        if self.clock() - self.groups.get(chat_id, float("-inf")) >= 60:
            self.groups[chat_id] = self.clock()
            self.say(chat_id, "Please use a private chat with this bot.")

    def _delete_password(self, event):
        async def remove():
            if not await self.transport.delete(event.owner, event.message_id):
                self.alert("password_message_deletion_failed")
        self.task(remove())

    def _stale_button(self, data):
        prefix, _, rest = data.partition(":")
        nonce = rest.partition(":")[0]
        current = {"s": self.settings.nonce, "j": getattr(self.documents, "nonce", None)}.get(prefix)
        return prefix in ("s", "j") and nonce != current

    def job_active(self, owner):
        return self.documents is not None and self.documents.active(owner)

    def job_waiting(self, owner):
        return self.documents is not None and self.documents.waiting(owner)

    def menu(self, owner):
        text = "Send one document, or choose Several pages or Settings."
        if self.job_active(owner):
            text += "\nDocument: " + self.documents.status(owner)
        self.say(owner, text, menu=True)

    async def transition(self, event):
        session = self.session(event.owner)
        if self.closing and event.kind not in ("settings_result", "document_terminal"):
            return
        if event.kind != "tick":
            session.active_at = self.clock()
        if event.update_id is not None:
            if event.update_id in session.seen:
                return
            session.seen.add(event.update_id)
            if len(session.seen) > SEEN_LIMIT:
                session.seen = set(sorted(session.seen)[-SEEN_LIMIT // 2:])
        if event.created_at is not None and event.created_at < self.started_at:
            if event.kind == "text" and hmac.compare_digest(str(event.payload).encode(), self.config.password.encode()):
                self._delete_password(event)
            if not session.restart_notified:
                session.restart_notified = True
                self.say(event.owner, "The bot restarted. Send /start to sign in and resend your document.")
            return
        if event.kind == "tick":
            self.guard.prune()
            self.settings.expire(event.owner)
            if self.documents is not None:
                if not self.settings.waiting(event.owner):
                    self.documents.settings_closed(event.owner)
                await self.documents.handle(event)
            return
        if isinstance(event.payload, ButtonClick) and self._stale_button(event.payload.data):
            # A button from a previous process: Session expired, one restart notice.
            self.task(self.transport.answer_callback(event.payload.query_id, "Session expired"))
            if not session.restart_notified:
                session.restart_notified = True
                self.say(event.owner, "The bot restarted. Send /start to sign in and resend your document.")
            return
        if event.kind.startswith("document_"):
            if self.documents is not None:
                await self.documents.handle(event)
            return
        if event.kind == "text" and event.payload in ("/logout", "Logout"):
            session.signed_in, session.awaiting_password = False, False
            self.settings.discard(event.owner)
            if self.documents is not None:
                self.documents.cancel(event.owner)
            self.say(event.owner, "Logged out. Send /start to sign in again.", remove_menu=True)
            return
        if event.kind == "text" and event.payload in ("/cancel", "Cancel") and session.signed_in:
            active = self.job_active(event.owner)
            if self.documents is not None:
                self.documents.cancel(event.owner)
            self.say(event.owner, "Cancelled. Cleanup is running." if active else "No active document.")
            return
        if event.kind == "text" and event.payload == "/start":
            session.awaiting_password = not session.signed_in
            if session.signed_in:
                self.menu(event.owner)
            else:
                self.say(event.owner, "Enter the shared password.", remove_menu=True)
            return
        if session.awaiting_password and event.kind == "text":
            attempt = self.guard.attempt(event.owner, str(event.payload))
            self._delete_password(event)
            if attempt.operator_alert:
                self.alert("password_attempt_surge")
            if attempt.success:
                session.signed_in, session.awaiting_password = True, False
                self.menu(event.owner)
            else:
                self.say(event.owner, "Too many attempts. Try again after the sign-in window expires."
                         if attempt.locked else "Incorrect password.")
            return
        if not session.signed_in:
            if isinstance(event.payload, ButtonClick):
                self.task(self.transport.answer_callback(event.payload.query_id, "Session expired"))
            elif self.clock() - session.reminder_at >= 60:
                session.reminder_at = self.clock()
                self.say(event.owner, "Send /start to sign in.")
            return
        if self.settings.waiting(event.owner) and event.kind == "text" and event.payload == "Several pages":
            self.say(event.owner, "Finish or cancel the profile draft before collecting several pages.")
            return
        handled = await self.settings.handle(event, signed_in=True,
            read_only=self.job_waiting(event.owner), job_active=self.job_active(event.owner))
        if handled:
            if self.documents is not None and not self.settings.waiting(event.owner):
                self.documents.settings_closed(event.owner)
            return
        if self.documents is not None and await self.documents.handle(event):
            return
        if isinstance(event.payload, ButtonClick):
            self.task(self.transport.answer_callback(event.payload.query_id, "Session expired"))
        elif event.kind == "file":
            self.say(event.owner, "Temporarily unavailable. Please try again later.")
        elif self.settings.waiting(event.owner):
            self.say(event.owner, "Finish or cancel the current profile draft.")
        else:
            self.menu(event.owner)

    def tick(self):
        now = self.clock()
        for owner in tuple(self.actors):
            if self._retirable(owner, now):
                self._retire(owner)
            else:
                self.submit(Event("tick", owner))

    def _retirable(self, owner, now):
        session, settings = self.sessions.get(owner), self.settings.sessions.get(owner)
        return (session is not None and not session.signed_in and not session.awaiting_password
                and not self.job_active(owner) and (settings is None or settings.state == "closed")
                and self.actors[owner].idle and now - session.active_at >= IDLE_ACTOR_S)

    def _retire(self, owner):
        """Release a signed-out user's idle actor; a later update creates a new one."""
        actor = self.actors.pop(owner)
        self.sessions.pop(owner, None)
        self.settings.sessions.pop(owner, None)
        self.task(actor.close())

    async def close(self):
        self.closing = True
        for actor in tuple(self.actors.values()):
            await actor.mailbox.join()
        if self.documents is not None:
            await asyncio.gather(self.settings.close(), self.documents.close())
        else:
            await self.settings.close()
        for task in tuple(self.tasks):
            task.cancel()
        await asyncio.gather(*tuple(self.tasks), return_exceptions=True)
        for actor in tuple(self.actors.values()):
            await actor.close()
