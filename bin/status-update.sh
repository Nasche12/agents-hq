#!/usr/bin/env bash
# Aufruf: status-update.sh <agent-id> <status> <phase> <progress> <message> [details_json] [outputs_json]
# Schreibt den Agent-Status ins Dashboard (status.json). Läuft über Node – überall vorhanden.
BASE="$(cd "$(dirname "$0")/.." && pwd)"
WEBDIR="$BASE/httpdocs"; [ -d "$WEBDIR" ] || WEBDIR="$BASE/dashboard"
NODE="$(command -v node 2>/dev/null)"
[ -n "$NODE" ] || { NODE="${HQ_NODE:-node}"; NODE="${NODE//\\//}"; }
"$NODE" "$BASE/bin/hq.js" status "$WEBDIR/status.json" "$@"
