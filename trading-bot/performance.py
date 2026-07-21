"""Performance metrics -- pure functions over an equity series and a trade list.
Used by the backtester and the dashboard export. Every number rounded for display."""
import numpy as np
import pandas as pd

TRADING_DAYS = 252


def equity_metrics(equity):
    """equity: pd.Series indexed by date. Returns the headline numbers."""
    equity = equity.dropna()
    if len(equity) < 2:
        return {}
    rets = equity.pct_change().dropna()
    total_return = equity.iloc[-1] / equity.iloc[0] - 1
    years = max((equity.index[-1] - equity.index[0]).days / 365.25, 1e-9)
    cagr = (equity.iloc[-1] / equity.iloc[0]) ** (1 / years) - 1
    sharpe = 0.0
    if rets.std() > 0:
        sharpe = np.sqrt(TRADING_DAYS) * rets.mean() / rets.std()
    dd = drawdown_series(equity)
    return {
        "total_return": round(float(total_return), 4),
        "cagr": round(float(cagr), 4),
        "sharpe": round(float(sharpe), 3),
        "max_drawdown": round(float(dd.min()), 4),
        "final_equity": round(float(equity.iloc[-1]), 2),
        "start_equity": round(float(equity.iloc[0]), 2),
    }


def drawdown_series(equity):
    """% below the running peak (<= 0). The 'underwater' plot."""
    peak = equity.cummax()
    return equity / peak - 1


def monthly_returns(equity):
    """Return per calendar month as {'YYYY-MM': ret}."""
    m = equity.resample("ME").last().pct_change().dropna()
    return {ts.strftime("%Y-%m"): round(float(v), 4) for ts, v in m.items()}


def trade_stats(trades):
    """trades: list of dicts with 'pnl' (currency). Returns the analytics cards."""
    pnls = np.array([t["pnl"] for t in trades], float) if trades else np.array([])
    if pnls.size == 0:
        return {"total_trades": 0, "win_rate": 0.0, "avg_win": 0.0, "avg_loss": 0.0,
                "profit_factor": 0.0, "expectancy": 0.0}
    wins, losses = pnls[pnls > 0], pnls[pnls < 0]
    gross_win, gross_loss = wins.sum(), -losses.sum()
    return {
        "total_trades": int(pnls.size),
        "win_rate": round(float(len(wins) / len(pnls)), 4),
        "avg_win": round(float(wins.mean()) if len(wins) else 0.0, 2),
        "avg_loss": round(float(losses.mean()) if len(losses) else 0.0, 2),
        "profit_factor": round(float(gross_win / gross_loss), 3) if gross_loss > 0 else float("inf"),
        "expectancy": round(float(pnls.mean()), 2),
    }


def pnl_by_regime(trades):
    """Total P&L grouped by the regime at entry -- shows where the edge (or bleed) is."""
    agg = {}
    for t in trades:
        agg[t.get("regime", "?")] = agg.get(t.get("regime", "?"), 0.0) + t["pnl"]
    return {k: round(v, 2) for k, v in agg.items()}


def cumulative_pnl(trades):
    """Running total across trades (by trade number)."""
    out, run = [], 0.0
    for t in trades:
        run += t["pnl"]
        out.append(round(run, 2))
    return out


if __name__ == "__main__":
    idx = pd.date_range("2023-01-01", periods=260, freq="B")
    eq = pd.Series(100000 * np.cumprod(1 + np.random.default_rng(0).normal(0.0005, 0.01, 260)), index=idx)
    m = equity_metrics(eq)
    assert "sharpe" in m and m["final_equity"] > 0
    ts = trade_stats([{"pnl": 100, "regime": "bull"}, {"pnl": -40, "regime": "bear"}])
    assert ts["total_trades"] == 2 and ts["win_rate"] == 0.5
    print("performance self-check ok:", m, ts)
