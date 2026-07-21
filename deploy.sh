#!/usr/bin/env bash
# Einmaliges Setup im Projektordner ausführen:
#   /var/www/vhosts/naschberger.info/agents.naschberger.info
# Aufruf:  bash deploy.sh
set -e
BASE="$(cd "$(dirname "$0")" && pwd)"
cd "$BASE"
echo "== Agent HQ Setup in: $BASE"

# 1) Ordner (inkl. Output-Ordner der neuen Agents)
mkdir -p logs belege/inbox belege/archiv belege/pakete reports content \
         uptime/alerts seo rechnungen master httpdocs

# 2) Dashboard in den Web-Docroot (httpdocs) legen – NUR diese Dateien sind öffentlich.
#    Zentral über bin/publish.sh (index.html + styles.css + app.js + assets/).
bash bin/publish.sh

# 3) Rechte
chmod +x bin/run-agent.sh bin/status-update.sh bin/publish.sh bin/backup.sh
[ -f .env ] && chmod 600 .env || echo "!! .env fehlt noch – aus .env.example erstellen: cp .env.example .env && nano .env"

# 4) Sicherheitsnetz: nichts außer httpdocs darf je im Docroot landen
cat > httpdocs/.htaccess << 'HT'
Options -Indexes
HT

# 5) Checks
echo "-- Node: $(command -v node >/dev/null && node -v || echo 'FEHLT – in Plesk Node.js aktivieren oder nvm installieren')"
echo "-- Claude Code: $(command -v claude >/dev/null && claude --version || echo 'FEHLT – npm install -g @anthropic-ai/claude-code')"
echo "-- Python3: $(command -v python3 >/dev/null && python3 -V || echo 'FEHLT')"

# 6) Status-Pipeline testen
bin/status-update.sh wochenreport idle "Bereit" 0 "Warte auf Freitag 08:00…" '[]' '[]'
python3 -c "import json;json.load(open('httpdocs/status.json'));print('-- status.json OK')"

# 7) Trading-Bot (Python) – venv, Abhaengigkeiten, systemd-Service. Fehler hier duerfen
#    das HQ-Setup NICHT abbrechen, darum in ( … ) mit eigenem Fehlerfang.
echo "== Trading-Bot Setup"
(
  set +e
  cd "$BASE/trading-bot" || { echo "!! trading-bot/ fehlt"; exit 0; }
  PYBIN="$(command -v python3.12 || command -v python3.11 || command -v python3)"
  PYVER="$("$PYBIN" -c 'import sys;print("%d.%d"%sys.version_info[:2])' 2>/dev/null)"
  echo "-- Python: $PYBIN ($PYVER)"
  case "$PYVER" in 3.1[0-9]|3.[2-9]*) : ;; *) echo "!! Python >=3.10 noetig (numpy/hmmlearn). Ueberspringe Bot."; exit 0;; esac

  [ -d .venv ] || "$PYBIN" -m venv .venv
  ./.venv/bin/python -m pip install -q --upgrade pip
  ./.venv/bin/pip install -q -r requirements.txt || { echo "!! pip install fehlgeschlagen"; exit 0; }
  mkdir -p logs state

  # Alpaca-Keys? Der Bot liest trading-bot/.env, sonst die Repo-Root .env (Fallback).
  if ./.venv/bin/python -c "import settings,sys; sys.exit(0 if (settings.env('ALPACA_API_KEY') and settings.env('ALPACA_SECRET_KEY')) else 1)"; then
    echo "-- Alpaca-Keys gefunden -> Bot handelt (paper)."
    ./.venv/bin/python main.py --once >/dev/null 2>&1 && echo "-- erster Cycle ok (httpdocs/trading.json geschrieben)"
  else
    echo "!! KEINE Alpaca-Keys in .env -> Bot laeuft im Beobachtungsmodus (keine Orders)."
    echo "   Keys eintragen: nano $BASE/.env  (ALPACA_API_KEY, ALPACA_SECRET_KEY, ALPACA_PAPER=true)"
    ./.venv/bin/python dashboard_export.py >/dev/null 2>&1
  fi

  # systemd-Service (autostart + restart). Braucht sudo; sonst Befehle ausgeben.
  SVC=/etc/systemd/system/regime-trader.service
  RUNUSER="$(whoami)"
  if command -v systemctl >/dev/null 2>&1 && command -v sudo >/dev/null 2>&1; then
    sudo tee "$SVC" >/dev/null <<UNIT
[Unit]
Description=Regime Trading Bot (Paper) - agents-hq
After=network-online.target
Wants=network-online.target

[Service]
Type=simple
User=$RUNUSER
WorkingDirectory=$BASE/trading-bot
ExecStart=$BASE/trading-bot/.venv/bin/python main.py
Restart=always
RestartSec=15
StandardOutput=append:$BASE/trading-bot/logs/bot.log
StandardError=append:$BASE/trading-bot/logs/bot.err.log

[Install]
WantedBy=multi-user.target
UNIT
    sudo systemctl daemon-reload
    sudo systemctl enable --now regime-trader && echo "-- Service regime-trader aktiv"
    sudo systemctl --no-pager --lines=3 status regime-trader || true
  else
    echo "!! systemctl/sudo fehlt -> Service manuell installieren:"
    echo "   sudo cp trading-bot/deploy/regime-trader.service $SVC"
    echo "   sudo sed -i \"s#/CHANGE_ME/agents-hq#$BASE#g; s#User=CHANGE_ME#User=$RUNUSER#\" $SVC"
    echo "   sudo systemctl daemon-reload && sudo systemctl enable --now regime-trader"
  fi
)

echo
echo "== Fertig. Nächste Schritte (mach ich mit dir Schritt für Schritt):"
echo "   1. Plesk: Subdomain agents.naschberger.info -> Docroot auf $BASE/httpdocs"
echo "   2. Plesk: SSL (Let's Encrypt) + Passwortschutz auf /"
echo "   3. .env befuellen, dann Cronjobs eintragen (docs/DASHBOARD-DEPLOY.md, Schritt 3)"
echo "   4. Trading-Tab: laeuft ueber httpdocs/trading.json (Bot-Service schreibt es);"
echo "      nginx-Block aus deploy/nginx-proxy.conf enthaelt jetzt 'location = /trading'."
