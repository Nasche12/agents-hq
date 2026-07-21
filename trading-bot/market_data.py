"""Layer 0 -- data acquisition. Fetches historical daily bars from Alpaca (Data API v2)
via requests (no heavy SDK). Caches to disk so repeated backtests don't re-download.
WITHOUT keys -> a reproducible synthetic dataset (fixed seed) so the backtester and
tests run fully offline. Every real value comes from the API, never guessed; if the
API is unavailable it is honestly marked source='synthetic'."""
import time
from datetime import datetime, timedelta, timezone

import numpy as np
import pandas as pd

import settings

_DATA_URL = "https://data.alpaca.markets/v2/stocks/{sym}/bars"


# bars per US trading day, used to size synthetic data and tail() windows
_TF_PER_DAY = {"1Day": 1, "1Hour": 7, "30Min": 13, "15Min": 26, "5Min": 78}
_TF_FREQ = {"1Day": "B", "1Hour": "h", "30Min": "30min", "15Min": "15min", "5Min": "5min"}


def _stable_cache(symbol, timeframe):
    """One rolling file per symbol+timeframe that always holds the latest REAL bars."""
    return settings.CACHE_DIR / f"{symbol}_{timeframe}.parquet"


def _have_keys():
    return bool(settings.env("ALPACA_API_KEY") and settings.env("ALPACA_SECRET_KEY"))


def get_bars(symbol, days=504, timeframe="1Day", end=None, force_synthetic=False):
    """DataFrame [open,high,low,close,volume], DatetimeIndex (UTC), oldest first.
    timeframe: 1Day | 1Hour | 30Min | 15Min | 5Min (intraday -> more signals).

    Data policy:
      1. keys present -> ALWAYS fetch fresh from Alpaca and use that; persist it.
      2. Alpaca unreachable -> fall back to the last STORED real bars (never synthetic).
      3. only truly offline dev (no keys, no store) uses synthetic, flagged real=False.
    df.attrs['source'] = 'alpaca' | 'stored' | 'synthetic'; df.attrs['real'] = bool.
    force_synthetic=True is for the offline test suite only."""
    end = end or datetime.now(timezone.utc).date()
    start = end - timedelta(days=int(days * 1.5) + 10)  # buffer for weekends/holidays
    n_bars = days * _TF_PER_DAY.get(timeframe, 1)
    stable = _stable_cache(symbol, timeframe)

    if force_synthetic:
        return _tag(_synthetic(symbol, start, end, timeframe), "synthetic", False, n_bars)

    if _have_keys():
        df = _fetch_alpaca(symbol, start, end, timeframe)
        if df is not None and len(df):
            df.to_parquet(stable)                       # keep the latest real bars
            return _tag(df, "alpaca", True, n_bars)
        # Alpaca returned nothing (down / rate-limited) -> use last stored real bars

    if stable.exists():
        return _tag(pd.read_parquet(stable), "stored", True, n_bars)

    return _tag(_synthetic(symbol, start, end, timeframe), "synthetic", False, n_bars)


def get_daily_bars(symbol, days=504, end=None, force_synthetic=False):
    """Daily bars (backtester + tests)."""
    return get_bars(symbol, days, "1Day", end, force_synthetic)


def _tag(df, source, real, n_bars):
    out = df.tail(n_bars).copy()
    out.attrs["source"] = source
    out.attrs["real"] = real
    return out


def _fetch_alpaca(symbol, start, end, timeframe="1Day"):
    import requests  # only imported when keys exist
    headers = {
        "APCA-API-KEY-ID": settings.env("ALPACA_API_KEY"),
        "APCA-API-SECRET-KEY": settings.env("ALPACA_SECRET_KEY"),
    }
    rows, page = [], None
    for _ in range(20):  # pagination cap
        params = {"timeframe": timeframe, "start": f"{start}T00:00:00Z",
                  "end": f"{end}T00:00:00Z", "limit": 10000, "adjustment": "split"}
        if page:
            params["page_token"] = page
        try:
            r = requests.get(_DATA_URL.format(sym=symbol), headers=headers, params=params, timeout=30)
        except Exception:
            return None
        if r.status_code != 200:
            return None
        j = r.json()
        rows.extend(j.get("bars") or [])
        page = j.get("next_page_token")
        if not page:
            break
        time.sleep(0.2)
    if not rows:
        return None
    df = pd.DataFrame(rows)
    df["t"] = pd.to_datetime(df["t"], utc=True)
    df = df.set_index("t").sort_index()
    return df.rename(columns={"o": "open", "h": "high", "l": "low", "c": "close", "v": "volume"})[
        ["open", "high", "low", "close", "volume"]]


def _synthetic(symbol, start, end, timeframe="1Day"):
    """Regime-switching GBM with a fixed per-symbol seed: produces real bull/bear/crash
    phases so the HMM has something to find. Deterministic -> reproducible tests."""
    seed = abs(hash(symbol)) % (2**32)
    rng = np.random.default_rng(seed)
    freq = _TF_FREQ.get(timeframe, "B")
    idx = pd.date_range(start=start, end=end, freq=freq, tz="UTC")
    n = len(idx)
    # hidden regime chain: drift/vol per state (crash,bear,neutral,bull,euphoria)
    drift = np.array([-0.004, -0.0012, 0.0002, 0.0011, 0.0025])
    vol = np.array([0.035, 0.018, 0.009, 0.011, 0.016])
    trans = 0.04  # daily switch probability
    state = 2
    rets = np.empty(n)
    states = np.empty(n, dtype=int)
    for i in range(n):
        if rng.random() < trans:
            state = int(np.clip(state + rng.integers(-1, 2), 0, 4))
        states[i] = state
        rets[i] = rng.normal(drift[state], vol[state])
    close = 100 * np.exp(np.cumsum(rets))
    high = close * (1 + np.abs(rng.normal(0, 0.004, n)))
    low = close * (1 - np.abs(rng.normal(0, 0.004, n)))
    open_ = np.concatenate([[close[0]], close[:-1]])
    volume = rng.integers(5_000_000, 50_000_000, n).astype(float)
    df = pd.DataFrame({"open": open_, "high": high, "low": low, "close": close, "volume": volume}, index=idx)
    return df


if __name__ == "__main__":
    d = get_daily_bars("SPY", days=300, force_synthetic=True)
    print(f"source={d.attrs['source']} rows={len(d)} last_close={d['close'].iloc[-1]:.2f}")
    assert len(d) > 100, "too few bars"
    assert (d["close"] > 0).all(), "negative prices"
    print("market_data self-check ok")
