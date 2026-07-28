"""Cross-sectional relative-strength (momentum) backtest over the whole universe.

The live bot trades each symbol on its OWN noisy HMM regime -- and that has < 50% accuracy.
This is a structurally different bet, and the most-replicated retail-viable edge: rank ALL
symbols by trailing momentum each rebalance, go LONG the strongest few, SHORT the weakest
few (crypto cannot short -> those drop to flat). It exploits RELATIVE strength across the
universe instead of trying to time each symbol's direction.

Deliberately NOT optimized to this data: standard momentum parameters (a ~3-month lookback
skipping the last week -- the classic 12-1 / 60-5 construction that avoids short-term
reversal), fixed K, periodic rebalance. Hyperparameter honesty: if it only works at one
magic lookback, it is a fluke -- so __main__ sweeps a few standard settings and you can see
whether the effect is stable or cherry-picked. Net of turnover cost. Benchmark = equal-
weight buy&hold of the same universe."""
import numpy as np
import pandas as pd

import market_data


def panel(symbols, days=700):
    """Aligned daily close panel for the universe. Equities are stamped at 04:00 UTC and
    crypto at 00:00 UTC -- so normalise to the calendar DATE, forward-fill crypto onto the
    weekday grid, and keep the common window where every symbol has history."""
    cols = {}
    for s in symbols:
        try:
            ser = market_data.get_daily_bars(s, days=days)["close"].astype(float)
            ser.index = ser.index.normalize()             # 04:00/00:00 -> same calendar date
            cols[s] = ser[~ser.index.duplicated(keep="last")]
        except Exception:
            continue
    if not cols:
        return pd.DataFrame()
    px = pd.DataFrame(cols).sort_index().ffill()
    return px.dropna()                                     # common window: all symbols present


def backtest(px, lookback=63, skip=5, k=4, reb=5, slip_bps=5, allow_short=True):
    """Walk the panel day by day. Every `reb` days, rank by momentum (return from
    t-lookback-skip to t-skip), long the top k, short the bottom k (shorts skipped for
    crypto). Equal weight, dollar-neutral-ish. Charge slippage on turnover.
    Returns dict with strat/bh metrics."""
    if len(px) < lookback + skip + 20 or px.shape[1] < 4:
        return None
    rets = px.pct_change().fillna(0.0)
    crypto = {s for s in px.columns if market_data.is_crypto(s)}
    dates = px.index
    eq, held = 1.0, {}
    strat_ret = []
    start = lookback + skip
    for i in range(start, len(dates)):
        if (i - start) % reb == 0:                         # rebalance day
            mom = (px.iloc[i - skip] / px.iloc[i - lookback - skip] - 1).dropna()
            if len(mom) >= 2 * k:
                ranked = mom.sort_values()
                longs = list(ranked.index[-k:])
                shorts = [s for s in ranked.index[:k] if allow_short and s not in crypto]
                n = len(longs) + len(shorts) or 1
                w = {s: 1.0 / n for s in longs}
                for s in shorts:
                    w[s] = -1.0 / n
                turn = sum(abs(w.get(s, 0) - held.get(s, 0)) for s in set(w) | set(held))
                eq -= turn * (slip_bps / 1e4) * eq
                held = w
        day = sum(held.get(s, 0.0) * rets.iloc[i].get(s, 0.0) for s in held)
        eq *= (1 + day)
        strat_ret.append(day)
    sr = np.array(strat_ret)
    ann = np.sqrt(252)
    sharpe = round(float(ann * sr.mean() / (sr.std() + 1e-12)), 2)
    bh = (1 + rets.iloc[start:].mean(axis=1)).cumprod()
    # max drawdown of the strat curve
    curve = np.cumprod(1 + sr)
    dd = float((curve / np.maximum.accumulate(curve) - 1).min())
    return {"total": round(eq - 1, 4), "sharpe": sharpe, "maxdd": round(dd, 4),
            "buy_hold": round(float(bh.iloc[-1] - 1), 4), "days": len(sr),
            "symbols": px.shape[1]}


if __name__ == "__main__":
    import settings
    syms = settings.load_config()["watchlist"]
    px = panel(syms, days=700)
    print(f"Universe: {px.shape[1]} Symbole, {len(px)} Tage\n")
    print(f"{'lookback':>8} {'k':>3} {'reb':>4} {'strat':>9} {'sharpe':>7} {'maxDD':>8} {'B&H(EW)':>9}")
    for lookback in (21, 42, 63, 126):
        for k in (3, 4):
            for reb in (5, 10):
                r = backtest(px, lookback=lookback, k=k, reb=reb, slip_bps=5)
                if r:
                    print(f"{lookback:8d} {k:3d} {reb:4d} {r['total']:+8.1%} {r['sharpe']:7.2f} "
                          f"{r['maxdd']:+7.1%} {r['buy_hold']:+8.1%}")
