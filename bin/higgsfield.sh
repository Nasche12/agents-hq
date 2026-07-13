#!/usr/bin/env bash
# Higgsfield-Video HEADLESS ueber die REST-API (fuer Cron-Laeufe ohne MCP).
# Aufruf:  higgsfield.sh video "<prompt>" [start_image_url] [aspect_ratio]
#          higgsfield.sh image "<prompt>" [aspect_ratio]
# Gibt bei Erfolg die Ergebnis-URL auf stdout aus; sonst Exit != 0 mit Fehlertext auf stderr.
#
# ACHTUNG – SCAFFOLD: Auth-Schema (Bearer) und der Ablauf (POST /v1/generations -> Status pollen)
# stammen aus der oeffentlichen Doku. Die genauen Pfade/Feldnamen bitte gegen die offizielle
# Higgsfield-Doku bestaetigen, sobald du den Key hast; hier zentral anpassbar (GEN_PATH, STATUS_PATH).
set -u
BASE="$(cd "$(dirname "$0")/.." && pwd)"
set -a; [ -f "$BASE/.env" ] && . "$BASE/.env"; set +a

API="${HIGGSFIELD_API_BASE:-https://platform.higgsfield.ai}"
KEY="${HIGGSFIELD_API_KEY:-}"
GEN_PATH="/v1/generations"        # <- ggf. an offizielle Doku anpassen
STATUS_PATH="/v1/generations"     # GET $STATUS_PATH/<id>  <- ggf. anpassen
[ -n "$KEY" ] || { echo "higgsfield: HIGGSFIELD_API_KEY fehlt (.env)" >&2; exit 2; }
command -v curl >/dev/null || { echo "higgsfield: curl fehlt" >&2; exit 2; }

MODE="${1:?mode fehlt: video|image}"; PROMPT="${2:?prompt fehlt}"

# Prompt EINMAL sicher als JSON-String kodieren (jq bevorzugt, sonst simpler Fallback).
if command -v jq >/dev/null; then
  PJ="$(jq -Rn --arg p "$PROMPT" '$p')"
else
  esc="${PROMPT//\\/\\\\}"; esc="${esc//\"/\\\"}"; esc="${esc//$'\n'/\\n}"; PJ="\"$esc\""
fi

case "$MODE" in
  video) IMG="${3:-}"; AR="${4:-9:16}"
    if [ -n "$IMG" ]; then
      BODY="{\"model\":\"higgsfield-dop\",\"task\":\"image-to-video\",\"prompt\":$PJ,\"image_url\":\"$IMG\",\"aspect_ratio\":\"$AR\"}"
    else
      BODY="{\"model\":\"higgsfield-dop\",\"task\":\"text-to-video\",\"prompt\":$PJ,\"aspect_ratio\":\"$AR\"}"
    fi ;;
  image) AR="${3:-9:16}"
    BODY="{\"model\":\"soul\",\"task\":\"text-to-image\",\"prompt\":$PJ,\"aspect_ratio\":\"$AR\"}" ;;
  *) echo "higgsfield: mode muss video|image sein" >&2; exit 2 ;;
esac

RESP="$(curl -sS -X POST "$API$GEN_PATH" \
  -H "Authorization: Bearer $KEY" -H "Content-Type: application/json" \
  --max-time 60 -d "$BODY")" || { echo "higgsfield: Request fehlgeschlagen" >&2; exit 1; }

ID="$(printf '%s' "$RESP" | grep -oE '"(id|request_id|generation_id)"\s*:\s*"[^"]+"' | head -1 | grep -oE '[^"]+"$' | tr -d '"')"
[ -n "$ID" ] || { echo "higgsfield: keine Job-ID in Antwort: $RESP" >&2; exit 1; }

# Status pollen bis fertig (max ~5 Min)
for i in $(seq 1 60); do
  sleep 5
  ST="$(curl -sS "$API$STATUS_PATH/$ID" -H "Authorization: Bearer $KEY" --max-time 30)" || continue
  STATE="$(printf '%s' "$ST" | grep -oE '"(status|state)"\s*:\s*"[^"]+"' | head -1 | grep -oE '[^"]+"$' | tr -d '"')"
  case "$STATE" in
    completed|succeeded|done|success)
      printf '%s' "$ST" | grep -oE 'https?://[^"[:space:]]+\.(mp4|webm|png|jpg|jpeg|webp)' | head -1; exit 0 ;;
    failed|error|canceled)
      echo "higgsfield: Job $STATE: $ST" >&2; exit 1 ;;
  esac
done
echo "higgsfield: Timeout beim Warten auf Job $ID" >&2; exit 1
