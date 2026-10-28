from pathlib import Path

from aiogram import F, Router
from aiogram.filters import Command, CommandStart
from aiogram.types import FSInputFile, Message

import config as cfg
from keyboards import main_keyboard
from middlewares.auth import is_group_member
from utils import md

router = Router()

_DONATE_QR_PATH = Path(__file__).resolve().parent.parent / "assets" / "donate_qr.jpg"

HELP_TEXT = r"""
*Доступные команды:*

*WireGuard \(AmneziaWG\):*
/new\_wg — создать конфиг
/my\_configs — список конфигов

*VLESS / Reality:*
/new\_xray — создать конфиг

*Прокси для Telegram:*
/tg\_proxy — HTTP\-прокси \(Telegram Desktop\)

*Статистика:*
/traffic — трафик по всем конфигам

*Поддержать сервер:*
/donate — реквизиты для перевода
"""


@router.message(CommandStart())
async def cmd_start(message: Message) -> None:
    bot = message.bot
    user = message.from_user

    in_group = await is_group_member(bot, user.id)
    if not in_group:
        await message.answer(
            "👋 Привет!\n\n"
            "⛔ Для использования бота нужно быть участником группы.\n"
            "Вступи в группу и попробуй снова."
        )
        return

    await message.answer(
        f"👋 Привет, *{md(user.full_name)}*\\!\n\n"
        "Этот бот управляет твоими VPN\\-конфигурациями\\.\n"
        "Используй кнопки меню или команды ниже\\.\n"
        f"{HELP_TEXT}",
        parse_mode="MarkdownV2",
        reply_markup=main_keyboard(),
    )


@router.message(Command("help"))
async def cmd_help(message: Message) -> None:
    await message.answer(HELP_TEXT, parse_mode="MarkdownV2", reply_markup=main_keyboard())


@router.message(Command("tg_proxy"))
@router.message(F.text == "📡 Прокси для Telegram")
async def cmd_tg_proxy(message: Message) -> None:
    # Telegram has no share link for HTTP proxies, so the settings are entered by hand
    await message.answer(
        "📡 *HTTP\\-прокси для Telegram*\n\n"
        f"Сервер: `{md(cfg.SERVER_IP)}`\n"
        f"Порт: `{cfg.TG_PROXY_PORT}`\n"
        f"Логин: `{md(cfg.TG_PROXY_USER)}`\n"
        f"Пароль: `{md(cfg.TG_PROXY_PASSWORD)}`\n\n"
        "*Telegram Desktop:* Настройки → Продвинутые настройки → Тип соединения → "
        "Использовать собственный прокси → HTTP\\.\n\n"
        "В мобильных приложениях Telegram HTTP\\-прокси нет — там используй VLESS или WireGuard\\.",
        parse_mode="MarkdownV2",
    )


@router.message(Command("donate"))
@router.message(F.text == "💛 Поддержать")
async def cmd_donate(message: Message) -> None:
    if not _DONATE_QR_PATH.exists():
        await message.answer("Реквизиты временно недоступны.")
        return

    await message.answer_photo(
        photo=FSInputFile(_DONATE_QR_PATH),
        caption="💛 Спасибо, что пользуешься сервером\\!\n\nЕсли хочешь поддержать — вот реквизиты для перевода\\.",
        parse_mode="MarkdownV2",
    )
