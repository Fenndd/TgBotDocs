import asyncio
from dataclasses import replace
from datetime import datetime, timedelta, timezone
import json
import math
from pathlib import Path
from uuid import uuid4

from PIL import Image
import pytest

from tgbotdocs.application.config import AppConfig, ConfigurationError
from tgbotdocs.application.events import Event
from tgbotdocs.application.rendering import render_result, RenderingError
from tgbotdocs.application.skeleton import WalkingSkeleton
from tgbotdocs.application.transport import Upload
from tgbotdocs.recognition.adapter import ModelReply, TokenScore
from tgbotdocs.recognition.contracts import ExtractionProfile, FieldResult, RecognitionResult, ScalarField
from tgbotdocs.recognition.core import CoreSettings, RecognitionCore
from tgbotdocs.recognition.runtime import RuntimeProfile
from tgbotdocs.recognition.verification import VerificationPolicy


def profile(owner):
    return ExtractionProfile(id=str(uuid4()), owner=str(owner), version=1, name="Synthetic card",
        description="Fictional card", original_instruction="Read identifier",
        fields=(ScalarField(id="identifier", label="Identifier", description="Printed ID", type="text"),))


def config(tmp_path):
    return AppConfig(tmp_path, tmp_path / "frozen.json", tmp_path / "temporary", "postgresql+psycopg://",
                     "123456:synthetic_token", "synthetic-password-only")


def test_external_configuration_hides_secret_error(tmp_path):
    path = tmp_path / "bot.env"
    password = "test-secret-not-for-output"
    path.write_text(f"DATA_ROOT={tmp_path}\nFROZEN_CONFIG={tmp_path}/frozen.json\n"
                    f"BOT_TOKEN=123456:synthetic_token\nSHARED_PASSWORD={password}\n"
                    "DATABASE_URL=postgresql+psycopg://synthetic\n")
    cfg = AppConfig.load(path)
    assert cfg.password == password and password not in repr(cfg)
    path.write_text("BOT_TOKEN=some-secret\nSHARED_PASSWORD=another-secret\nDATA_ROOT=relative\n")
    with pytest.raises(ConfigurationError) as failure:
        AppConfig.load(path)
    assert "secret" not in str(failure.value)


def test_timer_and_capacity_configuration_is_parsed_and_validated(tmp_path):
    path = tmp_path / "bot.env"
    base = (f"DATA_ROOT={tmp_path}\nFROZEN_CONFIG={tmp_path}/frozen.json\nBOT_TOKEN=123456:synthetic_token\n"
            "SHARED_PASSWORD=synthetic-password-only\nDATABASE_URL=postgresql+psycopg://synthetic\n")
    path.write_text(base + "INACTIVITY_S=60\nALBUM_QUIET_S=0.5\nQUEUE_TIMEOUT_S=120\nDELIVERY_S=30\n"
                    "DELIVERY_ATTEMPTS=2\nADMITTED_JOBS=3\nDOWNLOAD_LIMIT=1\nOPERATOR_TELEGRAM_IDS=11, 22\n")
    cfg = AppConfig.load(path)
    assert (cfg.inactivity_s, cfg.album_quiet_s, cfg.queue_timeout_s, cfg.delivery_s) == (60, 0.5, 120, 30)
    assert (cfg.delivery_attempts, cfg.admitted_jobs, cfg.download_limit) == (2, 3, 1)
    assert cfg.operator_ids == (11, 22) and cfg.processing_s == 1800
    for setting, code in (("INACTIVITY_S=0", "invalid_timer_setting"), ("ALBUM_QUIET_S=nan", "invalid_timer_setting"),
                          ("PROCESSING_S=-1", "invalid_timer_setting"), ("ADMITTED_JOBS=0", "invalid_capacity_setting")):
        path.write_text(base + setting + "\n")
        with pytest.raises(ConfigurationError, match=code):
            AppConfig.load(path)


def test_platform_runtime_executable_override_needs_an_absolute_path_and_pinned_hash(tmp_path):
    path = tmp_path / "bot.env"
    base = (f"DATA_ROOT={tmp_path}\nFROZEN_CONFIG={tmp_path}/frozen.json\nBOT_TOKEN=123456:synthetic_token\n"
            "SHARED_PASSWORD=synthetic-password-only\nDATABASE_URL=postgresql+psycopg://synthetic\n")
    path.write_text(base)
    assert AppConfig.load(path).runtime_executable is None
    digest = "a" * 64
    path.write_text(base + f"RUNTIME_EXECUTABLE={tmp_path}/llama-server\nRUNTIME_EXECUTABLE_SHA256={digest}\n")
    cfg = AppConfig.load(path)
    assert cfg.runtime_executable == tmp_path / "llama-server" and cfg.runtime_executable_sha256 == digest
    for extra, code in ((f"RUNTIME_EXECUTABLE={tmp_path}/llama-server\n", "required_together"),
                        (f"RUNTIME_EXECUTABLE=relative\nRUNTIME_EXECUTABLE_SHA256={digest}\n", "invalid_runtime"),
                        (f"RUNTIME_EXECUTABLE={tmp_path}/x\nRUNTIME_EXECUTABLE_SHA256=ABC\n", "invalid_runtime")):
        path.write_text(base + extra)
        with pytest.raises(ConfigurationError, match=code):
            AppConfig.load(path)


def test_virtualized_appdata_is_rejected(tmp_path):
    path = tmp_path / "bot.env"
    path.write_text(f"DATA_ROOT={tmp_path}/AppData/Local/TgBotDocs\nFROZEN_CONFIG={tmp_path}/f.json\n")
    with pytest.raises(ConfigurationError, match="virtualized_appdata"):
        AppConfig.load(path)


def test_rendering_uses_utf16_entities_and_withholds_invalid_candidates():
    p = profile(1)
    result = RecognitionResult(outcome="complete", fields=(
        FieldResult(field_id="identifier", status="extracted", raw_value="🧪@name https://example.invalid", source_pages=(1,)),),
        lists=())
    parts = render_result(p, result)
    encoded = parts[0].text.encode("utf-16-le")
    entity = parts[0].entities[0]
    assert encoded[entity.offset*2:(entity.offset+entity.length)*2].decode("utf-16-le") == result.fields[0].raw_value
    invalid = result.model_copy(update={"outcome": "failed", "fields": (
        FieldResult(field_id="identifier", status="invalid", raw_value="private-candidate", source_pages=(1,)),)})
    part = render_result(p, invalid)[0]
    assert "private-candidate" not in part.text and "format check" in part.text and not part.entities
    long = result.model_copy(update={"fields": (result.fields[0].model_copy(update={"raw_value": "x"*5000}),)})
    with pytest.raises(RenderingError, match="exceeds_telegram_limit"):
        render_result(p, long)


class Transport:
    def __init__(self, image):
        self.image, self.downloads, self.sent, self.deleted = image, [], [], []
        self.gate = None

    async def send(self, owner, text, **kwargs):
        self.sent.append((owner, text, kwargs))

    async def delete(self, owner, message_id):
        self.deleted.append((owner, message_id))

    async def download(self, upload, destination):
        self.downloads.append(upload.file_id)
        if self.gate:
            await self.gate.wait()
        await asyncio.to_thread(Path(destination).write_bytes, self.image.read_bytes())


class Adapter:
    async def count_input_tokens(self, *args, **kwargs):
        return 100

    async def generate(self, *args, **kwargs):
        text = json.dumps({"fields": {"identifier": {"s": "extracted", "v": "AB-001", "p": [1]}},
                           "lists": {}, "membership": {"1": "yes"}})
        tokens = tuple(TokenScore(c.encode(), math.log(.99)) for c in text)
        return ModelReply(text, tokens, True, 100, len(tokens), .001)


async def drain(app):
    for actor in tuple(app.actors.values()):
        await actor.mailbox.join()
    await asyncio.sleep(0)


async def test_walking_path_real_core_fake_telegram_cleanup_and_stale(tmp_path):
    from tgbotdocs.application.lifecycle import TemporaryLifecycle

    image = tmp_path / "synthetic.png"
    Image.new("RGB", (30, 50), "white").save(image)
    lifecycle = TemporaryLifecycle(tmp_path / "temporary", free_reserve_bytes=0)
    await lifecycle.initialize()
    transport = Transport(image)
    settings = CoreSettings(RuntimeProfile(), VerificationPolicy(min_token_probability=.7), .9)
    app = WalkingSkeleton(config(tmp_path), transport, lifecycle, lambda _: RecognitionCore(Adapter(), settings), profile)
    try:
        upload = Upload("synthetic-file", 100)
        app.submit(Event("file", 1, update_id=1, payload=upload))
        await drain(app)
        assert not transport.downloads
        app.submit(Event("text", 1, update_id=2, payload="/start"))
        app.submit(Event("text", 1, update_id=3, message_id=3, payload=app.config.password))
        app.submit(Event("file", 1, update_id=4, payload=upload))
        app.submit(Event("file", 1, update_id=4, payload=upload))
        await drain(app)
        operation = app.sessions[1].operation
        await operation
        await drain(app)
        assert transport.downloads == ["synthetic-file"]
        assert any("AB-001" in x[1] and x[2]["entities"] for x in transport.sent)
        assert not list(lifecycle.root.glob("job-*"))
        stale = datetime.now(timezone.utc) - timedelta(days=1)
        app.submit(Event("file", 2, update_id=5, created_at=stale, payload=upload))
        app.submit(Event("text", 2, update_id=6, message_id=6, created_at=stale, payload=app.config.password))
        await drain(app)
        assert len(transport.downloads) == 1 and not app.sessions[2].signed_in
        assert (2, 6) in transport.deleted
    finally:
        await app.close()


async def test_cancel_remains_responsive_during_download(tmp_path):
    from tgbotdocs.application.lifecycle import TemporaryLifecycle

    image = tmp_path / "synthetic.png"
    Image.new("RGB", (30, 50), "white").save(image)
    lifecycle = TemporaryLifecycle(tmp_path / "temporary", free_reserve_bytes=0)
    await lifecycle.initialize()
    transport = Transport(image)
    transport.gate = asyncio.Event()
    app = WalkingSkeleton(replace(config(tmp_path), admitted_jobs=1), transport, lifecycle,
                          lambda _: None, profile)
    try:
        for owner in (1, 2):
            app.submit(Event("text", owner, payload="/start"))
            app.submit(Event("text", owner, payload=app.config.password))
        app.submit(Event("file", 1, payload=Upload("first", 100)))
        await drain(app)
        app.submit(Event("file", 2, payload=Upload("second", 100)))
        app.submit(Event("text", 1, payload="/cancel"))
        await drain(app)
        await asyncio.gather(*tuple(app.tasks))
        await drain(app)
        assert transport.downloads == ["first"]
        assert any("Busy" in x[1] for x in transport.sent)
        assert not list(lifecycle.root.glob("job-*")) and app.sessions[1].job_id is None
    finally:
        await app.close()


async def test_repeated_cancel_during_cleanup_cannot_abandon_originals(tmp_path, monkeypatch):
    from tgbotdocs.application.lifecycle import TemporaryLifecycle

    image = tmp_path / "synthetic.png"
    Image.new("RGB", (30, 50), "white").save(image)
    lifecycle = TemporaryLifecycle(tmp_path / "temporary", free_reserve_bytes=0)
    await lifecycle.initialize()
    cleanup_started, release_cleanup = asyncio.Event(), asyncio.Event()
    original_cleanup = lifecycle.cleanup_job

    async def cleanup(path):
        cleanup_started.set()
        await release_cleanup.wait()
        return await original_cleanup(path)

    monkeypatch.setattr(lifecycle, "cleanup_job", cleanup)
    transport = Transport(image)
    transport.gate = asyncio.Event()
    app = WalkingSkeleton(config(tmp_path), transport, lifecycle, lambda _: None, profile)
    try:
        app.submit(Event("text", 1, payload="/start"))
        app.submit(Event("text", 1, payload=app.config.password))
        app.submit(Event("file", 1, payload=Upload("synthetic", 100)))
        await drain(app)
        app.submit(Event("text", 1, payload="/cancel"))
        await drain(app)
        await cleanup_started.wait()
        app.submit(Event("text", 1, payload="/cancel"))
        app.submit(Event("text", 1, payload="/logout"))
        await drain(app)
        release_cleanup.set()
        await asyncio.gather(*tuple(app.tasks))
        await drain(app)
        assert app.sessions[1].job_id is None and not app.sessions[1].signed_in
        assert not list(lifecycle.root.glob("job-*"))
    finally:
        release_cleanup.set()
        await app.close()


async def test_close_before_mailbox_runs_does_not_start_work(tmp_path):
    from tgbotdocs.application.lifecycle import TemporaryLifecycle

    image = tmp_path / "synthetic.png"
    Image.new("RGB", (30, 50), "white").save(image)
    lifecycle = TemporaryLifecycle(tmp_path / "temporary", free_reserve_bytes=0)
    await lifecycle.initialize()
    transport = Transport(image)
    transport.gate = asyncio.Event()
    app = WalkingSkeleton(config(tmp_path), transport, lifecycle, lambda _: None, profile)
    app.submit(Event("text", 1, payload="/start"))
    app.submit(Event("text", 1, payload=app.config.password))
    app.submit(Event("file", 1, payload=Upload("synthetic", 100)))
    await app.close()
    assert not transport.downloads and not list(lifecycle.root.glob("job-*"))
    assert not app.tasks and app.actors[1].task.done()
