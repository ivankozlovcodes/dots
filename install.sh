#!/usr/bin/env bash
# Sync/link Herdr config between ~/git/dots and ~/.config
#
# Usage:
#   ./install.sh          # link mods + layouts + keys.json, copy settings.json & config.toml
#   ./install.sh --pull   # copy settings.json & config.toml back from ~/.config into dots

set -euo pipefail

DOTS=$(cd -- "$(dirname -- "$(readlink -f -- "$0")")" && pwd)
APP_SRC="$DOTS/.config/herdr-app"
APP_DST="$HOME/.config/herdr-app"
HERDR_SRC="$DOTS/.config/herdr"
HERDR_DST="$HOME/.config/herdr"

if [[ "${1:-}" == "--pull" ]]; then
	cp -v "$APP_DST/settings.json" "$APP_SRC/settings.json"
	cp -v "$APP_DST/keys.json" "$APP_SRC/keys.json"
	[[ -f "$HERDR_DST/config.toml" ]] && cp -v "$HERDR_DST/config.toml" "$HERDR_SRC/config.toml"
	exit 0
fi

mkdir -p "$APP_DST/layouts" "$APP_DST/mods" "$HERDR_DST"

# 1. Symlink each custom mod folder into ~/.config/herdr-app/mods/<name>
for mod_dir in "$APP_SRC/mods"/*/; do
	[[ -d "$mod_dir" ]] || continue
	mod=$(basename "$mod_dir")
	target="$APP_DST/mods/$mod"
	if [[ -d "$target" && ! -L "$target" ]]; then
		# Preserve any machine-local runtime.json before replacing directory with symlink
		[[ -f "$target/runtime.json" && ! -f "$mod_dir/runtime.json" ]] && cp "$target/runtime.json" "$mod_dir/runtime.json"
		rm -rf "$target"
	fi
	ln -sfn "$mod_dir" "$target"
	echo "linked mod: $target -> $mod_dir"
done

# 2. Symlink custom layouts into ~/.config/herdr-app/layouts/<name>.json
for layout in "$APP_SRC/layouts"/*.json; do
	[[ -f "$layout" ]] || continue
	name=$(basename "$layout")
	ln -sfn "$layout" "$APP_DST/layouts/$name"
	echo "linked layout: $APP_DST/layouts/$name -> $layout"
done

# 3. Symlink keys.json (edited by hand, not overwritten by Herdr UI)
ln -sfn "$APP_SRC/keys.json" "$APP_DST/keys.json"
echo "linked keys: $APP_DST/keys.json -> $APP_SRC/keys.json"

# 4. Copy settings.json and herdr/config.toml (Herdr rewrites settings.json atomically on zoom/settings change)
cp "$APP_SRC/settings.json" "$APP_DST/settings.json"
echo "copied: $APP_DST/settings.json"

if [[ -f "$HERDR_SRC/config.toml" ]]; then
	cp "$HERDR_SRC/config.toml" "$HERDR_DST/config.toml"
	echo "copied: $HERDR_DST/config.toml"
fi
