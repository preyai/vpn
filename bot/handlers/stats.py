from aiogram import Router
from aiogram.filters import Command
from aiogram.types import Message

import database as db
from services.traffic import get_wg_peer_traffic, get_xray_user_traffic, format_bytes

router = Router()


@router.message(Command("traffic"))
async def cmd_traffic(message: Message) -> None:
    db_user = await db.get_user(message.from_user.id)
    wg_cfgs = await db.get_wg_configs(db_user["id"])
    xray_cfgs = await db.get_xray_configs(db_user["id"])

    if not wg_cfgs and not xray_cfgs:
        await message.answer("У тебя нет активных конфигов.")
        return

    lines = ["📊 *Статистика трафика*\n"]

    if wg_cfgs:
        lines.append("*WireGuard:*")
        for cfg in wg_cfgs:
            rx, tx = get_wg_peer_traffic(cfg["public_key"])
            lines.append(
                f"  • *{cfg['name']}* `{cfg['ip_address']}`\n"
                f"    ↓ {format_bytes(rx)}  ↑ {format_bytes(tx)}"
            )

    if xray_cfgs:
        lines.append("\n*VLESS/Reality:*")
        for cfg in xray_cfgs:
            up, down = get_xray_user_traffic(cfg["email"])
            lines.append(
                f"  • *{cfg['name']}*\n"
                f"    ↑ {format_bytes(up)}  ↓ {format_bytes(down)}"
            )

    await message.answer("\n".join(lines), parse_mode="MarkdownV2")
