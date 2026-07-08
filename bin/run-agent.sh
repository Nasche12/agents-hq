#!/usr/bin/env bash
# Aufruf: run-agent.sh <agent-id> "<prompt>"
# Führt einen Agent headless aus und pflegt dashboard/status.json fürs Agent HQ.
set -u
BASE="$(cd "$(dirname "$0")/.." && pwd)"
WEBDIR="$BASE/httpdocs"; [ -d "$WEBDIR" ] || WEBDIR="$BASE/dashboard"
STATUS="$WEBDIR/status.json"
LOGDIR="$BASE/logs"; mkdir -p "$LOGDIR"
AGENT="$1"; PROMPT="$2"
LOG="$LOGDIR/$AGENT.log"
set -a; [ -f "$BASE/.env" ] && . "$BASE/.env"; set +a

# Modellwahl = Tokenkosten. Leichte Agents laufen auf Haiku (5x billiger als Opus),
# schwere auf Sonnet (3x billiger), der Kommandant/Master auf Opus.
# Steuersignal ist das "schwer"-Flag in config/schedule.json; überschreibbar via AGENT_MODEL.
# ponytail: schwer-Flag als Proxy, per-Agent-Override in schedule.json wenn's mal feiner sein muss.
MODEL="${AGENT_MODEL:-$(python3 - "$BASE/config/schedule.json" "$AGENT" << 'PY'
import json,sys
f,agent=sys.argv[1:3]
if agent in ("master","kommandant"): print("opus"); sys.exit()
try: a=json.load(open(f))["agents"].get(agent,{})
except Exception: a={}
print("sonnet" if a.get("schwer") else "haiku")
PY
)}"

LOG_CH="${DISCORD_LOG_CHANNEL:-agent-logs}"
CMD_CH="${DISCORD_COMMAND_CHANNEL:-freigaben}"
dpost() { # dpost <kanal> <text> – nur wenn Bot konfiguriert; Fehler schlucken
  [ -n "${DISCORD_BOT_TOKEN:-}" ] || return 0
  python3 "$BASE/bin/discord.py" post "$1" "$2" >/dev/null 2>&1 || true
}

upd() { # upd <status> <phase> <progress> <message> [details_json] [outputs_json]
python3 - "$STATUS" "$AGENT" "$1" "$2" "$3" "$4" "${5:-}" "${6:-}" << 'PY'
import json,sys,datetime,os
f,agent,st,phase,prog,msg,det,out=sys.argv[1:9]
d=json.load(open(f)) if os.path.exists(f) else {"agents":{}}
a=d.setdefault("agents",{}).setdefault(agent,{"name":agent})
a.update(status=st,phase=phase,progress=int(prog),message=msg)
now=datetime.datetime.now().astimezone().isoformat(timespec="seconds")
if st=="running": a["last_run"]=now
if det: a["details"]=json.loads(det)
if out: a["outputs"]=json.loads(out)
logf=os.path.join(os.path.dirname(f),"..","logs",agent+".log")
try: a["log_tail"]=open(logf,errors="replace").read()[-1500:]
except OSError: pass
d["updated"]=now
tmp=f+".tmp"; json.dump(d,open(tmp,"w"),ensure_ascii=False,indent=1); os.replace(tmp,f)
PY
}

upd running "Gestartet" 5 "Ich lege los…"
dpost "$LOG_CH" "▶️ $AGENT gestartet"
echo "=== $(date -Is) START $AGENT (Modell: $MODEL) ===" >> "$LOG"

cd "$BASE"
claude -p "$PROMPT

ZUSÄTZLICH – DISCORD ist Sebastians Kommunikationskanal. Poste deine Kernergebnisse selbst in den passenden Kanal (interne Kommunikation ist erwünscht):
  $BASE/bin/discord.py post <kanal> \"<text>\"                 # Kanäle: reports, belege, content, ideen, verkauf, kunden-notizen, freigaben, agent-logs
  $BASE/bin/discord.py post <kanal> \"<text>\" --attach <datei>  # z. B. PDF/HTML-Report anhängen
Regel: Discord-Posts an EIGENE Kanäle jederzeit ok. NUR Versand nach AUSSEN (Kunden-E-Mail) braucht weiterhin Sebastians Go – lege dafür einen Entwurf ab und melde dich (Status waiting) in #freigaben.

ZUSÄTZLICH (Status fürs Dashboard): Rufe während der Arbeit bei jedem größeren Schritt auf:
  $BASE/bin/status-update.sh $AGENT running \"<Phase>\" <Fortschritt 0-100> \"<kurze Sprechblasen-Nachricht, max 34 Zeichen>\"
und ganz am Ende mit Status ok (oder waiting, falls du auf Sebastians Go wartest) inkl. Details/Outputs:
  $BASE/bin/status-update.sh $AGENT ok \"Fertig\" 100 \"<Kurzfazit>\" '<json-array details>' '<json-array outputs>'" \
  --model "$MODEL" --dangerously-skip-permissions < /dev/null >> "$LOG" 2>&1
RC=$?

if [ $RC -eq 0 ]; then
  # Falls der Agent selbst keinen Endstatus gesetzt hat: ok setzen
  python3 -c "
import json;d=json.load(open('$STATUS'))
a=d['agents'].get('$AGENT',{})
print('running' if a.get('status')=='running' else 'done')" | grep -q running && \
    upd ok "Fertig" 100 "Lauf abgeschlossen ✓"
else
  upd error "Abgebrochen (Exit $RC)" 0 "Fehler – Log prüfen!"
fi

# Endstatus nach Discord melden (waiting -> Kommando-Kanal fürs Go, sonst Log-Kanal)
FINAL=$(python3 -c "import json;d=json.load(open('$STATUS'));a=d['agents'].get('$AGENT',{});print((a.get('status') or '')+'\t'+(a.get('message') or ''))" 2>/dev/null)
FSTATUS="${FINAL%%$'\t'*}"; FMSG="${FINAL#*$'\t'}"
case "$FSTATUS" in
  waiting) dpost "$CMD_CH" "⏳ $AGENT wartet auf dein Go: ${FMSG:-siehe Dashboard}. Antworte mit \`go $AGENT\`." ;;
  error)   dpost "$LOG_CH" "❌ $AGENT: Fehler – Log prüfen. ${FMSG}" ;;
  *)       [ $RC -eq 0 ] && dpost "$LOG_CH" "✅ $AGENT fertig: ${FMSG:-Lauf abgeschlossen}" || dpost "$LOG_CH" "❌ $AGENT abgebrochen (Exit $RC)" ;;
esac

# Dashboard-Datenfiles ins statische Docroot spiegeln (index.html liest sie ohne server.js)
[ -f "$BASE/uptime/uptime.json" ] && cp -f "$BASE/uptime/uptime.json" "$WEBDIR/uptime.json" 2>/dev/null
echo "=== $(date -Is) ENDE rc=$RC ===" >> "$LOG"
exit $RC
