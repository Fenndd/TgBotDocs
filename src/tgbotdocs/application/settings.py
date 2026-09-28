"""Nonblocking personal-profile dialogue, composed with the document actor in T06."""

import asyncio
from dataclasses import dataclass, field
import secrets
import time

from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup

from tgbotdocs.storage import ProfileConflict, ProfileNotFound, StorageUnavailable

from .compiler import CompileError
from .events import ButtonClick, Event
from .profiles import DeletePreview, PreviewExpired, ProfilePreview
from .rendering import utf16_length


@dataclass(repr=False)
class SettingsSession:
    state: str = "closed"
    revision: int = 0
    activity_at: float = 0.0
    operation: asyncio.Task | None = None
    preview: ProfilePreview | DeletePreview | None = None
    current: tuple = ()
    instruction: str = ""
    editing: object = None
    buttons: dict = field(default_factory=dict)
    read_only: bool = False
    job_active: bool = False


def profile_text(profile):
    lines = [profile.name, "Applies to: " + profile.description,
             "Original instruction: " + profile.original_instruction, "Fields:"]
    for definition in profile.fields:
        lines.append(f"- {definition.label}: {definition.description} ({definition.type})")
        scalars = definition.columns if definition.type == "list" else (definition,)
        for scalar in scalars:
            if definition.type == "list":
                lines.append(f"  Column {scalar.label}: {scalar.description} ({scalar.type})")
            if scalar.validator is not None:
                validator = scalar.validator
                if validator.kind == "calendar_date":
                    formats = tuple(pattern.replace("%Y", "YYYY").replace("%m", "MM").replace("%d", "DD")
                                    for pattern in validator.date_formats)
                    detail = "Calendar date" + (" in " + ", ".join(formats) if formats else "")
                elif validator.kind == "iso_code":
                    detail = "Allowed codes: " + ", ".join(validator.allowlist)
                else:
                    detail = "IBAN checksum" if validator.kind == "iban" else "Luhn checksum"
                lines.append("  Format check: " + detail)
    lines.append("Additional instructions: " + (profile.guidance or "None"))
    return "\n".join(lines)


def split_preview(text):
    """Keep all text, including an unusually long instruction or field definition."""
    chunks, current, length = [], [], 0
    for character in text:
        size = utf16_length(character)
        if length + size > 3900:
            chunks.append("".join(current))
            current, length = [], 0
        current.append(character)
        length += size
    if current:
        chunks.append("".join(current))
    if len(chunks) > 1:
        chunks = [f"Preview part {i}/{len(chunks)}\n{chunk}" for i, chunk in enumerate(chunks, 1)]
    return tuple(chunks)


class SettingsFlow:
    """Actor transitions perform no I/O; operations return revision-tagged events.

    The parent routes text here only while ``waiting`` is true, calls ``handle``
    for Settings/callback/internal events, and supplies current job restrictions.
    Callback tokens are process-local, owner-scoped and bounded to 64 bytes.
    """

    def __init__(self, store, compiler, previews, transport, submit, *, ttl_s=900, clock=time.monotonic):
        self.store, self.compiler, self.previews = store, compiler, previews
        self.transport, self.submit = transport, submit
        self.ttl_s, self.clock = ttl_s, clock
        self.nonce = secrets.token_hex(4)
        self.sessions, self.tasks = {}, set()
        self.closing = False

    def session(self, owner):
        return self.sessions.setdefault(owner, SettingsSession())

    def waiting(self, owner):
        return self.session(owner).state in ("instruction", "compiling", "preview", "saving", "delete")

    def _task(self, coroutine):
        task = asyncio.create_task(coroutine)
        self.tasks.add(task)
        def completed(task):
            self.tasks.discard(task)
            if not task.cancelled():
                task.exception()  # Consume transport errors without response bodies in logs.
        task.add_done_callback(completed)
        return task

    def _send(self, owner, text, buttons=()):
        session = self.session(owner)
        session.buttons.clear()
        keyboard = []
        for label, action, argument in buttons:
            token = f"s:{self.nonce}:{session.revision:x}:{secrets.token_hex(8)}"
            session.buttons[token] = (action, argument)
            keyboard.append([InlineKeyboardButton(text=label, callback_data=token)])
        markup = InlineKeyboardMarkup(inline_keyboard=keyboard) if keyboard else None
        revision = session.revision
        async def send():
            parts = split_preview(text)
            for index, part in enumerate(parts):
                if self.closing or self.session(owner).revision != revision:
                    return
                await self.transport.send(owner, part, reply_markup=markup if index == len(parts) - 1 else None)
        self._task(send())

    def _request(self, owner, state, operation, result_kind):
        session = self.session(owner)
        session.revision += 1
        session.state, session.activity_at = state, self.clock()
        session.buttons.clear()
        revision = session.revision
        async def work():
            try:
                value, code = await operation(), None
            except asyncio.CancelledError:
                return
            except StorageUnavailable:
                value, code = None, "storage"
            except (ProfileConflict, ProfileNotFound):
                value, code = None, "conflict"
            except PreviewExpired:
                value, code = None, "expired"
            except CompileError:
                value, code = None, "compiler"
            except Exception:
                value, code = None, "operation"
            self.submit(Event("settings_result", owner, generation=revision,
                              payload=(result_kind, value, code)))
        session.operation = self._task(work())

    def discard(self, owner):
        session = self.session(owner)
        session.revision += 1
        if session.operation and not session.operation.cancelling():
            session.operation.cancel()
        self.previews.discard_owner(owner)
        session.state, session.preview, session.current = "closed", None, ()
        session.instruction, session.editing = "", None
        session.buttons.clear()

    def expire(self, owner=None):
        self.previews.expire()
        for candidate, session in tuple(self.sessions.items()):
            if owner is not None and candidate != owner:
                continue
            if self.waiting(candidate) and session.state != "saving" and self.clock() - session.activity_at >= self.ttl_s:
                self.discard(candidate)
                self._send(candidate, "The profile draft expired. Open Settings to start again.")

    def _list(self, owner):
        self._request(owner, "loading", lambda: self.store.list_profiles(owner), "list")

    def _instruction(self, owner, *, editing=None, current=()):
        session = self.session(owner)
        session.revision += 1
        session.state, session.activity_at = "instruction", self.clock()
        session.current, session.editing = current, editing
        self._send(owner, "Describe the document types and exactly which fields or lists to extract."
                   if not current else "Describe the changes to this preview. Unchanged requested fields will be kept.",
                   (("Cancel draft", "cancel", None),))

    def _preview(self, owner):
        session = self.session(owner)
        preview = session.preview
        session.state = "preview"
        self._send(owner, "Review every profile before saving.\n\n" + "\n\n".join(
            profile_text(profile) for profile in preview.drafts),
            (("Save all", "save", preview.nonce), ("Edit", "edit_draft", preview.nonce),
             ("Cancel draft", "cancel", None)))

    async def handle(self, event, *, signed_in, read_only=False, job_active=False):
        if self.closing:
            return False
        session = self.session(event.owner)
        session.read_only, session.job_active = read_only, job_active
        if event.kind == "settings_result":
            if event.generation != session.revision:
                return True
            session.operation = None
            kind, value, error = event.payload
            if error:
                if kind == "compile":
                    session.state = "instruction"
                    self._send(event.owner, "The instruction could not be compiled. Please simplify it and try again.",
                               (("Cancel draft", "cancel", None),))
                elif kind in ("save", "delete_save") and error == "storage":
                    if kind == "save":
                        self._preview(event.owner)
                    else:
                        self._delete_preview(event.owner)
                    self._task(self.transport.send(event.owner, "Storage is temporarily unavailable. Nothing is reported saved; retry this preview."))
                else:
                    self.discard(event.owner)
                    self._send(event.owner, "The profile operation could not complete. Open Settings for the current profiles.")
                return True
            session.activity_at = self.clock()
            if kind == "list":
                session.state = "list"
                buttons = [(profile.name, "view", profile.id) for profile in value]
                if not read_only:
                    buttons.append(("Create profile", "create", None))
                text = "Your profiles:" if value else "You have no saved profiles."
                if read_only:
                    text += "\nAnswer the document first or Cancel it before changing Settings."
                self._send(event.owner, text, buttons)
            elif kind == "view":
                session.state, session.editing = "view", value
                buttons = [("Back", "list", None)]
                if not read_only:
                    buttons = [("Edit", "edit", value.id), ("Delete", "delete", value.id), *buttons]
                self._send(event.owner, profile_text(value), buttons)
            elif kind == "compile":
                if value.questions:
                    session.state = "instruction"
                    self._send(event.owner, "\n".join(value.questions), (("Cancel draft", "cancel", None),))
                else:
                    try:
                        session.preview = self.previews.stage(event.owner, value, editing=session.editing)
                    except ValueError:
                        session.state = "instruction"
                        self._send(event.owner, "An edit must keep one profile and its identity. Describe changes to that profile only.",
                                   (("Cancel draft", "cancel", None),))
                    else:
                        session.current = value.drafts
                        self._preview(event.owner)
            elif kind == "delete":
                session.preview = value
                self._delete_preview(event.owner)
            elif kind in ("save", "delete_save"):
                session.preview, session.current, session.editing = None, (), None
                session.instruction, session.state = "", "closed"
                self._send(event.owner, "Profiles saved." if kind == "save" else "Profile deleted.")
                if job_active:
                    self._task(self.transport.send(event.owner, "This change applies to later documents. The active document keeps its profile snapshot."))
            return True
        if not signed_in:
            return False
        if event.kind == "text" and event.payload in ("Settings", "/settings"):
            if session.state == "saving":
                self._send(event.owner, "The confirmed change is being saved. Wait for the result.")
            elif self.waiting(event.owner):
                self._send(event.owner, "Finish or cancel the open profile draft first.", (("Cancel draft", "cancel", None),))
            else:
                self._list(event.owner)
            return True
        if event.kind == "text" and session.state == "instruction":
            if read_only:
                self._send(event.owner, "Answer the document first or Cancel it before changing Settings.")
                return True
            instruction = str(event.payload).strip()
            if not instruction:
                self._send(event.owner, "Send a nonempty instruction.", (("Cancel draft", "cancel", None),))
                return True
            # Clarification answers are appended to the original instruction; they
            # must not silently replace earlier requested fields/types.
            session.instruction = session.instruction + "\n" + instruction if session.instruction else instruction
            instruction, current = session.instruction, session.current
            self._request(event.owner, "compiling", lambda: self.compiler.compile(
                event.owner, instruction, current=current), "compile")
            return True
        if event.kind != "callback" or not isinstance(event.payload, ButtonClick) or not event.payload.data.startswith("s:"):
            return False
        choice = session.buttons.get(event.payload.data)
        self._task(self.transport.answer_callback(event.payload.query_id, "" if choice else "Session expired"))
        if choice is None:
            return True
        action, argument = choice
        if read_only and action in ("create", "edit", "delete", "save", "edit_draft", "delete_save"):
            self._send(event.owner, "Answer the document first or Cancel it before changing Settings.")
            return True
        session.activity_at = self.clock()
        if action == "cancel":
            self.discard(event.owner)
            self._send(event.owner, "Draft cancelled. Saved profiles were not changed.")
        elif action == "list":
            self._list(event.owner)
        elif action == "create":
            session.instruction = ""
            self._instruction(event.owner)
        elif action == "view":
            self._request(event.owner, "loading", lambda: self.store.get_profile(event.owner, argument), "view")
        elif action == "edit":
            profile = session.editing
            session.instruction = ""
            self._instruction(event.owner, editing=profile, current=(profile,))
        elif action == "delete":
            self._request(event.owner, "loading", lambda: self.previews.begin_delete(event.owner, argument), "delete")
        elif action == "delete_save":
            self._request(event.owner, "saving", lambda: self.previews.confirm_delete(event.owner, argument), "delete_save")
        elif action == "save":
            self._request(event.owner, "saving", lambda: self.previews.confirm(event.owner, argument), "save")
        elif action == "edit_draft":
            try:
                preview = self.previews.get(event.owner, argument)
            except PreviewExpired:
                self.discard(event.owner)
                self._send(event.owner, "Session expired")
            else:
                self._instruction(event.owner, editing=preview.editing, current=preview.drafts)
        return True

    def _delete_preview(self, owner):
        session = self.session(owner)
        session.state = "delete"
        self._send(owner, "Delete this profile?\n\n" + profile_text(session.preview.profile),
                   (("Delete permanently", "delete_save", session.preview.nonce), ("Cancel draft", "cancel", None)))

    async def close(self):
        self.closing = True
        operations = {session.operation for session in self.sessions.values() if session.operation is not None}
        for owner in tuple(self.sessions):
            self.discard(owner)
        for task in tuple(self.tasks):
            if task not in operations:
                task.cancel()
        await asyncio.gather(*tuple(self.tasks), return_exceptions=True)

