#!/usr/bin/env bash
# Aufruf: run-agent.sh <agent-id> "<prompt>"
# Führt einen Agent headless aus, schreibt PRO LAUF ein eigenes Log + einen Report-
# Datensatz (logs/<agent>.jsonl) und pflegt dashboard/status.json fürs Agent HQ.
set -u
BASE="$(cd "$(dirname "$0")/.." && pwd)"
WEBDIR="$BASE/httpdocs"; [ -d "$WEBDIR" ] || WEBDIR="$BASE/dashboard"
STATUS="$WEBDIR/status.json"
LOGDIR="$BASE/logs"; mkdir -p "$LOGDIR"
AGENT="$1"; PROMPT="$2"
LOG="$LOGDIR/$AGENT.log"                       # aktueller Lauf (live fürs Dashboard-Log)
set -a; [ -f "$BASE/.env" ] && . "$BASE/.env"; set +a

# Kern-Logik läuft über Node (überall vorhanden, wo der Server läuft – auch ohne Python).
# PATH-node zuerst; HQ_NODE (vom Server übergeben) als Fallback, \ -> / für Git-Bash.
NODE="$(command -v node 2>/dev/null)"
[ -n "$NODE" ] || { NODE="${HQ_NODE:-node}"; NODE="${NODE//\\//}"; }
HQ="$BASE/bin/hq.js"
SCHED="$BASE/config/schedule.json"

# Modellwahl = Tokenkosten (schwer-Flag in schedule.json steuert Haiku/Sonnet, Master=Opus).
# Override via AGENT_MODEL. Sicherheitsnetz gegen leeres --model.
MODEL="${AGENT_MODEL:-$("$NODE" "$HQ" model "$SCHED" "$AGENT" 2>/dev/null)}"
[ -n "$MODEL" ] || MODEL=sonnet

LOG_CH="${DISCORD_LOG_CHANNEL:-agent-logs}"
CMD_CH="${DISCORD_COMMAND_CHANNEL:-freigaben}"

# Slash-Kurzname des Agents (für /go-Hinweis; muss zu discord-register.py passen)
case "$AGENT" in
  wochenreport)        ALIAS=report ;;
  belege-buchhaltung)  ALIAS=belege ;;
  content-recherche)   ALIAS=content ;;
  uptime-waechter)     ALIAS=uptime ;;
  seo-audit)           ALIAS=seo ;;
  rechnungssteller)    ALIAS=rechnung ;;
  server-waechter)     ALIAS=server ;;
  mail-assistent)      ALIAS=mail ;;
  video-producent)     ALIAS=video ;;
  ki-influencer)       ALIAS=influencer ;;
  *)                   ALIAS="$AGENT" ;;
esac
dpost() { # dpost <kanal> <text> – nur wenn Bot konfiguriert; Fehler schlucken (Python nur hier nötig)
  [ -n "${DISCORD_BOT_TOKEN:-}" ] || return 0
  python3 "$BASE/bin/discord.py" post "$1" "$2" >/dev/null 2>&1 || true
}

upd() { # upd <status> <phase> <progress> <message> [details_json] [outputs_json]
  "$NODE" "$HQ" status "$STATUS" "$AGENT" "$1" "$2" "$3" "$4" "${5:-}" "${6:-}"
}

errtail() { # Knackige Fehlerursache aus dem Live-Log ziehen (nur der aktuelle Lauf steht in $LOG).
  # Erst Zeilen mit Fehler-Signalwoertern bevorzugen, sonst die letzte nicht-leere Zeile.
  local line
  line="$(grep -viE '^===|^\*\*|^\| ' "$LOG" 2>/dev/null \
        | grep -iE 'error|exception|fehler|not found|permission|denied|refus|time.?out|quota|rate.?limit|unauthor|forbidden|invalid|401|403|429|5[0-9][0-9]|cannot|failed|no such' \
        | tail -n1)"
  [ -n "$line" ] || line="$(grep -vE '^===|^$' "$LOG" 2>/dev/null | tail -n1)"
  printf '%s' "$line" | tr -d '\r' | sed -e 's/^[[:space:]]*//' -e 's/[[:space:]]*$//' | cut -c1-220
}

# quiet-Flag: leise Agents melden Routine-Erfolge nicht (nur Fehler/Waits).
QUIET="$("$NODE" "$HQ" cfg "$SCHED" "$AGENT" quiet 2>/dev/null)"
# Themen-Kanal des Agents (knappe Einzeiler landen dort, nicht im Log-Kanal)
CHAN="$("$NODE" "$HQ" cfg "$SCHED" "$AGENT" channel 2>/dev/null)"; [ -n "$CHAN" ] || CHAN="$LOG_CH"

# ---- Lauf vorbereiten: eigenes Log PRO LAUF, Live-Log leeren (zeigt nur diesen Lauf) ----
RUN_TS="$(date +%Y%m%dT%H%M%S)"
RUNDIR="$LOGDIR/$AGENT"; mkdir -p "$RUNDIR"
RUNLOG="$RUNDIR/$RUN_TS.log"
T0="$(date -Is)"

upd running "Gestartet" 5 "Ich lege los…"
: > "$LOG"
{ echo "=== $T0 START $AGENT (Modell: $MODEL) ==="; } | tee -a "$RUNLOG" >> "$LOG"

cd "$BASE"
claude -p "$PROMPT

ZUSÄTZLICH – DISCORD ist Sebastians Kanal. Poste dein Kernergebnis als EINEN knappen Einzeiler (kein Roman, keine Aufzählung, ~1 Zeile) in den passenden Kanal:
  $BASE/bin/discord.py post <kanal> \"<einzeiler>\"                 # Kanäle: reports, belege, content, ideen, verkauf, kunden-notizen, freigaben, agent-logs
  $BASE/bin/discord.py post <kanal> \"<einzeiler>\" --attach <datei>  # z. B. PDF/HTML-Report anhängen
Dein Themen-Kanal ist #$CHAN. Regel: Posts an EIGENE Kanäle jederzeit ok, aber kurz. NUR Versand nach AUSSEN (Kunden-E-Mail) braucht Sebastians Go – lege dafür einen Entwurf ab und melde dich (Status waiting).

ZUSÄTZLICH (Status fürs Dashboard): Rufe während der Arbeit bei jedem größeren Schritt auf:
  $BASE/bin/status-update.sh $AGENT running \"<Phase>\" <Fortschritt 0-100> \"<kurze Sprechblasen-Nachricht, max 34 Zeichen>\"
und ganz am Ende mit Status ok (oder waiting, falls du auf Sebastians Go wartest) inkl. Details/Outputs:
  $BASE/bin/status-update.sh $AGENT ok \"Fertig\" 100 \"<Kurzfazit>\" '<json-array details>' '<json-array outputs>'" \
  --model "$MODEL" --dangerously-skip-permissions < /dev/null 2>&1 | tee -a "$RUNLOG" >> "$LOG"
RC=${PIPESTATUS[0]}

if [ "$RC" -eq 0 ]; then
  # Falls der Agent selbst keinen Endstatus gesetzt hat: ok setzen
  CUR="$("$NODE" "$HQ" final "$STATUS" "$AGENT" 2>/dev/null)"; CUR="${CUR%%$'\t'*}"
  [ "$CUR" = "running" ] && upd ok "Fertig" 100 "Lauf abgeschlossen ✓"
else
  CAUSE="$(errtail)"; [ -n "$CAUSE" ] || CAUSE="Fehler – Log prüfen (Exit $RC)"
  upd error "Abgebrochen (Exit $RC)" 0 "$CAUSE"
fi

T1="$(date -Is)"
{ echo "=== $T1 ENDE rc=$RC ==="; } | tee -a "$RUNLOG" >> "$LOG"

# ---- Report-Datensatz: EIN JSONL-Eintrag pro Lauf (fürs Dashboard-Verlauf) ----
"$NODE" "$HQ" record "$STATUS" "$LOGDIR/$AGENT.jsonl" "$AGENT" "$T0" "$T1" "$RC" "$MODEL" "$RUN_TS" 2>/dev/null || true

# Endstatus nach Discord melden (waiting -> Kommando-Kanal fürs Go, sonst Log-/Themen-Kanal)
FINAL="$("$NODE" "$HQ" final "$STATUS" "$AGENT" 2>/dev/null)"
FSTATUS="${FINAL%%$'\t'*}"; FMSG="${FINAL#*$'\t'}"

# ---- Alarm-Throttle: denselben Fehler nicht bei jedem Lauf posten ----------
# State-Zeile: sig \t count \t first_hhmm \t last_post_epoch. Signatur = normalisierte
# Ursache (Ziffern/Satzzeichen raus), damit "gleicher Fehler" wiedererkannt wird.
ALARM_STATE="$LOGDIR/$AGENT.alarm"
REALERT_H="${HQ_REALERT_HOURS:-6}"                 # denselben Fehler erst nach so vielen Std. erneut melden
sig_of() { printf '%s' "$1" | tr 'A-Z' 'a-z' | tr -cd 'a-z ' | tr -s ' ' | cut -c1-80; }
prev_alarm() { [ -f "$ALARM_STATE" ] && cat "$ALARM_STATE" || printf '\t0\t\t0'; }

case "$FSTATUS" in
  waiting)
    dpost "$CMD_CH" "⏳ **$AGENT** wartet auf Go — \`/go $ALIAS\`. ${FMSG}"
    ;;
  error)
    CAUSE="${FMSG:-Fehler, Log prüfen}"
    NEWSIG="$(sig_of "$CAUSE")"
    IFS=$'\t' read -r OLDSIG OLDCNT OLDFIRST OLDPOST <<EOF
$(prev_alarm)
EOF
    NOW="$(date +%s)"
    if [ "$NEWSIG" = "$OLDSIG" ] && [ "$OLDCNT" -gt 0 ]; then
      CNT=$((OLDCNT + 1)); FIRST="${OLDFIRST:-$(date +%H:%M)}"
      if [ $((NOW - ${OLDPOST:-0})) -ge $((REALERT_H * 3600)) ]; then
        dpost "$CHAN" "❌ **$AGENT** weiter defekt (${CNT}× seit ${FIRST}): ${CAUSE}"; POST="$NOW"
      else
        POST="${OLDPOST:-0}"                        # gleicher Fehler, noch im Ruhefenster -> still
      fi
    else
      CNT=1; FIRST="$(date +%H:%M)"
      dpost "$CHAN" "❌ **$AGENT**: ${CAUSE}"; POST="$NOW"
    fi
    printf '%s\t%s\t%s\t%s\n' "$NEWSIG" "$CNT" "$FIRST" "$POST" > "$ALARM_STATE"
    ;;
  *)
    if [ -s "$ALARM_STATE" ]; then                  # war ein Fehler offen? -> genau eine Entwarnung
      IFS=$'\t' read -r _ RCNT _ _ <<EOF
$(prev_alarm)
EOF
      dpost "$CHAN" "✅ **$AGENT** wieder OK${RCNT:+ (nach ${RCNT} Fehlversuchen)}."
      rm -f "$ALARM_STATE"
    elif [ "$RC" -eq 0 ]; then
      [ -n "$QUIET" ] || dpost "$CHAN" "✅ **$AGENT**: ${FMSG:-fertig}"
    else
      dpost "$CHAN" "❌ **$AGENT** abgebrochen (Exit $RC)"
    fi
    ;;
esac

# Dashboard-Datenfiles ins statische Docroot spiegeln (index.html liest sie ohne server.js)
[ -f "$BASE/uptime/uptime.json" ] && cp -f "$BASE/uptime/uptime.json" "$WEBDIR/uptime.json" 2>/dev/null
[ -f "$BASE/server/server-status.json" ] && cp -f "$BASE/server/server-status.json" "$WEBDIR/server.json" 2>/dev/null
exit "$RC"
