"""Opt-in T07 local resilience, leak and resource check against the real product.

Uses the real startup, PostgreSQL and the frozen GPU runtime with a controlled Bot
API session (no Telegram request). Scenarios:

- baseline: a synthetic document is recognized and delivered;
- runtime crash: llama-server is killed while the job's model call runs; the job
  must end with an explicit error, the runtime must recover, and the next document
  must succeed;
- database outage (``--database-outage``): the development cluster is stopped;
  intake must refuse a new document before download and alert the operator, and
  after the cluster is started again a document must succeed;
- leaks: the technical log, operator alerts, PostgreSQL tables and the temporary
  root are checked for synthetic document values, the password and leftovers;
- resources: peak resident memory of the bot and llama-server and GPU memory.

Output is content-free JSON. Synthetic profiles are deleted at the end.
"""

import argparse
import asyncio
from datetime import datetime, timezone
import json
from pathlib import Path
import secrets
import subprocess
import time
from uuid import uuid4

from aiogram import Bot
from dotenv import dotenv_values
import psutil
from sqlalchemy import create_engine, text

from tgbotdocs.application.bootstrap import resources
from tgbotdocs.application.service import Alerts, compose, configure_logging, run_service
from tgbotdocs.recognition.contracts import ExtractionProfile, ScalarField
from tgbotdocs.storage import ProfileNotFound

import importlib.util

_spec = importlib.util.spec_from_file_location("product_check", Path(__file__).with_name("check-product-local.py"))
product_check = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(product_check)

REPOSITORY = Path(__file__).resolve().parents[1]
VALUE = "SYN-88317"


def postgres(action):
    subprocess.run(["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-File",
                    str(REPOSITORY / "scripts" / "setup-postgres.ps1"), "-Action", action],
                   # No captured pipes: the started postgres inherits and keeps them open.
                   check=True, stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                   stderr=subprocess.DEVNULL, timeout=120)


class Sampler:
    def __init__(self, runtime):
        self.runtime, self.bot_rss, self.runtime_rss, self.gpu = runtime, 0, 0, 0
        self.process = psutil.Process()

    def sample(self):
        self.bot_rss = max(self.bot_rss, self.process.memory_info().rss)
        pid = self.runtime.pid
        if pid:
            try:
                self.runtime_rss = max(self.runtime_rss, psutil.Process(pid).memory_info().rss)
            except psutil.Error:
                pass
        try:
            used = subprocess.run(["nvidia-smi", "--query-gpu=memory.used", "--format=csv,noheader,nounits"],
                                  capture_output=True, text=True, timeout=10).stdout.strip().splitlines()[0]
            self.gpu = max(self.gpu, int(used))
        except (OSError, ValueError, IndexError, subprocess.SubprocessError):
            pass

    async def run(self):
        while True:
            self.sample()
            await asyncio.sleep(0.5)


async def check(source, summary, database_outage):
    configure_logging(source)
    started_day = datetime.now().strftime("%Y-%m-%d")  # asctime uses local time
    values = dotenv_values(source, interpolate=False)
    log_file = Path(values["DATA_ROOT"]) / "logs" / "tgbotdocs.log"
    owner = 10**15 + secrets.randbelow(10**15)
    document = product_check.document(["INVOICE", f"Invoice number: {VALUE}", "Invoice date: 2026-09-02"])
    api = product_check.ControlledApi({f"doc{i}": document for i in range(6)})
    alerts = Alerts()
    async with resources(source, alert=alerts.lifecycle) as res:
        card = ExtractionProfile(id=str(uuid4()), owner=str(owner), version=1, name="Invoice",
                                 description="Invoices with a printed invoice number",
                                 original_instruction="For invoices extract the printed invoice number.",
                                 fields=(ScalarField(id="invoice_number", label="Invoice number", type="text",
                                                     description="Printed invoice number"),))
        await res.storage.save_drafts(owner, (card,))
        bot = Bot(res.config.bot_token, session=api)
        service = compose(res, bot, alerts)
        service.health.interval_s = 2
        operators = res.config.operator_ids
        stop = asyncio.Event()
        running = asyncio.create_task(run_service(service, stop=stop, handle_signals=False))
        sampler = Sampler(res.runtime)
        sampling = asyncio.create_task(sampler.run())
        documents, counter = service.documents, iter(range(6))
        try:
            def send():
                name = f"doc{next(counter)}"
                api.message(owner, document={"file_id": name, "file_unique_id": "u" + name, "file_name": "x.png",
                                             "mime_type": "image/png", "file_size": len(document)})

            def results():
                return [t for t in api.texts(owner) if t.startswith("Result:")]

            api.message(owner, text="/start")
            api.message(owner, text=res.config.password)
            await product_check.until(lambda: any(t.startswith("Send one document") for t in api.texts(owner)), 60)

            begin = time.monotonic()
            send()
            await product_check.until(lambda: len(results()) == 1 and owner not in documents.jobs, 600)
            summary["baseline_s"] = round(time.monotonic() - begin, 1)
            summary["baseline_exact"] = VALUE in results()[-1]

            # Runtime crash while the job's model call runs.
            messages = len(api.texts(owner))
            send()
            await product_check.until(lambda: owner in documents.jobs and documents.jobs[owner].phase_started, 120)
            await asyncio.sleep(1.0)
            res.runtime._process.kill()
            await product_check.until(lambda: owner not in documents.jobs, 300)
            reply = api.texts(owner)[messages:]
            summary["crash_job_result"] = "result" if any(t.startswith("Result:") for t in reply) else (
                "explicit_error" if reply else "no_reply")
            await product_check.until(lambda: res.runtime._process is not None
                                      and res.runtime._process.returncode is None and service.health.healthy(), 300)
            begin = time.monotonic()
            before = len(results())
            send()
            await product_check.until(lambda: len(results()) == before + 1 and owner not in documents.jobs, 600)
            summary["after_crash_s"] = round(time.monotonic() - begin, 1)
            summary["after_crash_exact"] = VALUE in results()[-1]

            if database_outage:
                postgres("Stop")
                await product_check.until(lambda: not service.health.database, 60)
                messages = len(api.texts(owner))
                send()
                await product_check.until(lambda: len(api.texts(owner)) > messages, 60)
                # Refused before any download: no job and no temporary job directory.
                summary["outage_reply"] = api.texts(owner)[-1][:60]
                summary["outage_job_created"] = owner in documents.jobs or bool(
                    list(res.lifecycle.root.glob("job-*")))
                postgres("Start")
                await product_check.until(lambda: service.health.database, 120)
                before = len(results())
                send()
                await product_check.until(lambda: len(results()) == before + 1 and owner not in documents.jobs, 600)
                summary["after_outage_exact"] = VALUE in results()[-1]
            summary["job_directories_left"] = len(list(res.lifecycle.root.glob("job-*")))
            summary["reservations_left"] = len(res.lifecycle._reserved)
        finally:
            sampling.cancel()
            await asyncio.gather(sampling, return_exceptions=True)
            stop.set()
            await running
            await bot.session.close()
            for profile in await res.storage.list_profiles(owner):
                try:
                    await res.storage.delete_profile(owner, profile.id, profile.version)
                except ProfileNotFound:
                    pass
        alerts_sent = [m.text for m in api.sent if m.chat_id in operators]
        summary["operator_messages_content_free"] = all(len(t.split(" ")) <= 3 and VALUE not in t
                                                        for t in alerts_sent)
        engine = create_engine(res.config.database_url, hide_parameters=True)
        try:
            with engine.connect() as connection:
                tables = connection.execute(text(
                    "SELECT table_name FROM information_schema.tables WHERE table_schema = current_schema()"
                )).scalars().all()
        finally:
            engine.dispose()
        summary["database_tables"] = sorted(tables)
    log = log_file.read_text(encoding="utf-8", errors="replace") if log_file.exists() else ""
    summary["log_lines"] = len(log.splitlines())
    events = [line.split(" tgbotdocs.events ", 1)[1] for line in log.splitlines()
              if " tgbotdocs.events " in line and line.startswith(started_day)]
    summary["alert_codes_logged"] = sorted({event for event in events if " " not in event})
    summary["job_outcomes_logged"] = sorted({event.split(" ")[2] for event in events if event.startswith("job_finished ")})
    summary["log_contains_document_value"] = VALUE in log
    summary["log_contains_password"] = values["SHARED_PASSWORD"] in log
    summary["log_contains_token"] = values["BOT_TOKEN"].split(":", 1)[-1] in log
    summary["peak_bot_rss_mib"] = round(sampler.bot_rss / 2**20)
    summary["peak_runtime_rss_mib"] = round(sampler.runtime_rss / 2**20)
    summary["peak_gpu_memory_mib"] = sampler.gpu
    summary["status"] = "completed"


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", required=True, type=Path)
    parser.add_argument("--database-outage", action="store_true",
                        help="stop and restart the local development PostgreSQL cluster during the check")
    arguments = parser.parse_args()
    summary = {"status": "failed", "telegram_network_requests": 0}
    started = time.monotonic()
    try:
        asyncio.run(check(arguments.config, summary, arguments.database_outage))
    except Exception as error:
        summary["error"] = type(error).__name__
    summary["total_s"] = round(time.monotonic() - started, 1)
    summary["checked_at"] = datetime.now(timezone.utc).isoformat(timespec="seconds")
    print(json.dumps(summary, indent=1))
    return 0 if summary.get("status") == "completed" else 1


if __name__ == "__main__":
    raise SystemExit(main())
