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
from services import xray_service as xray_svc

router = Router()


@router.message(Command("new_xray"))
async def cmd_new_xray(message: Message) -> None:
    args = message.text.split(maxsplit=1)
    name = args[1].strip() if len(args) > 1 else "VLESS"

    db_user = await db.get_user(message.from_user.id)
    await message.answer("⏳ Создаю конфиг, перезапускаю Xray...")

    try:
        link = await xray_svc.create_vless_config(db_user["id"], name)
    except Exception as e:
        await message.answer(f"❌ Ошибка: {e}")
        return

    await message.answer(
        f"✅ *{name}* — VLESS/Reality конфиг\n\n"
        f"Скопируй ссылку в клиент \\(v2rayNG, Hiddify, Streisand\\):\n\n"
        f"`{link}`",
        parse_mode="MarkdownV2",
    )

    # QR code
    qr = qrcode.make(link)
    buf = io.BytesIO()
    qr.save(buf, format="PNG")
    buf.seek(0)
    await message.answer_photo(
        photo=BufferedInputFile(buf.read(), filename="qr.png"),
        caption="📱 QR-код для импорта в клиент",
    )


@router.callback_query(F.data.startswith("del_xray:"))
async def cb_delete_xray(callback: CallbackQuery) -> None:
    config_id = int(callback.data.split(":")[1])
    db_user = await db.get_user(callback.from_user.id)

    await callback.answer("⏳ Удаляю...")
    try:
        ok = await xray_svc.remove_vless_config(config_id, db_user["id"])
    except Exception as e:
        await callback.message.answer(f"❌ Ошибка при удалении: {e}")
        return

    if ok:
        await callback.message.edit_text("✅ VLESS конфиг удалён. Xray перезапущен.")
    else:
        await callback.message.edit_text("❌ Конфиг не найден.")
