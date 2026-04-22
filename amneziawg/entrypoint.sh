#!/bin/bash
set -e

# Try to load the kernel module (must be installed on host)
modprobe amneziawg 2>/dev/null || echo "[warn] amneziawg module not found, falling back to wireguard"
modprobe wireguard 2>/dev/null || true

# Enable IP forwarding when writable; otherwise rely on container sysctls.
if [ -w /proc/sys/net/ipv4/ip_forward ]; then
    echo 1 > /proc/sys/net/ipv4/ip_forward
else
    echo "[warn] /proc/sys/net/ipv4/ip_forward is read-only, relying on container sysctls"
fi

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
