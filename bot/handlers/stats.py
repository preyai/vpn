import logging

from aiogram import Router, F
from aiogram.filters import Command
from aiogram.types import Message

import database as db
from services.traffic import get_wg_peer_traffic, get_xray_user_traffic, format_bytes, format_handshake
from utils import md

logger = logging.getLogger(__name__)
router = Router()


def _effective_total(total: int, last: int, current: int) -> int:
    """Lifetime total as of right now: stored total plus whatever has
    accumulated since the last background poll (reset-aware, same logic
    as db.accumulate_*_traffic)."""
    delta = current - last if current >= last else current
    return total + delta


@router.message(Command("traffic"))
@router.message(F.text == "📊 Трафик")
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
            total_rx = _effective_total(c["traffic_rx_total"], c["traffic_rx_last"], rx)
            total_tx = _effective_total(c["traffic_tx_total"], c["traffic_tx_last"], tx)
            lines.append(
                f"  • *{md(c['name'])}* `{md(c['ip_address'])}`\n"
                f"    ↑ `{md(format_bytes(rx))}`  ↓ `{md(format_bytes(tx))}` \\(с рестарта\\)\n"
                f"    ↑ `{md(format_bytes(total_rx))}`  ↓ `{md(format_bytes(total_tx))}` \\(всего\\)\n"
                f"    🕐 `{md(format_handshake(handshake))}`"
            )

    if xray_cfgs:
        lines.append("\n*VLESS/Reality:*")
        for c in xray_cfgs:
            up, down = await get_xray_user_traffic(c["email"])
            total_up = _effective_total(c["traffic_up_total"], c["traffic_up_last"], up)
            total_down = _effective_total(c["traffic_down_total"], c["traffic_down_last"], down)
            lines.append(
                f"  • *{md(c['name'])}*\n"
                f"    ↑ `{md(format_bytes(up))}`  ↓ `{md(format_bytes(down))}` \\(с рестарта\\)\n"
                f"    ↑ `{md(format_bytes(total_up))}`  ↓ `{md(format_bytes(total_down))}` \\(всего\\)"
            )

    await message.answer("\n".join(lines), parse_mode="MarkdownV2")
