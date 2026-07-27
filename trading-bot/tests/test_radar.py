"""Verification for the portfolio risk radar -- the component allowed to act instantly.

The single most important property: it can ONLY take risk off. Everything else in the
system is gated by a walk-forward and a holdout; this one is not, so its authority is
deliberately one-directional. If these tests pass, an unvalidated radar signal can cost
you upside but cannot enlarge a position.

Needs pandas/numpy but not hmmlearn, so it runs anywhere. Run: pytest -q"""
import sys
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import risk_radar

IDX = pd.date_range("2026-01-01", periods=400, freq="h", tz="UTC")


def frame(rets, vols=None, start=100.0):
    close = start * np.exp(np.cumsum(rets))
    rng = np.random.default_rng(1)
    return pd.DataFrame({"open": close, "high": close * 1.001, "low": close * 0.999,
                         "close": close,
                         "volume": vols if vols is not None
                         else rng.integers(1_000_000, 2_000_000, len(rets)).astype(float)},
                        index=IDX)


@pytest.fixture
def calm():
    rng = np.random.default_rng(0)
    return {f"S{i}": frame(rng.normal(0, 0.004, 400)) for i in range(5)}


@pytest.fixture
def correlated():
    rng = np.random.default_rng(2)
    shock = rng.normal(0, 0.03, 400)          # one common driver = crisis signature
    return {f"S{i}": frame(shock + rng.normal(0, 0.001, 400)) for i in range(5)}


# ---------------------------------------------------------------- the core guarantee
def test_multiplier_can_never_exceed_one(calm, correlated):
    for bars in (calm, correlated):
        for weak in (None, 0.0, 0.5, 1.0):
            r = risk_radar.assess(bars, weak_share=weak)
            assert 0.0 <= r["multiplier"] <= 1.0, r


def test_calm_market_does_not_throttle(calm):
    r = risk_radar.assess(calm, weak_share=0.0)
    assert r["level"] == risk_radar.CALM
    assert r["multiplier"] == 1.0


def test_correlated_shock_reduces_risk(correlated, calm):
    hot = risk_radar.assess(correlated, weak_share=0.0)
    cool = risk_radar.assess(calm, weak_share=0.0)
    assert hot["correlation"] > 0.8, hot["correlation"]
    assert hot["level"] != risk_radar.CALM
    assert hot["multiplier"] < cool["multiplier"], "a crisis signature must take risk off"


def test_weak_breadth_alone_escalates(calm):
    r = risk_radar.assess(calm, weak_share=0.9)
    assert r["level"] != risk_radar.CALM
    assert r["multiplier"] < 1.0


def test_escalates_to_the_worst_signal_not_the_average(calm, correlated):
    """Three mild warnings at once must not average out into 'fine'."""
    r = risk_radar.assess(correlated, weak_share=0.9)
    assert r["level"] in (risk_radar.STRESS, risk_radar.CRISIS)


def test_too_few_symbols_is_neutral_not_a_false_alarm():
    r = risk_radar.assess({"ONLY": frame(np.zeros(400))})
    assert r["multiplier"] == 1.0


# ---------------------------------------------------------------- pump handling
@pytest.fixture
def pumped(calm):
    rng = np.random.default_rng(3)
    rets = rng.normal(0, 0.004, 400)
    rets[-1] = 0.25                                   # violent last-bar move
    vols = rng.integers(1_000_000, 1_100_000, 400).astype(float)
    vols[-1] = 50_000_000                             # on 40x normal volume
    return dict(calm, PUMP=frame(rets, vols))


def test_pump_is_detected(pumped):
    r = risk_radar.assess(pumped, weak_share=0.0)
    assert "PUMP" in r["anomalies"]
    assert r["anomalies"]["PUMP"]["direction"] == "up"


def test_pump_caps_exposure_instead_of_chasing(pumped):
    """The whole point: an anomaly means hold LESS, never more. Buying into a detected
    pump makes you the exit liquidity."""
    r = risk_radar.assess(pumped, weak_share=0.0)
    capped, note = risk_radar.cap_for_anomaly(0.95, "PUMP", r)
    assert capped < 0.95 and note
    assert abs(capped) <= 0.31


def test_anomaly_cap_never_increases_a_position(pumped):
    r = risk_radar.assess(pumped, weak_share=0.0)
    for target in (0.0, 0.1, -0.1, 0.95, -0.95):
        capped, _ = risk_radar.cap_for_anomaly(target, "PUMP", r)
        assert abs(capped) <= abs(target) + 1e-9
        assert capped * target >= 0, "capping must never flip direction"


def test_quiet_symbols_are_untouched(pumped):
    r = risk_radar.assess(pumped, weak_share=0.0)
    capped, note = risk_radar.cap_for_anomaly(0.95, "S0", r)
    assert capped == 0.95 and note is None


# ---------------------------------------------------------------- diversification
CM = {"A": {"A": 1.0, "B": 0.97, "C": -0.05},
      "B": {"A": 0.97, "B": 1.0, "C": -0.05},
      "C": {"A": -0.05, "B": -0.05, "C": 1.0}}


def test_correlated_same_direction_is_halved():
    adj, notes = risk_radar.diversify({"A": 0.9, "B": 0.9, "C": 0.8}, CM, 0.7)
    assert adj["A"] == 0.9, "the largest intended position is kept"
    assert adj["B"] == 0.45, "its correlated twin is cut"
    assert adj["C"] == 0.8, "an uncorrelated name is untouched"
    assert "B" in notes


def test_opposite_directions_are_not_penalised():
    adj, _ = risk_radar.diversify({"A": 0.9, "B": -0.9}, CM, 0.7)
    assert adj["A"] == 0.9 and adj["B"] == -0.9, "a hedge is not a concentration"


def test_diversify_never_increases_a_target():
    targets = {"A": 0.9, "B": 0.9, "C": 0.8}
    adj, _ = risk_radar.diversify(targets, CM, 0.7)
    for k, v in targets.items():
        assert abs(adj[k]) <= abs(v) + 1e-9


def test_missing_correlation_data_is_a_no_op():
    targets = {"A": 0.9, "B": 0.9}
    assert risk_radar.diversify(targets, {}, 0.7)[0] == targets
    assert risk_radar.diversify(targets, CM, None)[0] == targets


def test_flat_targets_stay_flat():
    adj, _ = risk_radar.diversify({"A": 0.0, "B": 0.9}, CM, 0.7)
    assert adj["A"] == 0.0
