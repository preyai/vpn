"""User menu: choosing a protocol, the device list and per-config cards."""
import logging

from aiogram import Router, F
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.types import Message, CallbackQuery, InlineKeyboardMarkup, InlineKeyboardButton

import database as db
from keyboards import BTN_CANCEL, BTN_CONFIGS, BTN_CONNECT, cancel_keyboard, main_keyboard, protocol_keyboard
from services import rate_limit
from services import traffic as traffic_svc
from states import RenameConfig
from utils import md

logger = logging.getLogger(__name__)
router = Router()

_PROTOCOL_TEXT = (
    "➕ *Подключить устройство*\n\n"
    "🔒 *WireGuard* — защищает весь трафик телефона или компьютера\\. "
    "Приложение AmneziaVPN, один файл или QR\\-код\\.\n\n"
    "⚡ *VLESS* — маскируется под обычный сайт и лучше переживает блокировки\\. "
    "Приложения Karing, Hiddify, v2rayNG, Streisand\\.\n\n"
    "Не знаешь, что выбрать — начни с VLESS\\."
)

_VLESS_ONLY_TEXT = (
    "➕ *Подключить устройство*\n\n"
    "⚡ *VLESS* — маскируется под обычный сайт и хорошо переживает блокировки\\. "
    "Приложения Karing, Hiddify, v2rayNG, Streisand\\.\n\n"
    "Создание новых WireGuard конфигов временно закрыто\\."
)

_KINDS = {"wg": "🔒", "xray": "⚡"}


def _protocol_view(telegram_id: int) -> tuple[str, InlineKeyboardMarkup]:
    with_wg = rate_limit.can_create_wg(telegram_id)
    return _PROTOCOL_TEXT if with_wg else _VLESS_ONLY_TEXT, protocol_keyboard(with_wg)


# ── Connect a device ──────────────────────────────────────────────────────────

@router.message(F.text == BTN_CONNECT)
async def msg_connect(message: Message) -> None:
    text, keyboard = _protocol_view(message.from_user.id)
    await message.answer(text, parse_mode="MarkdownV2", reply_markup=keyboard)


@router.callback_query(F.data == "connect")
async def cb_connect(callback: CallbackQuery) -> None:
    await callback.answer()
    text, keyboard = _protocol_view(callback.from_user.id)
    await callback.message.edit_text(text, parse_mode="MarkdownV2", reply_markup=keyboard)


# ── Device list ───────────────────────────────────────────────────────────────

async def _render_list(telegram_id: int) -> tuple[str, InlineKeyboardMarkup]:
    db_user = await db.get_user(telegram_id)
    wg_cfgs = await db.get_wg_configs(db_user["id"])
    xray_cfgs = await db.get_xray_configs(db_user["id"])

    if not wg_cfgs and not xray_cfgs:
        return (
            "У тебя пока нет подключённых устройств\\.",
            InlineKeyboardMarkup(inline_keyboard=[[
                InlineKeyboardButton(text=BTN_CONNECT, callback_data="connect"),
            ]]),
        )

    rows = [
        [InlineKeyboardButton(text=f"🔒 {c['name']}", callback_data=f"cfg:wg:{c['id']}")]
        for c in wg_cfgs
    ] + [
        [InlineKeyboardButton(text=f"⚡ {c['name']}", callback_data=f"cfg:xray:{c['id']}")]
        for c in xray_cfgs
    ]
    rows.append([InlineKeyboardButton(text=BTN_CONNECT, callback_data="connect")])
    text = (
        f"📁 *Мои устройства* \\({len(wg_cfgs) + len(xray_cfgs)}\\)\n\n"
        "🔒 — WireGuard, ⚡ — VLESS\\. Нажми на устройство, чтобы получить конфиг, "
        "переименовать или удалить\\."
    )
    return text, InlineKeyboardMarkup(inline_keyboard=rows)


@router.message(Command("my_configs"))
@router.message(F.text == BTN_CONFIGS)
async def msg_configs(message: Message) -> None:
    text, keyboard = await _render_list(message.from_user.id)
    await message.answer(text, parse_mode="MarkdownV2", reply_markup=keyboard)


@router.callback_query(F.data == "cfg_list")
async def cb_configs(callback: CallbackQuery) -> None:
    text, keyboard = await _render_list(callback.from_user.id)
    await callback.answer()
    await callback.message.edit_text(text, parse_mode="MarkdownV2", reply_markup=keyboard)


# ── Config card ───────────────────────────────────────────────────────────────

async def _get_config(kind: str, config_id: int, telegram_id: int) -> dict | None:
    db_user = await db.get_user(telegram_id)
    getter = db.get_wg_config_by_id if kind == "wg" else db.get_xray_config_by_id
    return await getter(config_id, db_user["id"])


async def _render_card(kind: str, record: dict) -> tuple[str, InlineKeyboardMarkup]:
    expiry = f"до {record['expires_at'].strftime('%d.%m.%Y')}" if record["expires_at"] else "бессрочно"
    created = record["created_at"].strftime("%d.%m.%Y")

    if kind == "wg":
        u = await traffic_svc.get_wg_config_usage(record)
        lines = [
            f"🔒 *{md(record['name'])}* · WireGuard",
            f"IP: `{md(record['ip_address'])}`",
            f"Последнее подключение: {md(traffic_svc.format_handshake(u['handshake']))}",
        ]
    else:
        u = await traffic_svc.get_xray_config_usage(record)
        lines = [f"⚡ *{md(record['name'])}* · VLESS/Reality"]
    lines += [
        f"Трафик: ↑ `{md(traffic_svc.format_bytes(u['up_total']))}`  ↓ `{md(traffic_svc.format_bytes(u['down_total']))}`",
        f"Создан {md(created)}, {md(expiry)}",
    ]

    cid = record["id"]
    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="📤 Получить заново", callback_data=f"resend_{kind}:{cid}"),
         InlineKeyboardButton(text="📱 QR", callback_data=f"qr_{kind}:{cid}")],
        [InlineKeyboardButton(text="✏️ Переименовать", callback_data=f"rename:{kind}:{cid}"),
         InlineKeyboardButton(text="🗑 Удалить", callback_data=f"del_{kind}:{cid}")],
        [InlineKeyboardButton(text="← К списку", callback_data="cfg_list")],
    ])
    return "\n".join(lines), keyboard


def _parse_kind_id(data: str) -> tuple[str, int] | None:
    """Parses "<prefix>:<wg|xray>:<id>"."""
    parts = data.split(":")
    if len(parts) != 3 or parts[1] not in _KINDS or not parts[2].isdigit():
        return None
    return parts[1], int(parts[2])


@router.callback_query(F.data.startswith("cfg:"))
async def cb_card(callback: CallbackQuery) -> None:
    parsed = _parse_kind_id(callback.data)
    if not parsed:
        await callback.answer("Неверный запрос.", show_alert=True)
        return

    record = await _get_config(*parsed, callback.from_user.id)
    if not record:
        await callback.answer("Конфиг не найден.", show_alert=True)
        return

    await callback.answer()
    text, keyboard = await _render_card(parsed[0], record)
    await callback.message.edit_text(text, parse_mode="MarkdownV2", reply_markup=keyboard)


# ── Rename ────────────────────────────────────────────────────────────────────

@router.callback_query(F.data.startswith("rename:"))
async def cb_rename(callback: CallbackQuery, state: FSMContext) -> None:
    parsed = _parse_kind_id(callback.data)
    if not parsed:
        await callback.answer("Неверный запрос.", show_alert=True)
        return

    record = await _get_config(*parsed, callback.from_user.id)
    if not record:
        await callback.answer("Конфиг не найден.", show_alert=True)
        return

    await callback.answer()
    await state.set_state(RenameConfig.name)
    await state.update_data(kind=parsed[0], config_id=parsed[1])
    await callback.message.answer(
        f"✏️ Новое название для *{md(record['name'])}*:",
        parse_mode="MarkdownV2",
        reply_markup=cancel_keyboard(),
    )


@router.message(RenameConfig.name)
async def msg_rename(message: Message, state: FSMContext) -> None:
    data = await state.get_data()
    await state.clear()
    keyboard = main_keyboard(message.from_user.id)

    if message.text == BTN_CANCEL or not message.text:
        await message.answer("✖️ Отменено.", reply_markup=keyboard)
        return

    kind, config_id = data["kind"], data["config_id"]
    name = message.text.strip()[:50] or ("WireGuard" if kind == "wg" else "VLESS")
    db_user = await db.get_user(message.from_user.id)
    rename = db.rename_wg_config if kind == "wg" else db.rename_xray_config
    if not await rename(config_id, db_user["id"], name):
        await message.answer("❌ Конфиг не найден.", reply_markup=keyboard)
        return

    hint = (
        "Чтобы имя поменялось и в приложении, получи конфиг заново или обнови подписку\\."
        if kind == "xray"
        else "В AmneziaVPN имя не меняется само — его можно поправить в приложении\\."
    )
    await message.answer(f"✅ Переименовано в *{md(name)}*\\. {hint}", parse_mode="MarkdownV2", reply_markup=keyboard)

    record = await _get_config(kind, config_id, message.from_user.id)
    text, card_keyboard = await _render_card(kind, record)
    await message.answer(text, parse_mode="MarkdownV2", reply_markup=card_keyboard)
