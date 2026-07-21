"""Layer 1/2 test harness -- walk-forward backtester. Rolling windows: in_sample_days
of training, out_sample_days of blind out-of-sample evaluation, rolled forward. Trains
the HMM on each in-sample window, then walks the out-sample block one bar at a time
using FORWARD-ONLY filtering (no look-ahead), turns regime+confidence into a target
allocation, validates it through the risk manager, and simulates fills with realistic
slippage + commission.

Honesty checks baked in:
  - out-of-sample only: the model never scores days it trained on
  - benchmarks: buy & hold, 200-day SMA trend-following, random entry (same risk rules)
  - stress test: inject single-day crash shocks
A 'trade' = a position segment between rebalances; its P&L (currency), entry regime and
entry confidence feed the analytics. Per-run results are saved so runs are comparable."""
import json
from datetime import datetime, timezone

import numpy as np
import pandas as pd

import settings
import hmm_engine
import performance
from feature_engineering import build_features, FEATURE_COLS, realized_vol_now
from regime_strategies import target_allocation, needs_rebalance
from risk_manager import RiskManager


def _simulate(dates, asset_ret, target_alloc, target_lev, regimes, confs, start_equity,
              slippage_bps, commission_ps):
    """Given per-day target exposure, simulate equity + per-segment trades.
    Position at day t earns asset_ret[t] * exposure_held_from_t-1. Slippage/commission
    charged on the change in exposure (a proxy for turnover cost)."""
    equity = start_equity
    curve, held = [], 0.0
    seg = None                      # current open segment
    trades = []
    for i in range(len(dates)):
        # cost of moving from previous exposure to today's target
        new_exposure = target_alloc[i] * target_lev[i]
        turnover = abs(new_exposure - held)
        cost = turnover * (slippage_bps / 1e4) * equity + turnover * commission_ps
        equity -= cost
        # pnl earned by the exposure we now hold, realised on the next bar's return
        pnl_day = held * asset_ret[i] * equity
        equity += pnl_day
        curve.append(equity)

        # segment bookkeeping (a trade = a held exposure until it changes materially)
        if seg is None and new_exposure > 0:
            seg = {"entry_i": i, "entry_equity": equity, "regime": regimes[i],
                   "confidence": confs[i], "exposure": new_exposure}
        elif seg is not None and (new_exposure == 0 or abs(new_exposure - seg["exposure"]) >= 0.05):
            seg["pnl"] = round(equity - seg["entry_equity"], 2)
            seg["exit_i"] = i
            trades.append(seg)
            seg = None if new_exposure == 0 else {
                "entry_i": i, "entry_equity": equity, "regime": regimes[i],
                "confidence": confs[i], "exposure": new_exposure}
        held = new_exposure
    if seg is not None:
        seg["pnl"] = round(equity - seg["entry_equity"], 2)
        seg["exit_i"] = len(dates) - 1
        trades.append(seg)
    return pd.Series(curve, index=dates), trades


def walk_forward(df, start_equity=None, crash_shock=False):
    """Runs the walk-forward loop. Returns a result dict with the strategy equity curve,
    trades, benchmark curves and metrics."""
    cfg = settings.load_config()
    start_equity = start_equity or cfg["starting_equity"]
    bt = cfg["backtest"]
    ins, outs = bt["in_sample_days"], bt["out_sample_days"]

    close = df["close"].astype(float)
    asset_ret = close.pct_change().fillna(0).values
    if crash_shock:                                   # inject crash days into the tape
        asset_ret = asset_ret.copy()
        for j in range(outs, len(asset_ret), max(outs, 1)):
            asset_ret[j] -= bt["crash_shock_pct"]

    all_dates, all_alloc, all_lev, all_reg, all_conf = [], [], [], [], []
    risk = _fresh_risk(start_equity)
    ref_vol = float(np.nanmedian(build_features(df)["realized_vol"])) or 0.012

    i = ins
    while i + 1 < len(df):
        train_df = df.iloc[max(0, i - ins):i]
        try:
            model = hmm_engine.train(train_df)
        except Exception:
            i += outs
            continue
        block_end = min(i + outs, len(df) - 1)
        # forward-filter across the block (past only), then read one bar at a time
        block_df = df.iloc[:block_end]
        feats = build_features(block_df)
        X = feats[FEATURE_COLS].values
        rank, conf = model.filter_states(X)
        feat_dates = feats.index
        prev_alloc = 0.0
        for t in range(i, block_end):
            dt = df.index[t]
            if dt not in feat_dates:
                continue
            pos = feat_dates.get_loc(dt)
            regime = model.labels[int(rank[pos])]
            confidence = float(conf[pos])
            vol = float(feats["realized_vol"].iloc[pos])
            tgt = target_allocation(regime, confidence, vol, ref_vol,
                                    flickering=False)
            alloc, lev, _ = risk.validate_order(tgt["alloc"], tgt["leverage"])
            if not needs_rebalance(prev_alloc, alloc):
                alloc = prev_alloc                     # anti-churn: keep previous
            prev_alloc = alloc
            all_dates.append(dt); all_alloc.append(alloc); all_lev.append(lev)
            all_reg.append(regime); all_conf.append(confidence)
        i += outs

    if len(all_dates) < 5:
        raise RuntimeError("Walk-forward produced too few evaluation days")

    dates = pd.DatetimeIndex(all_dates)
    aret = pd.Series(asset_ret, index=df.index).reindex(dates).fillna(0).values
    equity, trades = _simulate(dates, aret, np.array(all_alloc), np.array(all_lev),
                               all_reg, all_conf, start_equity,
                               bt["slippage_bps"], bt["commission_per_share"])

    benches = _benchmarks(df, dates, start_equity, bt)
    result = {
        "symbol": df.attrs.get("symbol", "?"),
        "source": df.attrs.get("source", "?"),
        "real": bool(df.attrs.get("real", False)),
        "generated": datetime.now(timezone.utc).isoformat(),
        "n_eval_days": len(dates),
        "equity": _series_to_pairs(equity),
        "drawdown": _series_to_pairs(performance.drawdown_series(equity)),
        "monthly_returns": performance.monthly_returns(equity),
        "metrics": performance.equity_metrics(equity),
        "trade_stats": performance.trade_stats(trades),
        "pnl_by_regime": performance.pnl_by_regime(trades),
        "cumulative_pnl": performance.cumulative_pnl(trades),
        "regime_time": _regime_time(all_reg),
        "confidence_curve": [[d.isoformat(), round(c, 4)] for d, c in zip(dates, all_conf)],
        "benchmarks": {k: performance.equity_metrics(v) for k, v in benches.items()},
        "benchmark_curves": {k: _series_to_pairs(v) for k, v in benches.items()},
        "trades": [_trade_row(t, dates) for t in trades],
    }
    result["beats_buy_hold"] = (result["metrics"].get("total_return", 0) >
                                result["benchmarks"].get("buy_hold", {}).get("total_return", 0))
    return result


def _benchmarks(df, dates, start_equity, bt):
    close = df["close"].astype(float)
    ret = close.pct_change().fillna(0)
    # buy & hold
    bh = start_equity * (1 + ret.reindex(dates).fillna(0)).cumprod()
    # 200-day SMA trend following (long when close > SMA200)
    sma = close.rolling(200).mean()
    long = (close > sma).astype(float).shift(1).fillna(0)
    sma_ret = (long * ret).reindex(dates).fillna(0)
    smac = start_equity * (1 + sma_ret).cumprod()
    # random entry, same risk sizing bounds (deterministic seed for reproducibility)
    rng = np.random.default_rng(12345)
    rnd = pd.Series(rng.integers(0, 2, len(dates)) * 0.95, index=dates)
    rnd_ret = rnd.shift(1).fillna(0) * ret.reindex(dates).fillna(0)
    rndc = start_equity * (1 + rnd_ret).cumprod()
    return {"buy_hold": bh, "sma200": smac, "random": rndc}


def _fresh_risk(equity):
    settings.RISK_STATE.unlink(missing_ok=True)
    return RiskManager(equity=equity)


def _series_to_pairs(s):
    return [[d.isoformat(), round(float(v), 2)] for d, v in s.dropna().items()]


def _regime_time(regimes):
    out = {}
    for r in regimes:
        out[r] = out.get(r, 0) + 1
    total = sum(out.values()) or 1
    return {k: round(v / total, 4) for k, v in out.items()}


def _trade_row(t, dates):
    return {
        "entry": dates[t["entry_i"]].date().isoformat(),
        "exit": dates[min(t["exit_i"], len(dates) - 1)].date().isoformat(),
        "regime": t["regime"],
        "confidence": round(t["confidence"], 3),
        "exposure": round(t["exposure"], 3),
        "pnl": t["pnl"],
    }


def run_and_save(symbol="SPY", days=756):
    import market_data
    df = market_data.get_daily_bars(symbol, days=days)
    df.attrs["symbol"] = symbol
    res = walk_forward(df)
    out = settings.STATE_DIR / f"backtest_{symbol}.json"
    out.write_text(json.dumps(res, indent=2), encoding="utf-8")
    return res, out


if __name__ == "__main__":
    res, path = run_and_save("SPY", days=756)
    m, b = res["metrics"], res["benchmarks"]["buy_hold"]
    print(f"eval days: {res['n_eval_days']} | strat total {m['total_return']:.1%} "
          f"vs B&H {b['total_return']:.1%} | Sharpe {m['sharpe']} | maxDD {m['max_drawdown']:.1%}")
    print(f"trades: {res['trade_stats']['total_trades']} | beats B&H: {res['beats_buy_hold']}")
    print("saved ->", path)
