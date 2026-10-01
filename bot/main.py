import asyncio
import logging

from aiogram import Bot, Dispatcher
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from aiogram.exceptions import TelegramBadRequest
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.types import BotCommand, BotCommandScopeAllPrivateChats, BotCommandScopeChat

import config as cfg
import database as db
from middlewares.auth import AuthMiddleware
from handlers import start, wireguard, xray_handler, stats, admin, resend
from services import expiry as expiry_svc
from services import status as status_svc
from services import traffic as traffic_svc
from services import xray_service as xray_svc

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger(__name__)

USER_COMMANDS = [
    BotCommand(command="start", description="Главное меню"),
    BotCommand(command="new_wg", description="Создать WireGuard конфиг"),
    BotCommand(command="new_xray", description="Создать VLESS конфиг"),
    BotCommand(command="my_configs", description="Мои конфиги"),
    BotCommand(command="traffic", description="Статистика трафика"),
    BotCommand(command="mtproxy", description="Прокси для Telegram"),
    BotCommand(command="donate", description="Поддержать сервер"),
    BotCommand(command="help", description="Список команд"),
]

ADMIN_COMMANDS = USER_COMMANDS + [
    BotCommand(command="status", description="Статус сервисов"),
    BotCommand(command="admin_users", description="Пользователи"),
    BotCommand(command="admin_set_expiry", description="Срок действия конфига"),
    BotCommand(command="admin_cleanup_wg", description="Удалить неактивные WG конфиги"),
    BotCommand(command="admin_rebuild_xray", description="Пересобрать конфиг Xray из БД"),
]


async def set_bot_commands(bot: Bot) -> None:
    """Fills the Telegram command menu; admins get the extended list."""
    await bot.set_my_commands(USER_COMMANDS, scope=BotCommandScopeAllPrivateChats())
    for admin_id in cfg.ADMIN_IDS:
        try:
            await bot.set_my_commands(ADMIN_COMMANDS, scope=BotCommandScopeChat(chat_id=admin_id))
        except TelegramBadRequest:
            # Telegram refuses a per-chat menu until the admin has opened a chat with the bot
            logger.warning("Admin %s has not started the bot yet, admin menu not set", admin_id)


async def main() -> None:
    await db.init_db()
    logger.info("Database initialized")

    try:
        await xray_svc.sync_xray_config()
    except Exception:
        logger.exception("Failed to sync Xray config")

    bot = Bot(
        token=cfg.BOT_TOKEN,
        default=DefaultBotProperties(parse_mode=ParseMode.HTML),
    )
    dp = Dispatcher(storage=MemoryStorage())

    dp.message.middleware(AuthMiddleware())
    dp.callback_query.middleware(AuthMiddleware())

    dp.include_router(start.router)
    dp.include_router(wireguard.router)
    dp.include_router(xray_handler.router)
    dp.include_router(resend.router)
    dp.include_router(stats.router)
    dp.include_router(admin.router)

    try:
        await set_bot_commands(bot)
    except Exception:
        logger.exception("Failed to set bot commands")

    watcher_task = asyncio.create_task(status_svc.watch_containers(bot))
    expiry_task = asyncio.create_task(expiry_svc.sweep_expired_configs())
    traffic_task = asyncio.create_task(traffic_svc.poll_traffic_totals())
    live_status_task = asyncio.create_task(status_svc.live_status_updater(bot))

    logger.info("Starting bot polling...")
    try:
        await dp.start_polling(bot, allowed_updates=dp.resolve_used_update_types())
    finally:
        watcher_task.cancel()
        expiry_task.cancel()
        traffic_task.cancel()
        live_status_task.cancel()
        await db.close_db()
        await bot.session.close()


if __name__ == "__main__":
    asyncio.run(main())
