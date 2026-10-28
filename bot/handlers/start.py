from pathlib import Path

from aiogram import F, Router
from aiogram.filters import Command, CommandStart
from aiogram.types import FSInputFile, InlineKeyboardButton, InlineKeyboardMarkup, Message

import config as cfg
from keyboards import BTN_DONATE, BTN_TG_PROXY, main_keyboard
from middlewares.auth import is_group_member
from utils import md

router = Router()

_DONATE_QR_PATH = Path(__file__).resolve().parent.parent / "assets" / "donate_qr.jpg"

HELP_TEXT = r"""
*Доступные команды:*

/my\_configs — мои устройства

*WireGuard \(AmneziaWG\):*
/new\_wg — создать конфиг

*VLESS / Reality:*
/new\_xray — создать конфиг
/sub — подписка: все VLESS\-конфиги одной ссылкой

*Прокси для Telegram:*
/tg\_proxy — WEB\-прокси \(Telegram Desktop\)

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
        reply_markup=main_keyboard(user.id),
    )


@router.message(Command("help"))
async def cmd_help(message: Message) -> None:
    await message.answer(HELP_TEXT, parse_mode="MarkdownV2", reply_markup=main_keyboard(message.from_user.id))


@router.message(Command("tg_proxy"))
@router.message(F.text == BTN_TG_PROXY)
async def cmd_tg_proxy(message: Message) -> None:
    params = f"server={cfg.TG_WEBPROXY_DOMAIN}&secret={cfg.TG_WEBPROXY_SECRET}"
    await message.answer(
        "📡 *WEB\\-прокси для Telegram*\n\n"
        "Нажми «Подключить» под сообщением\\.\n\n"
        "Если не сработало, скопируй и отправь себе в Избранное, затем нажми:\n"
        f"`tg://webproxy?{md(params)}`\n\n"
        "Или добавь вручную в настройках прокси Telegram, тип — WEB:\n"
        f"Сервер: `{md(cfg.TG_WEBPROXY_DOMAIN)}`\n"
        f"Секрет: `{md(cfg.TG_WEBPROXY_SECRET)}`\n\n"
        "Нужен Telegram Desktop 7\\.1 или новее\\. На Android WEB\\-прокси пока в бете, "
        "на iOS его ещё нет — там используй VLESS или WireGuard\\.",
        parse_mode="MarkdownV2",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[[
            InlineKeyboardButton(text="📡 Подключить", url=f"https://t.me/webproxy?{params}"),
        ]]),
    )


@router.message(Command("donate"))
@router.message(F.text == BTN_DONATE)
async def cmd_donate(message: Message) -> None:
    if not _DONATE_QR_PATH.exists():
        await message.answer("Реквизиты временно недоступны.")
        return

    await message.answer_photo(
        photo=FSInputFile(_DONATE_QR_PATH),
        caption="💛 Спасибо, что пользуешься сервером\\!\n\nЕсли хочешь поддержать — вот реквизиты для перевода\\.",
        parse_mode="MarkdownV2",
        # Scanning a QR code is awkward on the phone the bot is open on
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[[
            InlineKeyboardButton(text="💛 Перевести по ссылке", url=cfg.DONATE_URL),
        ]]) if cfg.DONATE_URL else None,
    )
