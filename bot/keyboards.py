from aiogram.types import ReplyKeyboardMarkup, KeyboardButton, ReplyKeyboardRemove


def main_keyboard() -> ReplyKeyboardMarkup:
    return ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text="🔒 Новый WG"), KeyboardButton(text="⚡ Новый VLESS")],
            [KeyboardButton(text="📁 Мои конфиги"), KeyboardButton(text="📊 Трафик")],
            [KeyboardButton(text="📡 MTProxy"), KeyboardButton(text="💛 Поддержать")],
        ],
        resize_keyboard=True,
        persistent=True,
    )


def cancel_keyboard() -> ReplyKeyboardMarkup:
    return ReplyKeyboardMarkup(
        keyboard=[[KeyboardButton(text="❌ Отмена")]],
        resize_keyboard=True,
    )


remove_keyboard = ReplyKeyboardRemove()
