# VPN Server Manager

Self-hosted VPN server with a Telegram bot interface. Supports three protocols:

- **AmneziaWG** — obfuscated WireGuard (bypasses DPI)
- **VLESS + Reality** — Xray proxy with TLS camouflage
- **HTTP proxy for Telegram** — served by Xray, works in Telegram Desktop

Everything runs in Docker Compose. Users manage their own configs via a Telegram bot — no web UI, no manual config editing.

## Requirements

- Linux server with a public IP
- Docker + Docker Compose
- `openssl` and `python3` (`apt install openssl python3`)
- AmneziaWG kernel module on the host:
  ```bash
  sudo add-apt-repository ppa:amnezia/ppa
  sudo apt update && sudo apt install amneziawg
  sudo modprobe amneziawg
  ```

## Quick Start

```bash
git clone https://github.com/preyai/vpn.git && cd vpn

# Generate keys, create configs and connect the Telegram bot
bash scripts/setup.sh

# Start everything
docker compose up -d --build
```

`setup.sh` ends with a short Telegram wizard:

1. Create a bot in [@BotFather](https://t.me/BotFather) (`/newbot`) and paste its token — the script checks it right away.
2. Add the bot to your group and promote it to administrator — the script detects the group and writes `GROUP_ID`.
3. Whoever added the bot becomes the bot admin (`ADMIN_IDS`); add more IDs to `.env` by hand, comma-separated.

The wizard only asks for values missing from `.env`, so it is safe to re-run: `python3 scripts/telegram_setup.py` (stop the bot container first — only one process can read the bot's updates). You can also skip it and fill the three values in `.env` manually.

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
| `TG_PROXY_PORT` | Telegram HTTP proxy TCP port (default: `8080`) |
| `TG_PROXY_USER` / `TG_PROXY_PASSWORD` | Telegram HTTP proxy credentials, shared by all users |
| `MAX_WG_CONFIGS` | Max WireGuard configs per user (default: `5`) |
| `MAX_XRAY_CONFIGS` | Max VLESS configs per user (default: `5`) |
| `CREATION_COOLDOWN_SECS` | Cooldown between config creations (default: `15`) |

`XRAY_REALITY_*` and `TG_PROXY_PASSWORD` are generated automatically by `setup.sh`.

`XRAY_REALITY_SNI` can be changed after setup: edit `.env` and run `docker compose up -d` — the bot rewrites `xray/config.json` on startup and restarts Xray. Links issued earlier carry the old SNI and must be re-sent from `/my_configs`.

The Telegram proxy is an `http` inbound the bot adds to `xray/config.json` on startup, so changing `TG_PROXY_USER` / `TG_PROXY_PASSWORD` works the same way. It only connects to [Telegram's IP ranges](https://core.telegram.org/resources/cidr.txt) — with a password shared by the whole group it must not work as a general-purpose proxy. Telegram has no share links for HTTP proxies, so `/tg_proxy` sends the settings to enter by hand; Telegram's mobile apps support only SOCKS5 and MTProto proxies.

Upgrading from a version with MTProxy: run `bash scripts/setup.sh` (it adds the `TG_PROXY_*` settings to `.env`), open port `8080/tcp` in the firewall, then `docker compose up -d --build --remove-orphans` to remove the old `mtproxy` container. The `MTPROXY_*` lines left in `.env` are ignored.

## Bot Commands

| Command | Description |
|---|---|
| `/start` | Show welcome message and main menu |
| `/new_wg` | Create a WireGuard config (dialog) |
| `/new_xray` | Create a VLESS/Reality config (dialog) |
| `/my_configs` | List all configs with resend and delete buttons |
| `/traffic` | Traffic stats for all active configs |
| `/tg_proxy` | Telegram HTTP proxy settings |

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
│  ┌──────────┐ ┌───────────────────┐   │
│  │amneziawg │ │       xray        │   │
│  │ :51820   │ │ :443 VLESS        │   │
│  │          │ │ :8080 TG HTTP     │   │
│  └──────────┘ └───────────────────┘   │
└─────────────────────────────────────────┘
```

- The bot talks to containers via `docker-socket-proxy` — it never touches the raw Docker socket directly. Only `CONTAINERS`, `EXEC`, `KILL`, and `POST` APIs are permitted.
- Two Docker networks keep VPN clients away from the control plane: `backend` (socket proxy, Postgres) is internal and only the bot is attached to it; `frontend` holds the containers that forward client traffic. Xray additionally refuses to proxy to private addresses, and its access log is off, so users' destinations are not recorded. Container logs are capped at 3 × 10 MB each.
- WireGuard peer configs are written to `amneziawg/config/wg0.conf` (shared volume) and applied with `awg syncconf` — no tunnel restart.
- Xray is reloaded with `SIGHUP` when clients are added or removed — reload takes ~50 ms vs several seconds for a restart.
- Peer creation uses an `asyncio.Lock` to prevent IP allocation races under concurrent requests.

## Clients

| Protocol | App |
|---|---|
| AmneziaWG | [AmneziaVPN](https://amnezia.org) (iOS, Android, macOS, Windows) |
| VLESS/Reality | [v2rayNG](https://github.com/2dust/v2rayNG) (Android), [Hiddify](https://hiddify.com) (all platforms), [Streisand](https://apps.apple.com/app/streisand/id6450534064) (iOS) |
| Telegram HTTP proxy | Telegram Desktop: Settings → Advanced → Connection type → Use custom proxy → HTTP |

## Data

- PostgreSQL data: `postgres_data` Docker volume
- WireGuard config: `./amneziawg/config/` (bind mount)
- Xray config: `./xray/` (bind mount)

To back up: dump the Postgres volume and copy both config directories.
