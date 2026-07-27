"""The decision rules, deliberately separated from the machinery that produces the
numbers. This module has NO dependencies -- no pandas, no hmmlearn, no I/O -- because
it is the component that decides whether a change reaches the live bot, and that
deserves to be readable and testable on its own.

Everything here is arithmetic over measured values, so any verdict in the memory can be
reproduced from the stored numbers without re-running a single backtest."""
import statistics


def aggregate(per_symbol, errors, changes):
    """Collapse per-symbol walk-forward results into one comparable score.

    MEDIAN, not mean: with a mean, one symbol that got lucky can carry an otherwise bad
    parameter set over the line. The median demands that the change works for the
    typical symbol, which is the claim actually being made."""
    good = [v for v in per_symbol.values() if v.get("sharpe") is not None]
    if not good:
        return {"changes": changes, "ok": False, "objective": None,
                "per_symbol": per_symbol, "errors": errors,
                "reason": "keine auswertbaren Symbole"}
    bh = [v["buy_hold_sharpe"] for v in good if v.get("buy_hold_sharpe") is not None]
    dd = [v["max_drawdown"] for v in good if v.get("max_drawdown") is not None]
    return {
        "changes": changes,
        "ok": True,
        "objective": round(statistics.median(v["sharpe"] for v in good), 4),
        "buy_hold_objective": round(statistics.median(bh), 4) if bh else None,
        "max_drawdown": round(statistics.median(dd), 4) if dd else None,
        "trades": sum(v.get("trades", 0) for v in good),
        "symbols_scored": len(good),
        "per_symbol": per_symbol,
        "errors": errors,
    }


def gate(cand, champ, lcfg):
    """(passes, reason). Every gate exists for a specific failure mode:

    min_trades       a great Sharpe over 4 trades is noise, not an edge.
    min_symbols      one symbol is an anecdote.
    min_improvement  without a margin the bot churns its own parameters forever on
                     differences that are pure sampling noise.
    buy & hold       if simply holding beats the strategy, the strategy is overhead.
    drawdown         a higher Sharpe bought with a much deeper hole is not an improvement.
    """
    if not cand.get("ok"):
        return False, cand.get("reason", "nicht auswertbar")
    if cand.get("trades", 0) < lcfg["min_trades"]:
        return False, f"zu wenige Trades ({cand.get('trades', 0)} < {lcfg['min_trades']})"
    if cand.get("symbols_scored", 0) < lcfg["min_symbols"]:
        return False, f"nur {cand.get('symbols_scored', 0)} Symbole auswertbar"

    champ_obj = (champ or {}).get("objective")
    if champ_obj is not None:
        # relative margin, plus an absolute floor so a champion near zero still needs
        # a real gap rather than a rounding difference
        need = max(champ_obj + abs(champ_obj) * lcfg["min_improvement"], champ_obj + 0.05)
        if cand["objective"] <= need:
            return False, (f"schlaegt Champion nicht deutlich genug "
                           f"({cand['objective']} vs noetig {round(need, 4)})")

    if cand.get("buy_hold_objective") is not None and cand["objective"] <= cand["buy_hold_objective"]:
        return False, (f"schlaegt Buy&Hold nicht ({cand['objective']} vs "
                       f"{cand['buy_hold_objective']})")

    champ_dd = (champ or {}).get("max_drawdown")
    if cand.get("max_drawdown") is not None and champ_dd is not None:
        if cand["max_drawdown"] < champ_dd - lcfg["drawdown_tolerance"]:
            return False, (f"Drawdown zu tief ({cand['max_drawdown']:.1%} vs Champion "
                           f"{champ_dd:.1%})")

    return True, "alle Tore bestanden"


if __name__ == "__main__":
    lcfg = {"min_trades": 40, "min_symbols": 3, "min_improvement": 0.10,
            "drawdown_tolerance": 0.03}
    good = {"ok": True, "objective": 2.0, "buy_hold_objective": 1.0,
            "max_drawdown": -0.10, "trades": 100, "symbols_scored": 4}
    weak = dict(good, objective=1.0)
    assert gate(good, weak, lcfg)[0]
    assert not gate(dict(good, objective=1.02), weak, lcfg)[0], "marginal beat must fail"
    assert not gate(dict(good, trades=5), weak, lcfg)[0]
    assert not gate(dict(good, objective=0.9, buy_hold_objective=1.5), dict(weak, objective=0.1), lcfg)[0]
    assert not gate(dict(good, max_drawdown=-0.4), dict(weak, max_drawdown=-0.1), lcfg)[0]
    agg = aggregate({"A": {"sharpe": 3.0, "max_drawdown": -0.1, "trades": 10},
                     "B": {"sharpe": 0.1, "max_drawdown": -0.2, "trades": 10},
                     "C": {"sharpe": 0.2, "max_drawdown": -0.15, "trades": 10}}, [], {})
    assert agg["objective"] == 0.2, f"median must not be dragged up by one winner: {agg}"
    print("gate self-check ok")
