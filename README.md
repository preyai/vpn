# VPN Server Manager

Self-hosted VPN server with a Telegram bot interface. Supports three protocols:

- **AmneziaWG** — obfuscated WireGuard (bypasses DPI)
- **VLESS + Reality** — Xray proxy with TLS camouflage
- **MTProxy** — native Telegram proxy

Everything runs in Docker Compose. Users manage their own configs via a Telegram bot — no web UI, no manual config editing.

## Requirements

- Linux server with a public IP
- Docker + Docker Compose
- `openssl` (`apt install openssl`)
- AmneziaWG kernel module on the host:
  ```bash
  sudo add-apt-repository ppa:amnezia/ppa
  sudo apt update && sudo apt install amneziawg
  sudo modprobe amneziawg
  ```

## Quick Start

```bash
git clone <repo> && cd vpn

# Generate keys and create configs
bash scripts/setup.sh

# Edit .env — set BOT_TOKEN, GROUP_ID, ADMIN_IDS
nano .env

# Start everything
docker compose up -d --build
```

## Configuration

All settings live in `.env` (copied from `.env.example` by `setup.sh`).

| Variable | Description |
|---|---|
| `BOT_TOKEN` | Telegram bot token from [@BotFather](https://t.me/BotFather) |
| `GROUP_ID` | Telegram group ID — only members can use the bot |
| `ADMIN_IDS` | Comma-separated Telegram user IDs with admin access |
| `SERVER_IP` | Your server's public IP (auto-detected by `setup.sh`) |
| `AWG_PORT` | AmneziaWG UDP port (default: `51820`) |
| `XRAY_PORT` | VLESS/Reality TCP port (default: `443`) |
| `MTPROXY_PORT` | MTProxy TCP port (default: `8443`) |
| `MTPROXY_DOMAIN` | Fronting hostname embedded into the MTProxy secret |
| `MAX_WG_CONFIGS` | Max WireGuard configs per user (default: `5`) |
| `MAX_XRAY_CONFIGS` | Max VLESS configs per user (default: `5`) |
| `CREATION_COOLDOWN_SECS` | Cooldown between config creations (default: `15`) |

`XRAY_REALITY_*`, `MTPROXY_DOMAIN`, and `MTPROXY_SECRET` are generated automatically by `setup.sh`.
For `nineseconds/mtg:2`, the secret must be an `ee...` hex secret with an embedded fronting hostname, matching the upstream `mtg generate-secret --hex <domain>` format.

## Bot Commands

| Command | Description |
|---|---|
| `/start` | Show welcome message and main menu |
| `/new_wg` | Create a WireGuard config (dialog) |
| `/new_xray` | Create a VLESS/Reality config (dialog) |
| `/my_configs` | List all configs with resend and delete buttons |
| `/traffic` | Traffic stats for all active configs |
| `/mtproxy` | MTProxy connection link |

Admin commands (ADMIN_IDS only):

| Command | Description |
|---|---|
| `/admin_users` | List all registered users |
| `/admin_ban` / `/admin_unban` | Ban or unban a user |
| `/admin_rebuild_xray` | Rebuild Xray config from database |

## Architecture

```
┌─────────────────────────────────────────┐
│              docker-compose              │
│                                         │
│  ┌──────────┐    ┌──────────────────┐  │
│  │ postgres │    │ docker-socket-   │  │
│  │  (DB)    │    │ proxy (security) │  │
│  └──────────┘    └──────────────────┘  │
│       │                  │              │
│  ┌────▼──────────────────▼───────────┐ │
│  │            vpn_bot                │ │
│  │  (aiogram 3, asyncpg, FSM)        │ │
│  └───────────────────────────────────┘ │
│                                         │
│  ┌──────────┐ ┌────────┐ ┌──────────┐ │
│  │amneziawg │ │  xray  │ │ mtproxy  │ │
│  │ :51820   │ │  :443  │ │  :8443   │ │
│  └──────────┘ └────────┘ └──────────┘ │
└─────────────────────────────────────────┘
```

- The bot talks to containers via `docker-socket-proxy` — it never touches the raw Docker socket directly. Only `CONTAINERS`, `EXEC`, `KILL`, and `POST` APIs are permitted.
- WireGuard peer configs are written to `amneziawg/config/wg0.conf` (shared volume) and applied with `awg syncconf` — no tunnel restart.
- Xray is reloaded with `SIGHUP` when clients are added or removed — reload takes ~50 ms vs several seconds for a restart.
- Peer creation uses an `asyncio.Lock` to prevent IP allocation races under concurrent requests.

## Clients

| Protocol | App |
|---|---|
| AmneziaWG | [AmneziaVPN](https://amnezia.org) (iOS, Android, macOS, Windows) |
| VLESS/Reality | [v2rayNG](https://github.com/2dust/v2rayNG) (Android), [Hiddify](https://hiddify.com) (all platforms), [Streisand](https://apps.apple.com/app/streisand/id6450534064) (iOS) |
| MTProxy | Built into Telegram — tap the connection link |

## Data

- PostgreSQL data: `postgres_data` Docker volume
- WireGuard config: `./amneziawg/config/` (bind mount)
- Xray config: `./xray/` (bind mount)

To back up: dump the Postgres volume and copy both config directories.
