"""Chart analysis as NUMBERS -- the honest form of technical analysis.

A "hammer" is a statement about where the close sits inside the bar's range. A
"resistance level" is a position in the Donchian channel. A "consolidation before the
breakout" is Bollinger bandwidth in a low percentile. Expressed as a number, each of
these is measurable, look-ahead free and can be judged by the walk-forward. Expressed as
a picture, it is interpretation -- and interpretation is what the whole gate exists to
keep out of the order path.

EVIDENCE TIERS, stated honestly so nothing here gets more credit than it has earned:

  strong    volatility clustering (Engle 1982, Bollerslev 1986) -- vol is autocorrelated;
            this is the single best-replicated fact in the list, and it is what the HMM
            already exploits.
  strong    time-series momentum / trend (Moskowitz-Ooi-Pedersen 2012), cross-sectional
            momentum (Jegadeesh-Titman 1993). Replicated across decades and asset classes,
            though heavily crowded by now.
  moderate  short-horizon mean reversion (Lo-MacKinlay 1988), volume-volatility relation
            (Karpoff 1987).
  weak      classical chart PATTERNS -- head and shoulders, flags, and friends. The
            serious study (Lo-Mamaysky-Wang, Journal of Finance 2000) found some
            statistical content, weak and largely arbitraged away since.
  none      Elliott waves, Fibonacci retracements. No credible out-of-sample evidence.
            Deliberately absent from this module.

CORE RULE, same as feature_engineering: no look-ahead. Every value at bar t uses only
bars <= t. Every rolling window here looks backward; nothing is shifted forward. This is
enforced by tests/test_chart_features.py for EVERY feature, not just some."""
import numpy as np
import pandas as pd

EPS = 1e-12


# ---------------------------------------------------------------- building blocks
def true_range(df):
    """Max of (high-low), |high-prev_close|, |low-prev_close|. Uses the PREVIOUS close."""
    high, low, close = df["high"].astype(float), df["low"].astype(float), df["close"].astype(float)
    prev = close.shift(1)
    return pd.concat([high - low, (high - prev).abs(), (low - prev).abs()], axis=1).max(axis=1)


def atr(df, n=14):
    return true_range(df).rolling(n).mean()


# ---------------------------------------------------------------- trend (evidence: strong)
def trend_strength(df, n=50):
    """Distance from the moving average, scaled by ATR so it is comparable across a
    $90k BTC and a $30 ETF. This is 'is price extended' expressed as a number."""
    close = df["close"].astype(float)
    a = atr(df, n=14)
    return (close - close.rolling(n).mean()) / (a + EPS)


def ma_slope(df, n=50, k=10):
    """Is the average itself rising, and how fast -- direction rather than distance."""
    sma = df["close"].astype(float).rolling(n).mean()
    return (sma - sma.shift(k)) / (atr(df, n=14) + EPS)


# ---------------------------------------------------------------- range (evidence: moderate)
def range_pos(df, n=20):
    """Position in the Donchian channel, mapped to [-1, +1]. -1 = at the n-bar low,
    +1 = at the n-bar high. This is what 'support and resistance' actually is once you
    stop drawing lines on it: where price sits inside its own recent range."""
    close = df["close"].astype(float)
    lo = df["low"].astype(float).rolling(n).min()
    hi = df["high"].astype(float).rolling(n).max()
    span = (hi - lo).replace(0, np.nan)
    return ((close - lo) / span) * 2 - 1


def rsi(df, n=14):
    """Wilder's RSI, rescaled to [-1, +1]. Short-horizon mean-reversion proxy."""
    delta = df["close"].astype(float).diff()
    up = delta.clip(lower=0).ewm(alpha=1 / n, adjust=False).mean()
    down = (-delta.clip(upper=0)).ewm(alpha=1 / n, adjust=False).mean()
    rs = up / (down + EPS)
    return (100 - 100 / (1 + rs)) / 50 - 1


# ---------------------------------------------------------------- volatility (evidence: strong)
def atr_norm(df, n=14):
    """ATR relative to price -- volatility on a scale that compares across assets."""
    return atr(df, n) / (df["close"].astype(float) + EPS)


def parkinson(df, n=20):
    """High-low range volatility estimator. Uses the intrabar range, so it is roughly
    5x more efficient than close-to-close for the same window (Parkinson 1980)."""
    hl = np.log(df["high"].astype(float) / (df["low"].astype(float) + EPS))
    return np.sqrt((hl ** 2).rolling(n).mean() / (4 * np.log(2)))


def vol_of_vol(df, n=20):
    """Is volatility itself unstable -- the regime-change tell the HMM is looking for."""
    r = np.log(df["close"].astype(float) / df["close"].astype(float).shift(1))
    rv = r.rolling(n).std()
    return rv.rolling(n).std() / (rv.rolling(n).mean() + EPS)


def squeeze(df, n=20, lookback=100):
    """Bollinger bandwidth as a backward percentile rank. Low = the market is coiled.
    This is 'consolidation before a breakout' as a number instead of a drawing."""
    close = df["close"].astype(float)
    width = (close.rolling(n).std() * 2) / (close.rolling(n).mean() + EPS)
    return width.rolling(lookback).rank(pct=True) * 2 - 1


# ---------------------------------------------------------------- bar shape (evidence: weak)
def close_pos_in_bar(df):
    """Where inside its own range did the bar close, in [-1, +1]. A 'hammer' is a high
    value with a long lower wick; a 'shooting star' is the mirror image. Quantified, it
    can be tested -- which is the point, because the evidence for candlestick patterns
    is weak and this lets the walk-forward say so rather than folklore."""
    high, low, close = df["high"].astype(float), df["low"].astype(float), df["close"].astype(float)
    span = (high - low).replace(0, np.nan)
    return ((close - low) / span) * 2 - 1


def body_ratio(df):
    """|close-open| / range. Near 0 is a doji (indecision), near 1 a full-bodied bar."""
    high, low = df["high"].astype(float), df["low"].astype(float)
    span = (high - low).replace(0, np.nan)
    return (df["close"].astype(float) - df["open"].astype(float)).abs() / span


def gap(df):
    """Open versus the previous close. On crypto this is near zero (24/7, no gaps);
    on equities it carries the overnight news the bot never reads."""
    prev = df["close"].astype(float).shift(1)
    return (df["open"].astype(float) - prev) / (prev + EPS)


# ---------------------------------------------------------------- volume (evidence: moderate)
def obv_slope(df, n=20):
    """On-balance volume trend: is volume accumulating with up-moves or down-moves.
    Normalized by its own recent scale so it stays comparable across symbols."""
    close = df["close"].astype(float)
    direction = np.sign(close.diff()).fillna(0)
    obv = (direction * df["volume"].astype(float)).cumsum()
    change = obv - obv.shift(n)
    return change / (df["volume"].astype(float).rolling(n).mean() * n + EPS)


def volume_trend_agree(df, n=20):
    """Rolling correlation of returns and volume changes. Positive = moves come with
    participation; negative = the move is thinning out (Karpoff 1987)."""
    r = df["close"].astype(float).pct_change()
    v = df["volume"].astype(float).pct_change()
    return r.rolling(n).corr(v)


# ---------------------------------------------------------------- registry
BUILDERS = {
    "trend_strength": trend_strength,
    "ma_slope": ma_slope,
    "range_pos": range_pos,
    "rsi": rsi,
    "atr_norm": atr_norm,
    "parkinson": parkinson,
    "vol_of_vol": vol_of_vol,
    "squeeze": squeeze,
    "close_pos_in_bar": close_pos_in_bar,
    "body_ratio": body_ratio,
    "gap": gap,
    "obv_slope": obv_slope,
    "volume_trend_agree": volume_trend_agree,
}

# The HMM is a diagonal-covariance Gaussian mixture over states: every extra feature
# multiplies the parameters it has to estimate. Sets are kept deliberately small --
# a 7-state model on 13 features would fit the past beautifully and forecast nothing.
CORE = ["log_return", "realized_vol", "volume_z"]

FEATURE_SETS = {
    "core":       CORE,
    "trend":      CORE + ["trend_strength", "ma_slope", "range_pos"],
    "meanrev":    CORE + ["rsi", "range_pos", "close_pos_in_bar"],
    "volatility": CORE + ["atr_norm", "vol_of_vol", "squeeze"],
    "shape":      CORE + ["close_pos_in_bar", "body_ratio", "gap"],
    "broad":      CORE + ["trend_strength", "range_pos", "atr_norm", "obv_slope"],
}


def columns(feature_set):
    return list(FEATURE_SETS.get(feature_set, CORE))


def compute(df, names):
    """Extra (non-core) features by name. Returns a DataFrame aligned to df.index."""
    out = pd.DataFrame(index=df.index)
    for name in names:
        fn = BUILDERS.get(name)
        if fn is None:
            continue
        out[name] = fn(df)
    return out.replace([np.inf, -np.inf], np.nan)


if __name__ == "__main__":
    import market_data
    df = market_data.get_daily_bars("SPY", days=600, force_synthetic=True)
    extras = compute(df, list(BUILDERS))
    assert len(extras.columns) == len(BUILDERS), extras.columns

    # look-ahead self-test for EVERY feature: recomputing on a truncated history must
    # not change a single earlier value
    partial = compute(df.iloc[:400], list(BUILDERS))
    common = extras.index.intersection(partial.index)
    for col in extras.columns:
        a = extras.loc[common, col].values
        b = partial.loc[common, col].values
        mask = ~(np.isnan(a) | np.isnan(b))
        assert np.allclose(a[mask], b[mask], atol=1e-9), f"LOOK-AHEAD LEAK in {col}"

    for name, cols in FEATURE_SETS.items():
        assert cols[:3] == CORE, f"{name} must keep the core features"
    print(f"chart_features ok: {len(BUILDERS)} Features, {len(FEATURE_SETS)} Sets, "
          f"kein Look-Ahead")
