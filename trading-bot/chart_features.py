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
  weak      classical chart PATTERNS -- head and shoulders, double tops, triangles,
            flags. The serious study (Lo-Mamaysky-Wang, Journal of Finance 2000) found
            some statistical content, weak and largely arbitraged away since. They are
            IMPLEMENTED anyway, in chart_patterns.py, because "weak evidence" is an
            argument for testing something, not for refusing to build it -- that is what
            the walk-forward gate is for. It gets to answer the question for THIS system.
  none      Elliott waves, Fibonacci retracements, floor-trader pivots. No credible
            out-of-sample evidence. Present anyway (fib_position, wave_position,
            pivot_dist) by explicit request, implemented in the ONLY honest form -- as
            non-repainting numbers off CONFIRMED pivots / the previous bar, so the
            walk-forward gate gets to reject them for THIS system instead of a hand-drawn
            line deciding. MACD, EMA slope and Bollinger %B are just the standard indicator
            forms of the trend / mean-reversion / volatility facts already listed above.

CORE RULE, same as feature_engineering: no look-ahead. Every value at bar t uses only
bars <= t. Every rolling window here looks backward; nothing is shifted forward. This is
enforced by tests/test_chart_features.py for EVERY feature, not just some."""
import numpy as np
import pandas as pd

import chart_patterns

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


# ---------------------------------------------------------------- indicators (evidence: moderate)
def ema(series, n):
    """Exponential moving average -- weights recent bars more than the SMA. Backward only."""
    return series.astype(float).ewm(span=n, adjust=False).mean()


def ema_slope(df, n=21, k=10):
    """Slope of an EMA, ATR-scaled. Reacts faster than the SMA slope in ma_slope()."""
    e = ema(df["close"], n)
    return (e - e.shift(k)) / (atr(df, n=14) + EPS)


def macd(df, fast=12, slow=26, signal=9):
    """MACD histogram (line - signal line), ATR-normalized so it compares across a $90k BTC
    and a $30 ETF. Signed: >0 momentum turning up, <0 turning down. Standard 12/26/9,
    backward only -- this is 'momentum' as the chart-reader's favourite number."""
    close = df["close"].astype(float)
    line = ema(close, fast) - ema(close, slow)
    sig = line.ewm(span=signal, adjust=False).mean()
    return (line - sig) / (atr(df, n=14) + EPS)


def bollinger_b(df, n=20, k=2.0):
    """Bollinger %B mapped to [-1, +1]: where price sits BETWEEN the bands (-1 lower band,
    +1 upper). squeeze() gives band WIDTH, this gives POSITION -- the two together are the
    whole Bollinger picture as numbers instead of three drawn lines."""
    close = df["close"].astype(float)
    mid = close.rolling(n).mean()
    sd = close.rolling(n).std()
    span = (2 * k * sd).replace(0, np.nan)
    return (((close - (mid - k * sd)) / span) * 2 - 1).clip(-1, 1)


def pivot_dist(df):
    """Distance from the close to the classical floor-trader pivot P=(H+L+C)/3 of the
    PREVIOUS bar (shift(1) -> non-repainting), ATR-scaled. Signed: + above the pivot
    (bullish bias), - below. 'Pivot points' as one number, not five drawn levels."""
    high, low, close = df["high"].astype(float), df["low"].astype(float), df["close"].astype(float)
    p = (high.shift(1) + low.shift(1) + close.shift(1)) / 3
    return (close - p) / (atr(df, n=14) + EPS)


# ---------------------------------------------------------------- swing structure (evidence: none)
def _last_confirmed_levels(df):
    """Step series of the most recent CONFIRMED pivot-high and pivot-low price. Each level
    updates ONLY at that pivot's confirmation bar, so it can never repaint."""
    piv = chart_patterns.pivots(df)
    n = len(df)
    hi, lo = np.full(n, np.nan), np.full(n, np.nan)
    events = sorted((p[1], p[2], p[3]) for p in piv)        # (confirm_bar, price, kind)
    last_hi = last_lo = np.nan
    ei = 0
    for t in range(n):
        while ei < len(events) and events[ei][0] <= t:
            _, price, kind = events[ei]
            if kind > 0:
                last_hi = price
            else:
                last_lo = price
            ei += 1
        hi[t], lo[t] = last_hi, last_lo
    return pd.Series(hi, index=df.index), pd.Series(lo, index=df.index)


def fib_position(df):
    """Where the close sits inside the last CONFIRMED swing (low..high), mapped to [-1, +1]:
    +1 at the swing high, -1 at the swing low, ~0 near the 50% retracement. The Fibonacci
    LEVELS have no out-of-sample edge; this exposes 'how far has the move retraced' as a
    testable number so the walk-forward judges it, not folklore. Non-repainting via the
    confirmed-pivot swing."""
    hi, lo = _last_confirmed_levels(df)
    close = df["close"].astype(float)
    span = (hi - lo).replace(0, np.nan)
    return (((close - lo) / span) * 2 - 1).clip(-1, 1)


def wave_position(df):
    """Experimental Elliott-inspired swing read, evidence tier NONE. +1 when the last
    confirmed highs AND lows are both rising (impulse up), -1 when both fall, 0 mixed.
    Non-repainting (confirmed pivots only). Present so 'wave structure' is a number the
    gate can accept or reject, not a hand-drawn count that changes every bar."""
    highs, lows = chart_patterns._split(chart_patterns.pivots(df))
    n = len(df)

    def step_dir(seq):
        arr = np.zeros(n)
        prev = last = np.nan
        for p in sorted(seq, key=lambda x: x[1]):
            c = p[1]
            if c >= n:
                continue
            prev, last = last, p[2]
            arr[c:] = 0.0 if np.isnan(prev) else (1.0 if last > prev else (-1.0 if last < prev else 0.0))
        return arr

    return pd.Series((step_dir(highs) + step_dir(lows)) / 2.0, index=df.index)


# ---------------------------------------------------------------- combined decision vote
def _chart_votes(df):
    """The five component votes behind chart_bias, each signed [-1, +1]. The column NAMES are
    the human labels shown per trade, so 'which chart property drove this side' is answerable
    down to the single indicator. Non-repainting (every input is). NaN = no vote."""
    v = pd.DataFrame(index=df.index)
    v["Trend"] = np.tanh(ema_slope(df))                       # EMA-Slope: Richtung des Trends
    v["MACD"] = np.tanh(macd(df))                             # Momentum
    v["Muster"] = chart_patterns.pattern_score(df).clip(-1, 1)   # H&S / Doppeltop / Dreieck / Flagge / Bruch
    v["RSI-Div"] = chart_patterns.rsi_divergence(df)          # Divergenz Kurs vs. RSI
    v["Range"] = range_pos(df)                                # Position im Donchian-Kanal (S/R)
    return v


def chart_bias_series(df):
    """The whole toolkit distilled into ONE signed [-1, +1] directional vote per bar -- the
    module's answer to 'let the chart analysis DECIDE the side'. The five component votes
    (_chart_votes) are equal-weighted; the mean is the bias. The research loop tunes how hard
    this STEERS size (allocation.chart_min), not fifty coefficients hidden here."""
    return _chart_votes(df).mean(axis=1, skipna=True).fillna(0.0).clip(-1, 1)


def chart_bias(df):
    """Scalar chart-analysis vote for the latest bar (see chart_bias_series)."""
    s = chart_bias_series(df)
    return float(s.iloc[-1]) if len(s) else 0.0


def chart_decision(df):
    """(bias, parts) in ONE pass: the combined [-1,+1] vote AND its per-component breakdown for
    the latest bar -- so every trade can document WHICH chart property decided it and how
    strongly (e.g. {'Muster': -0.58, 'Range': -0.40, ...}). parts is sorted by |contribution|,
    strongest first. This is what turns the chart 'reason' from one opaque number into an
    auditable per-indicator record. Computed once so the live loop pays the pattern detectors
    only a single time per symbol."""
    votes = _chart_votes(df)
    if not len(votes):
        return 0.0, {}
    last = votes.iloc[-1]
    bias = float(np.clip(last.mean(), -1, 1)) if last.notna().any() else 0.0
    parts = {k: round(float(x), 3) for k, x in last.items() if pd.notna(x)}
    return bias, dict(sorted(parts.items(), key=lambda kv: -abs(kv[1])))


# ---------------------------------------------------------------- registry
BUILDERS = {
    # classical multi-bar formations (double top, head & shoulders, triangles, flags,
    # divergences) live in chart_patterns.py -- non-repainting, see its docstring
    **chart_patterns.BUILDERS,
    "trend_strength": trend_strength,
    "ma_slope": ma_slope,
    "ema_slope": ema_slope,
    "macd": macd,
    "bollinger_b": bollinger_b,
    "pivot_dist": pivot_dist,
    "fib_position": fib_position,
    "wave_position": wave_position,
    "chart_bias": chart_bias_series,
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
    # classical chart patterns as detectors. "patterns" keeps the three most structural
    # ones; "patterns_wide" adds the rest and is the most overfitting-prone set here --
    # 9 dimensions on a 7-state Gaussian HMM is a lot of parameters for the data.
    "patterns":   CORE + ["structure_break", "double_pattern", "head_shoulders"],
    "patterns_wide": CORE + ["structure_break", "double_pattern", "head_shoulders",
                             "triangle", "flag", "rsi_divergence"],
    "combo":      CORE + ["trend_strength", "range_pos", "pattern_score"],
    # indicator sets covering the classic chart-analysis toolkit (MACD, EMA, Bollinger %B,
    # RSI, pivots, Fibonacci). "full" is the widest -- 9 dims on a Gaussian HMM is the most
    # overfitting-prone set here; it exists so the walk-forward can PROVE that, not assume it.
    "indicators": CORE + ["macd", "rsi", "bollinger_b"],
    "classic":    CORE + ["ema_slope", "macd", "rsi", "bollinger_b", "range_pos", "pivot_dist"],
    "full":       CORE + ["trend_strength", "macd", "bollinger_b", "range_pos",
                          "pattern_score", "fib_position"],
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

    # the combined decision vote must stay bounded and be a real directional signal
    cb = chart_bias_series(df).dropna()
    assert cb.between(-1, 1).all(), "chart_bias out of [-1,1]"
    assert (cb != 0).any(), "chart_bias never fires -- vote is dead"
    # the per-trade breakdown must name every component and its bias must match chart_bias
    bias, parts = chart_decision(df)
    assert -1 <= bias <= 1 and set(parts) <= set(_chart_votes(df).columns), (bias, parts)
    assert abs(bias - float(chart_bias_series(df).iloc[-1])) < 1e-9, "decision bias != chart_bias"
    print(f"chart_decision ok: bias {bias:+.2f} · Teile {parts}")
    print(f"chart_features ok: {len(BUILDERS)} Features, {len(FEATURE_SETS)} Sets, "
          f"kein Look-Ahead")
