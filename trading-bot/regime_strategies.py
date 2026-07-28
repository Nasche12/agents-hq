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


def directional_exposure(regime_rank, n_regimes, confidence, vol, vol_ref, flickering=False,
                         trend=None, chart=None):
    """Signed target exposure in [-1, 1].

    The HMM proposes a DIRECTION from its regime ranking (weakest -> short, strongest ->
    long). But an HMM on intraday returns detects VOL regimes, not direction -- the mean-
    return sort it is ranked by is mostly noise on 5-min bars. So the HMM's direction is
    only ACTED ON when a price-trend filter agrees with it (trend confirmation). When the
    trend disagrees or is flat, we go flat rather than fight the tape on a noisy read. This
    is the fix for 'HMM used as a direction oracle': the HMM now sizes/gates, the trend
    decides the side. `trend` is a signed trend measure (e.g. MA slope); None or trend_filter
    off restores the old regime-only behaviour.

    `chart` is the combined chart-analysis vote in [-1,+1] (chart_features.chart_bias). When
    allocation.chart_decides is on, the CHART picks the side and the HMM/vol path only sets
    the SIZE -- this is the 'Chartanalyse entscheidet' mode. A chart vote below chart_min in
    magnitude means 'no readable structure' -> flat. Returns (exposure, reason)."""
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

    trend_note = ""
    if cfg.get("chart_decides", False) and chart is not None and expo != 0:
        # CHART DECIDES THE SIDE. The HMM/vol path above set the SIZE (|expo|); the combined
        # chart-analysis vote sets the direction. A near-neutral chart -> flat (a shapeless
        # tape is not a trade). This is the mode the user asked for.
        cmin = cfg.get("chart_min", 0.1)
        mag = abs(expo)
        if abs(chart) < cmin:
            expo, trend_note = 0.0, f" · Chart neutral (<{cmin:.2f}) -> flat"
        else:
            expo = mag if chart > 0 else -mag
            trend_note = f" · Chartanalyse entscheidet {'long' if chart > 0 else 'short'} ({chart:+.2f})"
    elif cfg.get("trend_filter", True) and trend is not None and expo != 0:
        # confirmation: take the HMM's side only if the trend points the same way.
        if trend == 0 or (expo > 0) != (trend > 0):
            expo = 0.0
            trend_note = " · Trend widerspricht -> flat"
        else:
            trend_note = " · Trend bestätigt"

    # The MOST extreme bullish regime (top rank = euphoria/mania) is an exhaustion zone, not a
    # continuation signal -- live data showed longs there lose ~100% (regime=euphoria: 0% win).
    # The HMM ranks it "strongest -> max long", which is exactly backwards at the top. Cap it.
    if expo > 0 and n_regimes > 1 and regime_rank == n_regimes - 1:
        expo *= cfg.get("extreme_long_cap", 0.25)
        trend_note += " · Euphorie-Cap"

    if abs(expo) < cfg["min_change_threshold"]:            # deadband near neutral -> flat
        expo = 0.0

    expo = round(max(-1.0, min(1.0, expo)), 4)
    direction = "long" if expo > 0 else ("short" if expo < 0 else "flat")
    reason = (f"{direction} {abs(expo):.0%} · rank {regime_rank + 1}/{n_regimes} · "
              f"{bucket}-vol · conf {int(confidence * 100)}%{trend_note}")
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
    thr = settings.load_config()["allocation"]["min_change_threshold"]
    assert not needs_rebalance(0.90, 0.90 + thr * 0.5), "below the deadband must not rebalance"
    assert needs_rebalance(0.90, 0.90 + thr * 1.5), "above the deadband must rebalance"
    assert needs_rebalance(0.20, 0.95), "large change must rebalance"
    # trend confirmation: strongest regime wants long -> trend up keeps it, trend down flattens
    up, _ = directional_exposure(2, 3, 0.9, 0.010, ref, trend=1.0)
    dn, _ = directional_exposure(2, 3, 0.9, 0.010, ref, trend=-1.0)
    none, _ = directional_exposure(2, 3, 0.9, 0.010, ref, trend=None)
    assert up > 0 and none > 0, (up, none)
    assert dn == 0.0, f"trend against a long must go flat, got {dn}"
    # chart-decides mode: the chart vote sets the SIDE, a neutral vote goes flat
    with settings.config_override({"allocation.chart_decides": True, "allocation.chart_min": 0.1}):
        clong, _ = directional_exposure(2, 3, 0.9, 0.010, ref, chart=0.5)
        cshort, _ = directional_exposure(2, 3, 0.9, 0.010, ref, chart=-0.5)
        cflat, _ = directional_exposure(2, 3, 0.9, 0.010, ref, chart=0.02)
    assert clong > 0 and cshort < 0 and cflat == 0.0, (clong, cshort, cflat)
    print("strategies self-check ok:", bull, crash)
