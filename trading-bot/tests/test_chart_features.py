"""Verification for the chart-analysis features.

The non-negotiable one is look-ahead freedom, tested for EVERY feature individually
rather than for the set as a whole: a single leaking column would make every backtest
that uses its set silently optimistic, and the whole promotion gate would then be
approving a fantasy.

Second: a model must only ever be scored with the columns it was TRAINED on. Feature
sets are a tunable parameter, so a mismatch is a real reachable state, not a theoretical
one -- and it would feed the Gaussians the wrong dimensions without raising anything.

No hmmlearn needed. Run: pytest -q"""
import sys
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import chart_features as cf
import market_data
from feature_engineering import build_features, feature_cols, FEATURE_COLS


@pytest.fixture(scope="module")
def df():
    d = market_data.get_daily_bars("SPY", days=800, force_synthetic=True)
    d.attrs["symbol"] = "SPY"
    return d


ALL_FEATURES = sorted(cf.BUILDERS)


def test_synthetic_bars_are_valid_ohlc(df):
    """high/low must bracket BOTH open and close. The generator once derived them from
    close alone, which produced impossible bars and made bar-shape features untestable."""
    assert (df["high"] >= df[["open", "close"]].max(axis=1) - 1e-9).all()
    assert (df["low"] <= df[["open", "close"]].min(axis=1) + 1e-9).all()
    assert (df["high"] >= df["low"]).all()


# ---------------------------------------------------------------- look-ahead
@pytest.mark.parametrize("name", ALL_FEATURES)
def test_feature_has_no_look_ahead(df, name):
    """Recomputing on a truncated history must not change any earlier value. If it does,
    the feature is reading bars that had not happened yet."""
    full = cf.compute(df, [name])[name]
    partial = cf.compute(df.iloc[:400], [name])[name]
    common = full.index.intersection(partial.index)
    assert len(common) > 100, "not enough overlap to judge"
    a, b = full.loc[common].values, partial.loc[common].values
    mask = ~(np.isnan(a) | np.isnan(b))
    assert mask.sum() > 50
    assert np.allclose(a[mask], b[mask], atol=1e-9), f"LOOK-AHEAD LEAK in {name}"


@pytest.mark.parametrize("set_name", sorted(cf.FEATURE_SETS))
def test_feature_set_has_no_look_ahead(df, set_name):
    full = build_features(df, feature_set=set_name)
    partial = build_features(df.iloc[:500], feature_set=set_name)
    common = full.index.intersection(partial.index)
    assert len(common) > 50, set_name
    assert np.allclose(full.loc[common].values, partial.loc[common].values, atol=1e-9), \
        f"LOOK-AHEAD LEAK in set {set_name}"


# ---------------------------------------------------------------- sanity of the values
@pytest.mark.parametrize("set_name", sorted(cf.FEATURE_SETS))
def test_sets_are_finite_and_complete(df, set_name):
    f = build_features(df, feature_set=set_name)
    assert list(f.columns) == feature_cols(set_name)
    assert len(f) > 100, f"{set_name} left too little history"
    assert np.isfinite(f.values).all(), f"non-finite values in {set_name}"


def test_every_set_keeps_the_core_features():
    for name, cols in cf.FEATURE_SETS.items():
        assert cols[:3] == FEATURE_COLS, name


def test_default_is_unchanged_core(df):
    assert list(build_features(df).columns) == FEATURE_COLS
    assert feature_cols(None) == FEATURE_COLS
    assert feature_cols("nonexistent-set") == FEATURE_COLS


def test_bounded_features_stay_in_range(df):
    f = cf.compute(df, ["range_pos", "rsi", "close_pos_in_bar", "squeeze", "body_ratio"])
    for col in ("range_pos", "rsi", "close_pos_in_bar", "squeeze"):
        v = f[col].dropna()
        assert v.between(-1.0001, 1.0001).all(), f"{col} outside [-1, 1]"
    # body_ratio <= 1 only holds for VALID OHLC (high/low bracketing open and close).
    # It is deliberately not clipped: a value above 1 means the data feed is broken and
    # should surface, not be silently hidden.
    b = f["body_ratio"].dropna()
    assert b.between(-0.0001, 1.0001).all(), "invalid OHLC or leaking feature"


def test_features_are_deterministic(df):
    a = cf.compute(df, ALL_FEATURES)
    b = cf.compute(df, ALL_FEATURES)
    assert a.equals(b)


# ---------------------------------------------------------------- do they mean anything
def _bars(close, high=None, low=None, open_=None, volume=None):
    n = len(close)
    idx = pd.date_range("2026-01-01", periods=n, freq="D", tz="UTC")
    return pd.DataFrame({
        "open": open_ if open_ is not None else close,
        "high": high if high is not None else close * 1.005,
        "low": low if low is not None else close * 0.995,
        "close": close,
        "volume": volume if volume is not None else np.full(n, 1e6),
    }, index=idx)


def test_range_pos_marks_highs_and_lows():
    rising = _bars(np.linspace(100, 200, 120))
    falling = _bars(np.linspace(200, 100, 120))
    # not exactly +/-1: the channel is built from highs/lows, which bracket the close
    assert cf.range_pos(rising).dropna().iloc[-1] > 0.8, "at a new high it must read near +1"
    assert cf.range_pos(falling).dropna().iloc[-1] < -0.8, "at a new low it must read near -1"


def test_trend_strength_signs_with_the_trend():
    up = cf.trend_strength(_bars(np.linspace(100, 200, 200))).dropna().iloc[-1]
    down = cf.trend_strength(_bars(np.linspace(200, 100, 200))).dropna().iloc[-1]
    assert up > 0 > down


def test_close_pos_in_bar_is_the_quantified_hammer():
    """A hammer = long lower wick, close near the top of the range."""
    close = np.full(60, 100.0)
    low = np.full(60, 100.0); low[-1] = 90.0        # long lower wick on the last bar
    high = np.full(60, 100.5)
    v = cf.close_pos_in_bar(_bars(close, high=high, low=low)).iloc[-1]
    assert v > 0.8, f"hammer should read near +1, got {v}"


def test_body_ratio_identifies_a_doji():
    close = np.full(60, 100.0)
    open_ = np.full(60, 100.0)                       # open == close -> no body
    v = cf.body_ratio(_bars(close, open_=open_, high=close * 1.02, low=close * 0.98)).iloc[-1]
    assert v < 0.05, f"doji should read near 0, got {v}"


def test_squeeze_is_low_when_the_market_is_coiled():
    rng = np.random.default_rng(0)
    noisy = 100 * np.exp(np.cumsum(rng.normal(0, 0.02, 200)))
    calm = np.concatenate([noisy, noisy[-1] * (1 + rng.normal(0, 0.0005, 120))])
    v = cf.squeeze(_bars(calm)).dropna().iloc[-1]
    assert v < 0, f"a quiet stretch after a noisy one should rank low, got {v}"


# ---------------------------------------------------------------- classical patterns
def _series_from(points, per=8):
    """Build a price path through a list of turning points, so a real formation exists."""
    seg = []
    for a, b in zip(points, points[1:]):
        seg.append(np.linspace(a, b, per, endpoint=False))
    close = np.concatenate(seg + [np.array([points[-1]])])
    return _bars(close, high=close * 1.002, low=close * 0.998,
                 open_=np.concatenate([[close[0]], close[:-1]]))


def test_pivots_are_append_only_and_lagged():
    """The non-repainting contract: confirm = index + RIGHT, and extending the history
    never alters or removes a pivot that was already emitted. A ZigZag fails this."""
    import chart_patterns as cp
    d = _series_from([100, 120, 105, 125, 100, 130, 95, 128, 90, 135])
    piv = cp.pivots(d)
    assert piv, "no pivots detected"
    for idx, confirm, price, kind in piv:
        assert confirm == idx + cp.RIGHT
        assert kind in (1, -1)
    shorter = cp.pivots(d.iloc[:len(d) - 20])
    assert shorter == piv[:len(shorter)], "extending history rewrote an earlier pivot"


def test_double_top_is_detected_and_is_bearish():
    import chart_patterns as cp
    # two peaks at ~the same level, a trough between, then a break below the trough
    d = _series_from([100, 130, 110, 129, 95, 90])
    s = cp.double_pattern(d)
    assert (s < 0).any(), "a double top must produce a bearish signal"


def test_double_bottom_is_detected_and_is_bullish():
    import chart_patterns as cp
    d = _series_from([130, 100, 120, 101, 135, 140])
    s = cp.double_pattern(d)
    assert (s > 0).any(), "a double bottom must produce a bullish signal"


def test_head_and_shoulders_is_detected_and_is_bearish():
    import chart_patterns as cp
    # left shoulder 120, head 140, right shoulder 121, then break the ~105 neckline
    d = _series_from([100, 120, 105, 140, 106, 121, 95, 90])
    s = cp.head_shoulders(d)
    assert (s < 0).any(), "head & shoulders must produce a bearish signal"


def test_inverse_head_and_shoulders_is_bullish():
    import chart_patterns as cp
    d = _series_from([140, 120, 135, 100, 134, 121, 145, 150])
    s = cp.head_shoulders(d)
    assert (s > 0).any(), "inverse head & shoulders must produce a bullish signal"


def test_structure_break_signs_correctly():
    import chart_patterns as cp
    up = _series_from([100, 110, 105, 130, 128, 145])
    down = _series_from([145, 130, 135, 110, 112, 95])
    assert cp.structure_break(up).iloc[-1] > 0
    assert cp.structure_break(down).iloc[-1] < 0


def test_pattern_signals_stay_bounded(df):
    import chart_patterns as cp
    for name, fn in cp.BUILDERS.items():
        v = fn(df)
        assert v.between(-1.0001, 1.0001).all(), f"{name} outside [-1, 1]"


def test_gap_is_zero_without_gaps():
    close = np.linspace(100, 110, 50)
    g = cf.gap(_bars(close, open_=np.concatenate([[100], close[:-1]]))).dropna()
    assert np.allclose(g.values, 0, atol=1e-9)
