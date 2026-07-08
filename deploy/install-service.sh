#!/usr/bin/env bash
# Installiert Agent HQ (dashboard/server.js) als systemd-Service.
# ALS ROOT ausführen:  bash deploy/install-service.sh
# Danach in Plesk /api/ an den Node-Server proxien (siehe deploy/nginx-proxy.conf).
set -e
BASE="$(cd "$(dirname "$0")/.." && pwd)"
PORT="${PORT:-8788}"

USER_="$(stat -c '%U' "$BASE")"
GRP="$(id -gn "$USER_" 2>/dev/null || echo psacln)"
NODE="$(command -v node || true)"
[ -n "$NODE" ] || { echo "!! node nicht im PATH gefunden – Node.js installieren/aktivieren"; exit 1; }

# PATH für die Agent-Läufe: claude + node müssen darin liegen
BIN="$(dirname "$NODE")"
CLAUDE="$(command -v claude || true)"
[ -n "$CLAUDE" ] && BIN="$(dirname "$CLAUDE"):$BIN"

SVC=/etc/systemd/system/agents-hq.service
cat > "$SVC" <<UNIT
[Unit]
Description=Agent HQ Dashboard + API (naschberger.info)
After=network.target

[Service]
Type=simple
User=$USER_
Group=$GRP
WorkingDirectory=$BASE
Environment=PORT=$PORT
Environment=HOST=127.0.0.1
Environment=PATH=$BIN:/usr/local/bin:/usr/bin:/bin
ExecStart=$NODE dashboard/server.js
Restart=always
RestartSec=3
NoNewPrivileges=true

[Install]
WantedBy=multi-user.target
UNIT

echo "== Service geschrieben: $SVC"
echo "   User=$USER_  Gruppe=$GRP  Node=$NODE  Port=$PORT"
echo "   PATH=$BIN:/usr/local/bin:/usr/bin:/bin"

systemctl daemon-reload
systemctl enable --now agents-hq
sleep 1
systemctl --no-pager --lines=10 status agents-hq || true

echo
echo "== Selbsttest =="
curl -s "http://127.0.0.1:$PORT/api/ping" && echo " <- API antwortet" || echo "!! API antwortet nicht – 'journalctl -u agents-hq -e' prüfen"

echo
echo "== NÄCHSTER SCHRITT (Plesk) =="
echo "Domain agents.naschberger.info -> Apache & nginx Settings ->"
echo "'Zusätzliche nginx-Direktiven' -> Inhalt von deploy/nginx-proxy.conf einfügen"
echo "(Port dort auf $PORT setzen, falls abweichend). Dann Passwortschutz der Domain prüfen."
echo
echo "Logs des Service:  journalctl -u agents-hq -f"
echo "Neustart:          systemctl restart agents-hq"
