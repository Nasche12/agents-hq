"""The judge. Takes candidate parameter sets and decides them with data, never with an
opinion. This is the component that turns "the agent proposes things" into "the agent
gets better".

How a candidate is judged:

  selection window   walk-forward, out-of-sample only, across several symbols.
                     Objective = MEDIAN Sharpe over symbols (median, so one lucky
                     symbol cannot carry a bad idea).
  holdout window     the most recent slice of history, NEVER used to rank candidates.
                     Only the single winner is measured here, once. This is the defence
                     against picking the best of N noise draws.
  hard gates         must beat the current champion by a margin, must beat buy & hold,
                     must not deepen drawdown beyond tolerance, must have enough trades.

Isolation: the backtester resets the RiskManager, which deletes risk_state.json and can
write EMERGENCY.lock. On the server this runs NEXT TO the live bot, so every evaluation
happens against a temporary state directory. The live bot's risk state is never touched."""
import shutil
import tempfile
from contextlib import contextmanager
from pathlib import Path

import settings
import backtester
import market_data
from optimizer_gate import aggregate, gate     # pure decision logic, dependency-free

_BARS = {}                       # (symbol, timeframe, days) -> DataFrame, reused across candidates


@contextmanager
def isolated_state():
    """Point the mutable state files at a throwaway directory for the duration.
    Without this, a research run on the server would wipe the live bot's daily P&L
    counters -- or arm its kill switch."""
    tmp = Path(tempfile.mkdtemp(prefix="tb-research-"))
    keep = (settings.RISK_STATE, settings.LOCK_FILE)
    settings.RISK_STATE = tmp / "risk_state.json"
    settings.LOCK_FILE = tmp / "EMERGENCY.lock"
    try:
        yield tmp
    finally:
        settings.RISK_STATE, settings.LOCK_FILE = keep
        shutil.rmtree(tmp, ignore_errors=True)


def _bars(symbol, timeframe, days):
    key = (symbol, timeframe, days)
    if key not in _BARS:
        df = market_data.get_bars(symbol, days=days, timeframe=timeframe)
        df.attrs["symbol"] = symbol
        _BARS[key] = df
    return _BARS[key]


def _split(df, holdout_frac):
    """Oldest part ranks candidates; newest part confirms the winner. Never mixed."""
    cut = int(len(df) * (1 - holdout_frac))
    sel, hold = df.iloc[:cut].copy(), df.iloc[cut:].copy()
    for part in (sel, hold):
        part.attrs.update(df.attrs)
    return sel, hold


def _score_one(df, lcfg):
    """Walk-forward one symbol under whatever config is currently in effect."""
    with settings.config_override({"backtest.in_sample_days": lcfg["in_sample_bars"],
                                   "backtest.out_sample_days": lcfg["out_sample_bars"]}):
        res = backtester.walk_forward(df)
    m = res.get("metrics") or {}
    ts = res.get("trade_stats") or {}
    bh = (res.get("benchmarks") or {}).get("buy_hold") or {}
    return {
        "sharpe": m.get("sharpe"),
        "total_return": m.get("total_return"),
        "max_drawdown": m.get("max_drawdown"),
        "trades": ts.get("total_trades", 0),
        "profit_factor": ts.get("profit_factor"),
        "buy_hold_sharpe": bh.get("sharpe"),
        "eval_bars": res.get("n_eval_days", 0),
    }


def evaluate(changes, symbols, lcfg, window="selection"):
    """Score one parameter set across all research symbols. Returns the aggregate plus
    the per-symbol detail, so a rejection can always be explained."""
    per_symbol, errors = {}, []
    timeframe = changes.get("hmm.live_timeframe") or settings.load_config()["hmm"]["live_timeframe"]
    with settings.config_override(changes):
        for sym in symbols:
            try:
                df = _bars(sym, timeframe, lcfg["eval_days"])
                sel, hold = _split(df, lcfg["holdout_frac"])
                per_symbol[sym] = _score_one(sel if window == "selection" else hold, lcfg)
            except Exception as e:                    # one bad symbol must not void the run
                errors.append(f"{sym}: {str(e)[:120]}")
    return aggregate(per_symbol, errors, changes)


def run(candidates, lcfg, symbols):
    """Full research pass: score the champion, score every candidate on the selection
    window, then confirm ONLY the best one on the untouched holdout."""
    results = {"champion": None, "candidates": [], "winner": None, "holdout": None}
    with isolated_state():
        champ = evaluate({}, symbols, lcfg, "selection")
        results["champion"] = champ

        scored = []
        for c in candidates[: lcfg["max_candidates"]]:
            ev = evaluate(c["changes"], symbols, lcfg, "selection")
            ok, reason = gate(ev, champ, lcfg)
            ev["passes_selection"] = ok
            ev["reason"] = reason
            ev["hypothesis"] = c.get("hypothesis")
            ev["rationale"] = c.get("rationale")
            results["candidates"].append(ev)
            if ok:
                scored.append(ev)

        if not scored:
            return results
        best = max(scored, key=lambda e: e["objective"])
        results["winner"] = best

        # The holdout is touched exactly once, by exactly one candidate. That is the
        # whole point: it cannot have been selected FOR this window.
        champ_hold = evaluate({}, symbols, lcfg, "holdout")
        cand_hold = evaluate(best["changes"], symbols, lcfg, "holdout")
        ok, reason = gate(cand_hold, champ_hold, lcfg)
        results["holdout"] = {"champion": champ_hold, "candidate": cand_hold,
                              "passes": ok, "reason": reason}
    return results


if __name__ == "__main__":
    cfg = settings.load_config()
    lcfg = cfg["learning"]
    syms = lcfg["eval_symbols"][:1]
    print(f"quick check on {syms} (synthetic if no keys) ...")
    with isolated_state():
        champ = evaluate({}, syms, dict(lcfg, eval_days=30), "selection")
    print("champion objective:", champ.get("objective"), "| trades:", champ.get("trades"),
          "| errors:", champ.get("errors"))
    assert settings.RISK_STATE.name == "risk_state.json", "state isolation leaked"
    print("optimizer self-check ok (live risk state untouched)")
