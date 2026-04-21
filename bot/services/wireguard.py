import base64
import re
from pathlib import Path

import docker
from cryptography.hazmat.primitives.asymmetric.x25519 import X25519PrivateKey
from cryptography.hazmat.primitives.serialization import (
    Encoding, NoEncryption, PrivateFormat, PublicFormat,
)

import config as cfg
import database as db


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


def _parse_interface_section(text: str) -> dict[str, str]:
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


def _get_server_public_key(iface: dict[str, str]) -> str:
    priv_b64 = iface["PrivateKey"]
    priv_bytes = base64.b64decode(priv_b64)
    priv = X25519PrivateKey.from_private_bytes(priv_bytes)
    return base64.b64encode(
        priv.public_key().public_bytes(Encoding.Raw, PublicFormat.Raw)
    ).decode()


async def _next_available_ip() -> str:
    used = set(await db.get_all_wg_ips())
    for i in range(2, cfg.WG_MAX_PEERS + 2):
        ip = f"{cfg.WG_SUBNET_BASE}.{i}"
        if ip not in used:
            return ip
    raise RuntimeError("No free IP addresses in the WireGuard subnet")


def _reload_wg() -> None:
    client = docker.from_env()
    container = client.containers.get(cfg.AWG_CONTAINER_NAME)
    result = container.exec_run("awg syncconf wg0 /etc/amneziawg/wg0.conf")
    if result.exit_code != 0:
        raise RuntimeError(f"awg syncconf failed: {result.output.decode()}")


async def create_peer(user_id: int, name: str) -> str:
    """
    Creates a WireGuard peer, saves to DB, adds to server config.
    Returns the client .conf file text.
    """
    config_text = Path(cfg.WG_CONFIG_PATH).read_text()
    iface = _parse_interface_section(config_text)
    server_pub = _get_server_public_key(iface)

    client_priv, client_pub = _generate_keypair()
    ip = await _next_available_ip()

    # Persist peer to server config file
    peer_block = (
        f"\n[Peer]\n"
        f"# {name}\n"
        f"PublicKey = {client_pub}\n"
        f"AllowedIPs = {ip}/32\n"
    )
    with open(cfg.WG_CONFIG_PATH, "a") as f:
        f.write(peer_block)

    # Apply without dropping existing connections
    _reload_wg()

    # Save to DB
    await db.add_wg_config(user_id, name, client_pub, client_priv, ip)

    # Build obfuscation params for client config
    obfs_keys = ("Jc", "Jmin", "Jmax", "S1", "S2", "H1", "H2", "H3", "H4")
    obfs_lines = "\n".join(f"{k} = {iface[k]}" for k in obfs_keys if k in iface)

    client_conf = (
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
    return client_conf


async def remove_peer(config_id: int, user_id: int) -> bool:
    """Removes peer from DB and server config. Returns True on success."""
    record = await db.delete_wg_config(config_id, user_id)
    if not record:
        return False

    pub_key = record["public_key"]

    # Remove the [Peer] block from config file
    config_text = Path(cfg.WG_CONFIG_PATH).read_text()
    # Match the peer block starting from [Peer] until the next [Peer]/[Interface] or EOF
    pattern = rf"\n?\[Peer\]\n(?:#[^\n]*\n)?PublicKey\s*=\s*{re.escape(pub_key)}\n(?:[^\[]*)"
    new_text = re.sub(pattern, "", config_text)
    Path(cfg.WG_CONFIG_PATH).write_text(new_text)

    _reload_wg()
    return True
