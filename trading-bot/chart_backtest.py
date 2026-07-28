"""Bringt chart_decides einen Edge? -- Backtest-Urteil JETZT, ohne auf Live-Trades zu warten
und ohne den LLM-Forscher.

Faehrt backtester.walk_forward pro eval-Symbol ZWEIMAL auf denselben echten Bars:
  * chart_decides AN  -- die Chartanalyse entscheidet die Seite (der Live-Modus)
  * chart_decides AUS -- nur der alte Trend-Filter (die Vergleichsbasis)
und stellt beides gegen Buy&Hold. Gedruckt werden Sharpe, Rendite, Trades und die
Richtungs-Trefferquote. Ein ehrlicher Vergleich braucht KEINE gute absolute Zahl -- er
braucht nur, dass 'AN' 'AUS' und Buy&Hold schlaegt. Tut es das nicht, hat die Chartanalyse
in diesem System keinen Edge, egal wie viele Indikatoren noch dazukommen.

    python chart_backtest.py            # eval_symbols aus config.learning
    python chart_backtest.py SPY BTC/USD
"""
import sys

import settings
import market_data
import backtester


def _score(sym, days, timeframe, in_bars, out_bars, chart_on):
    df = market_data.get_bars(sym, days=days, timeframe=timeframe)
    df.attrs["symbol"] = sym
    changes = {"backtest.in_sample_days": in_bars, "backtest.out_sample_days": out_bars,
               "allocation.chart_decides": chart_on}
    with settings.config_override(changes):
        r = backtester.walk_forward(df)
    m, ts = r.get("metrics") or {}, r.get("trade_stats") or {}
    bh = (r.get("benchmarks") or {}).get("buy_hold") or {}
    return {"sharpe": m.get("sharpe"), "ret": m.get("total_return"),
            "trades": ts.get("total_trades"), "pf": ts.get("profit_factor"),
            "diracc": r.get("directional_accuracy"), "bh_sharpe": bh.get("sharpe")}


def _fmt(x, pct=False):
    if x is None:
        return "   -"
    return f"{x:+.1%}" if pct else f"{x:+.2f}"


def run(symbols):
    cfg = settings.load_config()
    lcfg = cfg["learning"]
    tf = cfg["hmm"]["live_timeframe"]
    days = lcfg.get("eval_days", 90)
    in_bars, out_bars = lcfg.get("in_sample_bars", 2000), lcfg.get("out_sample_bars", 500)

    print(f"Backtest je Symbol · {days} Tage {tf} · in/out {in_bars}/{out_bars} Bars\n")
    hdr = f"{'Symbol':<10}{'Variante':<14}{'Sharpe':>8}{'Rendite':>10}{'Trades':>8}{'PF':>7}{'DirAcc':>8}{'B&H Sh':>8}"
    print(hdr)
    print("-" * len(hdr))
    agg = {"AN": [], "AUS": []}
    for sym in symbols:
        for label, chart_on in (("chart AN", True), ("chart AUS", False)):
            try:
                s = _score(sym, days, tf, in_bars, out_bars, chart_on)
            except Exception as e:
                print(f"{sym:<10}{label:<14}  Fehler: {str(e)[:60]}")
                continue
            print(f"{sym:<10}{label:<14}{_fmt(s['sharpe']):>8}{_fmt(s['ret'], True):>10}"
                  f"{(s['trades'] or 0):>8}{_fmt(s['pf']):>7}{_fmt(s['diracc']):>8}{_fmt(s['bh_sharpe']):>8}")
            agg["AN" if chart_on else "AUS"].append(s)
        print()

    def _avg(rows, key):
        vals = [r[key] for r in rows if r.get(key) is not None]
        return sum(vals) / len(vals) if vals else None

    print("== Fazit (Ø Sharpe ueber die Symbole) ==")
    an, aus = _avg(agg["AN"], "sharpe"), _avg(agg["AUS"], "sharpe")
    bh = _avg(agg["AN"], "bh_sharpe")
    print(f"  chart_decides AN : {_fmt(an)}")
    print(f"  chart_decides AUS: {_fmt(aus)}")
    print(f"  Buy & Hold       : {_fmt(bh)}")
    if an is not None and aus is not None and bh is not None:
        if an > aus and an > bh:
            print("  -> Chartanalyse schlaegt Trend-Filter UND Buy&Hold. Einziger Fall, in dem")
            print("     der ganze Umbau seinen Sharpe wert ist. Live weiter mit chart_eval pruefen.")
        else:
            print("  -> Chartanalyse schlaegt AUS/Buy&Hold NICHT. Ehrliche Antwort: in diesem")
            print("     System kein Edge. Weitere Indikatoren wuerden das nicht heilen -- das")
            print("     Problem ist der 5-Min-Richtungs-Vorhersage-Anspruch, nicht die Auswahl.")
    return agg


if __name__ == "__main__":
    args = [a for a in sys.argv[1:] if not a.startswith("-")]
    if "--self-test" in sys.argv:
        # Nur der Pfad muss laufen (Synthetik ohne Keys); Zahlen sind bedeutungslos.
        s = _score("SPY", 60, "5Min", 252, 126, True)
        assert "sharpe" in s and "diracc" in s, s
        print("chart_backtest self-check ok:", {k: s[k] for k in ("trades", "diracc")})
    else:
        syms = args or settings.load_config()["learning"]["eval_symbols"]
        run(syms)
