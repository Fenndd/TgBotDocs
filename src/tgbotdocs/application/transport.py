"""Telegram adapter. Handlers enqueue events; transport owns network calls."""

import asyncio
from dataclasses import dataclass

from aiogram import Bot, Dispatcher, Router
from aiogram.types import LinkPreviewOptions

from .events import ButtonClick, Event


@dataclass(frozen=True, repr=False)
class Upload:
    file_id: str
    size: int | None
    compressed: bool = False
    media_group_id: str | None = None


class SendSkipped(Exception):
    """The message was withdrawn before its request started; nothing was sent."""


class OrderedTransport:
    """Per-chat FIFO: a user's messages arrive in the order the flows issued them.

    Flows send from short tasks created in transition order; asyncio starts them in
    that order and ``asyncio.Lock`` wakes waiters first-in, first-out. ``guard`` is
    checked when the message's turn comes, so a message queued behind another one
    is withdrawn, not sent, after Cancel; only a request already started may finish.
    """

    def __init__(self, transport):
        self.transport = transport
        self._chats = {}

    def __getattr__(self, name):
        return getattr(self.transport, name)

    async def send(self, owner, text, *, guard=None, **kwargs):
        entry = self._chats.get(owner)
        if entry is None:
            entry = self._chats[owner] = [asyncio.Lock(), 0]
        entry[1] += 1
        try:
            async with entry[0]:
                if guard is not None and not guard():
                    raise SendSkipped
                return await self.transport.send(owner, text, **kwargs)
        finally:
            entry[1] -= 1
            if not entry[1]:
                self._chats.pop(owner, None)


class TelegramTransport:
    def __init__(self, bot: Bot):
        self.bot = bot

    async def send(self, owner, text, *, entities=(), reply_markup=None, guard=None):
        if guard is not None and not guard():
            raise SendSkipped
        return await self.bot.send_message(owner, text, entities=list(entities), parse_mode=None,
                                           link_preview_options=LinkPreviewOptions(is_disabled=True),
                                           reply_markup=reply_markup)

    async def delete(self, owner, message_id):
        try:
            await self.bot.delete_message(owner, message_id)
            return True
        except Exception:
            return False

    async def answer_callback(self, query_id, text=""):
        await self.bot.answer_callback_query(query_id, text=text)

    async def download(self, upload, destination):
        from .download_sink import DownloadError

        if upload.size is not None and upload.size > 20 * 1024 * 1024:
            raise DownloadError("file_too_large")
        file = await self.bot.get_file(upload.file_id)
        if not file.file_path or (file.file_size is not None and file.file_size > 20 * 1024 * 1024):
            raise DownloadError("download_failed")
        await self.bot.download_file(file.file_path, destination=destination, seek=False)


def dispatcher(application):
    router = Router()

    @router.message()
    async def message(message, event_update):
        if message.chat.type != "private" or message.from_user is None:
            if message.chat.type != "private" and hasattr(application, "nonprivate"):
                application.nonprivate(message.chat.id)
            return
        owner = message.from_user.id
        common = dict(owner=owner, update_id=event_update.update_id, message_id=message.message_id,
                      created_at=message.date)
        if message.photo:
            photo = max(message.photo, key=lambda x: x.width * x.height)
            payload = Upload(photo.file_id, photo.file_size, True, message.media_group_id)
            application.submit(Event("file", payload=payload, **common))
        elif message.document:
            document = message.document
            payload = Upload(document.file_id, document.file_size, False, message.media_group_id)
            application.submit(Event("file", payload=payload, **common))
        else:
            application.submit(Event("text", payload=message.text or "", **common))

    @router.callback_query()
    async def callback(query, event_update):
        if query.message is None or query.message.chat.type != "private":
            return
        application.submit(Event("callback", query.from_user.id, update_id=event_update.update_id,
                                 payload=ButtonClick(query.data or "", query.id)))

    result = Dispatcher()
    result.include_router(router)
    return result
