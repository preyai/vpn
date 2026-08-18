import asyncio
import logging

import docker
from aiogram.exceptions import TelegramBadRequest

import config as cfg
import database as db
from utils import md

logger = logging.getLogger(__name__)

_CONTAINERS = [
    ("WireGuard", cfg.AWG_CONTAINER_NAME),
    ("Xray", cfg.XRAY_CONTAINER_NAME),
    ("MTProxy", cfg.MTPROXY_CONTAINER_NAME),
]

_PORT_CHECKS = [
    ("Xray :443", cfg.XRAY_CONTAINER_NAME, 443),
    ("MTProxy :3128", cfg.MTPROXY_CONTAINER_NAME, 3128),
]


def _container_statuses_sync() -> list[tuple[str, str, str]]:
    """Returns (label, status, health) for each tracked container."""
    client = docker.from_env()
    results = []
    for label, name in _CONTAINERS:
        try:
            container = client.containers.get(name)
            status = container.status
            health = container.attrs.get("State", {}).get("Health", {}).get("Status", "n/a")
        except docker.errors.NotFound:
            status, health = "missing", "n/a"
        except Exception:
            logger.exception("Failed to inspect container %s", name)
            status, health = "error", "n/a"
        results.append((label, status, health))
    return results


async def get_container_statuses() -> list[tuple[str, str, str]]:
    return await asyncio.to_thread(_container_statuses_sync)


async def _tcp_check(host: str, port: int, timeout: float = 3.0) -> bool:
    try:
        _, writer = await asyncio.wait_for(asyncio.open_connection(host, port), timeout=timeout)
        writer.close()
        await writer.wait_closed()
        return True
    except Exception:
        return False


async def get_port_checks() -> list[tuple[str, bool]]:
    results = []
    for label, host, port in _PORT_CHECKS:
        ok = await _tcp_check(host, port)
        results.append((label, ok))
    return results


_STATUS_ICON = {"running": "✅", "missing": "⛔", "error": "⛔"}
_HEALTH_ICON = {"healthy": "✅", "unhealthy": "⚠️", "starting": "⏳", "n/a": ""}


async def render_status_text() -> str:
    containers = await get_container_statuses()
    ports = await get_port_checks()

    lines = ["🩺 *Статус сервисов*\n"]
    for label, status, health in containers:
        icon = _STATUS_ICON.get(status, "⚠️")
        health_str = f" \\({md(health)}\\)" if _HEALTH_ICON.get(health) else ""
        lines.append(f"{icon} {md(label)}: `{md(status)}`{health_str}")

    lines.append("")
    for label, ok in ports:
        icon = "✅" if ok else "⛔"
        lines.append(f"{icon} {md(label)}")

    return "\n".join(lines)


async def _notify_admins(bot, text: str) -> None:
    for admin_id in cfg.ADMIN_IDS:
        try:
            await bot.send_message(admin_id, text)
        except Exception:
            logger.exception("Failed to notify admin %s", admin_id)


async def watch_containers(bot, interval: int = 60) -> None:
    """Background task: alerts admins when a tracked container goes down or unhealthy."""
    last_bad: set[str] = set()
    while True:
        try:
            containers = await get_container_statuses()
            currently_bad = {
                label for label, status, health in containers
                if status != "running" or health == "unhealthy"
            }
            for label in currently_bad - last_bad:
                await _notify_admins(bot, f"⚠️ {label} нездоров или не запущен.")
            for label in last_bad - currently_bad:
                await _notify_admins(bot, f"✅ {label} восстановился.")
            last_bad = currently_bad
        except Exception:
            logger.exception("watch_containers iteration failed")
        await asyncio.sleep(interval)


_LIVE_STATUS_KEY = "live_status_message_id"


async def _publish_status(bot, text: str) -> None:
    """Edits the pinned status message in GROUP_ID in place, or creates and
    pins a fresh one if none is stored yet or the stored one is gone."""
    stored_id = await db.get_setting(_LIVE_STATUS_KEY)

    if stored_id:
        try:
            await bot.edit_message_text(
                text, chat_id=cfg.GROUP_ID, message_id=int(stored_id), parse_mode="MarkdownV2"
            )
            return
        except TelegramBadRequest as e:
            if "message is not modified" in e.message.lower():
                return
            if "message to edit not found" not in e.message.lower():
                logger.exception("Failed to edit live status message")
                return
            logger.info("Live status message no longer exists, recreating")
        except Exception:
            logger.exception("Failed to edit live status message")
            return

    message = await bot.send_message(cfg.GROUP_ID, text, parse_mode="MarkdownV2")
    await db.set_setting(_LIVE_STATUS_KEY, str(message.message_id))
    try:
        await bot.pin_chat_message(cfg.GROUP_ID, message.message_id, disable_notification=True)
    except Exception:
        logger.exception("Failed to pin live status message")


async def live_status_updater(bot, interval: int = 300) -> None:
    """Background task: keeps a pinned status message in GROUP_ID up to date."""
    while True:
        try:
            text = await render_status_text()
            await _publish_status(bot, text)
        except Exception:
            logger.exception("live_status_updater iteration failed")
        await asyncio.sleep(interval)
