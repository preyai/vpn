import logging

from aiogram import Router, F
from aiogram.filters import Command
from aiogram.types import Message, CallbackQuery, InlineKeyboardMarkup, InlineKeyboardButton

import config as cfg
import database as db
from services import xray_service as xray_svc
from utils import md

logger = logging.getLogger(__name__)
router = Router()


def _is_admin(user_id: int) -> bool:
    return user_id in cfg.ADMIN_IDS


@router.message(Command("admin_users"))
async def cmd_admin_users(message: Message) -> None:
    if not _is_admin(message.from_user.id):
        return

    users = await db.get_all_users()
    if not users:
        await message.answer("Нет пользователей.")
        return

    lines = ["👥 *Все пользователи:*\n"]
    for u in users:
        name = md(u["full_name"] or u["username"] or "—")
        status = "✅" if u["is_active"] else "🚫"
        username = md(f"@{u['username']}") if u["username"] else f"id:{u['telegram_id']}"
        lines.append(f"{status} {name} \\({username}\\) — id `{u['telegram_id']}`")

    buttons = [
        [
            InlineKeyboardButton(
                text=f"🚫 {u['telegram_id']}",
                callback_data=f"admin_block:{u['telegram_id']}",
            )
            if u["is_active"]
            else InlineKeyboardButton(
                text=f"✅ {u['telegram_id']}",
                callback_data=f"admin_unblock:{u['telegram_id']}",
            )
        ]
        for u in users
        if u["telegram_id"] not in cfg.ADMIN_IDS
    ]

    await message.answer(
        "\n".join(lines),
        parse_mode="MarkdownV2",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=buttons) if buttons else None,
    )


@router.callback_query(F.data.startswith("admin_block:"))
async def cb_admin_block(callback: CallbackQuery) -> None:
    if not _is_admin(callback.from_user.id):
        await callback.answer("⛔ Нет доступа.", show_alert=True)
        return

    parts = callback.data.split(":")
    if len(parts) != 2 or not parts[1].lstrip("-").isdigit():
        await callback.answer("Неверный запрос.", show_alert=True)
        return

    target_id = int(parts[1])
    await db.set_user_active(target_id, False)
    logger.info("Admin %s blocked user %s", callback.from_user.id, target_id)
    await callback.answer(f"Пользователь {target_id} заблокирован.")
    await callback.message.edit_text(
        f"🚫 Пользователь `{target_id}` заблокирован\\.", parse_mode="MarkdownV2"
    )


@router.callback_query(F.data.startswith("admin_unblock:"))
async def cb_admin_unblock(callback: CallbackQuery) -> None:
    if not _is_admin(callback.from_user.id):
        await callback.answer("⛔ Нет доступа.", show_alert=True)
        return

    parts = callback.data.split(":")
    if len(parts) != 2 or not parts[1].lstrip("-").isdigit():
        await callback.answer("Неверный запрос.", show_alert=True)
        return

    target_id = int(parts[1])
    await db.set_user_active(target_id, True)
    logger.info("Admin %s unblocked user %s", callback.from_user.id, target_id)
    await callback.answer(f"Пользователь {target_id} разблокирован.")
    await callback.message.edit_text(
        f"✅ Пользователь `{target_id}` разблокирован\\.", parse_mode="MarkdownV2"
    )


@router.message(Command("admin_rebuild_xray"))
async def cmd_admin_rebuild_xray(message: Message) -> None:
    if not _is_admin(message.from_user.id):
        return
    await message.answer("⏳ Пересобираю конфиг Xray из БД…")
    try:
        await xray_svc.rebuild_xray_config_from_db()
        await message.answer("✅ Готово\\. Xray перезапущен\\.", parse_mode="MarkdownV2")
    except Exception:
        logger.exception("rebuild_xray_config_from_db failed")
        await message.answer("❌ Ошибка\\. Подробности в логах\\.", parse_mode="MarkdownV2")
