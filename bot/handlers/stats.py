import logging

from aiogram import Router, F
from aiogram.filters import Command
from aiogram.types import Message

import database as db
from keyboards import BTN_TRAFFIC
from services.traffic import get_wg_config_usage, get_xray_config_usage, format_bytes, format_handshake
from utils import md

logger = logging.getLogger(__name__)
router = Router()


@router.message(Command("traffic"))
@router.message(F.text == BTN_TRAFFIC)
async def cmd_traffic(message: Message) -> None:
    db_user = await db.get_user(message.from_user.id)
    wg_cfgs   = await db.get_wg_configs(db_user["id"])
    xray_cfgs = await db.get_xray_configs(db_user["id"])

    if not wg_cfgs and not xray_cfgs:
        await message.answer("У тебя нет активных конфигов\\.", parse_mode="MarkdownV2")
        return

    lines = ["📊 *Статистика трафика*\n"]

    if wg_cfgs:
        lines.append("*WireGuard:*")
        for c in wg_cfgs:
            u = await get_wg_config_usage(c)
            lines.append(
                f"  • *{md(c['name'])}* `{md(c['ip_address'])}`\n"
                f"    ↑ `{md(format_bytes(u['up']))}`  ↓ `{md(format_bytes(u['down']))}` \\(с рестарта\\)\n"
                f"    ↑ `{md(format_bytes(u['up_total']))}`  ↓ `{md(format_bytes(u['down_total']))}` \\(всего\\)\n"
                f"    🕐 `{md(format_handshake(u['handshake']))}`"
            )

    if xray_cfgs:
        lines.append("\n*VLESS/Reality:*")
        for c in xray_cfgs:
            u = await get_xray_config_usage(c)
            lines.append(
                f"  • *{md(c['name'])}*\n"
                f"    ↑ `{md(format_bytes(u['up']))}`  ↓ `{md(format_bytes(u['down']))}` \\(с рестарта\\)\n"
                f"    ↑ `{md(format_bytes(u['up_total']))}`  ↓ `{md(format_bytes(u['down_total']))}` \\(всего\\)"
            )

    await message.answer("\n".join(lines), parse_mode="MarkdownV2")
