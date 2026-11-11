#!/bin/bash
# owl-hc.service ExecStartPost: start owl's serving pi as terminal "librarian" in owl's hc core.
# Runs at every core start; a librarian restored from state is only a shell, so it is replaced.
set -euo pipefail
log() { echo "start-owl-hc: $*" >&2; }
SOCK=/run/owl-hc/herdr-core/default.sock
VAULT=/home/owl/obsidian
PI=(/home/owl/.pi/agent/bin/pi --offline -ne -nc -ns -np -na --no-themes --no-mcp --continue
	--thinking medium -e /home/owl/.pi/agent/extensions/owl/index.ts
	--tools read,grep,find,ls,owl_reply,owl_complain,owl_message)

# wait for the socket; never call hc before it exists (hc would start a second core)
for _ in $(seq 1 30); do [ -S "$SOCK" ] && break; sleep 1; done
[ -S "$SOCK" ] || { log "core socket not up after 30 s"; exit 1; }

mountpoint -q "$VAULT" || { log "$VAULT is not mounted"; exit 1; }
for p in "$VAULT/.pi" "$VAULT/sb/.pi" "$VAULT/Second Brain/.pi"; do
	[ -e "$p" ] && { log "refusing: $p exists"; exit 1; }
done

# keep the old librarian's tab (and its name) for the new one
old=$(hc get --json librarian 2>/dev/null | python3 -I -c 'import json,sys; d=json.load(sys.stdin); print(d.get("address",""), d.get("labels",{}).get("herdr.tab",""))' 2>/dev/null || true)
old_addr=${old%% *}; old_tab=${old#* }
[ -n "$old_addr" ] && { hc kill "$old_addr" >/dev/null 2>&1 || true; sleep 1; }

label=()
if [ -s /etc/owl-hc.space ]; then
	label=(--label "herdr.space=$(tr -d '[:space:]' </etc/owl-hc.space)")
	[ -n "$old_tab" ] && label+=(--label "herdr.tab=$old_tab")
fi
log "starting librarian${old_tab:+ in tab $old_tab}"
hc run --bg --no-parent --name librarian --cwd "$VAULT" "${label[@]}" -- "${PI[@]}" >/dev/null
[ -n "$old_addr" ] && { sleep 1; hc rm "$old_addr" >/dev/null 2>&1 || true; }
exit 0
