"""Layer 2 -- allocation. Regime + confidence + vol become a target size (fraction of
capital, 0..1, plus leverage). Contains the anti-overtrading guard: a minimum-change
threshold so micro-moves don't trigger a rebalance.

Leverage warning: the base can go up to 1.25x (magnifies losses). config.json
'leverage' caps it globally; keep it at 1.0x to start."""
import settings


def _vol_bucket(vol, lo_pct, hi_pct, vol_ref):
    """low/medium/high from realized vol relative to a reference value."""
    if vol_ref <= 0:
        return "medium"
    r = vol / vol_ref
    if r <= lo_pct:
        return "low"
    if r >= hi_pct:
        return "high"
    return "medium"


def target_allocation(regime, confidence, vol, vol_ref, trend_ok=True, flickering=False):
    """Returns dict{alloc, leverage, reason}. alloc = 0..1 fraction of capital."""
    cfg = settings.load_config()["allocation"]
    cap_lev = cfg["leverage"]                       # global leverage cap
    bucket = _vol_bucket(vol, cfg["low_vol_pct"], cfg["high_vol_pct"], vol_ref)

    if regime in ("crash", "bear") or bucket == "high":
        alloc, lev, reason = cfg["high_vol_alloc"], cfg["high_vol_leverage"], f"{regime}/{bucket}-vol defensive"
    elif bucket == "low":
        alloc, lev, reason = cfg["low_vol_alloc"], cfg["low_vol_leverage"], "low-vol offensive"
    else:  # medium
        alloc = cfg["low_vol_alloc"] if trend_ok else cfg["high_vol_alloc"]
        lev, reason = cfg["medium_vol_leverage"], "medium-vol, trend " + ("intact" if trend_ok else "broken")

    # confidence bucketing: uncertain signals -> less capital.
    if confidence < 0.5:
        alloc *= 0.5
        reason += " · low-conf halved"
    elif confidence < 0.7:
        alloc *= 0.8
        reason += " · mid-conf trimmed"

    # flickering regimes -> cut further (couples to the stability filter).
    if flickering:
        alloc *= 0.5
        reason += " · flickering"

    lev = min(lev, cap_lev)
    alloc = max(0.0, min(1.0, alloc))
    return {"alloc": round(alloc, 4), "leverage": round(lev, 3), "reason": reason, "bucket": bucket}


def directional_exposure(regime_rank, n_regimes, confidence, vol, vol_ref, flickering=False):
    """Signed target exposure in [-1, 1] straight from the HMM regime ranking:
    weakest regime (crash) -> short, strongest (euphoria) -> long, middle -> flat.
    Magnitude scaled by max allocation, cut in high vol / low confidence / flicker.
    Returns (exposure, reason). This is what lets the live bot long AND short."""
    cfg = load_config_alloc()
    if n_regimes <= 1:
        base = 0.0
    else:
        base = (regime_rank / (n_regimes - 1)) * 2 - 1      # -1 (weakest) .. +1 (strongest)
    expo = base * cfg["low_vol_alloc"]                      # scale to max size (±0.95)

    bucket = _vol_bucket(vol, cfg["low_vol_pct"], cfg["high_vol_pct"], vol_ref)
    if bucket == "high":
        expo *= cfg["high_vol_alloc"] / cfg["low_vol_alloc"]   # shrink hard in high vol
    if confidence < 0.5:
        expo *= 0.5
    elif confidence < 0.7:
        expo *= 0.8
    if flickering:
        expo *= 0.5
    if abs(expo) < cfg["min_change_threshold"]:            # deadband near neutral -> flat
        expo = 0.0

    expo = round(max(-1.0, min(1.0, expo)), 4)
    direction = "long" if expo > 0 else ("short" if expo < 0 else "flat")
    reason = (f"{direction} {abs(expo):.0%} · rank {regime_rank + 1}/{n_regimes} · "
              f"{bucket}-vol · conf {int(confidence * 100)}%")
    return expo, reason


def load_config_alloc():
    return settings.load_config()["allocation"]


def needs_rebalance(current_alloc, target_alloc):
    """True only when the change exceeds the minimum threshold (anti-churn)."""
    thr = settings.load_config()["allocation"]["min_change_threshold"]
    return abs(target_alloc - current_alloc) >= thr


if __name__ == "__main__":
    ref = 0.012
    bull = target_allocation("bull", 0.9, 0.010, ref)
    crash = target_allocation("crash", 0.9, 0.040, ref)
    lowconf = target_allocation("bull", 0.4, 0.010, ref)
    assert bull["alloc"] > crash["alloc"], "crash must be more defensive than bull"
    assert lowconf["alloc"] < bull["alloc"], "low confidence must throttle"
    assert not needs_rebalance(0.90, 0.93), "tiny change must not rebalance"
    assert needs_rebalance(0.20, 0.95), "large change must rebalance"
    print("strategies self-check ok:", bull, crash)
