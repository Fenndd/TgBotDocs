"""Production composition and long polling (ADR-0005; OPERATIONS, Processes).

Startup order (STATE_MACHINE, Restart and Stale Updates): owned temporary
cleanup and orphaned children, then configuration, database and migrations and
the model runtime, and only then long polling. There is no public HTTP server:
content-free operator alerts and technical logs are the operational signal, and
the service manager restarts a failed bot. ``compose`` performs no network I/O,
so the complete Telegram path can be exercised with a controlled Bot API session.
"""

import asyncio
from dataclasses import dataclass
from datetime import datetime, timezone
import logging
from logging.handlers import TimedRotatingFileHandler
import math
from pathlib import Path
import re
import time

from aiogram import Bot
from dotenv import dotenv_values

from .bootstrap import resources
from .compiler import InstructionCompiler
from .config import AppConfig, startup_temporary_root
from .documents import DocumentsFlow
from .health import HealthMonitor
from .intake import IntakeManager
from .pipeline import RecognitionService
from .product import ProductApplication
from .profiles import PreviewService
from .transport import OrderedTransport, TelegramTransport, dispatcher

EVENTS = logging.getLogger("tgbotdocs.events")
ALLOWED_UPDATES = ["message", "callback_query"]
TECHNICAL_ALERTS = frozenset({
    "startup_completed", "startup_failed", "service_failed", "service_retry_scheduled",
    "password_message_deletion_failed", "password_attempt_surge", "temporary_startup_failed",
    "temporary_ownership_failed", "intake_closed", "intake_reopened", "delivery_failed",
    "database_available", "database_unavailable", "runtime_restarted", "runtime_available",
    "runtime_unavailable",
})


class TechnicalEventsOnly(logging.Filter):
    """Dependency diagnostics and tracebacks are not permitted persistent data."""

    def filter(self, record):
        if record.name != "tgbotdocs.events" or record.exc_info or record.stack_info or not isinstance(record.msg, str):
            return False
        if record.msg == "%s":
            return isinstance(record.args, tuple) and len(record.args) == 1 and record.args[0] in TECHNICAL_ALERTS
        if record.msg in TECHNICAL_ALERTS:
            return not record.args
        if record.msg != "job_finished %s %s pages=%d charged_s=%.1f" or not isinstance(record.args, tuple):
            return False
        if len(record.args) != 4:
            return False
        job, code, pages, charged = record.args
        return (isinstance(job, str) and re.fullmatch(r"[0-9a-f]{32}", job) is not None
                and isinstance(code, str) and re.fullmatch(r"[a-z][a-z0-9_]{0,79}", code) is not None
                and type(pages) is int and pages >= 0 and type(charged) in (int, float)
                and math.isfinite(charged) and charged >= 0)


class Alerts:
    """Operator alerts; before the product exists they go to the technical log only."""

    def __init__(self):
        self.target = None

    def __call__(self, code, job_id=None):
        if self.target is not None:
            self.target(code, job_id)
        else:
            EVENTS.info("%s", code)

    async def lifecycle(self, code):
        self(code)


@dataclass(repr=False)
class Service:
    application: ProductApplication
    documents: DocumentsFlow
    health: HealthMonitor
    dispatcher: object
    bot: Bot


def compose(res, bot, alerts, *, clock=time.monotonic):
    """Wire the product around started resources; no Telegram request is made."""
    cfg, runtime = res.config, res.frozen.runtime_profile
    transport = OrderedTransport(TelegramTransport(bot))
    compiler = InstructionCompiler(res.adapter, res.scheduler, context_tokens=runtime.context_tokens,
                                   output_tokens=runtime.output_tokens)
    health = HealthMonitor(res.storage, res.runtime, res.adapter, res.scheduler, alerts)
    intake = IntakeManager(res.lifecycle, transport, res.frozen, admitted_jobs=cfg.admitted_jobs,
                           download_limit=cfg.download_limit, healthy=health.healthy)
    recognition = RecognitionService(res.adapter, res.scheduler, res.frozen.core_settings(), res.lifecycle)
    application = ProductApplication(cfg, transport, res.storage, compiler, clock=clock)
    documents = DocumentsFlow(intake, transport, application.submit, cfg, recognition=recognition,
                              store=res.storage, compiler=compiler,
                              previews=PreviewService(res.storage, ttl_s=cfg.inactivity_s, clock=clock), clock=clock)
    application.attach(documents)
    alerts.target = application.alert
    return Service(application, documents, health, dispatcher(application), bot)


async def _tick(application, interval_s):
    while True:
        await asyncio.sleep(interval_s)
        application.tick()


async def run_service(service, *, stop=None, tick_s=1.0, handle_signals=True):
    """Poll until ``stop`` is set, a signal stops polling, or the task is cancelled."""
    background = [asyncio.create_task(_tick(service.application, tick_s)),
                  asyncio.create_task(service.health.run())]
    polling = None
    try:
        service.application.alert("startup_completed")
        polling = asyncio.create_task(service.dispatcher.start_polling(
            service.bot, allowed_updates=ALLOWED_UPDATES, handle_signals=handle_signals,
            close_bot_session=False))
        if stop is None:
            await polling
        else:
            waiter = asyncio.create_task(stop.wait())
            try:
                await asyncio.wait({polling, waiter}, return_when=asyncio.FIRST_COMPLETED)
            finally:
                waiter.cancel()
            if not polling.done():
                await service.dispatcher.stop_polling()
            await polling
    finally:
        if polling is not None and not polling.done():
            polling.cancel()
            await asyncio.gather(polling, return_exceptions=True)
        for task in background:
            task.cancel()
        await asyncio.gather(*background, return_exceptions=True)
        # Cancels jobs and waits for their cleanup; nothing is sent after this.
        await service.application.close()


def configure_logging(source):
    """Technical events only, rotated daily and kept for 7 days (OPERATIONS, Logs)."""
    startup_temporary_root(source)  # Validates external, non-virtualized data paths first.
    directory = Path(dotenv_values(source, interpolate=False)["DATA_ROOT"]) / "logs"
    directory.mkdir(parents=True, exist_ok=True)
    handler = TimedRotatingFileHandler(directory / "tgbotdocs.log", when="midnight", backupCount=7,
                                       encoding="utf-8", utc=True)
    handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(name)s %(message)s"))
    handler.addFilter(TechnicalEventsOnly())
    handler._tgbotdocs_owned = True
    root = logging.getLogger()
    for previous in root.handlers:
        if getattr(previous, "_tgbotdocs_owned", False):
            previous.close()
    root.handlers[:] = [handler]
    root.setLevel(logging.WARNING)
    logging.getLogger("tgbotdocs").setLevel(logging.INFO)
    # Dependency loggers could echo request URLs; the Bot API URL contains the token.
    for name in ("aiogram", "aiohttp", "httpx", "httpcore", "asyncio"):
        logging.getLogger(name).setLevel(logging.WARNING)
    return handler


async def _notify_failure(source, code):
    """Best effort: a content-free alert to configured operators when startup fails."""
    try:
        cfg = AppConfig.load(source)
    except Exception:
        return
    if not cfg.operator_ids:
        return
    bot = Bot(cfg.bot_token)
    text = code + " " + datetime.now(timezone.utc).isoformat()
    try:
        for operator in cfg.operator_ids:
            try:
                async with asyncio.timeout(10):
                    await bot.send_message(operator, text)
            except Exception:
                pass
    finally:
        await bot.session.close()


async def serve(source):
    alerts, started = Alerts(), False
    try:
        async with resources(source, alert=alerts.lifecycle) as res:
            bot = Bot(res.config.bot_token)
            try:
                service = compose(res, bot, alerts)
                started = True
                await run_service(service)
            finally:
                await bot.session.close()
    except asyncio.CancelledError:
        raise
    except Exception:
        EVENTS.error("%s", "service_failed" if started else "startup_failed")
        await _notify_failure(source, "service_failed" if started else "startup_failed")
        raise


async def supervised_serve(source, *, retry_s=60.0):
    """Retry after resource cleanup, within the process owned by the service manager.

    A normal shutdown or cancellation ends supervision. Dependency failures already
    produce the fixed technical alert in ``serve``; no exception text is logged here.
    """
    while True:
        try:
            await serve(source)
        except asyncio.CancelledError:
            raise
        except Exception:
            EVENTS.warning("service_retry_scheduled")
            await asyncio.sleep(retry_s)
        else:
            return
