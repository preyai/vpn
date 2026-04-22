from typing import Any, Awaitable, Callable
from aiogram import BaseMiddleware
from aiogram.types import TelegramObject, Update, Message, CallbackQuery
from aiogram.enums import ChatMemberStatus

import config as cfg
import database as db


async def is_group_member(bot, user_id: int) -> bool:
    try:
        member = await bot.get_chat_member(cfg.GROUP_ID, user_id)
        return member.status not in (
            ChatMemberStatus.KICKED,
            ChatMemberStatus.LEFT,
        )
    except Exception as e:
        print(f"[AuthMiddleware] get_chat_member error: {e}")
        return False


class AuthMiddleware(BaseMiddleware):
    async def __call__(
        self,
        handler: Callable[[TelegramObject, dict[str, Any]], Awaitable[Any]],
        event: TelegramObject,
        data: dict[str, Any],
    ) -> Any:
        user = None
        if isinstance(event, Message):
            user = event.from_user
        elif isinstance(event, CallbackQuery):
            user = event.from_user

        if user is None:
            return await handler(event, data)

        # Allow /start for non-members so they get an informative message
        if isinstance(event, Message) and event.text and event.text.startswith("/start"):
            return await handler(event, data)

        bot = data["bot"]
        if not await is_group_member(bot, user.id):
            if isinstance(event, Message):
                await event.answer("⛔ Доступ запрещён. Вы должны быть участником группы.")
            elif isinstance(event, CallbackQuery):
                await event.answer("⛔ Доступ запрещён.", show_alert=True)
            return

        db_user = await db.get_user(user.id)
        if db_user and not db_user["is_active"]:
            if isinstance(event, Message):
                await event.answer("⛔ Ваш аккаунт заблокирован.")
            elif isinstance(event, CallbackQuery):
                await event.answer("⛔ Аккаунт заблокирован.", show_alert=True)
            return

        await db.get_or_create_user(user.id, user.username, user.full_name)
        return await handler(event, data)
