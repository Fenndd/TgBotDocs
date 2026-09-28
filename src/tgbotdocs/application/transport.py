"""Telegram adapter. Handlers enqueue events; transport owns network calls."""

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


class TelegramTransport:
    def __init__(self, bot: Bot):
        self.bot = bot

    async def send(self, owner, text, *, entities=(), reply_markup=None):
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
        if upload.size is not None and upload.size > 20 * 1024 * 1024:
            raise ValueError("telegram_file_too_large")
        file = await self.bot.get_file(upload.file_id)
        if not file.file_path or (file.file_size is not None and file.file_size > 20 * 1024 * 1024):
            raise ValueError("telegram_file_unavailable")
        await self.bot.download_file(file.file_path, destination=destination)


def dispatcher(application):
    router = Router()

    @router.message()
    async def message(message, event_update):
        if message.chat.type != "private" or message.from_user is None:
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
