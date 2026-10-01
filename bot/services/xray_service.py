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
    """Restart the container to pick up the new config.json (SIGHUP kills this build instead of reloading it)."""
    client = docker.from_env()
    container = client.containers.get(cfg.XRAY_CONTAINER_NAME)
    container.restart(timeout=5)


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


def _apply_reality_sni(data: dict) -> bool:
    """Points the Reality inbound at XRAY_REALITY_SNI. Returns True if the config changed."""
    for inbound in data.get("inbounds", []):
        if inbound.get("tag") == "vless-in":
            reality = inbound["streamSettings"]["realitySettings"]
            wanted = {
                "dest": f"{cfg.XRAY_REALITY_SNI}:443",
                "serverNames": [cfg.XRAY_REALITY_SNI],
            }
            if all(reality.get(k) == v for k, v in wanted.items()):
                return False
            reality.update(wanted)
            return True
    raise RuntimeError("vless-in inbound not found in Xray config")


# Destinations a VPN client must never reach through the proxy: Xray's own API on
# localhost, other containers, the host, cloud metadata endpoints
_BLOCK_PRIVATE_RULE = {
    "type": "field",
    "ip": [
        "127.0.0.0/8", "10.0.0.0/8", "172.16.0.0/12", "192.168.0.0/16",
        "169.254.0.0/16", "100.64.0.0/10", "::1/128", "fc00::/7", "fe80::/10",
    ],
    "outboundTag": "blocked",
}


def _apply_hardening(data: dict) -> bool:
    """Disables the access log and blocks private destinations. Returns True if the config changed."""
    changed = False

    # The access log records every destination each user connects to
    log = data.setdefault("log", {})
    if log.get("access") != "none":
        log["access"] = "none"
        changed = True

    routing = data.setdefault("routing", {})
    # Without this, IP rules are skipped for destinations given as a hostname
    if routing.get("domainStrategy") != "IPIfNonMatch":
        routing["domainStrategy"] = "IPIfNonMatch"
        changed = True
    rules = routing.setdefault("rules", [])
    if _BLOCK_PRIVATE_RULE not in rules:
        rules.append(_BLOCK_PRIVATE_RULE)
        changed = True

    return changed


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


async def sync_xray_config() -> None:
    """Brings config.json in line with .env and the settings the bot relies on.

    setup.sh writes config.json once; without this, editing XRAY_REALITY_SNI in .env
    later changes only the share links and the server rejects them. It also upgrades
    configs generated by older versions of setup.sh.
    """
    async with _lock:
        data = await asyncio.to_thread(_read_xray_config)
        sni_changed = _apply_reality_sni(data)
        hardened = _apply_hardening(data)
        if not (sni_changed or hardened):
            return
        await asyncio.to_thread(_write_xray_config, data)
        await asyncio.to_thread(_do_reload_xray)

    if sni_changed:
        logger.info("Xray Reality SNI updated to %s", cfg.XRAY_REALITY_SNI)
    if hardened:
        logger.info("Xray config hardened: access log off, private destinations blocked")


async def rebuild_xray_config_from_db() -> None:
    """Rebuilds Xray config from DB. Admin utility."""
    active = await db.get_all_active_xray_configs()

    async with _lock:
        data = await asyncio.to_thread(_read_xray_config)
        _apply_reality_sni(data)
        _apply_hardening(data)
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
