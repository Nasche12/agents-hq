"""Layer 0 -- features for the HMM. CORE RULE: no look-ahead. Every feature at bar t
may only use data up to and including t. All rolling windows look backward; nothing is
shifted in a way that pulls the future in."""
import numpy as np
import pandas as pd

FEATURE_COLS = ["log_return", "realized_vol", "volume_z"]


def build_features(df, vol_window=20, vol_z_window=20):
    """Expects an OHLCV DataFrame (oldest first). Returns a DataFrame with FEATURE_COLS;
    rows with incomplete windows (NaN) are dropped. Look-ahead free."""
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
    out = out[FEATURE_COLS].dropna()
    return out


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
