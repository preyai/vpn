import os

POSTGRES_DB            = os.environ.get("POSTGRES_DB", "vpn")
POSTGRES_USER          = os.environ.get("POSTGRES_USER", "vpn")
POSTGRES_HOST          = os.environ.get("POSTGRES_HOST", "postgres")
POSTGRES_PORT          = int(os.environ.get("POSTGRES_PORT", "5432"))
POSTGRES_PASSWORD      = os.environ.get("POSTGRES_PASSWORD", "")
DATABASE_URL           = os.environ.get(
    "DATABASE_URL",
    f"postgresql://{POSTGRES_USER}:{POSTGRES_PASSWORD}@{POSTGRES_HOST}:{POSTGRES_PORT}/{POSTGRES_DB}",
)

BOT_TOKEN              = os.environ["BOT_TOKEN"]
GROUP_ID               = int(os.environ["GROUP_ID"])
SERVER_IP              = os.environ["SERVER_IP"]
ADMIN_IDS              = [int(x) for x in os.environ.get("ADMIN_IDS", "").split(",") if x.strip()]

AWG_PORT               = int(os.environ.get("AWG_PORT", "51820"))
XRAY_PORT              = int(os.environ.get("XRAY_PORT", "443"))
XRAY_REALITY_SNI       = os.environ.get("XRAY_REALITY_SNI", "www.microsoft.com")
XRAY_REALITY_PUBLIC_KEY = os.environ["XRAY_REALITY_PUBLIC_KEY"]
XRAY_REALITY_SHORT_ID  = os.environ["XRAY_REALITY_SHORT_ID"]

MTPROXY_PORT           = int(os.environ.get("MTPROXY_PORT", "8443"))
MTPROXY_DOMAIN         = os.environ.get("MTPROXY_DOMAIN", "www.microsoft.com")
MTPROXY_SECRET         = os.environ["MTPROXY_SECRET"]

WG_CONFIG_PATH         = "/etc/amneziawg/wg0.conf"
XRAY_CONFIG_PATH       = "/etc/xray/config.json"

AWG_CONTAINER_NAME     = "amneziawg"
XRAY_CONTAINER_NAME    = "xray"

WG_SERVER_IP           = "10.8.0.1"
WG_SUBNET_BASE         = "10.8.0"
WG_MAX_PEERS           = 250

# Rate limiting
CREATION_COOLDOWN_SECS = int(os.environ.get("CREATION_COOLDOWN_SECS", "15"))
MAX_WG_CONFIGS         = int(os.environ.get("MAX_WG_CONFIGS", "5"))
MAX_XRAY_CONFIGS       = int(os.environ.get("MAX_XRAY_CONFIGS", "5"))
