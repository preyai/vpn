# VPN Server Manager

Self-hosted VPN server with a Telegram bot interface. Supports three protocols:

- **AmneziaWG** — obfuscated WireGuard (bypasses DPI)
- **VLESS + Reality** — Xray proxy with TLS camouflage
- **Telegram WEB proxy** — Telegram's own proxy type that looks like an ordinary HTTPS website

Everything runs in Docker Compose. Users manage their own configs via a Telegram bot — no web UI, no manual config editing.

## Requirements

- Linux server with a public IP and open TCP ports 80 and 443
- Two domains (or subdomains) with A records pointing at the server — for the Telegram WEB proxy and for subscription links
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
| `TG_WEBPROXY_DOMAIN` | Domain of the Telegram WEB proxy (asked for by `setup.sh`) |
| `TG_WEBPROXY_SECRET` | Telegram WEB proxy secret, shared by all users |
| `SUBS_DOMAIN` | Domain for subscription links (asked for by `setup.sh`) |
| `DONATE_URL` | Optional payment link shown as a button under the donation QR code |
| `WG_ADMIN_ONLY` | `true`: only admins can create new WireGuard configs; existing ones keep working |
| `MAX_WG_CONFIGS` | Max WireGuard configs per user (default: `5`) |
| `MAX_XRAY_CONFIGS` | Max VLESS configs per user (default: `5`) |
| `CREATION_COOLDOWN_SECS` | Cooldown between config creations (default: `15`) |

`XRAY_REALITY_*` and `TG_WEBPROXY_SECRET` are generated automatically by `setup.sh`.

`XRAY_REALITY_SNI` can be changed after setup: edit `.env` and run `docker compose up -d` — the bot rewrites `xray/config.json` on startup and restarts Xray. Links issued earlier carry the old SNI and must be re-sent from `/my_configs`.

Xray is pinned to 26.7.28 and the bot sets Reality's `minClientVer` to `1.0.0`. Clients built on sing-box (Karing, Hiddify) report an old Xray version, and newer Xray turns them away with "reality verification failed": 26.7.28 by its default minimum client version, 26.9.8+ also by requiring an X25519MLKEM768 key share that sing-box does not send. Do not bump the Xray image until sing-box supports it.

### Telegram WEB proxy

Telegram Desktop 7.1 added a WEB proxy type: the app carries ordinary MTProxy traffic through a built-in browser over real HTTPS/WebSocket to your domain, so to an observer it looks like someone visiting a website. Android support is in beta, iOS does not have it yet.

The server side is Telegram's [tproxy-server](https://github.com/telegramdesktop/tproxy-server) (built from a pinned commit in `webproxy/Dockerfile` — upstream calls it a proof of concept), [Caddy](https://caddyserver.com) for the Let's Encrypt certificate, and [teleproxy](https://github.com/teleproxy/teleproxy) as the MTProxy backend in direct-to-DC mode. Without the secret the domain shows a plain website from `webproxy/site/` (a placeholder is created on first start — replace it with something real).

Port 443 is shared with VLESS/Reality: `sni-router` (nginx `stream`) reads the TLS SNI without decrypting and sends `TG_WEBPROXY_DOMAIN` to the WEB proxy and everything else to Xray. Port 80 is used by Caddy for the certificate.

`/tg_proxy` sends a `https://t.me/webproxy?server=…&secret=…` link. Changing `TG_WEBPROXY_DOMAIN` or `TG_WEBPROXY_SECRET`: edit `.env` and run `docker compose up -d`.

### Subscriptions

`/sub` gives each user a personal `https://SUBS_DOMAIN/<token>` link. VLESS clients (Karing, Hiddify, v2rayNG, Streisand) add it as a subscription and refresh it every 12 hours, so new configs and changed keys or SNI reach them without re-sending links. The bot serves it on port 8090 inside the Docker network; `sni-router` and Caddy put it on 443 with a Let's Encrypt certificate. An unknown token and a blocked user both get a plain 404. WireGuard is not included: subscription formats cannot carry AmneziaWG's obfuscation settings.

Subscriptions use their own domain: on the WEB proxy domain every path must look like the same ordinary website. Both still share the server's IP, so a leaked subscription link points at this server — that is what the reset button is for.

### Upgrading from MTProxy or the HTTP proxy

1. Point a domain's A record at the server.
2. `bash scripts/setup.sh` — adds `TG_WEBPROXY_SECRET` to `.env` and asks for the domain.
3. Open TCP 80 (443 is already open); 8443 and 8080 can be closed.
4. `docker compose up -d --build --remove-orphans` — removes the old `mtproxy` container; the bot removes the old HTTP proxy inbound from `xray/config.json`.

`XRAY_PORT` is gone: VLESS is always on 443 behind the router. If you had changed it, re-send VLESS links from `/my_configs`. Leftover `MTPROXY_*`, `TG_PROXY_*` and `XRAY_PORT` lines in `.env` are ignored.

## Bot Commands

Most things are reachable from the menu keyboard: **➕ Connect a device** asks WireGuard or VLESS with a short explanation of each; **📁 My devices** lists configs, and each opens a card with traffic, expiry, resend, QR only, rename and delete; admins also get **🛠 Admin** with buttons for users, traffic, status, stale WG cleanup and an Xray rebuild. Any message the bot does not understand gets the current menu back, which also replaces buttons left over from older versions.

| Command | Description |
|---|---|
| `/start` | Show welcome message and main menu |
| `/new_wg` | Create a WireGuard config (dialog) |
| `/new_xray` | Create a VLESS/Reality config (dialog) |
| `/sub` | Personal subscription link with all VLESS configs; can be reset |
| `/my_configs` | Device list; each config opens a card with resend, QR, rename and delete |
| `/traffic` | Traffic stats for all active configs |
| `/tg_proxy` | Telegram WEB proxy link |

Admin commands (ADMIN_IDS only):

| Command | Description |
|---|---|
| `/admin_users` | List all registered users; 📁 opens a user's configs |
| `/admin_traffic` | Traffic per user, heaviest first; 📁 opens a user's configs (names, types, ids, expiry, traffic — no keys or links) |
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
│  │amneziawg │ │ sni-router :443   │   │
│  │ :51820   │ └──┬─────────────┬──┘   │
│  └──────────┘    │ other SNI   │ TG_WEBPROXY_DOMAIN
│              ┌───▼────┐ ┌──────▼─────┐ │
│              │  xray  │ │ webproxy   │ │
│              │ VLESS  │ │ caddy :80  │ │
│              └────────┘ │ tproxy     │ │
│                         │ teleproxy  │ │
│                         └────────────┘ │
└─────────────────────────────────────────┘
```

- The bot talks to containers via `docker-socket-proxy` — it never touches the raw Docker socket directly. Only `CONTAINERS`, `EXEC`, `KILL`, and `POST` APIs are permitted.
- Two Docker networks keep VPN clients away from the control plane: `backend` (socket proxy, Postgres) is internal and only the bot and the backup job are attached to it; `frontend` holds the containers that forward client traffic. Xray additionally refuses to proxy to private addresses, and its access log is off, so users' destinations are not recorded. Container logs are capped at 3 × 10 MB each.
- WireGuard peer configs are written to `amneziawg/config/wg0.conf` (shared volume) and applied with `awg syncconf` — no tunnel restart.
- Xray is reloaded with `SIGHUP` when clients are added or removed — reload takes ~50 ms vs several seconds for a restart.
- Peer creation uses an `asyncio.Lock` to prevent IP allocation races under concurrent requests.

## Clients

| Protocol | App |
|---|---|
| AmneziaWG | [AmneziaVPN](https://amnezia.org) (iOS, Android, macOS, Windows) |
| VLESS/Reality | [v2rayNG](https://github.com/2dust/v2rayNG) (Android), [Hiddify](https://hiddify.com) (all platforms), [Streisand](https://apps.apple.com/app/streisand/id6450534064) (iOS) |
| Telegram WEB proxy | Telegram Desktop 7.1+ — tap the link from `/tg_proxy` (Android: beta, iOS: not yet) |

## Data

- PostgreSQL data: `postgres_data` Docker volume
- WireGuard config: `./amneziawg/config/` (bind mount)
- Xray config: `./xray/` (bind mount)

## Backups and moving to a new server

The `backup` container writes `backups/vpn-backup-<date>.tar.gz` once a day and deletes archives older than 14 days. Each holds the database, `.env`, `xray/config.json`, `wg0.conf`, the WEB proxy token key and `webproxy/site/`. Run one by hand with `docker compose exec backup sh /backup.sh now`. If no backup succeeds for 26 hours, the container turns unhealthy and the bot alerts admins.

The archives contain every private key and are stored unencrypted, readable by root only, on the same server. They do not protect against losing the server itself: copy them elsewhere from time to time, and do it right away if an IP gets blocked (it usually stays reachable from outside the country that blocked it).

```bash
scp root@OLD_IP:/opt/vpn/backups/vpn-backup-XXXX.tar.gz .
```

To move: install the requirements on the new server, clone the repository, copy the archive there, and run:

```bash
bash scripts/restore.sh vpn-backup-XXXX.tar.gz
```

It restores everything, sets `SERVER_IP` to the new address and starts the stack. It asks for confirmation if the server already has a configuration. Then point the `TG_WEBPROXY_DOMAIN` and `SUBS_DOMAIN` A records at the new IP and stop the bot on the old server. Subscriptions keep working and pick up the new IP on their own; VLESS links and WireGuard configs issued earlier carry the old IP and must be re-sent from the bot.
