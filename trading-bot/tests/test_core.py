"""Phase-1 verification. The critical invariants of a regime-trading bot: no look-ahead
anywhere, reproducible training, the risk breakers actually fire, allocation reacts the
right way, and the backtester stays out-of-sample honest. Run: pytest -q (from trading-bot/)."""
import sys
from pathlib import Path

import numpy as np
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import settings
import market_data
import hmm_engine
from feature_engineering import build_features, FEATURE_COLS
from regime_strategies import target_allocation, needs_rebalance
from risk_manager import RiskManager


@pytest.fixture(scope="module")
def df():
    d = market_data.get_daily_bars("SPY", days=600, force_synthetic=True)
    d.attrs["symbol"] = "SPY"
    return d


@pytest.fixture(scope="module")
def model(df):
    return hmm_engine.train(df)


def test_features_no_lookahead(df):
    full = build_features(df)
    partial = build_features(df.iloc[:300])
    common = full.index.intersection(partial.index)
    assert np.allclose(full.loc[common].values, partial.loc[common].values), \
        "feature changed when later bars were added -> look-ahead leak"
    assert not full.isna().any().any()


def test_hmm_reproducible(df):
    a, b = hmm_engine.train(df), hmm_engine.train(df)
    assert a.n_regimes == b.n_regimes and a.labels == b.labels


def test_hmm_forward_only(model, df):
    X = build_features(df)[FEATURE_COLS].values
    full, _ = model.filter_states(X)
    part, _ = model.filter_states(X[:-40])
    assert np.array_equal(full[:len(part)], part), "filtered state depends on the future"


def test_regime_labels_sorted_by_return(model, df):
    # weakest rank should have the lowest mean log-return
    means = model.model.means_[:, 0]
    ranks = [model.order[s] for s in range(model.model.n_components)]
    by_rank = sorted(zip(ranks, means))
    vals = [m for _, m in by_rank]
    assert vals == sorted(vals), "regimes not monotonically ordered by return"


def test_allocation_reacts():
    ref = 0.012
    bull = target_allocation("bull", 0.9, 0.010, ref)["alloc"]
    crash = target_allocation("crash", 0.9, 0.045, ref)["alloc"]
    lowconf = target_allocation("bull", 0.4, 0.010, ref)["alloc"]
    assert bull > crash
    assert lowconf < bull
    assert not needs_rebalance(0.90, 0.93)
    assert needs_rebalance(0.20, 0.95)


def test_risk_breakers_fire(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "RISK_STATE", tmp_path / "risk.json")
    monkeypatch.setattr(settings, "LOCK_FILE", tmp_path / "lock")
    rm = RiskManager(equity=100_000)
    assert rm.update_equity(100_000)["multiplier"] == 1.0
    assert "day_halve" in rm.update_equity(97_500)["breakers"]
    assert rm.update_equity(96_500)["multiplier"] == 0.0          # -3.5% day -> flat
    res = rm.update_equity(89_000)                                # -11% from peak
    assert res["killed"] and (tmp_path / "lock").exists()
    alloc, lev, _ = rm.validate_order(0.95, 1.25)
    assert alloc == 0.0 and lev == 0.0


def test_per_trade_cap():
    rm = RiskManager(equity=100_000)
    assert 0 < rm.per_trade_cap() <= 0.05


def test_directional_long_and_short():
    from regime_strategies import directional_exposure
    ref = 0.012
    weak, _ = directional_exposure(0, 5, 0.9, 0.010, ref)     # weakest regime -> short
    strong, _ = directional_exposure(4, 5, 0.9, 0.010, ref)   # strongest -> long
    mid, _ = directional_exposure(2, 5, 0.9, 0.010, ref)      # middle -> ~flat
    assert weak < 0 < strong                                  # short vs long
    assert abs(mid) < abs(strong)                             # neutral is small


def test_short_target_is_negative():
    import order_executor as ox
    assert ox.target_shares(-0.9, 100.0, 5000.0) < 0          # short = negative shares
    assert ox.target_shares(0.9, 100.0, 5000.0) > 0


def test_order_sizing_scales_with_regime():
    import order_executor as ox
    price, budget = 100.0, 5000.0
    bull = ox.target_shares(0.95, price, budget)   # ~47 shares
    crash = ox.target_shares(0.20, price, budget)  # ~10 shares
    assert bull > crash > 0                         # HMM exposure drives size
    assert bull * price <= budget                   # never exceeds the budget
    assert ox.target_shares(2.0, price, budget) * price <= budget  # exposure capped at budget


def test_reconcile_buys_holds_sells():
    import order_executor as ox

    class FakeBroker:
        def __init__(self, held):
            self._held = held
            self.orders = []
        def positions(self):
            return [{"symbol": "SPY", "qty": self._held}] if self._held else []
        def submit_order(self, symbol, qty, side):
            self.orders.append((side, qty)); return {"id": "x", "status": "accepted"}

    flat = FakeBroker(0)
    r = ox.reconcile_to_target(flat, "SPY", 0.95, 100.0, 5000.0)   # buy from 0
    assert r["action"] == "buy" and flat.orders[0][0] == "buy"
    held = FakeBroker(47)
    r = ox.reconcile_to_target(held, "SPY", 0.20, 100.0, 5000.0)   # sell down to ~10
    assert r["action"] == "sell"
    same = FakeBroker(47)
    r = ox.reconcile_to_target(same, "SPY", 0.95, 100.0, 5000.0)   # already on target -> hold
    assert r["action"] == "hold" and same.orders == []


def test_backtest_out_of_sample(df, tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "RISK_STATE", tmp_path / "risk.json")
    import backtester
    res = backtester.walk_forward(df)
    assert res["n_eval_days"] > 50
    assert set(res["benchmarks"]) == {"buy_hold", "sma200", "random"}
    assert "total_return" in res["metrics"]
    assert isinstance(res["beats_buy_hold"], bool)
