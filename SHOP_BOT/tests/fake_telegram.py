"""Soxta Telegram sessiyasi — handler oqimlarini tarmoqsiz (offline) sinash uchun.

Bu yordamchi bilan haqiqiy `Dispatcher` ishlaydi: middleware'lar, filterlar,
FSM va handler'lar — hammasi haqiqiy, faqat Bot API chaqiruvlari ushlab
olinadi va oldindan tayyorlangan javoblar qaytariladi.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any, AsyncGenerator

from aiogram import Bot, Dispatcher
from aiogram.client.session.base import BaseSession
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.methods import TelegramMethod
from aiogram.types import (
    CallbackQuery,
    Chat,
    ChatMemberAdministrator,
    ChatMemberLeft,
    ChatMemberMember,
    ChatMemberUpdated,
    Message,
    PhotoSize,
    Update,
    User as TgUser,
)

from app.handlers import build_root_router
from app.middlewares import DbSessionMiddleware, UserContextMiddleware

BOT_ID = 424242
ADMIN_ID = 111111
GROUP_CHAT_ID = -1002003004000
GROUP_TITLE = "📱 Telefonlar bozori"

# Natijasi Message bo'ladigan metodlar
_MESSAGE_METHODS = {
    "SendMessage",
    "EditMessageText",
    "EditMessageCaption",
    "EditMessageMedia",
    "EditMessageReplyMarkup",
    "SendPhoto",
    "SendDocument",
    "SendVideo",
    "SendAnimation",
    "SendLocation",
    "CopyMessage",
}


class FakeSession(BaseSession):
    """Bot API chaqiruvlarini yozib boradigan va oldindan belgilangan
    javoblarni qaytaradigan sessiya."""

    def __init__(self, **overrides: Any) -> None:
        super().__init__()
        self.calls: list[tuple[str, dict[str, Any]]] = []
        self.overrides = overrides
        self.errors: dict[str, Exception] = {}

    # ── BaseSession talablari ─────────────────────────────────────
    async def close(self) -> None:  # pragma: no cover
        return None

    async def stream_content(  # pragma: no cover
        self,
        url: str,
        headers: dict[str, Any] | None = None,
        timeout: int = 30,
        chunk_size: int = 65536,
        raise_for_status: bool = True,
    ) -> AsyncGenerator[bytes, None]:
        yield b""

    async def make_request(
        self,
        bot: Bot,
        method: TelegramMethod[Any],
        timeout: int | None = None,
    ) -> Any:
        name = type(method).__name__
        payload = method.model_dump(exclude_none=True)
        self.calls.append((name, payload))

        if name in self.errors:
            raise self.errors[name]

        if name in self.overrides:
            override = self.overrides[name]
            return override(payload) if callable(override) else override

        if name == "GetChatMember":
            return self._chat_member(payload)
        if name == "GetChatMemberCount":
            return 1234
        if name == "GetChat":
            return self._chat(payload.get("chat_id"))
        if name == "GetMe":
            return self._bot_user()
        if name == "SendMediaGroup":
            return [self._message(payload, index).as_(bot) for index in range(3)]
        if name in _MESSAGE_METHODS:
            # Real aiogram xulqi: sessiya qaytargan obyekt botga bog'lanadi
            # (aks holda `.edit_text()` ishlamaydi)
            return self._message(payload).as_(bot)

        return True

    # ── Yordamchilar ──────────────────────────────────────────────
    def _bot_user(self) -> TgUser:
        return TgUser(id=BOT_ID, is_bot=True, first_name="ShopBot", username="shopbot")

    def _chat(self, chat_id: Any) -> Chat:
        if isinstance(chat_id, int) and chat_id == GROUP_CHAT_ID:
            return Chat(id=GROUP_CHAT_ID, type="supergroup", title=GROUP_TITLE)
        return Chat(id=ADMIN_ID, type="private", first_name="Admin")

    def _message(self, payload: dict[str, Any], index: int = 0) -> Message:
        chat_id = payload.get("chat_id")
        chat = self._chat(chat_id)
        return Message(
            message_id=500 + index,
            date=datetime.now(UTC),
            chat=chat,
            text=payload.get("text") or payload.get("caption"),
        )

    def _chat_member(self, payload: dict[str, Any]) -> Any:
        """Bot uchun — admin; boshqa foydalanuvchilar uchun — a'zo emas."""
        if payload.get("user_id") == BOT_ID:
            return bot_member(is_admin=True)
        return ChatMemberLeft(user=self._bot_user(), status="left")

    # ── Tekshirish uchun ─────────────────────────────────────────
    def sent_texts(self) -> list[str]:
        return [
            payload.get("text") or payload.get("caption") or ""
            for name, payload in self.calls
            if name in _MESSAGE_METHODS
        ]

    def edited_texts(self) -> list[str]:
        return [payload.get("text", "") for name, payload in self.calls if name == "EditMessageText"]

    def answers(self) -> list[str]:
        return [payload.get("text", "") for name, payload in self.calls if name == "AnswerCallbackQuery"]

    def called(self, name: str) -> list[dict[str, Any]]:
        return [payload for method, payload in self.calls if method == name]

    def reset(self) -> None:
        self.calls.clear()


def make_bot(fake: FakeSession) -> Bot:
    return Bot(token="123456789:" + "A" * 35, session=fake)


# Router daraxti bir marta quriladi (aiogram router'ni faqat bir marta
# ulashga ruxsat beradi) va barcha testlarda qayta ishlatiladi.
_DISPATCHER: Dispatcher | None = None


def make_dispatcher() -> Dispatcher:
    """Haqiqiy router daraxti + DB/user kontekst middleware'lari (Redis kerak emas)."""
    global _DISPATCHER
    if _DISPATCHER is None:
        dp = Dispatcher(storage=MemoryStorage())
        dp.update.outer_middleware(DbSessionMiddleware())
        dp.update.outer_middleware(UserContextMiddleware())
        dp.include_router(build_root_router())
        _DISPATCHER = dp
    return _DISPATCHER


async def reset_dispatcher_state() -> None:
    """Testlar orasida FSM holati va admin keshini tozalash."""
    from app.middlewares.user_context import invalidate_admin_cache

    invalidate_admin_cache()
    if _DISPATCHER is not None and isinstance(_DISPATCHER.storage, MemoryStorage):
        _DISPATCHER.storage.storage.clear()


def admin_user(user_id: int = ADMIN_ID) -> TgUser:
    return TgUser(id=user_id, is_bot=False, first_name="Admin", username="admin")


def private_chat(user_id: int = ADMIN_ID) -> Chat:
    return Chat(id=user_id, type="private", first_name="Admin")


def group_chat() -> Chat:
    return Chat(id=GROUP_CHAT_ID, type="supergroup", title=GROUP_TITLE, username="telefonlar_bozori")


# ── Update yasash ─────────────────────────────────────────────────
def callback_update(data: str, *, message_text: str = "panel", user_id: int = ADMIN_ID, update_id: int = 1) -> Update:
    """Private chatdagi inline tugma bosilishi."""
    chat = private_chat(user_id)
    return Update(
        update_id=update_id,
        callback_query=CallbackQuery(
            id=str(update_id),
            from_user=admin_user(user_id),
            chat_instance="test-instance",
            data=data,
            message=Message(
                message_id=1000 + update_id,
                date=datetime.now(UTC),
                chat=chat,
                text=message_text,
                from_user=TgUser(id=BOT_ID, is_bot=True, first_name="ShopBot"),
            ),
        ),
    )


def text_update(text: str, *, user_id: int = ADMIN_ID, update_id: int = 1) -> Update:
    """Private chatda yuborilgan matn (FSM qadamlari uchun)."""
    return Update(
        update_id=update_id,
        message=Message(
            message_id=2000 + update_id,
            date=datetime.now(UTC),
            chat=private_chat(user_id),
            from_user=admin_user(user_id),
            text=text,
        ),
    )


def photo_update(
    *,
    file_id: str = "AgADfake-photo",
    file_unique_id: str | None = None,
    caption: str | None = None,
    user_id: int = ADMIN_ID,
    update_id: int = 1,
    width: int = 1280,
    height: int = 960,
) -> Update:
    """Private chatda yuborilgan rasm (e'lon ustasi uchun).

    `file_id` dan `file_unique_id` avtomatik yasaladi (Telegram'da ular
    har xil, lekin testda izchil bo'lishi yetarli).
    """
    unique = file_unique_id or f"AQAD{abs(hash(file_id)) % 10**12}"
    return Update(
        update_id=update_id,
        message=Message(
            message_id=3000 + update_id,
            date=datetime.now(UTC),
            chat=private_chat(user_id),
            from_user=admin_user(user_id),
            caption=caption,
            photo=[
                PhotoSize(file_id=file_id, file_unique_id=unique, width=90, height=67),
                PhotoSize(file_id=file_id, file_unique_id=unique, width=width, height=height),
            ],
        ),
    )


def bot_member(*, is_admin: bool = True) -> Any:
    """Botning guruhdagi holati (admin yoki oddiy a'zo)."""
    bot_user = TgUser(id=BOT_ID, is_bot=True, first_name="ShopBot", username="shopbot")
    if not is_admin:
        return ChatMemberMember(user=bot_user, status="member")
    return ChatMemberAdministrator(
        user=bot_user,
        status="administrator",
        can_be_edited=False,
        is_anonymous=False,
        can_manage_chat=True,
        can_delete_messages=True,
        can_manage_video_chats=True,
        can_restrict_members=True,
        can_promote_members=False,
        can_change_info=True,
        can_invite_users=True,
        can_pin_messages=True,
        can_post_stories=True,
        can_edit_stories=True,
        can_delete_stories=True,
        can_send_welcome_messages=True,
    )


def bot_added_update(*, is_admin: bool = True, update_id: int = 1, chat: Chat | None = None) -> Update:
    """Bot guruhga qo'shildi (my_chat_member)."""
    return Update(
        update_id=update_id,
        my_chat_member=ChatMemberUpdated(
            chat=chat or group_chat(),
            from_user=admin_user(),
            date=datetime.now(UTC),
            old_chat_member=ChatMemberLeft(
                user=TgUser(id=BOT_ID, is_bot=True, first_name="ShopBot"), status="left"
            ),
            new_chat_member=bot_member(is_admin=is_admin),
        ),
    )


def bot_removed_update(*, update_id: int = 1) -> Update:
    """Bot guruhdan chiqarildi (my_chat_member → left)."""
    return Update(
        update_id=update_id,
        my_chat_member=ChatMemberUpdated(
            chat=group_chat(),
            from_user=admin_user(),
            date=datetime.now(UTC),
            old_chat_member=bot_member(is_admin=True),
            new_chat_member=ChatMemberLeft(
                user=TgUser(id=BOT_ID, is_bot=True, first_name="ShopBot"), status="left"
            ),
        ),
    )
