import asyncio
from datetime import timedelta
from types import SimpleNamespace
from uuid import uuid4

from tgbotdocs.application.compiler import CompileResult
from tgbotdocs.application.events import ButtonClick, Event
from tgbotdocs.application.product import ProductApplication
from tgbotdocs.recognition.contracts import ExtractionProfile, ScalarField


class Store:
    def __init__(self):
        self.rows = {}

    async def list_profiles(self, owner):
        return tuple(p for p in self.rows.values() if p.owner == str(owner))

    async def save_drafts(self, owner, drafts):
        assert all(p.owner == str(owner) for p in drafts)
        self.rows.update((p.id, p) for p in drafts)
        return drafts


class Transport:
    def __init__(self):
        self.sent, self.deleted, self.answers = [], [], []

    async def send(self, owner, text, **kwargs):
        self.sent.append((owner, text, kwargs))

    async def delete(self, owner, identifier):
        self.deleted.append((owner, identifier))
        return True

    async def answer_callback(self, query_id, text):
        self.answers.append((query_id, text))


class Compiler:
    def __init__(self):
        self.calls = []

    async def compile(self, owner, instruction, **kwargs):
        self.calls.append(instruction)
        p = ExtractionProfile(id=str(uuid4()), owner=str(owner), version=1, name="Synthetic",
            description="Fictional card", original_instruction=instruction,
            fields=(ScalarField(id="id", label="ID", description="Printed ID", type="text"),))
        return CompileResult(drafts=(p,))


class Documents:
    def __init__(self):
        self.inputs, self.cancelled, self.closed = [], [], []

    def active(self, owner):
        return False

    def waiting(self, owner):
        return False

    def settings_closed(self, owner):
        self.closed.append(owner)

    def cancel(self, owner):
        self.cancelled.append(owner)

    async def handle(self, event):
        if event.kind == "file":
            self.inputs.append(event.owner)
            return True
        return False

    async def close(self):
        pass


def application(*, clock=lambda: 1.0, password="synthetic-password-123"):
    cfg = SimpleNamespace(password=password, inactivity_s=900, operator_ids=(999,))
    return ProductApplication(cfg, Transport(), Store(), Compiler(), documents=Documents(), clock=clock)


async def drain(app):
    for _ in range(30):
        for actor in tuple(app.actors.values()):
            await actor.mailbox.join()
        await asyncio.sleep(0)
        if not app.tasks and not app.settings.tasks:
            return


async def text(app, value, owner=1, **kwargs):
    app.submit(Event("text", owner, payload=value, **kwargs))
    await drain(app)


async def click(app, action, owner=1):
    token = next(t for t, (a, _) in app.settings.session(owner).buttons.items() if a == action)
    app.submit(Event("callback", owner, payload=ButtonClick(token, "query")))
    await drain(app)


async def test_access_before_download_password_deletion_logout_and_restart():
    app = application()
    try:
        app.submit(Event("file", 1, update_id=1))
        await text(app, "Settings")
        assert not app.documents.inputs and not app.settings.session(1).buttons
        await text(app, "/start")
        await text(app, "wrong", message_id=2)
        assert not app.session(1).signed_in and (1, 2) in app.transport.deleted
        await text(app, app.config.password, message_id=3)
        assert app.session(1).signed_in and (1, 3) in app.transport.deleted
        app.submit(Event("file", 1, update_id=4))
        app.submit(Event("file", 1, update_id=4))
        await drain(app)
        assert app.documents.inputs == [1]
        await text(app, "Logout")
        assert not app.session(1).signed_in and app.documents.cancelled == [1]
        assert any("Logged out" in value for _, value, _ in app.transport.sent)
    finally:
        await app.close()
    restarted = application(password="new-synthetic-password-456")
    try:
        await text(restarted, "/start")
        await text(restarted, app.config.password)
        assert not restarted.session(1).signed_in
        await text(restarted, restarted.config.password)
        assert restarted.session(1).signed_in
    finally:
        await restarted.close()


async def test_lock_window_global_surge_independent_users_and_stale_password():
    now = [1.0]
    app = application(clock=lambda: now[0])
    try:
        for owner in range(1, 7):
            await text(app, "/start", owner)
            for _ in range(5):
                await text(app, "bad", owner)
        assert sum("password_attempt_surge" in value for _, value, _ in app.transport.sent) == 1
        await text(app, app.config.password, 1)
        assert not app.session(1).signed_in
        await text(app, "/start", 7)
        await text(app, app.config.password, 7)
        assert app.session(7).signed_in
        now[0] += 901
        await text(app, app.config.password, 1)
        assert app.session(1).signed_in
        stale = app.started_at - timedelta(seconds=1)
        await text(app, app.config.password, 8, created_at=stale, message_id=100)
        app.submit(Event("file", 8, created_at=stale))
        await drain(app)
        assert not app.session(8).signed_in and (8, 100) in app.transport.deleted
        assert sum(owner == 8 and "restarted" in value for owner, value, _ in app.transport.sent) == 1
    finally:
        await app.close()


async def test_idle_signed_out_actors_are_released_and_signed_in_users_are_kept():
    now = [10.0]
    app = application(clock=lambda: now[0])
    try:
        await text(app, "hello", 1)
        await text(app, "/start", 2)
        await text(app, "/start", 3)
        await text(app, app.config.password, 3)
        now[0] += 3601
        app.tick()
        await drain(app)
        # Only the signed-out, idle user without a pending password prompt is released.
        assert 1 not in app.actors and 1 not in app.sessions
        assert 2 in app.actors and app.session(2).awaiting_password
        assert 3 in app.actors and app.session(3).signed_in
        await text(app, "hello again", 1)
        assert 1 in app.actors
        assert sum(owner == 1 and "Send /start" in value for owner, value, _ in app.transport.sent) == 2
        session = app.session(3)
        for update in range(1, 2 + 2000):
            app.submit(Event("text", 3, update_id=update, payload="x"))
        await drain(app)
        assert len(session.seen) <= 2000 and max(session.seen) == 2001
    finally:
        await app.close()


async def test_personal_dialogue_expiry_menu_text_routing_and_stale_buttons():
    now = [1.0]
    app = application(clock=lambda: now[0])
    try:
        await text(app, "/start")
        await text(app, app.config.password)
        await text(app, "Settings")
        await click(app, "create")
        await text(app, "Several pages")
        assert not app.settings.compiler.calls
        await text(app, "Read the printed ID")
        assert app.settings.session(1).state == "preview" and not app.store.rows
        token = next(t for t, (a, _) in app.settings.session(1).buttons.items() if a == "save")
        await click(app, "save")
        assert len(app.store.rows) == 1
        await text(app, "Settings")
        await click(app, "create")
        now[0] += 901
        app.tick()
        await drain(app)
        assert app.settings.session(1).state == "closed"
        await text(app, "Logout")
        app.submit(Event("callback", 1, payload=ButtonClick(token, "old")))
        await drain(app)
        assert ("old", "Session expired") in app.transport.answers
        app.nonprivate(-10)
        app.nonprivate(-10)
        await drain(app)
        assert sum(owner == -10 for owner, _, _ in app.transport.sent) == 1
        assert all("password" not in value for owner, value, _ in app.transport.sent if owner == -10)
    finally:
        await app.close()
