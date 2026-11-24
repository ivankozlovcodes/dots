#!/usr/bin/env bash
# Sync, link, and recover Herdr config between ~/git/dots and ~/.config
#
# Usage:
#   herdr/install.sh          # link mods + layouts + themes + keys.json, copy settings.json & config.toml
#   herdr/install.sh --clean  # purge any third-party mods/layouts/files not owned by Herdr or dots, then install
#   herdr/install.sh --pull   # copy settings.json, keys.json & config.toml back from ~/.config into dots

set -euo pipefail

DOTS=$(cd -- "$(dirname -- "$(readlink -f -- "$0")")/.." && pwd)
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

# --clean: remove any foreign mods, layouts, or extra folders left by third-party installers
if [[ "${1:-}" == "--clean" ]]; then
	if [[ ! -f "$APP_DST/installed.json" ]]; then
		echo "error: $APP_DST/installed.json not found (open Herdr once first)" >&2
		exit 1
	fi

	python3 - "$APP_SRC" "$APP_DST" <<-'PY'
	import json, os, shutil, sys

	src, dst = sys.argv[1], sys.argv[2]
	installed = json.load(open(os.path.join(dst, "installed.json")))

	shipped_mods = {k for k in installed if not k.startswith("layout:")}
	shipped_layouts = {f"{k.split(':', 1)[1]}.json" for k in installed if k.startswith("layout:")}
	shipped_layouts.update(f"{k.split(':', 1)[1]}.svg" for k in installed if k.startswith("layout:"))

	dots_mods = set(os.listdir(os.path.join(src, "mods"))) if os.path.isdir(os.path.join(src, "mods")) else set()
	dots_layouts = set(os.listdir(os.path.join(src, "layouts"))) if os.path.isdir(os.path.join(src, "layouts")) else set()

	keep_mods = shipped_mods | dots_mods
	keep_layouts = shipped_layouts | dots_layouts | {".state"}

	mods_dir = os.path.join(dst, "mods")
	if os.path.isdir(mods_dir):
	    for m in sorted(os.listdir(mods_dir)):
	        if m not in keep_mods:
	            p = os.path.join(mods_dir, m)
	            print(f"removed foreign mod: {p}")
	            os.unlink(p) if os.path.islink(p) else shutil.rmtree(p)

	layouts_dir = os.path.join(dst, "layouts")
	if os.path.isdir(layouts_dir):
	    for l in sorted(os.listdir(layouts_dir)):
	        if l not in keep_layouts:
	            p = os.path.join(layouts_dir, l)
	            print(f"removed foreign layout: {p}")
	            os.unlink(p) if os.path.islink(p) or os.path.isfile(p) else shutil.rmtree(p)

	for extra in ("lib", "core", "bin", ".shepherdr-backup", ".shepherdr-stage"):
	    p = os.path.join(dst, extra)
	    if os.path.lexists(p):
	        print(f"removed foreign path: {p}")
	        os.unlink(p) if os.path.islink(p) or os.path.isfile(p) else shutil.rmtree(p)
	PY
fi

mkdir -p "$APP_DST/layouts" "$APP_DST/mods" "$APP_DST/themes" "$HERDR_DST"

# 1. Symlink each custom mod folder into ~/.config/herdr-app/mods/<name>
for mod_dir in "$APP_SRC/mods"/*/; do
	[[ -d "$mod_dir" ]] || continue
	mod=${mod_dir%/}
	mod=$(basename "$mod")
	target="$APP_DST/mods/$mod"
	if [[ -d "$target" && ! -L "$target" ]]; then
		[[ -f "$target/runtime.json" && ! -f "$mod_dir/runtime.json" ]] && cp "$target/runtime.json" "$mod_dir/runtime.json"
		rm -rf "$target"
	fi
	ln -sfn "$APP_SRC/mods/$mod" "$target"
	echo "linked mod: $target -> $APP_SRC/mods/$mod"
done

# 2. Symlink custom layouts into ~/.config/herdr-app/layouts/<name>.json
for layout in "$APP_SRC/layouts"/*.json; do
	[[ -f "$layout" ]] || continue
	name=$(basename "$layout")
	ln -sfn "$layout" "$APP_DST/layouts/$name"
	echo "linked layout: $APP_DST/layouts/$name -> $layout"
done

# 3. Symlink custom themes into ~/.config/herdr-app/themes/<name>.json
if [[ -d "$APP_SRC/themes" ]]; then
	for theme in "$APP_SRC/themes"/*.json; do
		[[ -f "$theme" ]] || continue
		name=$(basename "$theme")
		ln -sfn "$theme" "$APP_DST/themes/$name"
		echo "linked theme: $APP_DST/themes/$name -> $theme"
	done
fi

# 4. Symlink keys.json
ln -sfn "$APP_SRC/keys.json" "$APP_DST/keys.json"
echo "linked keys: $APP_DST/keys.json -> $APP_SRC/keys.json"

# 5. Copy settings.json and herdr/config.toml
cp "$APP_SRC/settings.json" "$APP_DST/settings.json"
echo "copied: $APP_DST/settings.json"

if [[ -f "$HERDR_SRC/config.toml" ]]; then
	cp "$HERDR_SRC/config.toml" "$HERDR_DST/config.toml"
	echo "copied: $HERDR_DST/config.toml"
fi

# If --clean was passed and Herdr is running, switch back to iv layout
if [[ "${1:-}" == "--clean" ]] && command -v herdr-app >/dev/null 2>&1; then
	herdr-app do layout.switch '{"name":"iv"}' >/dev/null 2>&1 || true
	echo "switched layout -> iv"
fi
