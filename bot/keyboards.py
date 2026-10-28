from aiogram.types import (
    ReplyKeyboardMarkup, KeyboardButton, ReplyKeyboardRemove,
    InlineKeyboardMarkup, InlineKeyboardButton,
)

import config as cfg

# Reply keyboard labels; handlers match on these exact texts
BTN_CONNECT  = "➕ Подключить устройство"
BTN_CONFIGS  = "📁 Мои устройства"
BTN_TRAFFIC  = "📊 Трафик"
BTN_SUB      = "🔗 Подписка"
BTN_TG_PROXY = "📡 Прокси для Telegram"
BTN_DONATE   = "💛 Поддержать"
BTN_ADMIN    = "🛠 Админка"
BTN_CANCEL   = "❌ Отмена"

_AMNEZIA_URL = "https://amnezia.org/downloads"
_KARING_URL  = "https://karing.app/download"
_HIDDIFY_URL = "https://hiddify.com"


def main_keyboard(user_id: int) -> ReplyKeyboardMarkup:
    rows = [
        [KeyboardButton(text=BTN_CONNECT), KeyboardButton(text=BTN_CONFIGS)],
        [KeyboardButton(text=BTN_TRAFFIC), KeyboardButton(text=BTN_SUB)],
        [KeyboardButton(text=BTN_TG_PROXY), KeyboardButton(text=BTN_DONATE)],
    ]
    if user_id in cfg.ADMIN_IDS:
        rows.append([KeyboardButton(text=BTN_ADMIN)])
    return ReplyKeyboardMarkup(keyboard=rows, resize_keyboard=True, persistent=True)


def cancel_keyboard() -> ReplyKeyboardMarkup:
    return ReplyKeyboardMarkup(
        keyboard=[[KeyboardButton(text=BTN_CANCEL)]],
        resize_keyboard=True,
    )


def protocol_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🔒 WireGuard — весь телефон или ПК", callback_data="new:wg")],
        [InlineKeyboardButton(text="⚡ VLESS — лучше обходит блокировки", callback_data="new:xray")],
    ])


def back_to_list_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[[
        InlineKeyboardButton(text="← К списку", callback_data="cfg_list"),
    ]])


def wg_apps_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[[
        InlineKeyboardButton(text="📲 Скачать AmneziaVPN", url=_AMNEZIA_URL),
    ]])


def vless_apps_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[[
        InlineKeyboardButton(text="📲 Karing", url=_KARING_URL),
        InlineKeyboardButton(text="📲 Hiddify", url=_HIDDIFY_URL),
    ]])


remove_keyboard = ReplyKeyboardRemove()
