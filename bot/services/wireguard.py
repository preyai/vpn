import asyncio
import base64
import logging
import re
from pathlib import Path

import docker
from cryptography.hazmat.primitives.asymmetric.x25519 import X25519PrivateKey
from cryptography.hazmat.primitives.serialization import (
    Encoding, NoEncryption, PrivateFormat, PublicFormat,
)

import config as cfg
import database as db

logger = logging.getLogger(__name__)

# Serialises all WG config file operations — prevents concurrent race conditions
_lock = asyncio.Lock()
_WG_QUICK_ONLY_INTERFACE_KEYS = {
    "Address",
    "DNS",
    "MTU",
    "Table",
    "PreUp",
    "PostUp",
    "PreDown",
    "PostDown",
    "SaveConfig",
}


# ── Key helpers ───────────────────────────────────────────────────────────────

def _generate_keypair() -> tuple[str, str]:
    """Returns (private_key_b64, public_key_b64)."""
    priv = X25519PrivateKey.generate()
    priv_b64 = base64.b64encode(
        priv.private_bytes(Encoding.Raw, PrivateFormat.Raw, NoEncryption())
    ).decode()
    pub_b64 = base64.b64encode(
        priv.public_key().public_bytes(Encoding.Raw, PublicFormat.Raw)
    ).decode()
    return priv_b64, pub_b64


def _derive_public_key(private_key_b64: str) -> str:
    priv = X25519PrivateKey.from_private_bytes(base64.b64decode(private_key_b64))
    return base64.b64encode(
        priv.public_key().public_bytes(Encoding.Raw, PublicFormat.Raw)
    ).decode()


# ── Sync file/docker helpers (run via asyncio.to_thread) ─────────────────────

def _read_config() -> str:
    return Path(cfg.WG_CONFIG_PATH).read_text()


def _write_config(text: str) -> None:
    Path(cfg.WG_CONFIG_PATH).write_text(text)


def _append_config(text: str) -> None:
    with open(cfg.WG_CONFIG_PATH, "a") as f:
        f.write(text)


def _build_syncconf_text(text: str) -> str:
    lines: list[str] = []
    section: str | None = None

    for raw_line in text.splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        if line.startswith("[") and line.endswith("]"):
            section = line
            lines.append(line)
            continue
        if "=" not in line:
            continue

        key, _, value = line.partition("=")
        key = key.strip()
        value = value.strip()

        if section == "[Interface]" and key in _WG_QUICK_ONLY_INTERFACE_KEYS:
            continue

        lines.append(f"{key} = {value}")

    return "\n".join(lines) + "\n"


def _do_syncconf() -> None:
    runtime_config_path = Path(cfg.WG_CONFIG_PATH).with_name("wg0.syncconf")
    runtime_config_path.write_text(_build_syncconf_text(_read_config()))

    client = docker.from_env()
    container = client.containers.get(cfg.AWG_CONTAINER_NAME)
    result = container.exec_run(f"awg syncconf wg0 /etc/amneziawg/{runtime_config_path.name}")
    if result.exit_code != 0:
        raise RuntimeError(f"awg syncconf failed: {result.output.decode()}")


# ── Config parsing ────────────────────────────────────────────────────────────

def _parse_interface(text: str) -> dict[str, str]:
    params: dict[str, str] = {}
    in_iface = False
    for line in text.splitlines():
        line = line.strip()
        if line == "[Interface]":
            in_iface = True
            continue
        if line.startswith("[") and in_iface:
            break
        if in_iface and "=" in line:
            k, _, v = line.partition("=")
            params[k.strip()] = v.strip()
    return params


async def _next_available_ip() -> str:
    # Called inside _lock — no concurrent access possible here
    used = set(await db.get_all_wg_ips())
    for i in range(2, cfg.WG_MAX_PEERS + 2):
        ip = f"{cfg.WG_SUBNET_BASE}.{i}"
        if ip not in used:
            return ip
    raise RuntimeError("No free IP addresses in the WireGuard subnet")


# ── Public API ────────────────────────────────────────────────────────────────

async def create_peer(user_id: int, name: str) -> str:
    """Creates a WireGuard peer and returns the client .conf text."""
    async with _lock:
        config_text = await asyncio.to_thread(_read_config)
        iface = _parse_interface(config_text)
        server_pub = _derive_public_key(iface["PrivateKey"])

        client_priv, client_pub = _generate_keypair()
        ip = await _next_available_ip()

        peer_block = (
            f"\n[Peer]\n"
            f"# {name}\n"
            f"PublicKey = {client_pub}\n"
            f"AllowedIPs = {ip}/32\n"
        )
        await asyncio.to_thread(_append_config, peer_block)

        try:
            await asyncio.to_thread(_do_syncconf)
        except Exception:
            logger.exception("awg syncconf failed after adding peer, rolling back")
            # Remove the appended block to avoid inconsistency
            rolled = await asyncio.to_thread(_read_config)
            await asyncio.to_thread(_write_config, rolled.replace(peer_block, ""))
            raise

        await db.add_wg_config(user_id, name, client_pub, client_priv, ip)

        obfs_keys = ("Jc", "Jmin", "Jmax", "S1", "S2", "H1", "H2", "H3", "H4")
        obfs_lines = "\n".join(f"{k} = {iface[k]}" for k in obfs_keys if k in iface)

        return (
            f"[Interface]\n"
            f"PrivateKey = {client_priv}\n"
            f"Address = {ip}/32\n"
            f"DNS = 1.1.1.1, 8.8.8.8\n"
            + (f"{obfs_lines}\n" if obfs_lines else "")
            + f"\n[Peer]\n"
            f"PublicKey = {server_pub}\n"
            f"Endpoint = {cfg.SERVER_IP}:{cfg.AWG_PORT}\n"
            f"AllowedIPs = 0.0.0.0/0, ::/0\n"
            f"PersistentKeepalive = 25\n"
        )


async def get_peer_conf_text(wg_config: dict) -> str:
    """Reconstructs client .conf from a DB record (reads server config for pubkey + obfs params)."""
    # Read under lock so we get a consistent view of the server config
    async with _lock:
        config_text = await asyncio.to_thread(_read_config)

    iface = _parse_interface(config_text)
    server_pub = _derive_public_key(iface["PrivateKey"])

    obfs_keys = ("Jc", "Jmin", "Jmax", "S1", "S2", "H1", "H2", "H3", "H4")
    obfs_lines = "\n".join(f"{k} = {iface[k]}" for k in obfs_keys if k in iface)

    return (
        f"[Interface]\n"
        f"PrivateKey = {wg_config['private_key']}\n"
        f"Address = {wg_config['ip_address']}/32\n"
        f"DNS = 1.1.1.1, 8.8.8.8\n"
        + (f"{obfs_lines}\n" if obfs_lines else "")
        + f"\n[Peer]\n"
        f"PublicKey = {server_pub}\n"
        f"Endpoint = {cfg.SERVER_IP}:{cfg.AWG_PORT}\n"
        f"AllowedIPs = 0.0.0.0/0, ::/0\n"
        f"PersistentKeepalive = 25\n"
    )


async def remove_peer(config_id: int, user_id: int) -> bool:
    """Removes a WireGuard peer. Returns True on success."""
    record = await db.delete_wg_config(config_id, user_id)
    if not record:
        return False

    pub_key = record["public_key"]

    async with _lock:
        config_text = await asyncio.to_thread(_read_config)
        pattern = rf"\n?\[Peer\]\n(?:#[^\n]*\n)?PublicKey\s*=\s*{re.escape(pub_key)}\n[^\[]*"
        new_text = re.sub(pattern, "", config_text)
        await asyncio.to_thread(_write_config, new_text)
        await asyncio.to_thread(_do_syncconf)

    return True
