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
from services import wireguard as wg_svc
from services import rate_limit
from states import WGCreate
from utils import md

logger = logging.getLogger(__name__)
router = Router()


def _configs_keyboard(wg_cfgs: list[dict], xray_cfgs: list[dict]) -> InlineKeyboardMarkup:
    rows = []
    for c in wg_cfgs:
        rows.append([
            InlineKeyboardButton(
                text=f"🔒 {c['name']} ({c['ip_address']})",
                callback_data=f"resend_wg:{c['id']}",
            ),
            InlineKeyboardButton(text="🗑", callback_data=f"del_wg:{c['id']}"),
        ])
    for c in xray_cfgs:
        rows.append([
            InlineKeyboardButton(
                text=f"⚡ {c['name']}",
                callback_data=f"resend_xray:{c['id']}",
            ),
            InlineKeyboardButton(text="🗑", callback_data=f"del_xray:{c['id']}"),
        ])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def _confirm_keyboard(action: str, config_id: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[[
        InlineKeyboardButton(text="✅ Да, удалить", callback_data=f"{action}:{config_id}"),
        InlineKeyboardButton(text="❌ Отмена",      callback_data="cancel_del"),
    ]])


# ── /new_wg — start FSM ───────────────────────────────────────────────────────

@router.message(Command("new_wg"))
@router.message(F.text == "🔒 Новый WG")
async def cmd_new_wg(message: Message, state: FSMContext) -> None:
    db_user = await db.get_user(message.from_user.id)

    remaining = rate_limit.check_cooldown(message.from_user.id)
    if remaining > 0:
        await message.answer(f"⏳ Подожди {remaining:.0f} сек. перед созданием нового конфига.")
        return

    if not await rate_limit.check_wg_limit(db_user["id"]):
        await message.answer(f"❌ Максимум {cfg.MAX_WG_CONFIGS} WireGuard конфигов на пользователя.")
        return

    await state.set_state(WGCreate.name)
    await message.answer(
        "🔒 *Новый WireGuard конфиг*\n\nВведи название \\(например: _Home PC_, _Phone_\\):",
        parse_mode="MarkdownV2",
        reply_markup=cancel_keyboard(),
    )


@router.message(WGCreate.name)
async def cmd_new_wg_name(message: Message, state: FSMContext) -> None:
    if message.text == "❌ Отмена":
        await state.clear()
        await message.answer("✖️ Отменено.", reply_markup=main_keyboard())
        return

    name = message.text.strip()[:50] or "WireGuard"
    await state.clear()

    db_user = await db.get_user(message.from_user.id)

    remaining = rate_limit.check_cooldown(message.from_user.id)
    if remaining > 0:
        await message.answer(
            f"⏳ Подожди {remaining:.0f} сек. перед созданием нового конфига.",
            reply_markup=main_keyboard(),
        )
        return

    await message.answer("⏳ Создаю конфиг…", reply_markup=main_keyboard())

    try:
        conf_text = await wg_svc.create_peer(db_user["id"], name)
    except Exception:
        logger.exception("create_peer failed for user %s", message.from_user.id)
        await message.answer("❌ Не удалось создать конфиг. Попробуй позже.")
        return

    rate_limit.set_cooldown(message.from_user.id)

    await message.answer_document(
        document=BufferedInputFile(conf_text.encode(), filename=f"{name}.conf"),
        caption=(
            f"✅ *{md(name)}* — WireGuard конфиг\n\n"
            f"Используй приложение *AmneziaVPN* для подключения\\."
        ),
        parse_mode="MarkdownV2",
    )

    qr = qrcode.make(conf_text)
    buf = io.BytesIO()
    qr.save(buf, format="PNG")
    buf.seek(0)
    await message.answer_photo(
        photo=BufferedInputFile(buf.read(), filename="qr.png"),
        caption="📱 QR\\-код для AmneziaVPN",
        parse_mode="MarkdownV2",
    )


# ── /my_configs — unified view ────────────────────────────────────────────────

@router.message(Command("my_configs"))
@router.message(F.text == "📁 Мои конфиги")
async def cmd_my_configs(message: Message) -> None:
    db_user = await db.get_user(message.from_user.id)
    wg_cfgs   = await db.get_wg_configs(db_user["id"])
    xray_cfgs = await db.get_xray_configs(db_user["id"])

    if not wg_cfgs and not xray_cfgs:
        await message.answer(
            "У тебя нет активных конфигов\\.\n\nСоздай через кнопки ниже\\.",
            parse_mode="MarkdownV2",
        )
        return

    lines = ["📁 *Твои конфиги*\n"]
    if wg_cfgs:
        lines.append(f"🔒 WireGuard: {len(wg_cfgs)}")
    if xray_cfgs:
        lines.append(f"⚡ VLESS/Reality: {len(xray_cfgs)}")
    lines.append("\n_Нажми на конфиг — получить повторно_\n_🗑 — удалить_")

    await message.answer(
        "\n".join(lines),
        parse_mode="MarkdownV2",
        reply_markup=_configs_keyboard(wg_cfgs, xray_cfgs),
    )


# ── Delete WG — step 1: confirm ───────────────────────────────────────────────

@router.callback_query(F.data.startswith("del_wg:"))
async def cb_del_wg_confirm(callback: CallbackQuery) -> None:
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

    await callback.message.edit_text(
        f"⚠️ Удалить конфиг *{md(record['name'])}*?\n"
        f"IP: `{md(record['ip_address'])}`\n\n"
        f"Устройства с этим конфигом потеряют доступ\\.",
        parse_mode="MarkdownV2",
        reply_markup=_confirm_keyboard("confirm_del_wg", config_id),
    )
    await callback.answer()


# ── Delete WG — step 2: execute ───────────────────────────────────────────────

@router.callback_query(F.data.startswith("confirm_del_wg:"))
async def cb_del_wg_execute(callback: CallbackQuery) -> None:
    parts = callback.data.split(":")
    if len(parts) != 2 or not parts[1].isdigit():
        await callback.answer("Неверный запрос.", show_alert=True)
        return

    config_id = int(parts[1])
    db_user = await db.get_user(callback.from_user.id)

    await callback.answer("⏳ Удаляю…")
    try:
        ok = await wg_svc.remove_peer(config_id, db_user["id"])
    except Exception:
        logger.exception("remove_peer failed config_id=%s", config_id)
        await callback.message.edit_text("❌ Ошибка при удалении\\. Попробуй позже\\.", parse_mode="MarkdownV2")
        return

    if ok:
        await callback.message.edit_text("✅ WireGuard конфиг удалён\\.", parse_mode="MarkdownV2")
    else:
        await callback.message.edit_text("❌ Конфиг не найден\\.", parse_mode="MarkdownV2")


# ── Shared cancel ─────────────────────────────────────────────────────────────

@router.callback_query(F.data == "cancel_del")
async def cb_cancel_del(callback: CallbackQuery) -> None:
    await callback.message.edit_text("✖️ Отменено\\.", parse_mode="MarkdownV2")
    await callback.answer()
