import os


def _required(name: str) -> str:
    value = os.environ.get(name, "").strip()
    if not value:
        raise SystemExit(f"{name} is not set in .env. Run scripts/setup.sh on the host to fill it.")
    return value


POSTGRES_DB            = os.environ.get("POSTGRES_DB", "vpn")
POSTGRES_USER          = os.environ.get("POSTGRES_USER", "vpn")
POSTGRES_HOST          = os.environ.get("POSTGRES_HOST", "postgres")
POSTGRES_PORT          = int(os.environ.get("POSTGRES_PORT", "5432"))
POSTGRES_PASSWORD      = os.environ.get("POSTGRES_PASSWORD", "")
DATABASE_URL           = os.environ.get(
    "DATABASE_URL",
    f"postgresql://{POSTGRES_USER}:{POSTGRES_PASSWORD}@{POSTGRES_HOST}:{POSTGRES_PORT}/{POSTGRES_DB}",
)

BOT_TOKEN              = _required("BOT_TOKEN")
GROUP_ID               = int(_required("GROUP_ID"))
SERVER_IP              = _required("SERVER_IP")
ADMIN_IDS              = [int(x) for x in os.environ.get("ADMIN_IDS", "").split(",") if x.strip()]

AWG_PORT               = int(os.environ.get("AWG_PORT", "51820"))
XRAY_PORT              = int(os.environ.get("XRAY_PORT", "443"))
XRAY_REALITY_SNI       = os.environ.get("XRAY_REALITY_SNI", "www.microsoft.com")
XRAY_REALITY_PUBLIC_KEY = _required("XRAY_REALITY_PUBLIC_KEY")
XRAY_REALITY_SHORT_ID  = _required("XRAY_REALITY_SHORT_ID")

MTPROXY_PORT           = int(os.environ.get("MTPROXY_PORT", "8443"))
MTPROXY_DOMAIN         = os.environ.get("MTPROXY_DOMAIN", "www.microsoft.com")
MTPROXY_SECRET         = _required("MTPROXY_SECRET")

WG_CONFIG_PATH         = "/etc/amneziawg/wg0.conf"
XRAY_CONFIG_PATH       = "/etc/xray/config.json"

AWG_CONTAINER_NAME     = "amneziawg"
XRAY_CONTAINER_NAME    = "xray"
MTPROXY_CONTAINER_NAME = "mtproxy"

WG_SERVER_IP           = "10.8.0.1"
WG_SUBNET_BASE         = "10.8.0"
WG_MAX_PEERS           = 250

# Rate limiting
CREATION_COOLDOWN_SECS = int(os.environ.get("CREATION_COOLDOWN_SECS", "15"))
MAX_WG_CONFIGS         = int(os.environ.get("MAX_WG_CONFIGS", "50"))
MAX_XRAY_CONFIGS       = int(os.environ.get("MAX_XRAY_CONFIGS", "50"))
