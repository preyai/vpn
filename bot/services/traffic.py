import json
import docker

import config as cfg


def _exec(container_name: str, cmd: str) -> str:
    client = docker.from_env()
    container = client.containers.get(container_name)
    result = container.exec_run(["sh", "-c", cmd])
    return result.output.decode("utf-8", errors="replace")


def format_bytes(n: int) -> str:
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if n < 1024:
            return f"{n:.1f} {unit}"
        n /= 1024
    return f"{n:.1f} PB"


def get_wg_peer_traffic(public_key: str) -> tuple[int, int]:
    """Returns (bytes_received, bytes_sent) for a WireGuard peer."""
    try:
        output = _exec(cfg.AWG_CONTAINER_NAME, "awg show wg0 dump")
        for line in output.strip().splitlines()[1:]:  # first line = interface
            parts = line.split("\t")
            if len(parts) >= 7 and parts[0] == public_key:
                rx = int(parts[5]) if parts[5].isdigit() else 0
                tx = int(parts[6]) if parts[6].isdigit() else 0
                return rx, tx
    except Exception:
        pass
    return 0, 0


def get_xray_user_traffic(email: str) -> tuple[int, int]:
    """Returns (uplink_bytes, downlink_bytes) for an Xray user."""
    try:
        cmd = f'xray api statsquery --server=127.0.0.1:10085 -pattern "{email}"'
        output = _exec(cfg.XRAY_CONTAINER_NAME, cmd)
        # Trim leading non-JSON text (proto text lines before the JSON object)
        json_start = output.find("{")
        if json_start == -1:
            return 0, 0
        data = json.loads(output[json_start:])
        up = down = 0
        for stat in data.get("stat", []):
            name = stat.get("name", "")
            value = int(stat.get("value", 0) or 0)
            if "uplink" in name:
                up = value
            elif "downlink" in name:
                down = value
        return up, down
    except Exception:
        return 0, 0
