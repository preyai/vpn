#!/bin/bash
set -euo pipefail

RED='\033[0;31m'; GREEN='\033[0;32m'; YELLOW='\033[1;33m'; NC='\033[0m'
info()  { echo -e "${GREEN}[+]${NC} $*"; }
warn()  { echo -e "${YELLOW}[!]${NC} $*"; }
error() { echo -e "${RED}[x]${NC} $*"; exit 1; }

echo "=== VPN Server Setup ==="
echo ""

# --- Dependency checks ---
command -v docker  >/dev/null 2>&1 || error "Docker is required. Install: https://docs.docker.com/engine/install/"
command -v openssl >/dev/null 2>&1 || error "openssl is required: apt install openssl"

if ! command -v wg >/dev/null 2>&1; then
    warn "wireguard-tools not found. Will generate keys via Docker."
    USE_DOCKER_FOR_WG_KEYS=1
else
    USE_DOCKER_FOR_WG_KEYS=0
fi

# --- Check AmneziaWG kernel module on host ---
if ! lsmod | grep -q amneziawg 2>/dev/null; then
    warn "AmneziaWG kernel module not loaded on host."
    warn "Install it with:"
    warn "  sudo add-apt-repository ppa:amnezia/ppa"
    warn "  sudo apt update && sudo apt install amneziawg"
    warn "  sudo modprobe amneziawg"
    warn "Continuing setup, but AWG won't work until module is loaded."
fi

# --- Load existing .env if present ---
if [ -f .env ]; then
    warn ".env already exists. Skipping key generation (delete .env to regenerate)."
    exit 0
fi

cp .env.example .env

# --- Generate WireGuard server keys ---
info "Generating WireGuard server keys..."
if [ "$USE_DOCKER_FOR_WG_KEYS" -eq 0 ]; then
    WG_PRIVATE_KEY=$(wg genkey)
    WG_PUBLIC_KEY=$(echo "$WG_PRIVATE_KEY" | wg pubkey)
else
    WG_KEYS=$(docker run --rm alpine sh -c '
        apk add --quiet wireguard-tools >/dev/null 2>&1
        PRIV=$(wg genkey)
        echo "$PRIV"
        echo "$PRIV" | wg pubkey
    ')
    WG_PRIVATE_KEY=$(echo "$WG_KEYS" | sed -n '1p')
    WG_PUBLIC_KEY=$(echo "$WG_KEYS" | sed -n '2p')
fi

# --- Create AmneziaWG server config ---
mkdir -p amneziawg/config

cat > amneziawg/config/wg0.conf << EOF
[Interface]
PrivateKey = ${WG_PRIVATE_KEY}
Address = 10.8.0.1/24
ListenPort = 51820
PostUp = ETH=\$(ip route show default | awk '/default/{print \$5}' | head -1); iptables -A FORWARD -i wg0 -j ACCEPT; iptables -A FORWARD -o wg0 -j ACCEPT; iptables -t nat -A POSTROUTING -o \$ETH -j MASQUERADE
PostDown = ETH=\$(ip route show default | awk '/default/{print \$5}' | head -1); iptables -D FORWARD -i wg0 -j ACCEPT; iptables -D FORWARD -o wg0 -j ACCEPT; iptables -t nat -D POSTROUTING -o \$ETH -j MASQUERADE
Jc = 4
Jmin = 40
Jmax = 70
S1 = 0
S2 = 0
H1 = 1
H2 = 2
H3 = 3
H4 = 4
EOF

chmod 600 amneziawg/config/wg0.conf
info "WireGuard config created."

# --- Generate Xray Reality keys ---
info "Generating Xray Reality keys..."
XRAY_KEYS=$(docker run --rm ghcr.io/xtls/xray-core:latest xray x25519 2>/dev/null)
XRAY_PRIVATE_KEY=$(echo "$XRAY_KEYS" | grep "Private key:" | awk '{print $NF}')
XRAY_PUBLIC_KEY=$(echo "$XRAY_KEYS"  | grep "Public key:"  | awk '{print $NF}')
XRAY_SHORT_ID=$(openssl rand -hex 4)

# --- Generate Xray config ---
mkdir -p xray
cat > xray/config.json << EOF
{
  "log": { "loglevel": "warning" },
  "api": { "tag": "api", "services": ["StatsService"] },
  "stats": {},
  "policy": {
    "levels": { "0": { "statsUserUplink": true, "statsUserDownlink": true } },
    "system": { "statsInboundUplink": true, "statsInboundDownlink": true }
  },
  "inbounds": [
    {
      "tag": "vless-in",
      "listen": "0.0.0.0",
      "port": 443,
      "protocol": "vless",
      "settings": { "clients": [], "decryption": "none" },
      "streamSettings": {
        "network": "tcp",
        "security": "reality",
        "realitySettings": {
          "show": false,
          "dest": "www.microsoft.com:443",
          "xver": 0,
          "serverNames": ["www.microsoft.com"],
          "privateKey": "${XRAY_PRIVATE_KEY}",
          "shortIds": ["${XRAY_SHORT_ID}"]
        }
      },
      "sniffing": { "enabled": true, "destOverride": ["http", "tls", "quic"] }
    },
    {
      "tag": "api-in",
      "listen": "127.0.0.1",
      "port": 10085,
      "protocol": "dokodemo-door",
      "settings": { "address": "127.0.0.1" }
    }
  ],
  "outbounds": [
    { "protocol": "freedom", "tag": "direct" },
    { "protocol": "blackhole", "tag": "blocked" }
  ],
  "routing": {
    "rules": [{ "type": "field", "inboundTag": ["api-in"], "outboundTag": "api" }]
  }
}
EOF

info "Xray config created."

# --- Generate MTProxy secret ---
# dd prefix = DD-mode (obfuscated); 32 hex chars = 16 bytes of actual secret
# For FakeTLS (ee prefix), run manually:
#   docker run --rm ghcr.io/9seconds/mtg/mtg:2 generate-secret --hex tls google.com
MTPROXY_SECRET="dd$(openssl rand -hex 16)"

# --- Generate PostgreSQL password ---
POSTGRES_PASSWORD=$(openssl rand -base64 24 | tr -d '/+=' | head -c 32)

# --- Detect server IP ---
SERVER_IP=$(curl -s --connect-timeout 5 https://api.ipify.org 2>/dev/null || echo "")
if [ -z "$SERVER_IP" ]; then
    warn "Could not detect server IP. Set SERVER_IP manually in .env"
    SERVER_IP="YOUR_SERVER_IP"
fi

# --- Write .env ---
sed -i \
    -e "s|^POSTGRES_PASSWORD=.*|POSTGRES_PASSWORD=${POSTGRES_PASSWORD}|" \
    -e "s|^DATABASE_URL=.*|DATABASE_URL=postgresql://vpn:${POSTGRES_PASSWORD}@postgres:5432/vpn|" \
    -e "s|^SERVER_IP=.*|SERVER_IP=${SERVER_IP}|" \
    -e "s|^XRAY_REALITY_PRIVATE_KEY=.*|XRAY_REALITY_PRIVATE_KEY=${XRAY_PRIVATE_KEY}|" \
    -e "s|^XRAY_REALITY_PUBLIC_KEY=.*|XRAY_REALITY_PUBLIC_KEY=${XRAY_PUBLIC_KEY}|" \
    -e "s|^XRAY_REALITY_SHORT_ID=.*|XRAY_REALITY_SHORT_ID=${XRAY_SHORT_ID}|" \
    -e "s|^MTPROXY_SECRET=.*|MTPROXY_SECRET=${MTPROXY_SECRET}|" \
    .env

echo ""
info "Setup complete!"
echo ""
echo "Next steps:"
echo "  1. Edit .env — set BOT_TOKEN, GROUP_ID, ADMIN_IDS"
echo "  2. docker compose up -d --build"
echo ""
echo "Server IP:        ${SERVER_IP}"
echo "WireGuard pubkey: ${WG_PUBLIC_KEY}"
echo "Xray pubkey:      ${XRAY_PUBLIC_KEY}"
echo "MTProxy secret:   ${MTPROXY_SECRET}"
