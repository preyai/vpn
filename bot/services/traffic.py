import asyncio
import json
import logging
import time

import docker

import config as cfg
import database as db

logger = logging.getLogger(__name__)


def format_bytes(n: int) -> str:
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if n < 1024:
            return f"{n:.1f} {unit}"
        n /= 1024
    return f"{n:.1f} PB"


def format_handshake(ts: int) -> str:
    """Convert a Unix timestamp to a human-readable 'N units ago' string."""
    if ts == 0:
        return "никогда"
    delta = int(time.time()) - ts
    if delta < 60:
        return "только что"
    if delta < 3600:
        return f"{delta // 60} мин. назад"
    if delta < 86400:
        return f"{delta // 3600} ч. назад"
    return f"{delta // 86400} д. назад"


def _exec_sync(container_name: str, cmd: list[str]) -> str:
    client = docker.from_env()
    container = client.containers.get(container_name)
    result = container.exec_run(cmd)
    return result.output.decode("utf-8", errors="replace")


async def _exec(container_name: str, cmd: list[str]) -> str:
    return await asyncio.to_thread(_exec_sync, container_name, cmd)


async def get_wg_peer_traffic(public_key: str) -> tuple[int, int, int]:
    """Returns (bytes_received, bytes_sent, last_handshake_ts) for a WireGuard peer.

    awg show wg0 dump peer columns (tab-separated):
      0 public_key | 1 preshared | 2 endpoint | 3 allowed_ips
      4 last_handshake (unix ts, 0=never) | 5 rx | 6 tx | 7 keepalive
    """
    try:
        output = await _exec(cfg.AWG_CONTAINER_NAME, ["awg", "show", "wg0", "dump"])
        for line in output.strip().splitlines()[1:]:  # first line = interface
            parts = line.split("\t")
            if len(parts) >= 7 and parts[0] == public_key:
                handshake = int(parts[4]) if parts[4].isdigit() else 0
                rx        = int(parts[5]) if parts[5].isdigit() else 0
                tx        = int(parts[6]) if parts[6].isdigit() else 0
                return rx, tx, handshake
    except Exception:
        logger.exception("Failed to get WG traffic for key %s…", public_key[:8])
    return 0, 0, 0


async def get_xray_user_traffic(email: str) -> tuple[int, int]:
    """Returns (uplink_bytes, downlink_bytes) for an Xray user."""
    try:
        cmd = [
            "/usr/local/bin/xray", "api", "statsquery",
            "--server=127.0.0.1:10085", "-pattern", email,
        ]
        output = await _exec(cfg.XRAY_CONTAINER_NAME, cmd)

        json_start = output.find("{")
        if json_start == -1:
            return 0, 0
        data = json.loads(output[json_start:])

        up = down = 0
        for stat in data.get("stat", []):
            name = stat.get("name", "")
            value = int(stat.get("value") or 0)
            if "uplink" in name:
                up = value
            elif "downlink" in name:
                down = value
        return up, down
    except Exception:
        logger.exception("Failed to get Xray traffic for %s", email)
    return 0, 0


def _effective_total(total: int, last: int, current: int) -> int:
    """Lifetime total as of right now: stored total plus whatever has
    accumulated since the last background poll (reset-aware, same logic
    as db.accumulate_*_traffic)."""
    delta = current - last if current >= last else current
    return total + delta


async def get_wg_config_usage(config: dict) -> dict:
    """Live counters (since the tunnel restarted) and lifetime totals for a WG config row."""
    rx, tx, handshake = await get_wg_peer_traffic(config["public_key"])
    return {
        "up": rx, "down": tx, "handshake": handshake,
        "up_total": _effective_total(config["traffic_rx_total"], config["traffic_rx_last"], rx),
        "down_total": _effective_total(config["traffic_tx_total"], config["traffic_tx_last"], tx),
    }


async def get_xray_config_usage(config: dict) -> dict:
    """Live counters (since Xray restarted) and lifetime totals for a VLESS config row."""
    up, down = await get_xray_user_traffic(config["email"])
    return {
        "up": up, "down": down,
        "up_total": _effective_total(config["traffic_up_total"], config["traffic_up_last"], up),
        "down_total": _effective_total(config["traffic_down_total"], config["traffic_down_last"], down),
    }


async def _poll_once() -> None:
    for config in await db.get_all_active_wg_configs():
        rx, tx, _ = await get_wg_peer_traffic(config["public_key"])
        await db.accumulate_wg_traffic(config["id"], rx, tx)

    for config in await db.get_all_active_xray_configs():
        up, down = await get_xray_user_traffic(config["email"])
        await db.accumulate_xray_traffic(config["id"], up, down)


async def poll_traffic_totals(interval: int = 300) -> None:
    """Background task: periodically snapshots live counters into lifetime
    totals in the DB, so traffic history survives container restarts."""
    while True:
        try:
            await _poll_once()
        except Exception:
            logger.exception("poll_traffic_totals iteration failed")
        await asyncio.sleep(interval)
