import asyncpg
from config import DATABASE_URL

_pool: asyncpg.Pool | None = None

CREATE_SCHEMA = """
CREATE TABLE IF NOT EXISTS users (
    id          SERIAL PRIMARY KEY,
    telegram_id BIGINT  UNIQUE NOT NULL,
    username    TEXT,
    full_name   TEXT,
    is_active   BOOLEAN DEFAULT TRUE,
    created_at  TIMESTAMP DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS wg_configs (
    id               SERIAL PRIMARY KEY,
    user_id          INTEGER REFERENCES users(id) ON DELETE CASCADE,
    name             TEXT NOT NULL,
    public_key       TEXT UNIQUE NOT NULL,
    private_key      TEXT NOT NULL,
    ip_address       TEXT UNIQUE NOT NULL,
    is_active        BOOLEAN DEFAULT TRUE,
    expires_at       TIMESTAMP,
    traffic_rx_total BIGINT DEFAULT 0,
    traffic_tx_total BIGINT DEFAULT 0,
    traffic_rx_last  BIGINT DEFAULT 0,
    traffic_tx_last  BIGINT DEFAULT 0,
    created_at       TIMESTAMP DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS xray_configs (
    id                 SERIAL PRIMARY KEY,
    user_id            INTEGER REFERENCES users(id) ON DELETE CASCADE,
    name               TEXT NOT NULL,
    uuid               TEXT UNIQUE NOT NULL,
    email              TEXT UNIQUE NOT NULL,
    is_active          BOOLEAN DEFAULT TRUE,
    expires_at         TIMESTAMP,
    traffic_up_total   BIGINT DEFAULT 0,
    traffic_down_total BIGINT DEFAULT 0,
    traffic_up_last    BIGINT DEFAULT 0,
    traffic_down_last  BIGINT DEFAULT 0,
    created_at         TIMESTAMP DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS settings (
    key   TEXT PRIMARY KEY,
    value TEXT NOT NULL
);
"""

# Migration for databases created before expires_at/traffic totals existed.
MIGRATE_SCHEMA = """
ALTER TABLE wg_configs   ADD COLUMN IF NOT EXISTS expires_at TIMESTAMP;
ALTER TABLE xray_configs ADD COLUMN IF NOT EXISTS expires_at TIMESTAMP;

ALTER TABLE wg_configs   ADD COLUMN IF NOT EXISTS traffic_rx_total BIGINT DEFAULT 0;
ALTER TABLE wg_configs   ADD COLUMN IF NOT EXISTS traffic_tx_total BIGINT DEFAULT 0;
ALTER TABLE wg_configs   ADD COLUMN IF NOT EXISTS traffic_rx_last  BIGINT DEFAULT 0;
ALTER TABLE wg_configs   ADD COLUMN IF NOT EXISTS traffic_tx_last  BIGINT DEFAULT 0;

ALTER TABLE xray_configs ADD COLUMN IF NOT EXISTS traffic_up_total   BIGINT DEFAULT 0;
ALTER TABLE xray_configs ADD COLUMN IF NOT EXISTS traffic_down_total BIGINT DEFAULT 0;
ALTER TABLE xray_configs ADD COLUMN IF NOT EXISTS traffic_up_last    BIGINT DEFAULT 0;
ALTER TABLE xray_configs ADD COLUMN IF NOT EXISTS traffic_down_last  BIGINT DEFAULT 0;
"""


async def init_db() -> None:
    global _pool
    _pool = await asyncpg.create_pool(DATABASE_URL, min_size=2, max_size=10)
    async with _pool.acquire() as conn:
        await conn.execute(CREATE_SCHEMA)
        await conn.execute(MIGRATE_SCHEMA)


async def close_db() -> None:
    if _pool:
        await _pool.close()


def _pool_() -> asyncpg.Pool:
    if _pool is None:
        raise RuntimeError("DB pool not initialized — call init_db() first")
    return _pool


# ── Users ─────────────────────────────────────────────────────────────────────

async def get_or_create_user(telegram_id: int, username: str | None, full_name: str) -> dict:
    async with _pool_().acquire() as conn:
        row = await conn.fetchrow(
            """INSERT INTO users (telegram_id, username, full_name)
               VALUES ($1, $2, $3)
               ON CONFLICT (telegram_id) DO UPDATE
               SET username = EXCLUDED.username, full_name = EXCLUDED.full_name
               RETURNING *""",
            telegram_id, username, full_name,
        )
        return dict(row)


async def get_user(telegram_id: int) -> dict | None:
    async with _pool_().acquire() as conn:
        row = await conn.fetchrow("SELECT * FROM users WHERE telegram_id = $1", telegram_id)
        return dict(row) if row else None


async def set_user_active(telegram_id: int, active: bool) -> None:
    async with _pool_().acquire() as conn:
        await conn.execute(
            "UPDATE users SET is_active = $1 WHERE telegram_id = $2", active, telegram_id
        )


async def get_all_users() -> list[dict]:
    async with _pool_().acquire() as conn:
        rows = await conn.fetch("SELECT * FROM users ORDER BY created_at DESC")
        return [dict(r) for r in rows]


# ── WireGuard ─────────────────────────────────────────────────────────────────

async def add_wg_config(user_id: int, name: str, public_key: str, private_key: str, ip_address: str) -> int:
    async with _pool_().acquire() as conn:
        row = await conn.fetchrow(
            """INSERT INTO wg_configs (user_id, name, public_key, private_key, ip_address)
               VALUES ($1, $2, $3, $4, $5) RETURNING id""",
            user_id, name, public_key, private_key, ip_address,
        )
        return row["id"]


async def get_wg_configs(user_id: int) -> list[dict]:
    async with _pool_().acquire() as conn:
        rows = await conn.fetch(
            "SELECT * FROM wg_configs WHERE user_id = $1 AND is_active = TRUE ORDER BY created_at",
            user_id,
        )
        return [dict(r) for r in rows]


async def get_wg_config_by_id(config_id: int, user_id: int) -> dict | None:
    async with _pool_().acquire() as conn:
        row = await conn.fetchrow(
            "SELECT * FROM wg_configs WHERE id = $1 AND user_id = $2 AND is_active = TRUE",
            config_id, user_id,
        )
        return dict(row) if row else None


async def delete_wg_config(config_id: int, user_id: int) -> dict | None:
    async with _pool_().acquire() as conn:
        row = await conn.fetchrow(
            "SELECT * FROM wg_configs WHERE id = $1 AND user_id = $2", config_id, user_id
        )
        if row:
            await conn.execute(
                "UPDATE wg_configs SET is_active = FALSE WHERE id = $1", config_id
            )
        return dict(row) if row else None


async def get_all_wg_ips() -> list[str]:
    async with _pool_().acquire() as conn:
        rows = await conn.fetch("SELECT ip_address FROM wg_configs")
        return [r["ip_address"] for r in rows]


async def accumulate_wg_traffic(config_id: int, rx: int, tx: int) -> None:
    """Adds the delta since the last observed counter value to the lifetime
    total. If the live counter is smaller than last time (interface/container
    restart reset it), treats the current value itself as the delta."""
    async with _pool_().acquire() as conn:
        await conn.execute(
            """UPDATE wg_configs SET
                 traffic_rx_total = traffic_rx_total +
                     (CASE WHEN $2 >= traffic_rx_last THEN $2 - traffic_rx_last ELSE $2 END),
                 traffic_tx_total = traffic_tx_total +
                     (CASE WHEN $3 >= traffic_tx_last THEN $3 - traffic_tx_last ELSE $3 END),
                 traffic_rx_last = $2,
                 traffic_tx_last = $3
               WHERE id = $1""",
            config_id, rx, tx,
        )


async def set_wg_expiry(config_id: int, expires_at) -> bool:
    async with _pool_().acquire() as conn:
        tag = await conn.execute(
            "UPDATE wg_configs SET expires_at = $1 WHERE id = $2", expires_at, config_id
        )
        return tag.endswith(" 1")


async def get_expired_wg_configs() -> list[dict]:
    async with _pool_().acquire() as conn:
        rows = await conn.fetch(
            "SELECT * FROM wg_configs WHERE is_active = TRUE "
            "AND expires_at IS NOT NULL AND expires_at <= NOW()"
        )
        return [dict(r) for r in rows]


async def get_all_active_wg_configs() -> list[dict]:
    async with _pool_().acquire() as conn:
        rows = await conn.fetch("SELECT * FROM wg_configs WHERE is_active = TRUE")
        return [dict(r) for r in rows]


# ── Xray ──────────────────────────────────────────────────────────────────────

async def add_xray_config(user_id: int, name: str, uuid: str, email: str) -> int:
    async with _pool_().acquire() as conn:
        row = await conn.fetchrow(
            "INSERT INTO xray_configs (user_id, name, uuid, email) VALUES ($1, $2, $3, $4) RETURNING id",
            user_id, name, uuid, email,
        )
        return row["id"]


async def update_xray_email(config_id: int, email: str) -> None:
    async with _pool_().acquire() as conn:
        await conn.execute(
            "UPDATE xray_configs SET email = $1 WHERE id = $2", email, config_id
        )


async def get_xray_configs(user_id: int) -> list[dict]:
    async with _pool_().acquire() as conn:
        rows = await conn.fetch(
            "SELECT * FROM xray_configs WHERE user_id = $1 AND is_active = TRUE ORDER BY created_at",
            user_id,
        )
        return [dict(r) for r in rows]


async def get_xray_config_by_id(config_id: int, user_id: int) -> dict | None:
    async with _pool_().acquire() as conn:
        row = await conn.fetchrow(
            "SELECT * FROM xray_configs WHERE id = $1 AND user_id = $2 AND is_active = TRUE",
            config_id, user_id,
        )
        return dict(row) if row else None


async def delete_xray_config(config_id: int, user_id: int) -> dict | None:
    async with _pool_().acquire() as conn:
        row = await conn.fetchrow(
            "SELECT * FROM xray_configs WHERE id = $1 AND user_id = $2", config_id, user_id
        )
        if row:
            await conn.execute(
                "UPDATE xray_configs SET is_active = FALSE WHERE id = $1", config_id
            )
        return dict(row) if row else None


async def get_all_active_xray_configs() -> list[dict]:
    async with _pool_().acquire() as conn:
        rows = await conn.fetch("SELECT * FROM xray_configs WHERE is_active = TRUE")
        return [dict(r) for r in rows]


async def accumulate_xray_traffic(config_id: int, up: int, down: int) -> None:
    """Same reset-aware accumulation as accumulate_wg_traffic, for Xray's
    uplink/downlink counters."""
    async with _pool_().acquire() as conn:
        await conn.execute(
            """UPDATE xray_configs SET
                 traffic_up_total = traffic_up_total +
                     (CASE WHEN $2 >= traffic_up_last THEN $2 - traffic_up_last ELSE $2 END),
                 traffic_down_total = traffic_down_total +
                     (CASE WHEN $3 >= traffic_down_last THEN $3 - traffic_down_last ELSE $3 END),
                 traffic_up_last = $2,
                 traffic_down_last = $3
               WHERE id = $1""",
            config_id, up, down,
        )


async def set_xray_expiry(config_id: int, expires_at) -> bool:
    async with _pool_().acquire() as conn:
        tag = await conn.execute(
            "UPDATE xray_configs SET expires_at = $1 WHERE id = $2", expires_at, config_id
        )
        return tag.endswith(" 1")


async def get_expired_xray_configs() -> list[dict]:
    async with _pool_().acquire() as conn:
        rows = await conn.fetch(
            "SELECT * FROM xray_configs WHERE is_active = TRUE "
            "AND expires_at IS NOT NULL AND expires_at <= NOW()"
        )
        return [dict(r) for r in rows]


# ── Settings ──────────────────────────────────────────────────────────────────

async def get_setting(key: str) -> str | None:
    async with _pool_().acquire() as conn:
        row = await conn.fetchrow("SELECT value FROM settings WHERE key = $1", key)
        return row["value"] if row else None


async def set_setting(key: str, value: str) -> None:
    async with _pool_().acquire() as conn:
        await conn.execute(
            """INSERT INTO settings (key, value) VALUES ($1, $2)
               ON CONFLICT (key) DO UPDATE SET value = EXCLUDED.value""",
            key, value,
        )


async def delete_setting(key: str) -> None:
    async with _pool_().acquire() as conn:
        await conn.execute("DELETE FROM settings WHERE key = $1", key)
