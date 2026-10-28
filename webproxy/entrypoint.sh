#!/bin/sh
set -eu

: "${TG_WEBPROXY_DOMAIN:?TG_WEBPROXY_DOMAIN is not set in .env}"
: "${TG_WEBPROXY_SECRET:?TG_WEBPROXY_SECRET is not set in .env}"

# The relay rejects hostnames that are not lowercase
DOMAIN=$(printf '%s' "$TG_WEBPROXY_DOMAIN" | tr 'A-Z' 'a-z')

mkdir -p /data/site /etc/tproxy

# Signs relay sessions; kept across restarts so connected clients are not dropped
if [ ! -f /data/token.key ]; then
    head -c 32 /dev/urandom > /data/token.key
fi
chmod 600 /data/token.key

# Requests without valid relay credentials get this site, so the domain looks like
# an ordinary website. Replace webproxy/site/ with a real one if you have it
if [ ! -f /data/site/index.html ]; then
    cat > /data/site/index.html <<EOF
<!doctype html>
<html lang="en">
<head><meta charset="utf-8"><title>${DOMAIN}</title></head>
<body><h1>${DOMAIN}</h1><p>Nothing here yet.</p></body>
</html>
EOF
fi

# Regenerated on every start, so editing .env and restarting is enough
umask 077
cat > /etc/tproxy/config.json <<EOF
{
  "public_hostname": "${DOMAIN}",
  "listen": "127.0.0.1:8080",
  "admin_listen": "127.0.0.1:8081",
  "public_dir": "/data/site",
  "static_routes": "exact",
  "token_key_file": "/data/token.key",
  "profiles_file": "/etc/tproxy/profiles.json"
}
EOF
cat > /etc/tproxy/profiles.json <<EOF
{
  "profiles": [
    {"name": "default", "secret": "${TG_WEBPROXY_SECRET}", "backend": "127.0.0.1:2398"}
  ]
}
EOF

exec tproxy-server -config /etc/tproxy/config.json
