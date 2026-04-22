import io
import logging

import qrcode
from aiogram import Router, F
from aiogram.filters import Command
from aiogram.types import (
    Message, CallbackQuery,
    InlineKeyboardMarkup, InlineKeyboardButton,
    BufferedInputFile,
)

import database as db
from services import wireguard as wg_svc
from services.xray_service import get_vless_link
from utils import md

logger = logging.getLogger(__name__)
router = Router()


@router.message(Command("resend"))
async def cmd_resend(message: Message) -> None:
    db_user = await db.get_user(message.from_user.id)
    wg_cfgs   = await db.get_wg_configs(db_user["id"])
    xray_cfgs = await db.get_xray_configs(db_user["id"])

    if not wg_cfgs and not xray_cfgs:
        await message.answer("У тебя нет активных конфигов\\.", parse_mode="MarkdownV2")
        return

    buttons = [
        [InlineKeyboardButton(text=f"🔒 {c['name']} ({c['ip_address']})",
                              callback_data=f"resend_wg:{c['id']}")]
        for c in wg_cfgs
    ] + [
        [InlineKeyboardButton(text=f"⚡ {c['name']}",
                              callback_data=f"resend_xray:{c['id']}")]
        for c in xray_cfgs
    ]

    await message.answer(
        "📤 Выбери конфиг для повторной отправки:",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=buttons),
    )


@router.callback_query(F.data.startswith("resend_wg:"))
async def cb_resend_wg(callback: CallbackQuery) -> None:
    parts = callback.data.split(":")
    if len(parts) != 2 or not parts[1].isdigit():
        await callback.answer("Неверный запрос.", show_alert=True)
        return

    config_id = int(parts[1])
    db_user = await db.get_user(callback.from_user.id)
    record = await db.get_wg_config_by_id(config_id, db_user["id"])

    if not record:
        await callback.answer("Конфиг не найден.", show_alert=True)
        return

    await callback.answer("⏳ Отправляю…")

    try:
        conf_text = await wg_svc.get_peer_conf_text(record)
    except Exception:
        logger.exception("get_peer_conf_text failed config_id=%s", config_id)
        await callback.message.answer("❌ Не удалось восстановить конфиг\\.", parse_mode="MarkdownV2")
        return

    await callback.message.answer_document(
        document=BufferedInputFile(conf_text.encode(), filename=f"{record['name']}.conf"),
        caption=f"🔒 *{md(record['name'])}* — WireGuard конфиг",
        parse_mode="MarkdownV2",
    )

    qr = qrcode.make(conf_text)
    buf = io.BytesIO()
    qr.save(buf, format="PNG")
    buf.seek(0)
    await callback.message.answer_photo(
        photo=BufferedInputFile(buf.read(), filename="qr.png"),
        caption=f"📱 QR для *{md(record['name'])}*",
        parse_mode="MarkdownV2",
    )


@router.callback_query(F.data.startswith("resend_xray:"))
async def cb_resend_xray(callback: CallbackQuery) -> None:
    parts = callback.data.split(":")
    if len(parts) != 2 or not parts[1].isdigit():
        await callback.answer("Неверный запрос.", show_alert=True)
        return

    config_id = int(parts[1])
    db_user = await db.get_user(callback.from_user.id)
    record = await db.get_xray_config_by_id(config_id, db_user["id"])

    if not record:
        await callback.answer("Конфиг не найден.", show_alert=True)
        return

    await callback.answer("⏳ Отправляю…")

    link = get_vless_link(record)

    await callback.message.answer(
        f"⚡ *{md(record['name'])}* — VLESS/Reality конфиг\n\n`{md(link)}`",
        parse_mode="MarkdownV2",
    )

    qr = qrcode.make(link)
    buf = io.BytesIO()
    qr.save(buf, format="PNG")
    buf.seek(0)
    await callback.message.answer_photo(
        photo=BufferedInputFile(buf.read(), filename="qr.png"),
        caption=f"📱 QR для *{md(record['name'])}*",
        parse_mode="MarkdownV2",
    )
