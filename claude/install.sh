#!/usr/bin/env bash
# Sync Claude Code config between ~/git/dots/claude and ~/.claude
#
# Usage:
#   claude/install.sh                  # install: copy settings.json, link hooks + skills
#   claude/install.sh --tiny-engineer  # same, plus merge the tiny-engineer hooks into settings.json
#   claude/install.sh --pull           # copy ~/.claude/settings.json back into dots
#                                        # (tiny-engineer hooks split out, /home paths -> $HOME)
#
# Not synced on purpose: .credentials.json (log in again), settings.local.json (per-machine
# permissions), history, projects/ (memory), sessions, plugins/ (installed from settings.json).

set -euo pipefail

SRC=$(cd -- "$(dirname -- "$(readlink -f -- "$0")")" && pwd)
DST="$HOME/.claude"

if [[ "${1:-}" == "--pull" ]]; then
	python3 - "$DST/settings.json" "$SRC" "$HOME" <<-'PY'
	import json, sys
	live, src, home = sys.argv[1], sys.argv[2], sys.argv[3]
	d = json.load(open(live))
	te, keep = {}, {}
	for ev, arr in d.get("hooks", {}).items():
	    for m in arr:
	        tgt = te if any("tiny-engineer" in h.get("command", "") for h in m["hooks"]) else keep
	        tgt.setdefault(ev, []).append(m)
	d["hooks"] = keep
	s = json.dumps(d, indent=2, ensure_ascii=False)
	s = s.replace(f"'{home}/", '\\"$HOME/').replace(".sh'", '.sh\\"').replace(f"{home}/", "$HOME/")
	open(f"{src}/settings.json", "w").write(s + "\n")
	if te:
	    open(f"{src}/hooks.tiny-engineer.json", "w").write(json.dumps(te, indent=2).replace(f"{home}/", "$HOME/") + "\n")
	print("pulled settings.json" + (" (+ tiny-engineer hooks)" if te else ""))
	PY
	exit 0
fi

mkdir -p "$DST/hooks" "$DST/skills" "$HOME/.agents"

# settings.json: copied (Claude Code rewrites it in place), back up whatever is there
if [[ -f "$DST/settings.json" && ! -L "$DST/settings.json" ]]; then
	cp "$DST/settings.json" "$DST/settings.json.pre-dots.$(date +%s)"
fi
if [[ "${1:-}" == "--tiny-engineer" ]]; then
	python3 - "$SRC/settings.json" "$SRC/hooks.tiny-engineer.json" "$DST/settings.json" <<-'PY'
	import json, sys
	base, te, out = (json.load(open(sys.argv[1])), json.load(open(sys.argv[2])), sys.argv[3])
	for ev, arr in te.items():
	    base.setdefault("hooks", {}).setdefault(ev, []).extend(arr)
	open(out, "w").write(json.dumps(base, indent=2, ensure_ascii=False) + "\n")
	PY
	echo "settings.json installed with tiny-engineer hooks"
	command -v tiny-engineer >/dev/null || [[ -x "$HOME/.local/bin/tiny-engineer" ]] || echo "warning: tiny-engineer not installed; its hooks will fail" >&2
else
	cp "$SRC/settings.json" "$DST/settings.json"
	echo "settings.json installed (tiny-engineer hooks off)"
fi

# hooks: symlink each script
for f in "$SRC"/hooks/*; do
	ln -sfn "$f" "$DST/hooks/$(basename "$f")"
done

# skills: ~/.agents/skills -> dots, ~/.claude/skills/<name> -> ../../.agents/skills/<name>
if [[ -d "$HOME/.agents/skills" && ! -L "$HOME/.agents/skills" ]]; then
	mv "$HOME/.agents/skills" "$HOME/.agents/skills.pre-dots.$(date +%s)"
fi
ln -sfn "$SRC/skills" "$HOME/.agents/skills"
for s in "$SRC"/skills/*/; do
	n=$(basename "$s")
	ln -sfn "../../.agents/skills/$n" "$DST/skills/$n"
done
# prune skill links whose target no longer exists (skill removed from dots)
for l in "$DST"/skills/*; do
	[[ -L "$l" && ! -e "$l" ]] && rm -v "$l"
done

[[ -x "$HOME/.config/herdr-app/mods/chat/ask-hook.sh" || -f "$HOME/.config/herdr-app/mods/chat/ask-hook.sh" ]] \
	|| echo "note: two hooks use the herdr chat mod, which the Herdr app installs: open Herdr once" >&2
echo "done. Run 'claude' and log in; it offers to install the plugins listed in settings.json."
