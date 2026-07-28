"""Health + performance snapshot of the live bot, straight from state/dashboard.json.
Token-free, read-only. Run:  .venv/bin/python diagnose.py"""
import json
import collections
from pathlib import Path

import settings


def _load(name, fb):
    try:
        return json.loads((settings.STATE_DIR / name).read_text(encoding="utf-8"))
    except Exception:
        return fb


def main():
    d = _load("dashboard.json", {})
    if not d:
        print("keine dashboard.json -- laeuft der Bot?")
        return
    b, a, ts = d.get("bot", {}), d.get("account", {}), d.get("trade_stats", {})
    lv = d.get("live", {}) or {}
    news = ((d.get("radar", {}) or {}).get("external", {}) or {}).get("news", {})

    print("== FRISCHE ==")
    print(f"  generated {d.get('generated')}  stale_s {lv.get('stale_seconds')}  status {d.get('status')}")
    print(f"  cycles {b.get('cycles')}  orders {b.get('orders_sent')}  errors {b.get('errors')}  "
          f"cycle_s {b.get('cycle_seconds')}  uptime_h {b.get('uptime_hours')}")
    if b.get("last_error"):
        print(f"  LAST ERROR: {b.get('last_error')}")

    print("\n== KONTO ==")
    print(f"  equity {a.get('equity')}  Tag {a.get('day_change')} ({a.get('day_change_pct')})  "
          f"gesamt {a.get('total_change')} ({a.get('total_change_pct')})")
    print(f"  deployed {a.get('deployed')}  unreal {a.get('unrealized_pl')}  offen {len(a.get('open_positions') or [])}  "
          f"trading_enabled {a.get('trading_enabled')}")

    print("\n== REALISIERT ==")
    print(f"  trades {ts.get('trades')}  win_rate {ts.get('win_rate')}  profit_factor {ts.get('profit_factor')}")
    print(f"  avg_win {ts.get('avg_win')}  avg_loss {ts.get('avg_loss')}  realized {ts.get('realized_pnl')}  "
          f"best {ts.get('best')}  worst {ts.get('worst')}")
    print(f"  orders_24h {ts.get('orders_24h')}  vol_24h {ts.get('volume_24h')}  closed_24h {ts.get('closed_24h')}")

    print("\n== NEWS / WELT ==")
    print(f"  {news}")
    print(f"  news_events auf Charts: {len(d.get('news_events') or [])}")

    print("\n== LERNEN ==")
    L = d.get("learning", {}) or {}
    lr = L.get("last_run") or {}
    print(f"  enabled {L.get('enabled')}  overrides {L.get('override_count')}  memory {L.get('memory')}")
    print(f"  letzter Forschungslauf: {lr.get('generated')}  getestet {lr.get('tested')}  promotet {bool(lr.get('promoted'))}")

    print("\n== VERKNUEPFUNGEN (24/7) ==")
    C = d.get("connections", {}) or {}
    print(f"  analysiert {C.get('n_trades')} Trades  baseline_wr {C.get('baseline_win_rate')}  "
          f"Muster {len(C.get('insights') or [])}")
    for i in (C.get("insights") or [])[:8]:
        print(f"    {str(i.get('signal')):9} {str(i.get('key'))[:44]:44} {i.get('trades')}t  "
              f"wr {i.get('win_rate')}  pnl {i.get('total_pnl')}")

    print("\n== PER-TRADE-RUECKBLICK ==")
    tr = d.get("trades") or []
    print(f"  grades {dict(collections.Counter((t.get('review') or {}).get('grade') for t in tr))}")
    print(f"  verdicts {dict(collections.Counter((t.get('review') or {}).get('verdict') for t in tr))}")

    strat = (d.get("account", {}) or {})  # strategy lives in config, not export; infer from signals
    sigs = d.get("signals") or []
    if any(s.get("regime") in ("aufwärts", "abwärts") for s in sigs):
        ups = [s for s in sigs if s.get("regime") == "aufwärts"]
        print(f"\n== TREND-SIGNALE (trend_long) -- {len(ups)}/{len(sigs)} im Aufwaertstrend ==")
        for s in sigs:
            print(f"    {str(s.get('symbol')):10} {str(s.get('regime')):9} "
                  f"exp {s.get('exposure')}  {s.get('decision')}")

    print("\n== SCHLECHTESTE SYMBOLE (realisiert) ==")
    ps = d.get("per_symbol", {}) or {}
    for s, v in sorted(ps.items(), key=lambda kv: (kv[1] or {}).get("realized", 0))[:10]:
        print(f"    {s:10} realized {v.get('realized'):>10}  trades {v.get('trades')}  "
              f"wr {v.get('win_rate')}  unreal {v.get('unrealized')}")

    print("\n== TREND-FILTER (aus dem Journal) ==")
    lines = []
    try:
        lines = (settings.JOURNAL).read_text(encoding="utf-8").splitlines()[-4000:]
    except Exception:
        pass
    c = collections.Counter()
    for ln in lines:
        r = ln.count('"reason"') and ln
        if "Trend bestätigt" in ln:
            c["bestätigt"] += 1
        elif "Trend widerspricht" in ln:
            c["widerspricht"] += 1
    print(f"  {dict(c)}  (aus den letzten {len(lines)} Journal-Zeilen)")


if __name__ == "__main__":
    main()
