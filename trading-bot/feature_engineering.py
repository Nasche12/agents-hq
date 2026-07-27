"""Layer 0 -- features for the HMM. CORE RULE: no look-ahead. Every feature at bar t
may only use data up to and including t. All rolling windows look backward; nothing is
shifted in a way that pulls the future in.

The three CORE features are always present. Additional chart-analysis features live in
chart_features.py and are selected as a named SET via config hmm.feature_set -- so the
research agent can choose between sets (a bounded, allow-listed choice) without anyone
writing new code into the order path."""
import numpy as np
import pandas as pd

import chart_features

FEATURE_COLS = ["log_return", "realized_vol", "volume_z"]     # core, always computed


def feature_cols(feature_set=None):
    """Column list for a named set. Unknown/None -> core."""
    if not feature_set:
        return list(FEATURE_COLS)
    return chart_features.columns(feature_set)


def build_features(df, vol_window=20, vol_z_window=20, feature_set=None):
    """Expects an OHLCV DataFrame (oldest first). Returns the columns of `feature_set`
    (core when omitted); rows with incomplete windows (NaN) are dropped. Look-ahead free.

    NOTE the dropna: extra features use longer windows (e.g. squeeze needs 100 bars of
    lookback), so a richer set costs you leading history. That is honest -- those rows
    genuinely cannot be computed -- but it is why the sets are kept small."""
    out = pd.DataFrame(index=df.index)
    close = df["close"].astype(float)
    out["log_return"] = np.log(close / close.shift(1))
    # realized vol: std of log returns over a backward window (past only)
    out["realized_vol"] = out["log_return"].rolling(vol_window).std()
    # volume z-score against a rolling mean/std (backward)
    vol = df["volume"].astype(float)
    vmean = vol.rolling(vol_z_window).mean()
    vstd = vol.rolling(vol_z_window).std()
    out["volume_z"] = (vol - vmean) / vstd.replace(0, np.nan)

    cols = feature_cols(feature_set)
    extra = [c for c in cols if c not in FEATURE_COLS]
    if extra:
        out = out.join(chart_features.compute(df, extra))
    return out[cols].replace([np.inf, -np.inf], np.nan).dropna()


def realized_vol_now(df, window=20):
    """Current realized vol (last value) -- for the allocation layer."""
    r = np.log(df["close"].astype(float) / df["close"].astype(float).shift(1))
    return float(r.rolling(window).std().iloc[-1])


if __name__ == "__main__":
    # Look-ahead self-test: a feature at t must not depend on bars > t.
    import market_data
    df = market_data.get_daily_bars("SPY", days=300, force_synthetic=True)
    full = build_features(df)
    cut = 200
    partial = build_features(df.iloc[:cut])
    common = full.index.intersection(partial.index)
    # values over the shared range must be identical -> no future leaked in
    assert np.allclose(full.loc[common].values, partial.loc[common].values, equal_nan=True), \
        "LOOK-AHEAD LEAK: feature changes when later bars are added"
    assert not full.isna().any().any(), "NaN in finished features"
    print(f"features ok: {len(full)} rows, {list(full.columns)}, no look-ahead")
