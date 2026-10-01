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
command -v python3 >/dev/null 2>&1 || error "python3 is required: apt install python3"

# Asks for the bot token and detects GROUP_ID / ADMIN_IDS; skips values already in .env
setup_telegram() {
    if python3 "$(dirname "$0")/telegram_setup.py"; then
        TELEGRAM_READY=1
    else
        TELEGRAM_READY=0
    fi
}

print_next_steps() {
    echo ""
    echo "Next steps:"
    if [ "$TELEGRAM_READY" -eq 1 ]; then
        echo "  docker compose up -d --build"
    else
        echo "  1. Set BOT_TOKEN, GROUP_ID, ADMIN_IDS in .env (or run: python3 scripts/telegram_setup.py)"
        echo "  2. docker compose up -d --build"
    fi
}

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
    setup_telegram
    print_next_steps
    exit 0
fi

# Read configurable SNI/domain values — user may edit .env.example before running setup
XRAY_REALITY_SNI=$(grep -m1 '^XRAY_REALITY_SNI=' .env.example | cut -d= -f2-)
MTPROXY_DOMAIN=$(grep -m1 '^MTPROXY_DOMAIN=' .env.example | cut -d= -f2-)

# --- Ask for the Reality SNI ---
# Reality borrows the TLS handshake of this site, so it must serve TLS 1.3 on port 443
supports_tls13() {
    timeout 10 openssl s_client -connect "$1:443" -servername "$1" -tls1_3 </dev/null >/dev/null 2>&1
}

while [ -t 0 ]; do
    read -r -p "Xray Reality SNI [${XRAY_REALITY_SNI}]: " SNI_INPUT || true
    [ -z "$SNI_INPUT" ] && break
    if [[ ! "$SNI_INPUT" =~ ^[A-Za-z0-9.-]+$ ]]; then
        warn "That does not look like a domain."
        continue
    fi
    if ! supports_tls13 "$SNI_INPUT"; then
        warn "${SNI_INPUT} did not answer with TLS 1.3 on port 443 — Reality will not work with it."
        read -r -p "Use it anyway? [y/N] " SNI_FORCE || true
        [[ "$SNI_FORCE" =~ ^[Yy] ]] || continue
    fi
    XRAY_REALITY_SNI="$SNI_INPUT"
    break
done

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

# Generate random AmneziaWG obfuscation parameters
read AWG_JC AWG_JMIN AWG_JMAX AWG_S1 AWG_S2 AWG_H1 AWG_H2 AWG_H3 AWG_H4 < <(python3 - <<'PYEOF'
import random
jc   = random.randint(3, 10)
jmin = random.randint(40, 100)
jmax = random.randint(jmin + 10, 1400)
s1   = random.randint(15, 150)
s2   = random.randint(15, 150)
h    = random.sample(range(1, 2**32), 4)
print(jc, jmin, jmax, s1, s2, *h)
PYEOF
)

cat > amneziawg/config/wg0.conf << EOF
[Interface]
PrivateKey = ${WG_PRIVATE_KEY}
Address = 10.8.0.1/24
ListenPort = 51820
PostUp = ETH=\$(ip route show default | awk '/default/{print \$5}' | head -1); iptables -A FORWARD -i wg0 -j ACCEPT; iptables -A FORWARD -o wg0 -j ACCEPT; iptables -t nat -A POSTROUTING -o \$ETH -j MASQUERADE
PostDown = ETH=\$(ip route show default | awk '/default/{print \$5}' | head -1); iptables -D FORWARD -i wg0 -j ACCEPT; iptables -D FORWARD -o wg0 -j ACCEPT; iptables -t nat -D POSTROUTING -o \$ETH -j MASQUERADE
Jc = ${AWG_JC}
Jmin = ${AWG_JMIN}
Jmax = ${AWG_JMAX}
S1 = ${AWG_S1}
S2 = ${AWG_S2}
H1 = ${AWG_H1}
H2 = ${AWG_H2}
H3 = ${AWG_H3}
H4 = ${AWG_H4}
EOF

chmod 600 amneziawg/config/wg0.conf
info "WireGuard config created."

# --- Generate Xray Reality keys ---
info "Generating Xray Reality keys..."
# X25519 keys via openssl + python3 — no Docker image required
XRAY_KEYS=$(python3 - <<'PYEOF'
import base64, subprocess
pem = subprocess.check_output(['openssl', 'genpkey', '-algorithm', 'X25519'], stderr=subprocess.DEVNULL)
priv_der = subprocess.check_output(['openssl', 'pkey', '-outform', 'DER'], input=pem, stderr=subprocess.DEVNULL)
pub_der  = subprocess.check_output(['openssl', 'pkey', '-pubout', '-outform', 'DER'], input=pem, stderr=subprocess.DEVNULL)
print(base64.urlsafe_b64encode(priv_der[-32:]).rstrip(b'=').decode())
print(base64.urlsafe_b64encode(pub_der[-32:]).rstrip(b'=').decode())
PYEOF
)
XRAY_PRIVATE_KEY=$(echo "$XRAY_KEYS" | sed -n '1p')
XRAY_PUBLIC_KEY=$(echo "$XRAY_KEYS"  | sed -n '2p')
XRAY_SHORT_ID=$(openssl rand -hex 4)

# --- Generate Xray config ---
# The bot adds the routing rule that blocks private destinations on its first start
# (bot/services/xray_service.py, _apply_hardening)
mkdir -p xray
cat > xray/config.json << EOF
{
  "log": { "loglevel": "warning", "access": "none" },
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
          "dest": "${XRAY_REALITY_SNI}:443",
          "xver": 0,
          "serverNames": ["${XRAY_REALITY_SNI}"],
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
# mtg v2 expects an ee-prefixed secret that embeds a fronting hostname.
# See: mtg generate-secret --hex google.com
MTPROXY_SECRET=$(MTPROXY_DOMAIN="$MTPROXY_DOMAIN" python3 - <<'PYEOF'
import os, secrets

domain = os.environ["MTPROXY_DOMAIN"].encode("ascii")
print("ee" + secrets.token_hex(16) + domain.hex())
PYEOF
)

# --- Generate PostgreSQL password ---
POSTGRES_PASSWORD=$(openssl rand -base64 24 | tr -d '/+=' | head -c 32)

# --- Detect server IP ---
SERVER_IP=$(curl -s --connect-timeout 5 https://api.ipify.org 2>/dev/null || echo "")
if [[ ! "$SERVER_IP" =~ ^([0-9]{1,3}\.){3}[0-9]{1,3}$ ]]; then
    warn "Could not detect server IP."
    SERVER_IP=""
    while [ -t 0 ] && [ -z "$SERVER_IP" ]; do
        read -r -p "Server public IP or domain (Enter to skip): " SERVER_IP || true
        [ -z "$SERVER_IP" ] && break
        if [[ ! "$SERVER_IP" =~ ^[A-Za-z0-9.-]+$ ]]; then
            warn "That does not look like an IP address or domain."
            SERVER_IP=""
        fi
    done
    if [ -z "$SERVER_IP" ]; then
        warn "Set SERVER_IP manually in .env"
        SERVER_IP="YOUR_SERVER_IP"
    fi
fi

# --- Write .env ---
# Created only now, so a run that failed earlier can simply be repeated
sed \
    -e "s|^POSTGRES_PASSWORD=.*|POSTGRES_PASSWORD=${POSTGRES_PASSWORD}|" \
    -e "s|^DATABASE_URL=.*|DATABASE_URL=postgresql://vpn:${POSTGRES_PASSWORD}@postgres:5432/vpn|" \
    -e "s|^SERVER_IP=.*|SERVER_IP=${SERVER_IP}|" \
    -e "s|^XRAY_REALITY_PRIVATE_KEY=.*|XRAY_REALITY_PRIVATE_KEY=${XRAY_PRIVATE_KEY}|" \
    -e "s|^XRAY_REALITY_PUBLIC_KEY=.*|XRAY_REALITY_PUBLIC_KEY=${XRAY_PUBLIC_KEY}|" \
    -e "s|^XRAY_REALITY_SHORT_ID=.*|XRAY_REALITY_SHORT_ID=${XRAY_SHORT_ID}|" \
    -e "s|^XRAY_REALITY_SNI=.*|XRAY_REALITY_SNI=${XRAY_REALITY_SNI}|" \
    -e "s|^MTPROXY_DOMAIN=.*|MTPROXY_DOMAIN=${MTPROXY_DOMAIN}|" \
    -e "s|^MTPROXY_SECRET=.*|MTPROXY_SECRET=${MTPROXY_SECRET}|" \
    .env.example > .env

info "Keys and configs generated."

setup_telegram

echo ""
info "Setup complete!"
print_next_steps
echo ""
echo "Server IP:        ${SERVER_IP}"
echo "WireGuard pubkey: ${WG_PUBLIC_KEY}"
echo "Xray pubkey:      ${XRAY_PUBLIC_KEY}"
echo "Xray SNI:         ${XRAY_REALITY_SNI}"
echo "MTProxy domain:   ${MTPROXY_DOMAIN}"
echo "MTProxy secret:   ${MTPROXY_SECRET}"
