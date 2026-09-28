"""Opt-in local product check: real startup, PostgreSQL and the frozen GPU model.

Telegram is replaced by a controlled Bot API session inside this process, so no
Telegram request is made and no token is used on the network. A synthetic owner
signs in, creates a profile through the instruction compiler and preview, and
sends synthetic documents through the file and photo paths; a second document
type without a profile goes through the in-job instruction, preview and Save.
The output is content-free: statuses, counts and durations. Synthetic profiles
are deleted at the end. This is a functional check, not quality acceptance.
"""

import argparse
import asyncio
from datetime import datetime, timezone
from io import BytesIO
import json
from pathlib import Path
import secrets
import time

from aiogram import Bot
from aiogram.client.session.base import BaseSession
from aiogram.methods import AnswerCallbackQuery, DeleteMessage, GetFile, GetMe, GetUpdates, SendMessage
from aiogram.types import File, Message, Update, User
from PIL import Image, ImageDraw, ImageFont

from tgbotdocs.application.bootstrap import resources
from tgbotdocs.application.service import Alerts, compose, run_service
from tgbotdocs.storage import ProfileNotFound

FONT = Path("C:/Windows/Fonts/arial.ttf")
INVOICE_NUMBER, INVOICE_DATE = "SYN-40721", "2026-09-01"
RECEIPT_TOTAL = "57.30"


def document(lines):
    image = Image.new("RGB", (1240, 1754), "white")
    draw = ImageDraw.Draw(image)
    font = ImageFont.truetype(str(FONT), 44) if FONT.exists() else ImageFont.load_default(44)
    for index, line in enumerate(lines):
        draw.text((110, 140 + index * 110), line, fill="black", font=font)
    data = BytesIO()
    image.save(data, format="PNG")
    return data.getvalue()


def jpeg(png):
    data = BytesIO()
    with Image.open(BytesIO(png)) as image:
        image.convert("RGB").resize((620, 877)).save(data, format="JPEG", quality=85)
    return data.getvalue()


class ControlledApi(BaseSession):
    """In-process Bot API: scripted updates in, recorded requests out."""

    def __init__(self, files):
        super().__init__()
        self.files, self.queue, self.sent, self.answers = files, [], [], []
        self.next_update, self.next_message = 1, 1000

    def push(self, **payload):
        self.queue.append({"update_id": self.next_update, **payload})
        self.next_update += 1

    def message(self, owner, **content):
        self.next_message += 1
        self.push(message={"message_id": self.next_message, "date": int(time.time()) + 2,
                           "chat": {"id": owner, "type": "private"},
                           "from": {"id": owner, "is_bot": False, "first_name": "Synthetic"}, **content})

    def callback(self, owner, data):
        self.push(callback_query={"id": f"q{self.next_update}", "chat_instance": "c", "data": data,
                                  "from": {"id": owner, "is_bot": False, "first_name": "Synthetic"},
                                  "message": {"message_id": 1, "date": 1, "chat": {"id": owner, "type": "private"}}})

    async def make_request(self, bot, method, timeout=None):  # noqa: ASYNC109 - aiogram session interface
        if isinstance(method, GetMe):
            return User(id=1, is_bot=True, first_name="Bot", username="controlled_bot")
        if isinstance(method, GetUpdates):
            ready = [u for u in self.queue if u["update_id"] >= (method.offset or 0)]
            self.queue = ready
            if not ready:
                await asyncio.sleep(0.05)
                return []
            return [Update.model_validate(u, context={"bot": bot}) for u in ready]
        if isinstance(method, SendMessage):
            self.sent.append(method)
            self.next_message += 1
            return Message.model_validate({"message_id": self.next_message, "date": 1, "text": method.text,
                                           "chat": {"id": method.chat_id, "type": "private"}}, context={"bot": bot})
        if isinstance(method, AnswerCallbackQuery):
            self.answers.append(method.callback_query_id)
            return True
        if isinstance(method, DeleteMessage):
            return True
        if isinstance(method, GetFile):
            return File(file_id=method.file_id, file_unique_id="u" + method.file_id,
                        file_size=len(self.files[method.file_id]), file_path="files/" + method.file_id)
        raise RuntimeError("unexpected_bot_api_method")

    async def stream_content(self, url, headers=None, timeout=30,  # noqa: ASYNC109 - aiogram interface
                             chunk_size=65536, raise_for_status=True):
        data = self.files[url.rsplit("/", 1)[-1]]
        for start in range(0, len(data), chunk_size):
            yield data[start:start + chunk_size]

    async def close(self):
        pass

    def texts(self, owner):
        return [m.text for m in self.sent if m.chat_id == owner]


async def until(predicate, seconds):
    async with asyncio.timeout(seconds):
        while not predicate():  # noqa: ASYNC110 - bounded observation of the running service
            await asyncio.sleep(0.1)


async def check(source, summary, verbose=False):
    owner = 10**15 + secrets.randbelow(10**15)
    invoice = document(["INVOICE", f"Invoice number: {INVOICE_NUMBER}", f"Invoice date: {INVOICE_DATE}",
                        "Bill to: Synthetic Customer Ltd.", "Item: Consulting services"])
    receipt = document(["CASH RECEIPT", "Store: Synthetic Market", "Milk 2.10", "Bread 3.20",
                        f"TOTAL {RECEIPT_TOTAL}", "Thank you"])
    files = {"invoice-file": invoice, "invoice-photo": jpeg(invoice), "receipt-file": receipt}
    api = ControlledApi(files)
    started = time.monotonic()
    async with resources(source) as res:
        assert not await res.storage.list_profiles(owner), "synthetic_owner_collision"
        bot = Bot(res.config.bot_token, session=api)
        service = compose(res, bot, Alerts())
        service.health.interval_s = 3600
        stop = asyncio.Event()
        running = asyncio.create_task(run_service(service, stop=stop, handle_signals=False))
        documents = service.documents
        try:
            def say(text):
                api.message(owner, text=text)

            def click(predicate):
                job = documents.jobs.get(owner)
                source = job.buttons if job is not None else {}
                token = next(t for t, a in source.items() if predicate(a))
                api.callback(owner, token)

            def settings_click(action):
                token = next(t for t, (a, _) in service.application.settings.session(owner).buttons.items()
                             if a == action)
                api.callback(owner, token)

            say("/start")
            say(res.config.password)
            await until(lambda: any(t.startswith("Send one document") for t in api.texts(owner)), 30)
            say("Settings")
            await until(lambda: any(a == "create" for a, _ in
                                    service.application.settings.session(owner).buttons.values()), 30)
            settings_click("create")
            await until(lambda: service.application.settings.session(owner).state == "instruction", 30)
            say("For invoices extract the printed invoice number and the invoice date in YYYY-MM-DD format.")
            await until(lambda: service.application.settings.session(owner).state == "compiling", 30)
            await until(lambda: service.application.settings.session(owner).state in ("preview", "instruction")
                        and service.application.settings.session(owner).operation is None, 600)
            summary["settings_preview"] = service.application.settings.session(owner).state == "preview"
            settings_click("save")
            await until(lambda: any(t == "Profiles saved." for t in api.texts(owner)), 60)
            profiles = await res.storage.list_profiles(owner)
            summary["settings_profiles_saved"] = len(profiles)

            def results():
                return [t for t in api.texts(owner) if t.startswith("Result:")]

            begin = time.monotonic()
            api.message(owner, document={"file_id": "invoice-file", "file_unique_id": "f1",
                                         "file_name": "invoice.png", "mime_type": "image/png",
                                         "file_size": len(invoice)})
            await until(lambda: results() and owner not in documents.jobs, 900)
            summary["file_path_s"] = round(time.monotonic() - begin, 1)
            text = results()[-1]
            summary["file_path_result"] = text.splitlines()[0]
            summary["file_path_invoice_number_exact"] = INVOICE_NUMBER in text
            summary["file_path_invoice_date_exact"] = INVOICE_DATE in text

            begin = time.monotonic()
            api.message(owner, photo=[{"file_id": "invoice-photo", "file_unique_id": "p1", "width": 620,
                                       "height": 877, "file_size": len(files["invoice-photo"])}])
            await until(lambda: len(results()) == 2 and owner not in documents.jobs, 900)
            summary["photo_path_s"] = round(time.monotonic() - begin, 1)
            summary["photo_path_result"] = results()[-1].splitlines()[0]
            summary["photo_path_invoice_number_exact"] = INVOICE_NUMBER in results()[-1]

            # A different type: matching should not choose the invoice profile.
            begin = time.monotonic()
            api.message(owner, document={"file_id": "receipt-file", "file_unique_id": "f2",
                                         "file_name": "receipt.png", "mime_type": "image/png",
                                         "file_size": len(receipt)})
            await until(lambda: owner in documents.jobs, 30)
            await until(lambda: owner not in documents.jobs or documents.jobs[owner].state in (
                "awaiting_instruction", "awaiting_choice"), 900)
            job = documents.jobs.get(owner)
            summary["receipt_matching_state"] = job.state if job else "finished"
            if job is not None and job.state == "awaiting_choice":
                click(lambda a: a == "instruct")
                await until(lambda: documents.jobs[owner].state == "awaiting_instruction", 30)
            if owner in documents.jobs:
                say("For cash receipts extract the printed total amount as a number.")
                await until(lambda: owner not in documents.jobs or documents.jobs[owner].state == "compiling", 30)
                await until(lambda: owner not in documents.jobs or documents.jobs[owner].state in (
                    "awaiting_confirmation", "awaiting_instruction"), 600)
                job = documents.jobs.get(owner)
                summary["receipt_instruction_state"] = job.state if job else "finished"
                if job is not None and job.state == "awaiting_confirmation":
                    click(lambda a: isinstance(a, tuple) and a[0] == "save")
                    await until(lambda: len(results()) == 3 and owner not in documents.jobs, 900)
                    summary["receipt_result"] = results()[-1].splitlines()[0]
                    summary["receipt_total_exact"] = RECEIPT_TOTAL in results()[-1]
                    summary["receipt_chosen_by_user"] = "(chosen by you)" in results()[-1]
            summary["receipt_path_s"] = round(time.monotonic() - begin, 1)
            summary["profiles_after"] = len(await res.storage.list_profiles(owner))
            summary["job_directories_left"] = len(list(res.lifecycle.root.glob("job-*")))
            summary["reservations_left"] = len(res.lifecycle._reserved)
            summary["messages_to_user"] = len(api.texts(owner))
            summary["status"] = "completed"
        finally:
            if verbose:
                # Synthetic session only: the bot's own English texts, for diagnosis.
                summary["bot_texts"] = [t[:300] for t in api.texts(owner)]
            stop.set()
            await running
            await bot.session.close()
            for profile in await res.storage.list_profiles(owner):
                try:
                    await res.storage.delete_profile(owner, profile.id, profile.version)
                except ProfileNotFound:
                    pass
            summary["synthetic_profiles_deleted"] = not await res.storage.list_profiles(owner)
    summary["total_s"] = round(time.monotonic() - started, 1)
    summary["checked_at"] = datetime.now(timezone.utc).isoformat(timespec="seconds")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", required=True, type=Path)
    parser.add_argument("--verbose", action="store_true", help="print the bot's texts to the synthetic user")
    arguments = parser.parse_args()
    summary = {"status": "failed", "telegram_network_requests": 0}
    try:
        asyncio.run(check(arguments.config, summary, arguments.verbose))
    except Exception as error:
        summary["error"] = type(error).__name__
    print(json.dumps(summary, indent=1))
    return 0 if summary.get("status") == "completed" else 1


if __name__ == "__main__":
    raise SystemExit(main())
