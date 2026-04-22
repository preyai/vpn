import time
import logging

import config as cfg
import database as db

logger = logging.getLogger(__name__)

# telegram_id -> timestamp of last config creation
_last_creation: dict[int, float] = {}


def check_cooldown(telegram_id: int) -> float:
    """Returns remaining cooldown in seconds (0 = may proceed)."""
    elapsed = time.monotonic() - _last_creation.get(telegram_id, 0)
    remaining = cfg.CREATION_COOLDOWN_SECS - elapsed
    return max(0.0, remaining)


def set_cooldown(telegram_id: int) -> None:
    _last_creation[telegram_id] = time.monotonic()


async def check_wg_limit(user_id: int) -> bool:
    """Returns True if user is under the WG config cap."""
    configs = await db.get_wg_configs(user_id)
    if len(configs) >= cfg.MAX_WG_CONFIGS:
        logger.info("user_id=%s hit WG config limit (%s)", user_id, cfg.MAX_WG_CONFIGS)
        return False
    return True


async def check_xray_limit(user_id: int) -> bool:
    """Returns True if user is under the Xray config cap."""
    configs = await db.get_xray_configs(user_id)
    if len(configs) >= cfg.MAX_XRAY_CONFIGS:
        logger.info("user_id=%s hit Xray config limit (%s)", user_id, cfg.MAX_XRAY_CONFIGS)
        return False
    return True
