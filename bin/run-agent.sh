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
echo "=== $(date -Is) START $AGENT ===" >> "$LOG"

cd "$BASE"
claude -p "$PROMPT

ZUSÄTZLICH (Status fürs Dashboard): Rufe während der Arbeit bei jedem größeren Schritt auf:
  $BASE/bin/status-update.sh $AGENT running \"<Phase>\" <Fortschritt 0-100> \"<kurze Sprechblasen-Nachricht, max 34 Zeichen>\"
und ganz am Ende mit Status ok (oder waiting, falls du auf Sebastians Go wartest) inkl. Details/Outputs:
  $BASE/bin/status-update.sh $AGENT ok \"Fertig\" 100 \"<Kurzfazit>\" '<json-array details>' '<json-array outputs>'" \
  --dangerously-skip-permissions < /dev/null >> "$LOG" 2>&1
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

# Dashboard-Datenfiles ins statische Docroot spiegeln (index.html liest sie ohne server.js)
[ -f "$BASE/uptime/uptime.json" ] && cp -f "$BASE/uptime/uptime.json" "$WEBDIR/uptime.json" 2>/dev/null
echo "=== $(date -Is) ENDE rc=$RC ===" >> "$LOG"
exit $RC
