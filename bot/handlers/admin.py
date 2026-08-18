import logging
from datetime import datetime, timedelta

from aiogram import Router, F
from aiogram.filters import Command
from aiogram.types import Message, CallbackQuery, InlineKeyboardMarkup, InlineKeyboardButton

import config as cfg
import database as db
from services import status as status_svc
from services import wireguard as wg_svc
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


_STATUS_ICON = {"running": "✅", "missing": "⛔", "error": "⛔"}
_HEALTH_ICON = {"healthy": "✅", "unhealthy": "⚠️", "starting": "⏳", "n/a": ""}


@router.message(Command("status"))
async def cmd_status(message: Message) -> None:
    if not _is_admin(message.from_user.id):
        return

    await message.answer("⏳ Проверяю сервисы…")

    containers = await status_svc.get_container_statuses()
    ports = await status_svc.get_port_checks()

    lines = ["🩺 *Статус сервисов*\n"]
    for label, status, health in containers:
        icon = _STATUS_ICON.get(status, "⚠️")
        health_str = f" \\({md(health)}\\)" if _HEALTH_ICON.get(health) else ""
        lines.append(f"{icon} {md(label)}: `{md(status)}`{health_str}")

    lines.append("")
    for label, ok in ports:
        icon = "✅" if ok else "⛔"
        lines.append(f"{icon} {md(label)}")

    await message.answer("\n".join(lines), parse_mode="MarkdownV2")


@router.message(Command("admin_set_expiry"))
async def cmd_admin_set_expiry(message: Message) -> None:
    if not _is_admin(message.from_user.id):
        return

    parts = (message.text or "").split()
    if len(parts) != 4 or parts[1] not in ("wg", "xray") or not parts[2].isdigit() or not parts[3].lstrip("-").isdigit():
        await message.answer(
            "Использование: `/admin_set_expiry <wg|xray> <id> <дней>`\n"
            "`0` — снять срок действия \\(бессрочно\\)\\.",
            parse_mode="MarkdownV2",
        )
        return

    config_type, config_id, days = parts[1], int(parts[2]), int(parts[3])
    expires_at = None if days <= 0 else datetime.now() + timedelta(days=days)

    setter = db.set_wg_expiry if config_type == "wg" else db.set_xray_expiry
    ok = await setter(config_id, expires_at)

    if not ok:
        await message.answer("❌ Конфиг с таким id не найден.")
        return

    if expires_at is None:
        await message.answer(f"✅ Конфиг {config_type} `{config_id}` теперь бессрочный\\.", parse_mode="MarkdownV2")
    else:
        await message.answer(
            f"✅ Конфиг {config_type} `{config_id}` истечёт {md(expires_at.strftime('%Y-%m-%d %H:%M'))}\\.",
            parse_mode="MarkdownV2",
        )


_cleanup_candidates: dict[int, list[tuple[int, int]]] = {}  # admin telegram_id -> [(config_id, user_id)]


@router.message(Command("admin_cleanup_wg"))
async def cmd_admin_cleanup_wg(message: Message) -> None:
    if not _is_admin(message.from_user.id):
        return

    parts = (message.text or "").split()
    if len(parts) != 2 or not parts[1].isdigit():
        await message.answer(
            "Использование: `/admin_cleanup_wg <дней неактивности>`", parse_mode="MarkdownV2"
        )
        return

    threshold_days = int(parts[1])
    cutoff = datetime.now() - timedelta(days=threshold_days)

    configs = await db.get_all_active_wg_configs()
    try:
        handshakes = await wg_svc.get_peer_handshakes()
    except Exception:
        logger.exception("get_peer_handshakes failed")
        await message.answer("❌ Не удалось получить статистику WireGuard.")
        return

    stale = []
    for c in configs:
        ts = handshakes.get(c["public_key"], 0)
        last_seen = datetime.fromtimestamp(ts) if ts else c["created_at"]
        if last_seen <= cutoff:
            stale.append((c, ts))

    if not stale:
        await message.answer(f"✅ Нет пиров, неактивных более {threshold_days} дн\\.", parse_mode="MarkdownV2")
        return

    _cleanup_candidates[message.from_user.id] = [(c["id"], c["user_id"]) for c, _ in stale]

    lines = [f"🗑 *Неактивны более {threshold_days} дн\\.* \\({len(stale)}\\):\n"]
    for c, ts in stale:
        seen = f"хендшейк {md(datetime.fromtimestamp(ts).strftime('%Y-%m-%d'))}" if ts else "никогда не подключался"
        lines.append(f"• {md(c['name'])} \\(id {c['id']}\\) — {seen}")

    await message.answer(
        "\n".join(lines),
        parse_mode="MarkdownV2",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[[
            InlineKeyboardButton(text=f"🗑 Удалить все ({len(stale)})", callback_data="confirm_cleanup_wg"),
            InlineKeyboardButton(text="❌ Отмена", callback_data="cancel_cleanup_wg"),
        ]]),
    )


@router.callback_query(F.data == "confirm_cleanup_wg")
async def cb_confirm_cleanup_wg(callback: CallbackQuery) -> None:
    if not _is_admin(callback.from_user.id):
        await callback.answer("⛔ Нет доступа.", show_alert=True)
        return

    candidates = _cleanup_candidates.pop(callback.from_user.id, [])
    if not candidates:
        await callback.answer("Список устарел, запусти /admin_cleanup_wg заново.", show_alert=True)
        return

    await callback.answer("⏳ Удаляю…")
    removed = 0
    for config_id, user_id in candidates:
        try:
            if await wg_svc.remove_peer(config_id, user_id):
                removed += 1
        except Exception:
            logger.exception("cleanup: remove_peer failed for config_id=%s", config_id)

    await callback.message.edit_text(f"✅ Удалено конфигов: {removed}/{len(candidates)}\\.", parse_mode="MarkdownV2")


@router.callback_query(F.data == "cancel_cleanup_wg")
async def cb_cancel_cleanup_wg(callback: CallbackQuery) -> None:
    _cleanup_candidates.pop(callback.from_user.id, None)
    await callback.message.edit_text("✖️ Отменено\\.", parse_mode="MarkdownV2")
    await callback.answer()
