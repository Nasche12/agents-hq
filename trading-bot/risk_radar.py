"""Portfolio-level risk radar -- the part that acts IMMEDIATELY, without waiting for a
backtest, because it may only ever do one thing: take risk off.

The asymmetry is the whole design:

    reducing exposure   allowed instantly, on an unvalidated signal.
                        Worst case you miss upside.
    adding exposure     never happens here. That stays behind the walk-forward gate.
                        Instant risk-ON on an unproven signal is how accounts die.

So assess() returns a multiplier in [0, 1]. It cannot be above 1 by construction.

Why the tape and not the news: by the time a crisis is in the headlines the price has
already moved -- for macro events, news is a LAGGING indicator. What actually turns
first is measurable: a volatility shock, correlations collapsing towards 1 (in a crisis
everything moves together, which is exactly when diversification stops working), and
market breadth rolling over.

And the "something is being pumped" case: if you can read that somewhere, you are the
exit liquidity -- pump schemes need someone to buy the signal. But the pump itself IS
visible in the tape, as abnormal volume plus an outsized move. So it is detected here
and used to CAP that symbol, never to chase it."""
import numpy as np
import pandas as pd

import settings
from feature_engineering import build_features

CALM, ELEVATED, STRESS, CRISIS = "calm", "elevated", "stress", "crisis"
LEVEL_ORDER = [CALM, ELEVATED, STRESS, CRISIS]


def _rcfg():
    return settings.load_config().get("radar", {})


def _returns(df, n):
    close = df["close"].astype(float)
    return np.log(close / close.shift(1)).dropna().tail(n)


def market_correlation(bars, window):
    """Median pairwise correlation of returns across the universe. Rising towards 1 is
    the classic crisis signature: diversification quietly stops existing."""
    series = {}
    for sym, df in bars.items():
        r = _returns(df, window)
        if len(r) >= 30:
            series[sym] = r
    if len(series) < 3:
        return None, {}
    frame = pd.DataFrame(series).dropna(how="all")
    # different asset classes trade on different calendars -> align, then require overlap
    frame = frame.dropna()
    if len(frame) < 30:
        frame = pd.DataFrame(series).interpolate(limit_area="inside").dropna()
    if len(frame) < 30 or frame.shape[1] < 3:
        return None, {}
    corr = frame.corr()
    vals = corr.values[np.triu_indices_from(corr.values, k=1)]
    vals = vals[~np.isnan(vals)]
    if not len(vals):
        return None, {}
    return float(np.median(np.abs(vals))), corr.to_dict()


def vol_shock(bars):
    """Current realized vol against each symbol's OWN recent median, aggregated.
    Self-referencing, so a structurally volatile asset like crypto does not read as a
    permanent crisis."""
    ratios = []
    for df in bars.values():
        try:
            v = build_features(df)["realized_vol"].dropna()
            if len(v) < 50:
                continue
            base = float(v.median())
            if base > 0:
                ratios.append(float(v.iloc[-1]) / base)
        except Exception:
            continue
    return float(np.median(ratios)) if ratios else None


def anomalies(bars, rcfg):
    """Per-symbol 'something unusual is happening here' -- abnormal volume together with
    an outsized move. That is what a pump looks like from the inside of the tape, and it
    is a reason to hold LESS, not more."""
    out = {}
    vz_thr = rcfg.get("anomaly_volume_z", 3.0)
    rz_thr = rcfg.get("anomaly_return_z", 3.0)
    for sym, df in bars.items():
        try:
            f = build_features(df)
            if len(f) < 50:
                continue
            vz = float(f["volume_z"].iloc[-1])
            r = f["log_return"]
            sd = float(r.tail(200).std())
            rz = float(r.iloc[-1] / sd) if sd > 0 else 0.0
            hit = abs(vz) >= vz_thr and abs(rz) >= rz_thr
            if hit:
                out[sym] = {"volume_z": round(vz, 2), "return_z": round(rz, 2),
                            "direction": "up" if rz > 0 else "down"}
        except Exception:
            continue
    return out


def _level(vol_ratio, corr, weak_share, rcfg):
    """Escalate to the WORST signal, never average them. Three mild warnings at once
    are not reassuring."""
    level = CALM
    reasons = []

    def bump(to, why):
        nonlocal level
        if LEVEL_ORDER.index(to) > LEVEL_ORDER.index(level):
            level = to
        reasons.append(why)

    if vol_ratio is not None:
        if vol_ratio >= rcfg.get("vol_shock_crisis", 3.0):
            bump(CRISIS, f"Volatilitaet {vol_ratio:.1f}x normal")
        elif vol_ratio >= rcfg.get("vol_shock_stress", 2.2):
            bump(STRESS, f"Volatilitaet {vol_ratio:.1f}x normal")
        elif vol_ratio >= rcfg.get("vol_shock_elevated", 1.5):
            bump(ELEVATED, f"Volatilitaet {vol_ratio:.1f}x normal")
    if corr is not None:
        if corr >= rcfg.get("correlation_stress", 0.85):
            bump(STRESS, f"Korrelation {corr:.2f} — Streuung wirkt nicht mehr")
        elif corr >= rcfg.get("correlation_elevated", 0.75):
            bump(ELEVATED, f"Korrelation {corr:.2f} erhoeht")
    if weak_share is not None and weak_share >= rcfg.get("breadth_weak_stress", 0.6):
        bump(STRESS, f"{weak_share:.0%} der Symbole im schwachen Regime")
    return level, reasons


def assess(bars, weak_share=None):
    """The full read. Returns level, a de-risking multiplier in [0, 1], per-symbol
    anomalies and the correlation matrix (used to enforce real diversification)."""
    rcfg = _rcfg()
    if not rcfg.get("enabled", True) or len(bars) < 2:
        return {"enabled": False, "level": CALM, "multiplier": 1.0, "reasons": [],
                "anomalies": {}, "correlation": None, "corr_matrix": {}}

    corr, matrix = market_correlation(bars, rcfg.get("corr_window", 300))
    ratio = vol_shock(bars)
    level, reasons = _level(ratio, corr, weak_share, rcfg)
    mults = rcfg.get("multipliers", {})
    mult = float(mults.get(level, 1.0))
    # hard guarantee: this component can only ever take risk off
    mult = max(0.0, min(1.0, mult))
    return {
        "enabled": True,
        "level": level,
        "multiplier": round(mult, 3),
        "reasons": reasons,
        "vol_ratio": round(ratio, 2) if ratio is not None else None,
        "correlation": round(corr, 3) if corr is not None else None,
        "weak_share": round(weak_share, 3) if weak_share is not None else None,
        "anomalies": anomalies(bars, rcfg),
        "corr_matrix": matrix,
    }


def cap_for_anomaly(target, sym, radar):
    """An anomalous symbol gets capped, never chased. Returns (target, note|None)."""
    a = (radar.get("anomalies") or {}).get(sym)
    if not a:
        return target, None
    cap = _rcfg().get("anomaly_exposure_cap", 0.3)
    capped = max(-cap, min(cap, target))
    if abs(capped) < abs(target):
        return capped, (f"Anomalie (Vol-Z {a['volume_z']}, Ret-Z {a['return_z']}) "
                        f"-> auf {cap:.0%} gedeckelt statt hinterherzukaufen")
    return target, None


def diversify(targets, corr_matrix, max_corr):
    """Enforce the correlation limit that config.risk.max_correlation always promised.

    Walks symbols from the largest intended position down. A symbol that is highly
    correlated with something already allocated IN THE SAME DIRECTION gets halved --
    holding five names that are one bet is not diversification, it is leverage with
    extra steps. Returns (adjusted targets, notes)."""
    if not corr_matrix or max_corr is None:
        return dict(targets), {}
    out, notes, taken = {}, {}, []
    for sym in sorted(targets, key=lambda s: -abs(targets[s])):
        t = targets[sym]
        if t == 0:
            out[sym] = t
            continue
        worst, worst_sym = 0.0, None
        for other in taken:
            if (out[other] > 0) != (t > 0):
                continue                        # opposite directions actually offset
            c = (corr_matrix.get(sym) or {}).get(other)
            if c is None:
                continue
            if abs(c) > abs(worst):
                worst, worst_sym = abs(c), other
        if worst > max_corr:
            out[sym] = round(t * 0.5, 4)
            notes[sym] = f"Korrelation {worst:.2f} mit {worst_sym} -> halbiert"
        else:
            out[sym] = t
        taken.append(sym)
    return out, notes


if __name__ == "__main__":
    import market_data
    rng = np.random.default_rng(0)
    idx = pd.date_range("2026-01-01", periods=400, freq="h", tz="UTC")

    def frame(rets, vols=None):
        close = 100 * np.exp(np.cumsum(rets))
        return pd.DataFrame({"open": close, "high": close * 1.001, "low": close * 0.999,
                             "close": close,
                             "volume": vols if vols is not None else rng.integers(1e6, 2e6, len(rets)).astype(float)},
                            index=idx)

    calm = {f"S{i}": frame(rng.normal(0, 0.004, 400)) for i in range(4)}
    r = assess(calm)
    assert r["multiplier"] <= 1.0, "radar must never add risk"
    print("ruhig:", r["level"], r["multiplier"], "corr", r["correlation"])

    shared = rng.normal(0, 0.03, 400)                    # one common shock = crisis shape
    crisis = {f"S{i}": frame(shared + rng.normal(0, 0.002, 400)) for i in range(4)}
    rc = assess(crisis)
    print("Krise:", rc["level"], rc["multiplier"], "corr", rc["correlation"], rc["reasons"])
    assert rc["multiplier"] <= r["multiplier"], "correlated shock must not increase risk"

    # pump shape: quiet, then a huge volume + price spike on the last bar
    rets = rng.normal(0, 0.004, 400); rets[-1] = 0.25
    vols = rng.integers(1e6, 1.1e6, 400).astype(float); vols[-1] = 5e7
    pumped = dict(calm, PUMP=frame(rets, vols))
    rp = assess(pumped)
    assert "PUMP" in rp["anomalies"], rp["anomalies"]
    capped, note = cap_for_anomaly(0.95, "PUMP", rp)
    assert capped < 0.95 and note, (capped, note)
    print("Pump erkannt:", rp["anomalies"]["PUMP"], "->", note)

    tg = {"A": 0.9, "B": 0.9, "C": -0.8}
    cm = {"A": {"B": 0.97, "C": -0.1}, "B": {"A": 0.97, "C": -0.1}, "C": {"A": -0.1, "B": -0.1}}
    adj, notes = diversify(tg, cm, 0.7)
    assert adj["B"] == 0.45 and adj["A"] == 0.9 and adj["C"] == -0.8, (adj, notes)
    print("Diversifikation:", adj, notes)
    print("risk_radar self-check ok")
