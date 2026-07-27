"""Layer 0 -- data acquisition. Fetches historical bars from Alpaca (Data API) via
requests (no heavy SDK). Handles BOTH asset classes:
  * US equities  -> /v2/stocks/{sym}/bars      (session-bound: Mon-Fri, ~6.5h/day)
  * crypto       -> /v1beta3/crypto/us/bars    (24/7, symbols look like 'BTC/USD')
Caches to disk so repeated backtests don't re-download. WITHOUT keys -> a reproducible
synthetic dataset (fixed seed) so the backtester and tests run fully offline. Every real
value comes from the API, never guessed; if the API is unavailable it is honestly marked
source='synthetic'."""
import time
from datetime import datetime, timedelta, timezone

import numpy as np
import pandas as pd

import settings

_DATA_URL = "https://data.alpaca.markets/v2/stocks/{sym}/bars"
_CRYPTO_URL = "https://data.alpaca.markets/v1beta3/crypto/us/bars"


# bars per day. Equities only trade ~6.5h Mon-Fri, crypto runs 24/7 -> far more bars
# per calendar day, which is exactly why crypto gives the bot something to do at night.
_TF_PER_DAY = {"1Day": 1, "1Hour": 7, "30Min": 13, "15Min": 26, "5Min": 78, "1Min": 390}
_TF_PER_DAY_CRYPTO = {"1Day": 1, "1Hour": 24, "30Min": 48, "15Min": 96, "5Min": 288, "1Min": 1440}
_TF_FREQ = {"1Day": "B", "1Hour": "h", "30Min": "30min", "15Min": "15min",
            "5Min": "5min", "1Min": "1min"}
_TF_FREQ_CRYPTO = dict(_TF_FREQ, **{"1Day": "D"})


def is_crypto(symbol):
    """Alpaca crypto pairs carry a slash ('BTC/USD'); equities never do."""
    return "/" in str(symbol)


def pos_symbol(symbol):
    """Broker-side symbol. Alpaca reports crypto POSITIONS as 'BTCUSD' but accepts
    'BTC/USD' on orders -- normalize so position lookups match either spelling."""
    return str(symbol).replace("/", "").upper()


def bars_per_day(timeframe, symbol=None):
    table = _TF_PER_DAY_CRYPTO if (symbol and is_crypto(symbol)) else _TF_PER_DAY
    return table.get(timeframe, 1)


def _stable_cache(symbol, timeframe):
    """One rolling file per symbol+timeframe that always holds the latest REAL bars."""
    return settings.CACHE_DIR / f"{pos_symbol(symbol)}_{timeframe}.parquet"


def _have_keys():
    return bool(settings.env("ALPACA_API_KEY") and settings.env("ALPACA_SECRET_KEY"))


_MEMO = {}          # (symbol, timeframe, days) -> (monotonic_stamp, df)
_TF_SECONDS = {"1Min": 60, "5Min": 300, "15Min": 900, "30Min": 1800,
               "1Hour": 3600, "1Day": 86400}


def _memo_ttl(timeframe):
    """A 5-minute bar only changes every 5 minutes, so re-downloading the full history
    every 60s cycle is wasted work -- with a 20-symbol watchlist it was the single
    heaviest thing in the loop. Half a bar period keeps the data effectively fresh:
    the last CLOSED bar is always current, only the still-forming bar can lag."""
    return max(30, _TF_SECONDS.get(timeframe, 300) // 2)


def clear_memo():
    _MEMO.clear()


def get_bars(symbol, days=504, timeframe="1Day", end=None, force_synthetic=False,
             use_memo=False):
    """DataFrame [open,high,low,close,volume], DatetimeIndex (UTC), oldest first.
    timeframe: 1Day | 1Hour | 30Min | 15Min | 5Min | 1Min (intraday -> more signals).

    Data policy:
      1. keys present -> ALWAYS fetch fresh from Alpaca and use that; persist it.
      2. Alpaca unreachable -> fall back to the last STORED real bars (never synthetic).
      3. only truly offline dev (no keys, no store) uses synthetic, flagged real=False.
    df.attrs['source'] = 'alpaca' | 'stored' | 'synthetic'; df.attrs['real'] = bool.
    force_synthetic=True is for the offline test suite only."""
    if use_memo and not force_synthetic:
        hit = _MEMO.get((symbol, timeframe, days))
        if hit and (time.monotonic() - hit[0]) < _memo_ttl(timeframe):
            return hit[1]

    end = end or datetime.now(timezone.utc).date()
    crypto = is_crypto(symbol)
    # equities lose weekends/holidays, so ask for a wider calendar window; crypto doesn't
    span = int(days * (1.05 if crypto else 1.5)) + 10
    start = end - timedelta(days=span)
    n_bars = days * bars_per_day(timeframe, symbol)
    stable = _stable_cache(symbol, timeframe)

    def _done(df, source, real):
        out = _tag(df, source, real, n_bars)
        if use_memo:
            _MEMO[(symbol, timeframe, days)] = (time.monotonic(), out)
        return out

    if force_synthetic:
        return _tag(_synthetic(symbol, start, end, timeframe), "synthetic", False, n_bars)

    if _have_keys():
        df = _fetch_alpaca(symbol, start, end, timeframe)
        if df is not None and len(df):
            try:
                df.to_parquet(stable)                   # keep the latest real bars
            except Exception:
                pass
            return _done(df, "alpaca", True)
        # Alpaca returned nothing (down / rate-limited) -> use last stored real bars

    if stable.exists():
        return _done(pd.read_parquet(stable), "stored", True)

    return _done(_synthetic(symbol, start, end, timeframe), "synthetic", False)


def get_daily_bars(symbol, days=504, end=None, force_synthetic=False):
    """Daily bars (backtester + tests)."""
    return get_bars(symbol, days, "1Day", end, force_synthetic)


def _tag(df, source, real, n_bars):
    out = df.tail(n_bars).copy()
    out.attrs["source"] = source
    out.attrs["real"] = real
    return out


def _headers():
    return {
        "APCA-API-KEY-ID": settings.env("ALPACA_API_KEY"),
        "APCA-API-SECRET-KEY": settings.env("ALPACA_SECRET_KEY"),
    }


def _fetch_alpaca(symbol, start, end, timeframe="1Day"):
    if is_crypto(symbol):
        return _fetch_crypto(symbol, start, end, timeframe)
    import requests  # only imported when keys exist
    rows, page = [], None
    for _ in range(20):  # pagination cap
        params = {"timeframe": timeframe, "start": f"{start}T00:00:00Z",
                  "end": f"{end}T00:00:00Z", "limit": 10000, "adjustment": "split"}
        if page:
            params["page_token"] = page
        try:
            r = requests.get(_DATA_URL.format(sym=symbol), headers=_headers(),
                             params=params, timeout=30)
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
    return _frame(rows)


def _fetch_crypto(symbol, start, end, timeframe="1Day"):
    """Crypto bars (v1beta3). Same shape as equities, but bars arrive keyed by symbol
    and there is no split adjustment. 24/7 -> no session gaps."""
    import requests
    rows, page = [], None
    for _ in range(20):
        params = {"symbols": symbol, "timeframe": timeframe,
                  "start": f"{start}T00:00:00Z", "limit": 10000}
        if page:
            params["page_token"] = page
        try:
            r = requests.get(_CRYPTO_URL, headers=_headers(), params=params, timeout=30)
        except Exception:
            return None
        if r.status_code != 200:
            return None
        j = r.json()
        rows.extend((j.get("bars") or {}).get(symbol) or [])
        page = j.get("next_page_token")
        if not page:
            break
        time.sleep(0.2)
    return _frame(rows)


def _frame(rows):
    if not rows:
        return None
    df = pd.DataFrame(rows)
    df["t"] = pd.to_datetime(df["t"], utc=True, format="ISO8601", errors="coerce")
    df = df.dropna(subset=["t"]).set_index("t").sort_index()
    df = df[~df.index.duplicated(keep="last")]
    return df.rename(columns={"o": "open", "h": "high", "l": "low", "c": "close", "v": "volume"})[
        ["open", "high", "low", "close", "volume"]]


def _synthetic(symbol, start, end, timeframe="1Day"):
    """Regime-switching GBM with a fixed per-symbol seed: produces real bull/bear/crash
    phases so the HMM has something to find. Deterministic -> reproducible tests."""
    seed = abs(hash(symbol)) % (2**32)
    rng = np.random.default_rng(seed)
    crypto = is_crypto(symbol)
    freq = (_TF_FREQ_CRYPTO if crypto else _TF_FREQ).get(timeframe, "B")
    idx = pd.date_range(start=start, end=end, freq=freq, tz="UTC")
    n = len(idx)
    # hidden regime chain: drift/vol per state (crash,bear,neutral,bull,euphoria)
    drift = np.array([-0.004, -0.0012, 0.0002, 0.0011, 0.0025])
    vol = np.array([0.035, 0.018, 0.009, 0.011, 0.016])
    if crypto:
        vol = vol * 1.8                      # crypto is structurally more volatile
    trans = 0.04  # per-bar switch probability
    state = 2
    rets = np.empty(n)
    states = np.empty(n, dtype=int)
    for i in range(n):
        if rng.random() < trans:
            state = int(np.clip(state + rng.integers(-1, 2), 0, 4))
        states[i] = state
        rets[i] = rng.normal(drift[state], vol[state])
    close = (30000 if crypto else 100) * np.exp(np.cumsum(rets))
    open_ = np.concatenate([[close[0]], close[:-1]])
    # VALID OHLC: high/low must bracket BOTH open and close. Deriving them from close
    # alone produced bars where the open sat outside the range -- impossible in real
    # data, and it made every bar-shape feature untestable on the synthetic set.
    body_hi = np.maximum(open_, close)
    body_lo = np.minimum(open_, close)
    high = body_hi * (1 + np.abs(rng.normal(0, 0.004, n)))
    low = body_lo * (1 - np.abs(rng.normal(0, 0.004, n)))
    volume = rng.integers(5_000_000, 50_000_000, n).astype(float)
    df = pd.DataFrame({"open": open_, "high": high, "low": low, "close": close, "volume": volume}, index=idx)
    return df


if __name__ == "__main__":
    d = get_daily_bars("SPY", days=300, force_synthetic=True)
    print(f"source={d.attrs['source']} rows={len(d)} last_close={d['close'].iloc[-1]:.2f}")
    assert len(d) > 100, "too few bars"
    assert (d["close"] > 0).all(), "negative prices"
    c = get_bars("BTC/USD", days=30, timeframe="15Min", force_synthetic=True)
    assert is_crypto("BTC/USD") and not is_crypto("SPY")
    assert pos_symbol("BTC/USD") == "BTCUSD"
    assert len(c) > 1000, "crypto 15Min should give far more bars per day than equities"
    print(f"crypto synthetic rows={len(c)} last={c['close'].iloc[-1]:.0f}")
    print("market_data self-check ok")
