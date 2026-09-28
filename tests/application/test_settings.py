import asyncio
from uuid import uuid4

from tgbotdocs.application.compiler import CompileResult
from tgbotdocs.application.events import ButtonClick, Event
from tgbotdocs.application.profiles import PreviewService
from tgbotdocs.application.settings import SettingsFlow, split_preview
from tgbotdocs.recognition.contracts import ExtractionProfile, ScalarField
from tgbotdocs.storage import ProfileConflict, ProfileNotFound, StorageUnavailable


async def test_queued_profile_preview_is_withdrawn_after_logout_or_session_replacement():
    from tgbotdocs.application.transport import OrderedTransport

    entered, release = asyncio.Event(), asyncio.Event()
    sent = []

    class DelayedTransport:
        async def send(self, owner, text, **kwargs):
            if text == "hold":
                entered.set()
                await release.wait()
            sent.append(text)

    transport = OrderedTransport(DelayedTransport())
    store = Store()
    flow = SettingsFlow(store, Compiler(), PreviewService(store), transport, lambda event: None)
    first = asyncio.create_task(transport.send(1, "hold"))
    await entered.wait()
    try:
        flow._send(1, "SYNTHETIC_PRIVATE_PROFILE_PREVIEW")
        await asyncio.sleep(0)
        flow.discard(1)  # The product's logout/Cancel path invalidates Settings.
        flow.sessions.pop(1)
        flow.session(1)  # A later session cannot authorize the older preview.
        release.set()
        await first
        await asyncio.gather(*tuple(flow.tasks))
        assert sent == ["hold"]
    finally:
        release.set()
        await first
        await flow.close()


def profile(owner=1, name="Synthetic card"):
    return ExtractionProfile(id=str(uuid4()), owner=str(owner), version=1, name=name,
        description="Fictional document", original_instruction="Read identifier",
        fields=(ScalarField(id="identifier", label="Identifier", description="Requested ID", type="text"),))


class Store:
    def __init__(self):
        self.rows, self.writes = {}, 0
        self.failure, self.gate = False, None

    async def list_profiles(self, owner):
        return tuple(p for p in self.rows.values() if p.owner == str(owner))

    async def get_profile(self, owner, identifier):
        value = self.rows.get(identifier)
        if value is None or value.owner != str(owner):
            raise ProfileNotFound("profile not found")
        return value

    async def save_drafts(self, owner, drafts):
        if self.gate:
            await self.gate.wait()
        if self.failure:
            raise StorageUnavailable("storage unavailable")
        assert all(p.owner == str(owner) for p in drafts)
        self.writes += 1
        self.rows.update((p.id, p) for p in drafts)
        return drafts

    async def update_profile(self, owner, edited, expected_version):
        saved = await self.get_profile(owner, edited.id)
        if saved.version != expected_version:
            raise ProfileConflict("version conflict")
        saved = edited.model_copy(update={"version": expected_version + 1})
        self.rows[saved.id] = saved
        self.writes += 1
        return saved

    async def delete_profile(self, owner, identifier, expected_version):
        saved = await self.get_profile(owner, identifier)
        if saved.version != expected_version:
            raise ProfileConflict("version conflict")
        self.rows.pop(identifier)
        self.writes += 1


class Compiler:
    def __init__(self):
        self.calls, self.gate = [], None

    async def compile(self, owner, instruction, *, current=()):
        self.calls.append((owner, instruction, current))
        if self.gate:
            await self.gate.wait()
        if instruction == "unclear":
            return CompileResult(questions=("Which identifier?",))
        drafts = (current[0].model_copy(update={"name": "Edited"}),) if current else (profile(owner), profile(owner, "Second"))
        return CompileResult(drafts=drafts)


class Transport:
    def __init__(self):
        self.sent, self.answers = [], []

    async def send(self, owner, text, **kwargs):
        self.sent.append((owner, text, kwargs))

    async def answer_callback(self, identifier, text):
        self.answers.append((identifier, text))


class Harness:
    def __init__(self):
        self.now = 1.0
        self.store, self.compiler, self.transport = Store(), Compiler(), Transport()
        self.queue = asyncio.Queue()
        self.flow = SettingsFlow(self.store, self.compiler,
            PreviewService(self.store, ttl_s=900, clock=lambda: self.now), self.transport,
            self.queue.put_nowait, clock=lambda: self.now)
        self.read_only, self.active = False, False

    async def event(self, event, *, signed_in=True):
        return await self.flow.handle(event, signed_in=signed_in, read_only=self.read_only, job_active=self.active)

    async def drain(self):
        for _ in range(30):
            await asyncio.sleep(0)
            while not self.queue.empty():
                await self.event(self.queue.get_nowait())
            if not self.flow.tasks:
                return

    async def text(self, text, owner=1):
        await self.event(Event("text", owner, payload=text))
        await self.drain()

    def token(self, action, owner=1):
        return next(token for token, choice in self.flow.session(owner).buttons.items() if choice[0] == action)

    async def click(self, action, owner=1):
        await self.event(Event("callback", owner, payload=ButtonClick(self.token(action, owner), "synthetic-query")))
        await self.drain()


async def test_full_two_type_preview_explicit_atomic_save_owner_scope_and_callback_limit():
    h = Harness()
    try:
        assert not await h.event(Event("text", 1, payload="Settings"), signed_in=False)
        await h.text("Settings")
        await h.click("create")
        await h.text("Read identifiers from two document types")
        assert not h.store.rows and h.flow.session(1).state == "preview"
        assert any("Original instruction:" in text and "Fields:" in text for _, text, _ in h.transport.sent)
        token = h.token("save")
        assert len(token.encode()) <= 64 and h.flow.nonce in token
        await h.event(Event("callback", 2, payload=ButtonClick(token, "foreign-query")))
        await h.drain()
        assert not h.store.rows and ("foreign-query", "Session expired") in h.transport.answers
        h.active = True
        await h.click("save")
        assert len(h.store.rows) == 2 and h.store.writes == 1
        assert any("later documents" in text for _, text, _ in h.transport.sent)
        await h.event(Event("callback", 1, payload=ButtonClick(token, "duplicate")))
        await h.drain()
        assert h.store.writes == 1
        await h.text("Settings", owner=2)
        assert not any(choice[0] == "view" for choice in h.flow.session(2).buttons.values())
    finally:
        await h.flow.close()


async def test_cancel_and_logout_discard_slow_compiler_result_without_actor_blocking():
    h = Harness()
    try:
        await h.text("Settings")
        await h.click("create")
        h.compiler.gate = asyncio.Event()
        await h.text("Synthetic instruction")
        assert h.flow.session(1).state == "compiling" and not h.store.rows
        revision = h.flow.session(1).revision
        h.flow.discard(1)  # The parent calls this on logout.
        await h.event(Event("settings_result", 1, generation=revision,
                            payload=("compile", CompileResult(drafts=(profile(),)), None)))
        h.compiler.gate.set()
        await h.drain()
        assert h.flow.session(1).state == "closed" and not h.store.rows
    finally:
        await h.flow.close()


async def test_read_only_settings_expiry_clarification_preserves_original_and_retry_save():
    h = Harness()
    try:
        p = profile()
        h.store.rows[p.id] = p
        h.read_only = True
        await h.text("Settings")
        assert {action for action, _ in h.flow.session(1).buttons.values()} == {"view"}
        await h.click("view")
        assert {action for action, _ in h.flow.session(1).buttons.values()} == {"list"}
        h.read_only = False
        await h.text("Settings")
        await h.click("create")
        await h.text("unclear")
        await h.text("Printed identifier")
        assert h.compiler.calls[-1][1] == "unclear\nPrinted identifier"
        nonce = h.flow.session(1).preview.nonce
        h.store.failure = True
        await h.click("save")
        assert h.flow.session(1).state == "preview" and h.flow.session(1).preview.nonce == nonce
        assert h.store.writes == 0
        h.store.failure = False
        await h.click("save")
        assert h.store.writes == 1
        await h.text("Settings")
        await h.click("create")
        token = h.token("cancel")
        h.now += 901
        h.flow.expire()
        await h.event(Event("callback", 1, payload=ButtonClick(token, "expired")))
        await h.drain()
        assert h.flow.session(1).state == "closed" and ("expired", "Session expired") in h.transport.answers
    finally:
        await h.flow.close()


async def test_edit_version_conflict_and_delete_requires_current_explicit_confirmation():
    h = Harness()
    try:
        p = profile()
        h.store.rows[p.id] = p
        await h.text("Settings")
        await h.click("view")
        await h.click("edit")
        await h.text("Change label")
        assert h.flow.session(1).preview.editing.id == p.id
        h.store.rows[p.id] = p.model_copy(update={"version": 2, "name": "Newer"})
        await h.click("save")
        assert h.store.rows[p.id].name == "Newer" and h.store.writes == 0
        assert not h.flow.session(1).current and not h.flow.session(1).instruction and h.flow.session(1).editing is None
        await h.text("Settings")
        await h.click("view")
        await h.click("delete")
        assert p.id in h.store.rows
        await h.click("cancel")
        assert p.id in h.store.rows
        await h.text("Settings")
        await h.click("view")
        await h.click("delete")
        await h.click("delete_save")
        assert not h.store.rows and h.store.writes == 1
    finally:
        await h.flow.close()


async def test_confirmed_save_cannot_claim_cancellation_while_transaction_is_running():
    h = Harness()
    try:
        await h.text("Settings")
        await h.click("create")
        await h.text("Synthetic instruction")
        h.store.gate = asyncio.Event()
        await h.click("save")
        assert h.flow.session(1).state == "saving"
        await h.text("Settings")
        assert not h.flow.session(1).buttons
        assert not any("were not changed" in text for _, text, _ in h.transport.sent)
        h.store.gate.set()
        await h.drain()
        assert h.store.writes == 1 and h.flow.session(1).state == "closed"
    finally:
        h.store.gate.set()
        await h.flow.close()


def test_preview_preserves_entire_long_instruction_and_non_bmp_text():
    text = "😀" * 5000 + "end"
    chunks = split_preview(text)
    assert all(len(chunk.encode("utf-16-le")) // 2 <= 4096 for chunk in chunks)
    assert "".join(chunk.split("\n", 1)[1] for chunk in chunks) == text


async def test_shutdown_cancels_a_stalled_preview_send():
    h = Harness()
    started = asyncio.Event()
    async def stalled_send(*args, **kwargs):
        started.set()
        await asyncio.Event().wait()
    h.transport.send = stalled_send
    await h.event(Event("text", 1, payload="Settings"))
    await h.drain()
    await started.wait()
    await asyncio.wait_for(h.flow.close(), timeout=1)
    assert not h.flow.tasks

