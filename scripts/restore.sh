#!/bin/bash
# Rebuilds this server from a vpn-backup-*.tar.gz: same users, keys, subscription tokens
# and WEB proxy secret. Run from the repository root on the new server.
set -euo pipefail

RED='\033[0;31m'; GREEN='\033[0;32m'; YELLOW='\033[1;33m'; NC='\033[0m'
info()  { echo -e "${GREEN}[+]${NC} $*"; }
warn()  { echo -e "${YELLOW}[!]${NC} $*"; }
error() { echo -e "${RED}[x]${NC} $*"; exit 1; }

ARCHIVE="${1:-}"
[ -n "$ARCHIVE" ] || error "Usage: bash scripts/restore.sh <vpn-backup-*.tar.gz>"
[ -f "$ARCHIVE" ] || error "Archive not found: $ARCHIVE"
[ -f docker-compose.yml ] || error "Run this from the repository root."
command -v docker >/dev/null 2>&1 || error "Docker is required. Install: https://docs.docker.com/engine/install/"
if ! lsmod | grep -q amneziawg 2>/dev/null; then
    warn "AmneziaWG kernel module not loaded on host — see Requirements in README.md."
fi

WORK=$(mktemp -d)
trap 'rm -rf "$WORK"' EXIT
tar -xzf "$ARCHIVE" -C "$WORK"
for f in db.sql env xray/config.json amneziawg/wg0.conf webproxy/token.key; do
    [ -f "$WORK/$f" ] || error "$ARCHIVE has no $f — is this a vpn-backup archive?"
done

# Anything already on this server gets replaced, so it must be a deliberate choice
if [ -f .env ] || [ -f xray/config.json ] || [ -f amneziawg/config/wg0.conf ]; then
    warn "This server already has a configuration. Its database and configs will be replaced."
    read -r -p "Type 'restore' to continue: " ANSWER
    [ "$ANSWER" = "restore" ] || error "Cancelled."

    SAVED="backups/pre-restore-$(date -u +%Y%m%d-%H%M%S)"
    mkdir -p "$SAVED"
    chmod 700 backups "$SAVED"
    [ ! -f .env ] || cp -p .env "$SAVED/env"
    [ ! -f xray/config.json ] || cp -p xray/config.json "$SAVED/"
    [ ! -f amneziawg/config/wg0.conf ] || cp -p amneziawg/config/wg0.conf "$SAVED/"
    info "Previous configuration saved to $SAVED (the database is not — back it up first if it matters)."

    docker compose down --remove-orphans
fi

info "Restoring configuration..."
mkdir -p xray amneziawg/config webproxy/site
cp "$WORK/env" .env
chmod 600 .env
cp "$WORK/xray/config.json" xray/config.json
cp "$WORK/amneziawg/wg0.conf" amneziawg/config/wg0.conf
chmod 600 amneziawg/config/wg0.conf
if [ -d "$WORK/webproxy/site" ]; then
    cp -R "$WORK/webproxy/site/." webproxy/site/
fi

# VLESS links and WireGuard configs are built from SERVER_IP
OLD_IP=$(grep -m1 '^SERVER_IP=' .env | cut -d= -f2-)
NEW_IP=$(curl -s --connect-timeout 5 https://api.ipify.org 2>/dev/null || echo "")
if [[ "$NEW_IP" =~ ^([0-9]{1,3}\.){3}[0-9]{1,3}$ ]]; then
    sed -i "s|^SERVER_IP=.*|SERVER_IP=${NEW_IP}|" .env
    info "SERVER_IP: ${OLD_IP} -> ${NEW_IP}"
else
    NEW_IP="$OLD_IP"
    warn "Could not detect this server's IP. Set SERVER_IP in .env by hand and run: docker compose up -d"
fi

env_value() { grep -m1 "^$1=" .env | cut -d= -f2- || true; }
PG_USER=$(env_value POSTGRES_USER); PG_USER=${PG_USER:-vpn}
PG_DB=$(env_value POSTGRES_DB); PG_DB=${PG_DB:-vpn}
PG_PASSWORD=$(env_value POSTGRES_PASSWORD)

info "Restoring database..."
docker compose up -d postgres
for _ in $(seq 1 60); do
    docker compose exec -T postgres pg_isready -U "$PG_USER" >/dev/null 2>&1 && break
    sleep 2
done
docker compose exec -T postgres pg_isready -U "$PG_USER" >/dev/null || error "PostgreSQL did not start."

docker compose exec -T postgres psql -q -v ON_ERROR_STOP=1 --single-transaction \
    -U "$PG_USER" -d "$PG_DB" < "$WORK/db.sql" >/dev/null

# The data volume keeps the password it was created with, which may differ from the restored .env
docker compose exec -T postgres psql -q -v ON_ERROR_STOP=1 -v user="$PG_USER" -v password="$PG_PASSWORD" \
    -U "$PG_USER" -d "$PG_DB" >/dev/null <<'SQL'
ALTER USER :"user" PASSWORD :'password';
SQL

info "Restoring WEB proxy token key..."
docker compose run --rm --no-deps -T --entrypoint sh backup \
    -c 'cat > /webproxy-data/token.key && chmod 600 /webproxy-data/token.key' < "$WORK/webproxy/token.key"

info "Starting everything..."
docker compose up -d --build

echo ""
info "Restore complete. Still to do:"
echo "  1. Open TCP 80, 443 and UDP $(env_value AWG_PORT) in the firewall."
echo "  2. Point these domains' A records at ${NEW_IP}: $(env_value TG_WEBPROXY_DOMAIN), $(env_value SUBS_DOMAIN)"
echo "  3. Stop the bot on the old server if it still runs: two bots cannot share one token."
if [ "$OLD_IP" != "$NEW_IP" ]; then
    echo "  4. Tell users: subscriptions update on their own; VLESS links and WireGuard configs"
    echo "     issued earlier carry the old IP and must be re-sent from the bot."
fi
