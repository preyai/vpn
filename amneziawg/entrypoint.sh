#!/bin/bash
set -e

# Try to load the kernel module (must be installed on host)
modprobe amneziawg 2>/dev/null || echo "[warn] amneziawg module not found, falling back to wireguard"
modprobe wireguard 2>/dev/null || true

# Enable IP forwarding (may be read-only on WSL2/Docker Desktop; sysctls handle it)
echo 1 > /proc/sys/net/ipv4/ip_forward || true

CONFIG=/etc/amneziawg/wg0.conf

if [ ! -f "$CONFIG" ]; then
    echo "[error] $CONFIG not found. Run scripts/setup.sh first."
    exit 1
fi

# Bring up the interface
awg-quick up "$CONFIG" 2>/dev/null || wg-quick up "$CONFIG"

echo "[+] VPN interface up"

cleanup() {
    echo "[+] Shutting down VPN interface..."
    awg-quick down "$CONFIG" 2>/dev/null || wg-quick down "$CONFIG" || true
    exit 0
}

trap cleanup SIGTERM SIGINT

# Keep running; reload config on SIGHUP
while true; do
    sleep 30
done
