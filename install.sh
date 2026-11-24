#!/usr/bin/env bash
# Install everything in dots. Each component has its own installer; flags pass through to all
# of them and each one ignores flags it doesn't know.
#
#   ./install.sh                  # herdr + claude
#   ./install.sh --pull           # pull live config back into dots (both)
#   ./install.sh --clean          # herdr: purge third-party mods first
#   ./install.sh --tiny-engineer  # claude: also enable tiny-engineer hooks
#
# Run one component alone: herdr/install.sh [...] or claude/install.sh [...]

set -euo pipefail
DOTS=$(cd -- "$(dirname -- "$(readlink -f -- "$0")")" && pwd)

for component in herdr claude; do
	echo "== $component"
	"$DOTS/$component/install.sh" "$@"
done
