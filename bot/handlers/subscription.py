import logging

from aiogram import Router, F
from aiogram.filters import Command
from aiogram.types import Message, CallbackQuery, InlineKeyboardMarkup, InlineKeyboardButton

import database as db
from keyboards import BTN_SUB
from services.subscription import subscription_url
from utils import md

logger = logging.getLogger(__name__)
router = Router()

_RESET_KEYBOARD = InlineKeyboardMarkup(inline_keyboard=[[
    InlineKeyboardButton(text="🔄 Сбросить ссылку", callback_data="sub_reset"),
]])


def _sub_text(token: str) -> str:
    return (
        "🔗 *Подписка на VLESS\\-конфиги*\n\n"
        f"`{md(subscription_url(token))}`\n\n"
        "Добавь ссылку в приложение как подписку \\(Karing, Hiddify, v2rayNG, Streisand\\)\\. "
        "Оно само подтянет все твои VLESS\\-конфиги и будет обновлять их — "
        "новые и изменённые появятся без переотправки ссылок\\.\n\n"
        "Ссылка личная, не пересылай её\\. Если она утекла — сбрось, старая перестанет работать\\."
    )


@router.message(Command("sub"))
@router.message(F.text == BTN_SUB)
async def cmd_sub(message: Message) -> None:
    db_user = await db.get_user(message.from_user.id)
    token = await db.get_sub_token(db_user["id"])
    await message.answer(_sub_text(token), parse_mode="MarkdownV2", reply_markup=_RESET_KEYBOARD)


@router.callback_query(F.data == "sub_reset")
async def cb_sub_reset(callback: CallbackQuery) -> None:
    db_user = await db.get_user(callback.from_user.id)
    token = await db.reset_sub_token(db_user["id"])
    logger.info("Subscription token reset for user_id=%s", db_user["id"])
    await callback.answer("Ссылка сброшена.")
    await callback.message.edit_text(
        "✅ Старая ссылка больше не работает\\. Новая:\n\n" + _sub_text(token),
        parse_mode="MarkdownV2",
        reply_markup=_RESET_KEYBOARD,
    )
