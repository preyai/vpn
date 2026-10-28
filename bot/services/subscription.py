"""Subscription links: one URL per user that VLESS clients (Karing, Hiddify,
v2rayNG, Streisand) poll for the user's current configs, so changed keys or SNI
reach them without re-sending links.

Caddy terminates TLS for SUBS_DOMAIN and proxies here over the frontend network.
"""
import base64
import logging

from aiohttp import web

import config as cfg
import database as db
from services.xray_service import get_vless_link

logger = logging.getLogger(__name__)

_UPDATE_INTERVAL_HOURS = 12


def subscription_url(token: str) -> str:
    return f"https://{cfg.SUBS_DOMAIN}/{token}"


async def _handle(request: web.Request) -> web.Response:
    user = await db.get_user_by_sub_token(request.match_info["token"])
    # Unknown token and blocked user look the same, like any other missing page
    if not user or not user["is_active"]:
        raise web.HTTPNotFound()

    configs = await db.get_xray_configs(user["id"])
    body = "\n".join(get_vless_link(c) for c in configs)
    up = sum(c["traffic_up_total"] for c in configs)
    down = sum(c["traffic_down_total"] for c in configs)

    return web.Response(
        text=base64.b64encode(body.encode()).decode(),
        headers={
            "Cache-Control": "no-store",
            "Profile-Title": "base64:" + base64.b64encode(cfg.SUBS_DOMAIN.encode()).decode(),
            "Profile-Update-Interval": str(_UPDATE_INTERVAL_HOURS),
            "Subscription-Userinfo": f"upload={up}; download={down}; total=0; expire=0",
        },
    )


async def start_server() -> web.AppRunner:
    app = web.Application()
    app.router.add_get("/{token}", _handle)
    runner = web.AppRunner(app, access_log=None)  # the URL is the credential
    await runner.setup()
    await web.TCPSite(runner, "0.0.0.0", cfg.SUBS_LISTEN_PORT).start()
    logger.info("Subscription server listening on :%s", cfg.SUBS_LISTEN_PORT)
    return runner
