#!/usr/bin/env bash
# Veröffentlicht das statische Dashboard in den Plesk-Docroot (httpdocs/).
# Hintergrund: Plesk liefert httpdocs/ DIREKT aus; nur /api/ und /discord/interactions
# gehen an den Node-Service (siehe deploy/nginx-proxy.conf). Das Redesign in dashboard/
# ist daher nur die QUELLE – öffentlich wird ausschließlich, was hier kopiert wird.
# Nach jedem Dashboard-Umbau ausführen:  bash bin/publish.sh
set -e
BASE="$(cd "$(dirname "$0")/.." && pwd)"
cd "$BASE"
mkdir -p httpdocs

# Statische Frontend-Dateien (alles, was der Browser direkt lädt)
for f in index.html styles.css app.js; do
  [ -f "dashboard/$f" ] && cp -f "dashboard/$f" "httpdocs/$f"
done

# Bild-/Icon-Assets (ohne _alt-Backup-Ordner)
if [ -d dashboard/assets ]; then
  mkdir -p httpdocs/assets
  find dashboard/assets -maxdepth 1 -type f -exec cp -f {} httpdocs/assets/ \;
fi

# Runtime-JSON NICHT überschreiben – die Agents schreiben httpdocs/status.json &
# httpdocs/uptime.json selbst. Nur anlegen, falls noch nichts da ist.
[ -f httpdocs/status.json ] || cp -f dashboard/status.json httpdocs/status.json 2>/dev/null || true

# Sicherheitsnetz: kein Verzeichnis-Listing im Docroot
printf 'Options -Indexes\n' > httpdocs/.htaccess

echo "-- Dashboard veröffentlicht nach httpdocs/: $(ls -1 httpdocs | tr '\n' ' ')"
