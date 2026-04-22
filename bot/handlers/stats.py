import logging

from aiogram import Router
from aiogram.filters import Command
from aiogram.types import Message

import database as db
from services.traffic import get_wg_peer_traffic, get_xray_user_traffic, format_bytes, format_handshake
from utils import md

logger = logging.getLogger(__name__)
router = Router()


@router.message(Command("traffic"))
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
            rx, tx, handshake = await get_wg_peer_traffic(c["public_key"])
            lines.append(
                f"  • *{md(c['name'])}* `{md(c['ip_address'])}`\n"
                f"    ↓ `{md(format_bytes(rx))}`  ↑ `{md(format_bytes(tx))}`\n"
                f"    🕐 `{md(format_handshake(handshake))}`"
            )

    if xray_cfgs:
        lines.append("\n*VLESS/Reality:*")
        for c in xray_cfgs:
            up, down = await get_xray_user_traffic(c["email"])
            lines.append(
                f"  • *{md(c['name'])}*\n"
                f"    ↑ `{md(format_bytes(up))}`  ↓ `{md(format_bytes(down))}`"
            )

    await message.answer("\n".join(lines), parse_mode="MarkdownV2")
