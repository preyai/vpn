"""Answers private messages no other handler took — typos, stickers, and buttons from
an old reply keyboard (e.g. "📡 MTProxy") — with the current menu. Included last."""
from aiogram import Router, F
from aiogram.filters import StateFilter
from aiogram.types import Message

from keyboards import main_keyboard

router = Router()


@router.message(F.chat.type == "private", StateFilter(None))
async def msg_unknown(message: Message) -> None:
    await message.answer("Не понял 🤔 Вот актуальное меню:", reply_markup=main_keyboard(message.from_user.id))
