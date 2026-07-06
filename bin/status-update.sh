#!/usr/bin/env bash
# Aufruf: status-update.sh <agent-id> <status> <phase> <progress> <message> [details_json] [outputs_json]
BASE="$(cd "$(dirname "$0")/.." && pwd)"
WEBDIR="$BASE/httpdocs"; [ -d "$WEBDIR" ] || WEBDIR="$BASE/dashboard"
python3 - "$WEBDIR/status.json" "$@" << 'PY'
import json,sys,datetime,os
f,agent,st,phase,prog,msg=sys.argv[1:7]
det=sys.argv[7] if len(sys.argv)>7 else ""
out=sys.argv[8] if len(sys.argv)>8 else ""
d=json.load(open(f)) if os.path.exists(f) else {"agents":{}}
a=d.setdefault("agents",{}).setdefault(agent,{"name":agent})
a.update(status=st,phase=phase,progress=int(prog),message=msg)
if det: a["details"]=json.loads(det)
if out: a["outputs"]=json.loads(out)
d["updated"]=datetime.datetime.now().astimezone().isoformat(timespec="seconds")
tmp=f+".tmp"; json.dump(d,open(tmp,"w"),ensure_ascii=False,indent=1); os.replace(tmp,f)
PY
