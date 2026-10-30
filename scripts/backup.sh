#!/bin/sh
# Runs inside the backup container. Archives everything needed to rebuild this server
# with the same users and keys: `sh /backup.sh now` once, `sh /backup.sh loop` as a daemon.
set -eu

BACKUP_DIR=/backups
KEEP_DAYS=14
INTERVAL_MINUTES=1440

umask 077

make_backup() {
    work=$(mktemp -d)
    trap 'rm -rf "$work"' EXIT

    pg_dump --clean --if-exists --no-owner > "$work/db.sql"
    cp /project/.env "$work/env"
    mkdir -p "$work/xray" "$work/amneziawg" "$work/webproxy"
    cp /project/xray/config.json "$work/xray/config.json"
    cp /project/amneziawg/config/wg0.conf "$work/amneziawg/wg0.conf"
    cp /webproxy-data/token.key "$work/webproxy/token.key"
    cp -R /project/webproxy/site "$work/webproxy/site"

    name="vpn-backup-$(date -u +%Y%m%d-%H%M%S).tar.gz"
    # Written under a temporary name, so a failed run never looks like a good backup
    tar -czf "$BACKUP_DIR/.$name.tmp" -C "$work" .
    mv "$BACKUP_DIR/.$name.tmp" "$BACKUP_DIR/$name"

    rm -rf "$work"
    trap - EXIT

    # Only after a successful run, so old backups survive if new ones start failing
    find "$BACKUP_DIR" -name 'vpn-backup-*.tar.gz' -mtime +"$KEEP_DAYS" -delete
    echo "Backup written: $name"
}

case "${1:-now}" in
    now)
        make_backup
        ;;
    loop)
        while true; do
            # Age-based rather than a plain sleep: restarting the container neither
            # postpones the next backup nor produces extra ones
            if [ -z "$(find "$BACKUP_DIR" -name 'vpn-backup-*.tar.gz' -mmin -"$INTERVAL_MINUTES")" ]; then
                # A separate process: inside `make_backup || ...` the shell would ignore
                # set -e, and a failed pg_dump would still produce a "good" archive
                sh "$0" now || echo "Backup failed" >&2
            fi
            sleep 600
        done
        ;;
    *)
        echo "Usage: backup.sh [now|loop]" >&2
        exit 2
        ;;
esac
