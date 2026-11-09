#!/bin/bash
# owl.service ExecStartPost: start owl's pi inside owl's herdr. Idempotent. Logs to stderr (journald).
set -euo pipefail
log() { echo "start-owl: $*" >&2; }

PI='/home/owl/.pi/agent/bin/pi --offline -ne -nc -ns -np -na --no-themes --no-mcp --continue -e /home/owl/.pi/agent/extensions/owl/index.ts --tools read,grep,find,ls,owl_reply,owl_complain'
VAULT=/home/owl/obsidian

up=0
for _ in $(seq 1 30); do
	if herdr status server >/dev/null 2>&1; then up=1; break; fi
	sleep 1
done
[ "$up" = 1 ] || { log "herdr server not up after 30 s"; exit 1; }

mountpoint -q "$VAULT" || { log "$VAULT is not mounted"; exit 1; }
for p in "$VAULT/.pi" "$VAULT/sb/.pi" "$VAULT/Second Brain/.pi"; do
	[ -e "$p" ] && { log "refusing: $p exists"; exit 1; }
done

json() { python3 -I -c "import json,sys; d=json.load(sys.stdin); $1" "${@:2}"; }

ws=$(herdr workspace list | json 'print(next((w["workspace_id"] for w in d["result"]["workspaces"] if w.get("label") == "owl"), ""))')
if [ -n "$ws" ]; then
	has=$(herdr agent list | json 'print(any(a.get("workspace_id") == sys.argv[1] and a.get("agent") == "pi" for a in d["result"]["agents"]))' "$ws")
	if [ "$has" = True ]; then
		log "workspace $ws already runs pi"
		exit 0
	fi
else
	herdr workspace create --cwd "$VAULT" --label owl --no-focus >/dev/null
	ws=$(herdr workspace list | json 'print(next((w["workspace_id"] for w in d["result"]["workspaces"] if w.get("label") == "owl"), ""))')
	[ -n "$ws" ] || { log "could not create the owl workspace"; exit 1; }
fi
pane=$(herdr pane list --workspace "$ws" | json 'r=d["result"]; ps=r.get("panes", r) if isinstance(r, dict) else r; print(ps[0]["pane_id"])')
log "starting pi in $ws pane $pane"
herdr pane run "$pane" "cd $VAULT && $PI"
