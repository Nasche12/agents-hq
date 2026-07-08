#!/usr/bin/env python3
"""Pflegt uptime/uptime.json: aktueller Snapshot + rollierende Historie fuer die Charts.

Aufruf:
  python3 bin/uptime-record.py <uptime_json> '<sites_json>' [max_history]

<sites_json> ist die Liste der aktuellen Messungen (genau die Werte aus curl):
  [{"name","url","state","http","ms","ssl_days","checked"[,"reason"]}]

Der Recorder haengt daraus EINEN Historienpunkt an (Zeit + je Site ms/ssl/up),
trimmt auf max_history (Default 288 = 3 Tage bei 15-Min-Takt) und schreibt atomar.
So bleibt die Zeitreihe wachsend und deterministisch, unabhaengig vom Modell.
"""
import json, sys, os, datetime

def main():
    if len(sys.argv) < 3:
        print("usage: uptime-record.py <uptime_json> <sites_json> [max_history]", file=sys.stderr)
        return 2
    path = sys.argv[1]
    sites = json.loads(sys.argv[2])
    if not isinstance(sites, list):
        raise SystemExit("sites_json muss eine Liste sein")
    max_hist = int(sys.argv[3]) if len(sys.argv) > 3 else 288

    now = datetime.datetime.now().astimezone().replace(microsecond=0).isoformat()

    data = {"stand": now, "sites": [], "history": []}
    if os.path.exists(path):
        try:
            data = json.load(open(path, encoding="utf-8"))
        except (ValueError, OSError):
            pass  # kaputte Datei -> neu aufbauen, Historie geht verloren (akzeptabel)
    data.setdefault("history", [])

    data["stand"] = now
    data["sites"] = sites

    # up = 1 nur bei state "ok"/"slow" (erreichbar), sonst 0 -> Availability-Linie
    point = {"t": now, "p": [
        {"n": s.get("name"),
         "ms": s.get("ms"),
         "ssl": s.get("ssl_days"),
         "up": 1 if s.get("state") in ("ok", "slow") else 0}
        for s in sites
    ]}
    data["history"].append(point)
    if len(data["history"]) > max_hist:
        data["history"] = data["history"][-max_hist:]

    tmp = path + ".tmp"
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    json.dump(data, open(tmp, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    os.replace(tmp, path)
    print(f"uptime.json: {len(sites)} Sites, {len(data['history'])} Historienpunkte")
    return 0

if __name__ == "__main__":
    raise SystemExit(main())
