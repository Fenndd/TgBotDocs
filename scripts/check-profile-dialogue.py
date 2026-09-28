"""Opt-in real local model/PostgreSQL check using a controlled Telegram transport."""

import argparse
import asyncio
import json
from pathlib import Path
import secrets

from tgbotdocs.application.bootstrap import resources
from tgbotdocs.application.compiler import InstructionCompiler
from tgbotdocs.application.events import ButtonClick, Event
from tgbotdocs.application.product import ProductApplication
from tgbotdocs.storage import ProfileNotFound


class ControlledTransport:
    """Never constructs a Telegram client and never retains message content."""

    def __init__(self):
        self.messages, self.deletions, self.callback_answers = 0, 0, 0

    async def send(self, owner, text, **kwargs):
        self.messages += 1

    async def delete(self, owner, message_id):
        self.deletions += 1
        return True

    async def answer_callback(self, query_id, text):
        self.callback_answers += 1


async def settle(application):
    async with asyncio.timeout(360):
        while True:
            for actor in tuple(application.actors.values()):
                await actor.mailbox.join()
            await asyncio.sleep(0.01)
            if not application.tasks and not application.settings.tasks:
                return


async def check(source):
    owner = 10**18 + secrets.randbelow(10**18)
    async with resources(source) as r:
        assert not await r.storage.list_profiles(owner), "synthetic_owner_collision"
        compiler = InstructionCompiler(r.adapter, r.scheduler)
        transport = ControlledTransport()
        application = ProductApplication(r.config, transport, r.storage, compiler)
        identifiers = set()
        try:
            for text in ("/start", r.config.password, "Settings"):
                application.submit(Event("text", owner, message_id=1, payload=text))
                await settle(application)

            def click(action):
                token = next(t for t, (a, _) in application.settings.session(owner).buttons.items() if a == action)
                application.submit(Event("callback", owner, payload=ButtonClick(token, "synthetic-query")))

            click("create")
            await settle(application)
            instruction = ("For synthetic invoices extract the printed invoice number and a flat line-item list "
                           "with item name and quantity. For synthetic certificates extract the certificate "
                           "number and the printed issue date in YYYY-MM-DD format.")
            application.submit(Event("text", owner, payload=instruction))
            await settle(application)
            session = application.settings.session(owner)
            assert session.state == "preview", "supported_instruction_did_not_preview"
            drafts, nonce = session.preview.drafts, session.preview.nonce
            assert len(drafts) == 2, "two_types_not_preserved"
            assert sum(field.type == "list" for p in drafts for field in p.fields) == 1, "list_not_preserved"
            assert all(p.owner == str(owner) and p.original_instruction == instruction for p in drafts), "identity_contract"
            identifiers.update(p.id for p in drafts)
            click("save")
            await settle(application)
            rows = await r.storage.list_profiles(owner)
            assert {p.id: p for p in rows} == {p.id: p for p in drafts}, "atomic_save_readback"
            assert await application.settings.previews.confirm(owner, nonce) == drafts, "double_confirmation"
            assert len(await r.storage.list_profiles(owner)) == 2, "duplicate_profiles"
            unsupported = await compiler.compile(owner, "Extract nested orders containing nested line-item "
                "lists and calculate the average price from all rows.")
            assert not unsupported.drafts and unsupported.questions, "unsupported_request_was_simplified"
            for p in rows:
                preview = await application.settings.previews.begin_delete(owner, p.id)
                await application.settings.previews.confirm_delete(owner, preview.nonce)
            assert not await r.storage.list_profiles(owner), "synthetic_profile_cleanup"
            return {"status": "verified", "profile_count": 2, "list_count": 1,
                    "unsupported_question_count": len(unsupported.questions), "telegram_calls": 0}
        finally:
            await application.close()
            for identifier in identifiers:
                try:
                    p = await r.storage.get_profile(owner, identifier)
                except ProfileNotFound:
                    continue
                await r.storage.delete_profile(owner, identifier, p.version)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", required=True, type=Path)
    arguments = parser.parse_args()
    try:
        result = asyncio.run(check(arguments.config))
    except Exception:
        print(json.dumps({"status": "failed", "code": "profile_dialogue_check_failed", "telegram_calls": 0}))
        return 1
    print(json.dumps(result))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
