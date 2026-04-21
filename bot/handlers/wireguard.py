import io
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

router = Router()


def _configs_keyboard(configs: list[dict], prefix: str) -> InlineKeyboardMarkup:
    buttons = [
        [InlineKeyboardButton(
            text=f"🗑 {c['name']} ({c['ip_address']})",
            callback_data=f"{prefix}:{c['id']}",
        )]
        for c in configs
    ]
    return InlineKeyboardMarkup(inline_keyboard=buttons)


@router.message(Command("new_wg"))
async def cmd_new_wg(message: Message) -> None:
    args = message.text.split(maxsplit=1)
    name = args[1].strip() if len(args) > 1 else "WireGuard"

    db_user = await db.get_user(message.from_user.id)
    await message.answer("⏳ Создаю конфиг...")

    try:
        conf_text = await wg_svc.create_peer(db_user["id"], name)
    except Exception as e:
        await message.answer(f"❌ Ошибка: {e}")
        return

    # Send .conf file
    conf_bytes = conf_text.encode()
    await message.answer_document(
        document=BufferedInputFile(conf_bytes, filename=f"{name}.conf"),
        caption=f"✅ *{name}* — WireGuard конфиг\n\nИспользуй приложение *AmneziaVPN* для подключения.",
        parse_mode="MarkdownV2",
    )

    # Send QR code
    qr = qrcode.make(conf_text)
    buf = io.BytesIO()
    qr.save(buf, format="PNG")
    buf.seek(0)
    await message.answer_photo(
        photo=BufferedInputFile(buf.read(), filename="qr.png"),
        caption="📱 QR-код для AmneziaVPN",
    )


@router.message(Command("my_configs"))
async def cmd_my_configs(message: Message) -> None:
    db_user = await db.get_user(message.from_user.id)
    wg_cfgs = await db.get_wg_configs(db_user["id"])
    xray_cfgs = await db.get_xray_configs(db_user["id"])

    if not wg_cfgs and not xray_cfgs:
        await message.answer("У тебя нет активных конфигов. Создай через /new\\_wg или /new\\_xray.", parse_mode="MarkdownV2")
        return

    if wg_cfgs:
        await message.answer(
            "🔒 *WireGuard конфиги* — нажми для удаления:",
            reply_markup=_configs_keyboard(wg_cfgs, "del_wg"),
            parse_mode="MarkdownV2",
        )

    if xray_cfgs:
        xray_buttons = [
            [InlineKeyboardButton(
                text=f"🗑 {c['name']}",
                callback_data=f"del_xray:{c['id']}",
            )]
            for c in xray_cfgs
        ]
        await message.answer(
            "⚡ *VLESS конфиги* — нажми для удаления:",
            reply_markup=InlineKeyboardMarkup(inline_keyboard=xray_buttons),
            parse_mode="MarkdownV2",
        )


@router.callback_query(F.data.startswith("del_wg:"))
async def cb_delete_wg(callback: CallbackQuery) -> None:
    config_id = int(callback.data.split(":")[1])
    db_user = await db.get_user(callback.from_user.id)

    await callback.answer("⏳ Удаляю...")
    try:
        ok = await wg_svc.remove_peer(config_id, db_user["id"])
    except Exception as e:
        await callback.message.answer(f"❌ Ошибка при удалении: {e}")
        return

    if ok:
        await callback.message.edit_text("✅ WireGuard конфиг удалён.")
    else:
        await callback.message.edit_text("❌ Конфиг не найден.")
