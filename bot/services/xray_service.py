import asyncio
import json
import logging
import time
import uuid as _uuid
from pathlib import Path
from urllib.parse import quote

import docker

import config as cfg
import database as db

logger = logging.getLogger(__name__)

# Serialises all Xray config file operations — prevents concurrent race conditions
_lock = asyncio.Lock()


# ── Sync file/docker helpers (run via asyncio.to_thread) ─────────────────────

def _read_xray_config() -> dict:
    return json.loads(Path(cfg.XRAY_CONFIG_PATH).read_text())


def _write_xray_config(data: dict) -> None:
    Path(cfg.XRAY_CONFIG_PATH).write_text(
        json.dumps(data, indent=2, ensure_ascii=False)
    )


def _do_reload_xray() -> None:
    """Send SIGHUP — Xray reloads config.json in-process (~200 ms, no Docker overhead)."""
    client = docker.from_env()
    container = client.containers.get(cfg.XRAY_CONTAINER_NAME)
    try:
        container.kill(signal="SIGHUP")
    except docker.errors.APIError as e:
        if e.response is not None and e.response.status_code == 409:
            logger.warning("Xray container is not running; config written but not reloaded live")
        else:
            raise


# ── Internal helpers ──────────────────────────────────────────────────────────

def _make_email(user_id: int, config_id: int) -> str:
    return f"u{user_id}_{config_id}@vpn"


def _build_vless_link(uuid: str, name: str) -> str:
    params = (
        "encryption=none"
        f"&security=reality"
        f"&sni={cfg.XRAY_REALITY_SNI}"
        f"&fp=chrome"
        f"&pbk={cfg.XRAY_REALITY_PUBLIC_KEY}"
        f"&sid={cfg.XRAY_REALITY_SHORT_ID}"
        f"&type=tcp"
        f"&flow=xtls-rprx-vision"
    )
    return f"vless://{uuid}@{cfg.SERVER_IP}:{cfg.XRAY_PORT}?{params}#{quote(name)}"


def _add_client_to_config(data: dict, uuid: str, email: str) -> None:
    for inbound in data.get("inbounds", []):
        if inbound.get("tag") == "vless-in":
            inbound["settings"]["clients"].append(
                {"id": uuid, "email": email, "flow": "xtls-rprx-vision", "level": 0}
            )
            return
    raise RuntimeError("vless-in inbound not found in Xray config")


def _remove_client_from_config(data: dict, uuid: str) -> None:
    for inbound in data.get("inbounds", []):
        if inbound.get("tag") == "vless-in":
            clients = inbound["settings"].get("clients", [])
            inbound["settings"]["clients"] = [c for c in clients if c["id"] != uuid]
            return


# ── Public API ────────────────────────────────────────────────────────────────

async def create_vless_config(user_id: int, name: str) -> str:
    """Creates a VLESS user and returns the share link."""
    new_uuid = str(_uuid.uuid4())
    temp_email = f"u{user_id}_{int(time.time())}@vpn"

    config_id = await db.add_xray_config(user_id, name, new_uuid, temp_email)
    email = _make_email(user_id, config_id)
    await db.update_xray_email(config_id, email)

    try:
        async with _lock:
            data = await asyncio.to_thread(_read_xray_config)
            _add_client_to_config(data, new_uuid, email)
            await asyncio.to_thread(_write_xray_config, data)
            await asyncio.to_thread(_do_reload_xray)
    except Exception:
        logger.exception("Xray config write/reload failed for config_id=%s, rolling back DB", config_id)
        await db.delete_xray_config(config_id, user_id)
        raise

    logger.info("Created VLESS config id=%s for user_id=%s", config_id, user_id)
    return _build_vless_link(new_uuid, name)


async def remove_vless_config(config_id: int, user_id: int) -> bool:
    """Removes a VLESS user. Returns True on success."""
    record = await db.delete_xray_config(config_id, user_id)
    if not record:
        return False

    async with _lock:
        data = await asyncio.to_thread(_read_xray_config)
        _remove_client_from_config(data, record["uuid"])
        await asyncio.to_thread(_write_xray_config, data)
        await asyncio.to_thread(_do_reload_xray)

    logger.info("Removed VLESS config id=%s for user_id=%s", config_id, user_id)
    return True


async def rebuild_xray_config_from_db() -> None:
    """Rebuilds Xray config from DB. Admin utility."""
    active = await db.get_all_active_xray_configs()

    async with _lock:
        data = await asyncio.to_thread(_read_xray_config)
        for inbound in data.get("inbounds", []):
            if inbound.get("tag") == "vless-in":
                inbound["settings"]["clients"] = [
                    {"id": r["uuid"], "email": r["email"],
                     "flow": "xtls-rprx-vision", "level": 0}
                    for r in active
                ]
                break
        await asyncio.to_thread(_write_xray_config, data)
        await asyncio.to_thread(_do_reload_xray)

    logger.info("Rebuilt Xray config from DB (%d users)", len(active))


def get_vless_link(xray_config: dict) -> str:
    """Reconstructs the VLESS share link from a DB record (no I/O)."""
    return _build_vless_link(xray_config["uuid"], xray_config["name"])
