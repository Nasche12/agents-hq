"""Hat die Chartanalyse einen Edge? -- Trades gegen Outcome.

Verknuepft jeden geschlossenen Round-Trip mit dem chart_bias UND der Indikator-Zerlegung
(chart_parts), die der Bot BEIM EINSTIEG sah (aus dem Journal), und fragt zwei ehrliche
Dinge:

  1. Bringt ein STAERKERES Chart-Signal ein besseres Ergebnis? (Bucket nach |chart_bias|)
  2. WELCHER Indikator (Trend/MACD/Muster/RSI-Div/Range) trennt Gewinner von Verlierern?
     -- gemessen als "wie stark zeigte die Komponente in die tatsaechlich gehandelte
     Richtung", gemittelt ueber Gewinner vs. Verlierer.

Read-only. Erfindet nichts: Trades ohne Chart-Read am Einstieg (alles vor dem Umschalten
auf chart_decides) werden AUSGESCHLOSSEN und separat gezaehlt -- sie wuerden das Bild sonst
mit trend_long-/alt-hmm-Leichen verwaessern.

    python chart_eval.py            # gegen state/orders.json + state/journal.jsonl
"""
import json
from collections import defaultdict
from datetime import datetime

import settings
import trade_stats


def _parse(iso):
    try:
        return datetime.fromisoformat(str(iso).replace("Z", "+00:00"))
    except Exception:
        return None


def _chart_index(journal):
    """symbol -> sorted [(ts, chart_bias, direction, chart_parts)] fuer Zyklen mit Chart-Read."""
    idx = defaultdict(list)
    for e in journal or []:
        if e.get("type") != "cycle" or e.get("chart_bias") is None or not e.get("symbol"):
            continue
        ts = _parse(e.get("ts"))
        if ts is None:
            continue
        expo = e.get("exposure") or 0.0
        direction = "long" if expo > 0 else ("short" if expo < 0 else "flat")
        idx[e["symbol"]].append((ts, float(e["chart_bias"]), direction, e.get("chart_parts") or {}))
    for s in idx:
        idx[s].sort()
    return idx


def _chart_at(idx, symbol, opened):
    """Der letzte Chart-Read fuer `symbol` am/kurz vor dem Einstieg. None -> kein Read (Trade
    stammt aus der Zeit vor chart_decides)."""
    o = _parse(opened)
    if o is None:
        return None
    best = None
    for rec in idx.get(symbol, []):
        if rec[0] <= o:
            best = rec
        else:
            break
    return None if best is None else (best[1], best[2], best[3])


def _bucket(b):
    a = abs(b)
    return "stark  >=0.35" if a >= 0.35 else ("mittel 0.20-0.35" if a >= 0.20 else "schwach <0.20")


def evaluate(orders, journal):
    """Round-Trips mit Chart-Read verknuepfen. Gibt (alle_geschlossen, mit_chart) zurueck."""
    closed = trade_stats.realized_trades(orders)
    idx = _chart_index(journal)
    rows = []
    for t in closed:
        ca = _chart_at(idx, t["symbol"], t.get("opened"))
        if ca is None:
            continue
        bias, direction, parts = ca
        rows.append({**t, "chart_bias": bias, "chart_dir": direction, "chart_parts": parts})
    return closed, rows


def _wr(trades):
    if not trades:
        return None, 0.0, 0
    wins = sum(1 for t in trades if t["pnl"] > 0)
    return wins / len(trades), sum(t["pnl"] for t in trades) / len(trades), len(trades)


def report(orders, journal):
    closed, rows = evaluate(orders, journal)
    print(f"Geschlossene Round-Trips gesamt: {len(closed)}")
    print(f"davon MIT Chart-Read am Einstieg (chart_decides): {len(rows)}")
    print(f"ohne (Leichen vor dem Umschalten, ausgeschlossen): {len(closed) - len(rows)}\n")

    if len(rows) < 10:
        print("!! Zu wenig chart-entschiedene Trades fuer eine belastbare Aussage.")
        print("   chart_decides laeuft erst seit dem letzten Umschalten -- warte, bis sich")
        print("   >= 20-30 Round-Trips angesammelt haben, oder urteile ueber den Backtest")
        print("   (research_cycle), der jetzt genau diese Strategie testet.\n")

    # 1) bringt ein staerkeres Signal ein besseres Ergebnis?
    by_b = defaultdict(list)
    for r in rows:
        by_b[_bucket(r["chart_bias"])].append(r)
    print("== Ergebnis nach Signalstaerke |chart_bias| ==")
    print(f"{'Bucket':<18}{'Trades':>7}{'Trefferquote':>14}{'Ø P&L':>10}")
    for b in ("schwach <0.20", "mittel 0.20-0.35", "stark  >=0.35"):
        wr, avg, n = _wr(by_b.get(b, []))
        if n:
            print(f"{b:<18}{n:>7}{(f'{wr:.0%}' if wr is not None else '-'):>14}{avg:>+10.2f}")
    print("   Edge-Test: Trefferquote und Ø P&L sollten mit der Staerke STEIGEN. Tun sie das")
    print("   nicht (flach oder fallend), hat das Chart-Signal in echt keinen Vorhersagewert.\n")

    # 2) welcher Indikator trennt Gewinner von Verlierern?
    comps = defaultdict(lambda: {"win": [], "loss": []})
    for r in rows:
        d = 1.0 if r["chart_dir"] == "long" else -1.0        # in gehandelte Richtung projizieren
        out = "win" if r["pnl"] > 0 else "loss"
        for k, v in (r["chart_parts"] or {}).items():
            comps[k][out].append(float(v) * d)
    if comps:
        print("== Indikator-Beitrag: Zustimmung zur gehandelten Seite, Gewinner vs. Verlierer ==")
        print(f"{'Indikator':<12}{'Ø Gewinner':>12}{'Ø Verlierer':>13}{'Spreizung':>11}")
        def _m(a):
            return sum(a) / len(a) if a else 0.0
        for k in sorted(comps, key=lambda k: -( _m(comps[k]['win']) - _m(comps[k]['loss']) )):
            w, l = _m(comps[k]["win"]), _m(comps[k]["loss"])
            print(f"{k:<12}{w:>+12.2f}{l:>+13.2f}{(w - l):>+11.2f}")
        print("   Spreizung > 0 = dieser Indikator zeigte bei Gewinnern staerker in die")
        print("   gehandelte Richtung als bei Verlierern -> er traegt. Spreizung <= 0 = er")
        print("   ist Rauschen oder kontraproduktiv und gehoert aus dem chart_bias-Mix.\n")
    return closed, rows


def _load():
    orders = json.loads(settings.ORDERS.read_text(encoding="utf-8"))
    journal = [json.loads(l) for l in
               settings.JOURNAL.read_text(encoding="utf-8").splitlines() if l.strip()]
    return orders, journal


if __name__ == "__main__":
    import sys
    if "--self-test" in sys.argv or not settings.ORDERS.exists():
        # Synthetik: ein starkes Chart-Signal (+0.4, Muster dominant) fuehrt zum Gewinner,
        # ein schwaches (-0.12) zum Verlierer. Das Werkzeug muss beides korrekt zuordnen.
        journal = [
            {"type": "cycle", "symbol": "SPY", "ts": "2026-07-28T14:00:00Z", "exposure": 0.3,
             "chart_bias": 0.40, "chart_parts": {"Muster": 0.8, "Trend": 0.3}},
            {"type": "cycle", "symbol": "QQQ", "ts": "2026-07-28T14:00:00Z", "exposure": 0.2,
             "chart_bias": 0.12, "chart_parts": {"Muster": 0.1, "Trend": 0.2}},
        ]
        orders = [
            {"symbol": "SPY", "side": "buy", "filled_qty": 10, "filled_avg_price": 100,
             "filled_at": "2026-07-28T14:01:00Z", "status": "filled"},
            {"symbol": "SPY", "side": "sell", "filled_qty": 10, "filled_avg_price": 105,
             "filled_at": "2026-07-28T15:00:00Z", "status": "filled"},         # +50 Gewinner
            {"symbol": "QQQ", "side": "buy", "filled_qty": 10, "filled_avg_price": 100,
             "filled_at": "2026-07-28T14:01:00Z", "status": "filled"},
            {"symbol": "QQQ", "side": "sell", "filled_qty": 10, "filled_avg_price": 98,
             "filled_at": "2026-07-28T15:00:00Z", "status": "filled"},         # -20 Verlierer
        ]
        closed, rows = evaluate(orders, journal)
        assert len(closed) == 2 and len(rows) == 2, (len(closed), len(rows))
        spy = next(r for r in rows if r["symbol"] == "SPY")
        assert spy["chart_bias"] == 0.40 and spy["pnl"] > 0, spy
        assert next(r for r in rows if r["symbol"] == "QQQ")["pnl"] < 0
        print("chart_eval self-check ok\n")
        report(orders, journal)
    else:
        report(*_load())
