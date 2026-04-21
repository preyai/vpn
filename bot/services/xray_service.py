import json
import time
import uuid as _uuid
from pathlib import Path
from urllib.parse import quote

import docker

import config as cfg
import database as db  # uses asyncpg pool


def _load_xray_config() -> dict:
    return json.loads(Path(cfg.XRAY_CONFIG_PATH).read_text())


def _save_xray_config(data: dict) -> None:
    Path(cfg.XRAY_CONFIG_PATH).write_text(json.dumps(data, indent=2, ensure_ascii=False))


def _restart_xray() -> None:
    client = docker.from_env()
    container = client.containers.get(cfg.XRAY_CONTAINER_NAME)
    container.restart(timeout=5)


def _make_email(user_id: int, config_id: int) -> str:
    return f"u{user_id}_{config_id}@vpn"


async def create_vless_config(user_id: int, name: str) -> str:
    """Creates a VLESS user in Xray and returns the share link."""
    new_uuid = str(_uuid.uuid4())

    # Temporary email placeholder — we'll get the real config_id after DB insert
    # Use timestamp as interim unique email
    temp_email = f"u{user_id}_{int(time.time())}@vpn"

    config_id = await db.add_xray_config(user_id, name, new_uuid, temp_email)
    email = _make_email(user_id, config_id)
    await db.update_xray_email(config_id, email)

    # Add client to Xray config
    xray_cfg = _load_xray_config()
    for inbound in xray_cfg.get("inbounds", []):
        if inbound.get("tag") == "vless-in":
            inbound["settings"]["clients"].append({
                "id": new_uuid,
                "email": email,
                "flow": "xtls-rprx-vision",
                "level": 0,
            })
            break
    _save_xray_config(xray_cfg)
    _restart_xray()

    # Build share link
    params = (
        f"encryption=none"
        f"&security=reality"
        f"&sni={cfg.XRAY_REALITY_SNI}"
        f"&fp=chrome"
        f"&pbk={cfg.XRAY_REALITY_PUBLIC_KEY}"
        f"&sid={cfg.XRAY_REALITY_SHORT_ID}"
        f"&type=tcp"
        f"&flow=xtls-rprx-vision"
    )
    link = f"vless://{new_uuid}@{cfg.SERVER_IP}:{cfg.XRAY_PORT}?{params}#{quote(name)}"
    return link


async def remove_vless_config(config_id: int, user_id: int) -> bool:
    record = await db.delete_xray_config(config_id, user_id)
    if not record:
        return False

    target_uuid = record["uuid"]
    xray_cfg = _load_xray_config()
    for inbound in xray_cfg.get("inbounds", []):
        if inbound.get("tag") == "vless-in":
            clients = inbound["settings"].get("clients", [])
            inbound["settings"]["clients"] = [c for c in clients if c["id"] != target_uuid]
            break
    _save_xray_config(xray_cfg)
    _restart_xray()
    return True


async def rebuild_xray_config_from_db() -> None:
    """Rebuilds Xray config from DB — useful after manual edits or migration."""
    active = await db.get_all_active_xray_configs()
    xray_cfg = _load_xray_config()
    for inbound in xray_cfg.get("inbounds", []):
        if inbound.get("tag") == "vless-in":
            inbound["settings"]["clients"] = [
                {
                    "id": r["uuid"],
                    "email": r["email"],
                    "flow": "xtls-rprx-vision",
                    "level": 0,
                }
                for r in active
            ]
            break
    _save_xray_config(xray_cfg)
    _restart_xray()
