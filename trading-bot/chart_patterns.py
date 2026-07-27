"""Classical chart patterns as non-repainting detectors.

THE central problem, and the reason most implementations of this are quietly broken:

    A swing high at bar i is not KNOWN at bar i. You only know it once `right` further
    bars have failed to exceed it -- the information exists at bar i+right, not at i.
    Every ZigZag indicator repaints for exactly this reason: it redraws history as new
    bars arrive. Backtest a pattern detector built on repainting pivots and you are
    testing a strategy that reads the future. The equity curve looks wonderful and the
    live account never reproduces it.

Two rules keep this honest:

  1. Pivots are APPEND-ONLY. No collapsing of same-kind runs into "the most extreme
     one" -- that convenience step is what makes ZigZag repaint, because a higher high
     arriving later retroactively deletes the one you already acted on. Without it there
     is no strict alternation, so each detector searches for its shape among the pivots
     rather than assuming an alternating sequence. More work, causally honest.
  2. A pattern may only fire at a bar >= the confirmation index of EVERY pivot it uses,
     and the neckline break is then searched strictly forward from there.

tests/test_chart_features.py proves look-ahead freedom for each detector by recomputing
on truncated history -- an earlier value that changes is a leak.

Rules follow the standard published definitions (sources in the README):
  * double top/bottom: two extremes within `tol`, a counter pivot between them,
    confirmed by a close beyond that level. Common tolerance 2-6%; Bulkowski uses 6%.
  * head & shoulders: three same-kind extremes, middle the most extreme, outer two
    within `tol`; confirmed by a close through the neckline across the inner pivots.
  * triangles: ascending = flat top + rising bottoms, descending = flat bottom +
    falling tops, symmetric = both converging. Fires on the breakout.
  * flag: strong impulse, low-volatility drift, then continuation.

Signals are signed [-1, +1] (+ bullish, - bearish) and DECAY over HOLD bars, so the HMM
sees "a pattern completed recently" as a state rather than a one-bar spike it would
almost certainly ignore."""
import numpy as np
import pandas as pd

LEFT = RIGHT = 5          # pivot window; RIGHT is also the confirmation lag
HOLD = 20                 # bars a fired signal stays visible, decaying linearly
TOL = 0.03                # tolerance between the two comparable extremes
MAX_SPAN = 120            # a formation older than this is not a pattern any more
EPS = 1e-12


# ---------------------------------------------------------------- pivots
def pivots(df, left=LEFT, right=RIGHT):
    """Confirmed swing points, append-only: once emitted, a pivot NEVER changes.
    Returns (index, confirm, price, kind); kind +1 high / -1 low, confirm = index+right."""
    high = df["high"].astype(float).values
    low = df["low"].astype(float).values
    n = len(df)
    out = []
    for i in range(left, n - right):
        if high[i] >= high[i - left:i + right + 1].max():
            out.append((i, i + right, float(high[i]), 1))
        if low[i] <= low[i - left:i + right + 1].min():
            out.append((i, i + right, float(low[i]), -1))
    out.sort(key=lambda p: (p[0], -p[3]))
    return out


def _split(piv):
    return [p for p in piv if p[3] > 0], [p for p in piv if p[3] < 0]


def _between(seq, a, b):
    return [p for p in seq if a < p[0] < b]


def _emit(n, hits):
    """Turn (bar, signal) hits into a decaying series. Later hits overwrite earlier ones."""
    s = np.zeros(n)
    for bar, sig in sorted(hits):
        for j in range(HOLD):
            k = bar + j
            if k >= n:
                break
            s[k] = sig * (1 - j / HOLD)
    return s


def _break_bar(close, start, level, direction, limit=MAX_SPAN):
    """First bar >= start whose CLOSE breaks `level` in `direction` (+1 up / -1 down).
    Searches strictly forward -- the only place a pattern becomes actionable."""
    for b in range(start, min(len(close), start + limit)):
        if (direction > 0 and close[b] > level) or (direction < 0 and close[b] < level):
            return b
    return None


# ---------------------------------------------------------------- reversal patterns
def double_pattern(df, tol=TOL):
    """Double top (-1) and double bottom (+1). Volume is a STRENGTH modifier (the classic
    rule wants lower volume on the second peak) rather than a hard filter, which would
    make hits vanishingly rare."""
    piv = pivots(df)
    highs, lows = _split(piv)
    close = df["close"].astype(float).values
    vol = df["volume"].astype(float).values
    n = len(df)
    hits = []
    for seq, counter, sign in ((highs, lows, 1), (lows, highs, -1)):
        for a in range(len(seq) - 1):
            p1 = seq[a]
            for p2 in seq[a + 1:]:
                if p2[0] - p1[0] > MAX_SPAN:
                    break
                if abs(p2[2] - p1[2]) / (abs(p1[2]) + EPS) > tol:
                    continue
                mids = _between(counter, p1[0], p2[0])
                if not mids:
                    continue
                mid = min(mids, key=lambda p: p[2]) if sign > 0 else max(mids, key=lambda p: p[2])
                known = max(p1[1], mid[1], p2[1])       # every pivot confirmed and final
                if known >= n:
                    continue
                direction = -sign                        # top -> break down
                b = _break_bar(close, known, mid[2], direction)
                if b is None:
                    continue
                v1 = vol[max(0, p1[0] - 2):p1[0] + 3].mean()
                v2 = vol[max(0, p2[0] - 2):p2[0] + 3].mean()
                hits.append((b, direction * (1.0 if v2 < v1 else 0.6)))
                break                                    # one pattern per first extreme
    return pd.Series(_emit(n, hits), index=df.index)


def head_shoulders(df, tol=TOL):
    """Head & shoulders (-1) and inverse head & shoulders (+1). Three same-kind extremes,
    middle the most extreme, outer two within `tol`, neckline across the inner pivots."""
    piv = pivots(df)
    highs, lows = _split(piv)
    close = df["close"].astype(float).values
    n = len(df)
    hits = []
    for seq, counter, sign in ((highs, lows, 1), (lows, highs, -1)):
        pick = (lambda c: min(c, key=lambda p: p[2])) if sign > 0 else \
               (lambda c: max(c, key=lambda p: p[2]))
        for a in range(len(seq) - 2):
            ls = seq[a]
            done = False
            for bi in range(a + 1, len(seq) - 1):
                head = seq[bi]
                if head[0] - ls[0] > MAX_SPAN:
                    break
                if not (head[2] > ls[2] if sign > 0 else head[2] < ls[2]):
                    continue
                for rs in seq[bi + 1:]:
                    if rs[0] - ls[0] > MAX_SPAN * 1.5:
                        break
                    if not (head[2] > rs[2] if sign > 0 else head[2] < rs[2]):
                        continue
                    if abs(rs[2] - ls[2]) / (abs(ls[2]) + EPS) > tol:
                        continue
                    t1s = _between(counter, ls[0], head[0])
                    t2s = _between(counter, head[0], rs[0])
                    if not t1s or not t2s:
                        continue
                    t1, t2 = pick(t1s), pick(t2s)
                    known = max(ls[1], t1[1], head[1], t2[1], rs[1])
                    if known >= n:
                        continue
                    slope = (t2[2] - t1[2]) / max(1, (t2[0] - t1[0]))
                    direction = -sign
                    for k in range(known, min(n, known + MAX_SPAN)):
                        level = t1[2] + slope * (k - t1[0])
                        if (direction < 0 and close[k] < level) or (direction > 0 and close[k] > level):
                            hits.append((k, float(direction)))
                            break
                    done = True
                    break
                if done:
                    break
    return pd.Series(_emit(n, hits), index=df.index)


# ---------------------------------------------------------------- continuation patterns
def triangle(df):
    """Ascending (+1), descending (-1), symmetric (0.5, sign of the breakout).
    Fits two highs and two lows around them; a near-flat side plus a converging side is
    the classic definition. Fires on the close beyond the flat boundary."""
    piv = pivots(df)
    all_highs, all_lows = _split(piv)
    close = df["close"].astype(float).values
    n = len(df)
    hits = []
    for a in range(len(all_highs) - 1):
        highs = all_highs[a:a + 2]
        lows = [p for p in all_lows if highs[0][0] < p[0] < highs[1][0] + MAX_SPAN][:2]
        if len(lows) < 2:
            continue
        quad = highs + lows
        if max(p[0] for p in quad) - min(p[0] for p in quad) > MAX_SPAN:
            continue
        h_slope = (highs[1][2] - highs[0][2]) / max(1, highs[1][0] - highs[0][0])
        l_slope = (lows[1][2] - lows[0][2]) / max(1, lows[1][0] - lows[0][0])
        scale = abs(highs[0][2]) + EPS
        flat = 0.0005                                    # "near flat" relative to price
        if abs(h_slope) / scale < flat and l_slope > 0:
            bias, level, direction = 1.0, highs[1][2], 1      # ascending
        elif abs(l_slope) / scale < flat and h_slope < 0:
            bias, level, direction = -1.0, lows[1][2], -1     # descending
        elif h_slope < 0 < l_slope:
            bias, level, direction = 0.5, highs[1][2], 1      # symmetric, upside break
        else:
            continue
        known = max(p[1] for p in quad)
        if known >= n:
            continue
        b = _break_bar(close, known, level, direction)
        if b is not None:
            hits.append((b, bias if direction > 0 else -abs(bias)))
    return pd.Series(_emit(n, hits), index=df.index)


def flag(df, impulse_bars=10, rest_bars=8, impulse_atr=2.0):
    """Flag / pennant: strong impulse, quiet drift, then continuation. Purely local --
    no pivots, so no confirmation lag beyond the rolling windows themselves."""
    close = df["close"].astype(float)
    n = len(df)
    tr = pd.concat([df["high"].astype(float) - df["low"].astype(float),
                    (df["high"].astype(float) - close.shift(1)).abs(),
                    (df["low"].astype(float) - close.shift(1)).abs()], axis=1).max(axis=1)
    atr = tr.rolling(14).mean()
    impulse = (close - close.shift(impulse_bars)) / (atr + EPS)
    rest_range = (close.rolling(rest_bars).max() - close.rolling(rest_bars).min()) / (atr + EPS)
    prior = impulse.shift(rest_bars)                     # impulse BEFORE the rest phase
    quiet = rest_range < 2.0
    up = (prior > impulse_atr) & quiet & (close > close.rolling(rest_bars).max().shift(1))
    down = (prior < -impulse_atr) & quiet & (close < close.rolling(rest_bars).min().shift(1))
    hits = [(int(i), 1.0) for i in np.flatnonzero(up.fillna(False).values)]
    hits += [(int(i), -1.0) for i in np.flatnonzero(down.fillna(False).values)]
    return pd.Series(_emit(n, hits), index=df.index)


def structure_break(df):
    """Break of structure: close beyond the most recent CONFIRMED swing. +1 above the
    last swing high, -1 below the last swing low. The simplest of these detectors, and
    the one with the least interpretation in it."""
    piv = pivots(df)
    close = df["close"].astype(float).values
    n = len(df)
    s = np.zeros(n)
    by_confirm = {}
    for idx, conf, price, kind in piv:
        by_confirm.setdefault(conf, []).append((price, kind))
    last_hi = last_lo = None
    for t in range(n):
        for price, kind in by_confirm.get(t, []):
            if kind > 0:
                last_hi = price
            else:
                last_lo = price
        if last_hi is not None and close[t] > last_hi:
            s[t] = 1.0
        elif last_lo is not None and close[t] < last_lo:
            s[t] = -1.0
    return pd.Series(s, index=df.index)


def rsi_divergence(df, n_rsi=14, window=40):
    """Price makes a higher high while RSI does not (bearish, -1), or a lower low while
    RSI does not (bullish, +1). Both legs are confirmed pivots, so both are knowable."""
    from chart_features import rsi as _rsi
    r = _rsi(df, n_rsi)
    highs, lows = _split(pivots(df))
    n = len(df)
    hits = []
    for seq, sign in ((highs, -1.0), (lows, 1.0)):
        for a in range(len(seq) - 1):
            p1, p2 = seq[a], seq[a + 1]
            if p2[0] - p1[0] > window or p2[1] >= n:
                continue
            r1, r2 = r.iloc[p1[0]], r.iloc[p2[0]]
            if np.isnan(r1) or np.isnan(r2):
                continue
            if sign < 0 and p2[2] > p1[2] and r2 < r1:          # higher high, weaker RSI
                hits.append((p2[1], sign))
            elif sign > 0 and p2[2] < p1[2] and r2 > r1:        # lower low, stronger RSI
                hits.append((p2[1], sign))
    return pd.Series(_emit(n, hits), index=df.index)


def pattern_score(df):
    """All detectors combined into one signed score -- useful as a single feature when
    the HMM cannot afford many dimensions."""
    parts = [double_pattern(df), head_shoulders(df), triangle(df), flag(df), structure_break(df)]
    return sum(parts) / len(parts)


BUILDERS = {
    "structure_break": structure_break,
    "double_pattern": double_pattern,
    "head_shoulders": head_shoulders,
    "triangle": triangle,
    "flag": flag,
    "rsi_divergence": rsi_divergence,
    "pattern_score": pattern_score,
}


if __name__ == "__main__":
    import market_data
    df = market_data.get_daily_bars("SPY", days=900, force_synthetic=True)
    piv = pivots(df)
    assert piv and all(p[1] == p[0] + RIGHT for p in piv), "confirmation lag missing"
    assert piv == sorted(piv, key=lambda p: (p[0], -p[3])), "pivots must be ordered"
    print(f"{len(piv)} Pivots (append-only), Bestaetigungs-Lag {RIGHT} Bars")

    for name, fn in BUILDERS.items():
        s = fn(df)
        full, part = s.values, fn(df.iloc[:600]).values
        m = min(len(full), len(part))
        assert np.allclose(full[:m], part[:m], atol=1e-9), f"LOOK-AHEAD LEAK in {name}"
        print(f"  {name:<16} Treffer: {int((s != 0).sum()):>4}  Spanne "
              f"[{s.min():.2f}, {s.max():.2f}]")
    print("chart_patterns self-check ok (nicht-repaintend, kein Look-Ahead)")
