#!/usr/bin/env bash
# Sichert die geschäftskritischen HQ-Daten in ein tar.gz und kappt alte Stände.
# Läuft via server.js-Scheduler (HQ_BACKUP_DAILY=HH:MM) oder manuell / per Cron.
# Ziel: BACKUP_DIR (Default: <repo>/../agents-hq-backups). Für echten Schutz
# BACKUP_DIR auf ein ANDERES Volume oder einen Remote-Mount legen – ein Backup
# auf derselben Platte hilft bei Plattenverlust nicht.
set -u
BASE="$(cd "$(dirname "$0")/.." && pwd)"
set -a; [ -f "$BASE/.env" ] && . "$BASE/.env"; set +a

DEST="${BACKUP_DIR:-$BASE/../agents-hq-backups}"
KEEP="${BACKUP_KEEP:-14}"
mkdir -p "$DEST" 2>/dev/null || { echo "backup: Zielordner $DEST nicht anlegbar" >&2; exit 1; }
chmod 700 "$DEST" 2>/dev/null || true            # enthält .env-Secrets

TS="$(date +%Y%m%dT%H%M%S)"
OUT="$DEST/agents-hq_$TS.tar.gz"

# Nur vorhandene Pfade sichern (fehlende überspringen).
ITEMS=()
for p in belege rechnungen reports content seo uptime server mail master config .env; do
  [ -e "$BASE/$p" ] && ITEMS+=("$p")
done
# Aus logs/ nur die JSONL-Verläufe (Token/Kosten/Report) + Alarm-State – nicht die GB an Roh-Logs.
for jl in "$BASE"/logs/*.jsonl "$BASE"/logs/*.alarm "$BASE"/server/server-history.jsonl; do
  [ -e "$jl" ] && ITEMS+=("${jl#$BASE/}")
done

[ ${#ITEMS[@]} -gt 0 ] || { echo "backup: nichts zu sichern gefunden" >&2; exit 1; }

if tar -czf "$OUT" -C "$BASE" "${ITEMS[@]}" 2>/dev/null; then
  chmod 600 "$OUT" 2>/dev/null || true           # Archiv enthält Secrets
else
  echo "backup: tar fehlgeschlagen" >&2; rm -f "$OUT" 2>/dev/null; exit 1
fi

# Alte Backups kappen (die neuesten KEEP behalten).
ls -1t "$DEST"/agents-hq_*.tar.gz 2>/dev/null | tail -n +$((KEEP + 1)) | while IFS= read -r old; do rm -f "$old"; done

SIZE="$(du -h "$OUT" 2>/dev/null | cut -f1)"
N="$(ls -1 "$DEST"/agents-hq_*.tar.gz 2>/dev/null | wc -l | tr -d ' ')"
echo "backup: $OUT ($SIZE) – $N Stände in $DEST"
