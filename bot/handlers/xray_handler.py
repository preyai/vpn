import io
import logging

import qrcode
from aiogram import Router, F
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.types import (
    Message, CallbackQuery,
    InlineKeyboardMarkup, InlineKeyboardButton,
    BufferedInputFile,
)

import config as cfg
import database as db
from keyboards import main_keyboard, cancel_keyboard
from services import xray_service as xray_svc
from services import rate_limit
from states import XrayCreate
from utils import md

logger = logging.getLogger(__name__)
router = Router()


def _confirm_keyboard(config_id: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[[
        InlineKeyboardButton(text="✅ Да, удалить", callback_data=f"confirm_del_xray:{config_id}"),
        InlineKeyboardButton(text="❌ Отмена",      callback_data="cancel_del"),
    ]])


# ── /new_xray — start FSM ─────────────────────────────────────────────────────

@router.message(Command("new_xray"))
@router.message(F.text == "⚡ Новый VLESS")
async def cmd_new_xray(message: Message, state: FSMContext) -> None:
    db_user = await db.get_user(message.from_user.id)

    remaining = rate_limit.check_cooldown(message.from_user.id)
    if remaining > 0:
        await message.answer(f"⏳ Подожди {remaining:.0f} сек. перед созданием нового конфига.")
        return

    if not await rate_limit.check_xray_limit(db_user["id"]):
        await message.answer(f"❌ Максимум {cfg.MAX_XRAY_CONFIGS} VLESS конфигов на пользователя.")
        return

    await state.set_state(XrayCreate.name)
    await message.answer(
        "⚡ *Новый VLESS/Reality конфиг*\n\nВведи название \\(например: _Phone_, _Laptop_\\):",
        parse_mode="MarkdownV2",
        reply_markup=cancel_keyboard(),
    )


@router.message(XrayCreate.name)
async def cmd_new_xray_name(message: Message, state: FSMContext) -> None:
    if message.text == "❌ Отмена":
        await state.clear()
        await message.answer("✖️ Отменено.", reply_markup=main_keyboard())
        return

    name = message.text.strip()[:50] or "VLESS"
    await state.clear()

    db_user = await db.get_user(message.from_user.id)

    remaining = rate_limit.check_cooldown(message.from_user.id)
    if remaining > 0:
        await message.answer(
            f"⏳ Подожди {remaining:.0f} сек. перед созданием нового конфига.",
            reply_markup=main_keyboard(),
        )
        return

    await message.answer("⏳ Создаю конфиг, применяю изменения в Xray…", reply_markup=main_keyboard())

    try:
        link = await xray_svc.create_vless_config(db_user["id"], name)
    except Exception:
        logger.exception("create_vless_config failed for user %s", message.from_user.id)
        await message.answer("❌ Не удалось создать конфиг. Попробуй позже.")
        return

    rate_limit.set_cooldown(message.from_user.id)

    await message.answer(
        f"✅ *{md(name)}* — VLESS/Reality конфиг\n\n"
        f"Скопируй ссылку в клиент \\(v2rayNG, Hiddify, Streisand\\):\n\n"
        f"`{md(link)}`",
        parse_mode="MarkdownV2",
    )

    qr = qrcode.make(link)
    buf = io.BytesIO()
    qr.save(buf, format="PNG")
    buf.seek(0)
    await message.answer_photo(
        photo=BufferedInputFile(buf.read(), filename="qr.png"),
        caption="📱 QR\\-код для импорта в клиент",
        parse_mode="MarkdownV2",
    )


# ── Delete Xray — step 1: confirm ────────────────────────────────────────────

@router.callback_query(F.data.startswith("del_xray:"))
async def cb_del_xray_confirm(callback: CallbackQuery) -> None:
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

    await callback.message.edit_text(
        f"⚠️ Удалить конфиг *{md(record['name'])}*?\n\n"
        f"Устройства с этим конфигом потеряют доступ\\.",
        parse_mode="MarkdownV2",
        reply_markup=_confirm_keyboard(config_id),
    )
    await callback.answer()


# ── Delete Xray — step 2: execute ────────────────────────────────────────────

@router.callback_query(F.data.startswith("confirm_del_xray:"))
async def cb_del_xray_execute(callback: CallbackQuery) -> None:
    parts = callback.data.split(":")
    if len(parts) != 2 or not parts[1].isdigit():
        await callback.answer("Неверный запрос.", show_alert=True)
        return

    config_id = int(parts[1])
    db_user = await db.get_user(callback.from_user.id)

    await callback.answer("⏳ Удаляю…")
    try:
        ok = await xray_svc.remove_vless_config(config_id, db_user["id"])
    except Exception:
        logger.exception("remove_vless_config failed config_id=%s", config_id)
        await callback.message.edit_text("❌ Ошибка при удалении\\. Попробуй позже\\.", parse_mode="MarkdownV2")
        return

    if ok:
        await callback.message.edit_text("✅ VLESS конфиг удалён\\.", parse_mode="MarkdownV2")
    else:
        await callback.message.edit_text("❌ Конфиг не найден\\.", parse_mode="MarkdownV2")
