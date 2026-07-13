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
chmod +x bin/run-agent.sh bin/status-update.sh bin/publish.sh
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

echo
echo "== Fertig. Nächste Schritte (mach ich mit dir Schritt für Schritt):"
echo "   1. Plesk: Subdomain agents.naschberger.info -> Docroot auf $BASE/httpdocs"
echo "   2. Plesk: SSL (Let's Encrypt) + Passwortschutz auf /"
echo "   3. .env befuellen, dann Cronjobs eintragen (docs/DASHBOARD-DEPLOY.md, Schritt 3)"
