"""The production composition driven through aiogram with a controlled Bot API session.

No network: the Bot API is a scripted session, the model is a deterministic
adapter, PostgreSQL is an in-memory store. The dispatcher, product actors, real
intake with its parser child, the frozen recognition core (rendering, verification,
merging), rendering and delivery are the product code.
"""

import asyncio
from datetime import datetime, timezone
from io import BytesIO
import json
import math
from types import SimpleNamespace
from uuid import uuid4

from aiogram import Bot
from aiogram.client.session.base import BaseSession
from aiogram.methods import AnswerCallbackQuery, DeleteMessage, GetFile, GetMe, GetUpdates, SendMessage
from aiogram.types import File, Message, Update, User
from PIL import Image

from tgbotdocs.application.health import HealthMonitor
from tgbotdocs.application.lifecycle import TemporaryLifecycle
from tgbotdocs.application.scheduler import GpuScheduler
from tgbotdocs.application.service import Alerts, compose, run_service
from tgbotdocs.application.supervision import supervise_children
from tgbotdocs.recognition.adapter import ModelReply, TokenScore
from tgbotdocs.recognition.contracts import ExtractionProfile, ScalarField
from tgbotdocs.recognition.core import CoreSettings
from tgbotdocs.recognition.runtime import RuntimeProfile
from tgbotdocs.recognition.verification import VerificationPolicy

PASSWORD = "synthetic-password-123"
TOKEN = "123456:synthetic_token"
USER, OPERATOR = 4242, 999


def png():
    data = BytesIO()
    Image.new("RGB", (120, 90), "white").save(data, format="PNG")
    return data.getvalue()


class TelegramApi(BaseSession):
    """Scripted Bot API: queued updates in, recorded requests out."""

    def __init__(self, files):
        super().__init__()
        self.files, self.queue, self.sent, self.answers, self.deleted = files, [], [], [], []
        self.next_update, self.next_message = 1, 100

    def push(self, **payload):
        self.queue.append({"update_id": self.next_update, **payload})
        self.next_update += 1

    def message(self, owner, *, date=None, chat_type="private", **content):
        self.next_message += 1
        stamp = int((date or datetime.now(timezone.utc)).timestamp()) + 2
        self.push(message={"message_id": self.next_message, "date": stamp,
                           "chat": {"id": owner, "type": chat_type},
                           "from": {"id": owner, "is_bot": False, "first_name": "Synthetic"}, **content})

    def callback(self, owner, data):
        self.push(callback_query={"id": f"q{self.next_update}", "chat_instance": "c", "data": data,
                                  "from": {"id": owner, "is_bot": False, "first_name": "Synthetic"},
                                  "message": {"message_id": 1, "date": 1, "chat": {"id": owner, "type": "private"}}})

    async def make_request(self, bot, method, timeout=None):  # noqa: ASYNC109 - aiogram session interface
        if isinstance(method, GetMe):
            return User(id=1, is_bot=True, first_name="Bot", username="synthetic_bot")
        if isinstance(method, GetUpdates):
            ready = [u for u in self.queue if u["update_id"] >= (method.offset or 0)]
            self.queue = ready
            if not ready:
                await asyncio.sleep(0.02)
                return []
            return [Update.model_validate(u, context={"bot": bot}) for u in ready]
        if isinstance(method, SendMessage):
            self.sent.append(method)
            self.next_message += 1
            return Message.model_validate({"message_id": self.next_message, "date": 1, "text": method.text,
                                           "chat": {"id": method.chat_id, "type": "private"}}, context={"bot": bot})
        if isinstance(method, AnswerCallbackQuery):
            self.answers.append((method.callback_query_id, method.text))
            return True
        if isinstance(method, DeleteMessage):
            self.deleted.append(method.message_id)
            return True
        if isinstance(method, GetFile):
            return File(file_id=method.file_id, file_unique_id="u" + method.file_id,
                        file_size=len(self.files[method.file_id]), file_path="files/" + method.file_id)
        raise AssertionError(type(method).__name__)

    async def stream_content(self, url, headers=None, timeout=30,  # noqa: ASYNC109 - aiogram interface
                             chunk_size=65536, raise_for_status=True):
        data = self.files[url.rsplit("/", 1)[-1]]
        for start in range(0, len(data), chunk_size):
            yield data[start:start + chunk_size]

    async def close(self):
        pass

    def texts(self, owner=USER):
        return [m.text for m in self.sent if m.chat_id == owner]


class Model:
    """Deterministic model: the only profile matches; the identifier is read."""

    def __init__(self):
        self.calls = 0

    async def count_input_tokens(self, *args, **kwargs):
        return 600

    async def generate(self, messages, schema, **kwargs):
        self.calls += 1
        if "profile_index" in json.dumps(schema):
            value = {"type_description": "Synthetic card", "status": "matched", "profile_index": 1}
        else:
            value = {"fields": {"identifier": {"s": "extracted", "v": "SYN-0042", "p": [1]}}, "lists": {},
                     "membership": {"1": "yes"}}
        text = json.dumps(value)
        tokens = tuple(TokenScore(c.encode(), math.log(0.99)) for c in text)
        return ModelReply(text, tokens, True, 600, len(tokens), 0.001)


class Store:
    def __init__(self, profiles):
        self.rows = {p.id: p for p in profiles}

    async def list_profiles(self, owner):
        return tuple(p for p in self.rows.values() if p.owner == str(owner))

    async def health(self):
        return True


async def test_telegram_updates_reach_a_delivered_result_through_the_production_composition(tmp_path):
    lifecycle = TemporaryLifecycle(tmp_path / "temporary", free_reserve_bytes=0)
    assert await lifecycle.initialize()
    card = ExtractionProfile(id=str(uuid4()), owner=str(USER), version=1, name="Synthetic card",
                             description="Fictional card", original_instruction="Read the identifier",
                             fields=(ScalarField(id="identifier", label="Identifier", type="text",
                                                 description="Printed identifier"),))
    settings = CoreSettings(runtime=RuntimeProfile(), verification=VerificationPolicy(
        min_token_probability=0.7, check_alternate_view=True, check_declared_format=True),
        matching_margin=0.9, compute_alternate_view=True)
    frozen = SimpleNamespace(
        page_times=tuple(SimpleNamespace(kind=k, p5=10.0) for k in ("png", "jpeg", "pdf")),
        core=SimpleNamespace(processing_budget_s=1800.0, call_timeout_s=30.0, max_pixels=89_478_485,
                             quota_bytes=2 * 1024**3, free_reserve_bytes=0),
        runtime_profile=RuntimeProfile(), core_settings=lambda: settings)
    config = SimpleNamespace(password=PASSWORD, inactivity_s=900, processing_s=1800, album_quiet_s=0.2,
                             delivery_s=60, delivery_attempts=3, admitted_jobs=8, download_limit=2,
                             operator_ids=(OPERATOR,))
    scheduler, model = GpuScheduler(), Model()
    runtime = SimpleNamespace(_process=SimpleNamespace(returncode=None), port=1)
    resources = SimpleNamespace(config=config, frozen=frozen, lifecycle=lifecycle, storage=Store((card,)),
                                runtime=runtime, adapter=model, scheduler=scheduler)
    api = TelegramApi({"photo-small": png(), "photo-large": png()})
    bot = Bot(TOKEN, session=api)
    service = compose(resources, bot, Alerts())
    assert isinstance(service.health, HealthMonitor)
    service.health.interval_s = 3600  # no real runtime health endpoint in this test
    stop = asyncio.Event()

    async def until(predicate):
        async with asyncio.timeout(30):
            while not predicate():  # noqa: ASYNC110 - bounded observation of the running service
                await asyncio.sleep(0.02)

    async with supervise_children(lifecycle):
        running = asyncio.create_task(run_service(service, stop=stop, tick_s=0.05, handle_signals=False))
        try:
            await until(lambda: any("startup_completed" in m.text for m in api.sent if m.chat_id == OPERATOR))
            api.message(-100, chat_type="group", text="/start")
            api.message(USER, date=datetime(2020, 1, 1, tzinfo=timezone.utc), text=PASSWORD)
            api.message(USER, text="/start")
            api.message(USER, text=PASSWORD)
            await until(lambda: any(t.startswith("Send one document") for t in api.texts()))
            assert any("restarted" in t for t in api.texts()) and len(api.deleted) == 2
            assert [m.text for m in api.sent if m.chat_id == -100] == ["Please use a private chat with this bot."]
            api.message(USER, photo=[
                {"file_id": "photo-small", "file_unique_id": "s", "width": 60, "height": 45, "file_size": 10},
                {"file_id": "photo-large", "file_unique_id": "l", "width": 120, "height": 90, "file_size": 20}])
            await until(lambda: any(t.startswith("Result:") for t in api.texts()))
            result = next(m for m in api.sent if m.chat_id == USER and m.text.startswith("Result:"))
            assert "Result: Complete" in result.text and "SYN-0042" in result.text
            assert "Profile: Synthetic card" in result.text and "(chosen by you)" not in result.text
            code = [e for e in result.entities if e.type == "code"]
            assert len(code) == 1 and result.link_preview_options.is_disabled and result.parse_mode is None
            assert model.calls == 3  # matching, extraction and the alternate view
            await until(lambda: not service.documents.jobs)
            assert not list(lifecycle.root.glob("job-*")) and not lifecycle._reserved
            # A button from a previous process answers Session expired.
            api.callback(USER, "j:deadbeef:" + "0" * 32 + ":1:00000000")
            await until(lambda: api.answers)
            assert api.answers[-1][1] == "Session expired"
        finally:
            stop.set()
            await running
    await scheduler.close()
    assert service.application.closing and not service.documents.jobs
    assert all("SYN-0042" not in m.text for m in api.sent if m.chat_id == OPERATOR)
