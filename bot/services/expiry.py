import asyncio
import logging

import database as db
from services import wireguard as wg_svc
from services import xray_service as xray_svc

logger = logging.getLogger(__name__)


async def _sweep_once() -> None:
    for record in await db.get_expired_wg_configs():
        try:
            await wg_svc.remove_peer(record["id"], record["user_id"])
            logger.info("Expired WG config id=%s revoked", record["id"])
        except Exception:
            logger.exception("Failed to revoke expired WG config id=%s", record["id"])

    for record in await db.get_expired_xray_configs():
        try:
            await xray_svc.remove_vless_config(record["id"], record["user_id"])
            logger.info("Expired Xray config id=%s revoked", record["id"])
        except Exception:
            logger.exception("Failed to revoke expired Xray config id=%s", record["id"])


async def sweep_expired_configs(interval: int = 3600) -> None:
    """Background task: periodically revokes configs past their expires_at."""
    while True:
        try:
            await _sweep_once()
        except Exception:
            logger.exception("sweep_expired_configs iteration failed")
        await asyncio.sleep(interval)
