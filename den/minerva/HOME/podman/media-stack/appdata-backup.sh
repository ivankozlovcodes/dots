#!/bin/bash
set -euo pipefail

UNITS="radarr sonarr prowlarr bazarr qbittorrent jellyfin seerr vaultwarden"
DEST=/mnt/nas/backups/media-stack

mountpoint -q /mnt/nas || { echo "NAS not mounted, aborting"; exit 1; }
mkdir -p "$DEST"

trap 'systemctl --user start $UNITS' EXIT
systemctl --user stop $UNITS

tar czf "$DEST/appdata-$(date +%F).tar.gz" -C /home/minerva appdata

ls -1t "$DEST"/appdata-*.tar.gz | tail -n +5 | xargs -r rm
