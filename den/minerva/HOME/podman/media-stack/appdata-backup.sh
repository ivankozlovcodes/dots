#!/bin/bash
set -euo pipefail

UNITS="radarr sonarr prowlarr bazarr qbittorrent jellyfin seerr vaultwarden immich-server immich-machine-learning"
DEST=/mnt/nas/backups/media-stack

mountpoint -q /mnt/nas || { echo "NAS not mounted, aborting"; exit 1; }
mkdir -p "$DEST"

trap 'systemctl --user start $UNITS' EXIT
systemctl --user stop $UNITS

# Back up appdata (excluding immich pgdata - handled separately)
tar czf "$DEST/appdata-$(date +%F).tar.gz" -C /home/minerva --exclude='immich/pgdata' appdata

# Back up Immich database via pg_dump
BACKUP_FILE="$DEST/immich-db-$(date +%F).sql.gz"
podman exec systemd-immich-database pg_dump --clean --if-exists --dbname=immich --username=postgres | gzip > "$BACKUP_FILE"

ls -1t "$DEST"/appdata-*.tar.gz | tail -n +5 | xargs -r rm
ls -1t "$DEST"/immich-db-*.sql.gz | tail -n +5 | xargs -r rm
