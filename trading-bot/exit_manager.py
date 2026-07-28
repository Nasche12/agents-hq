"""Per-position exits -- the piece the target-following rebalancer structurally cannot do.

reconcile_to_target() only ever moves a position toward what the HMM wants. It has no
notion of "this specific entry is 1.5% underwater, cut it" or "this one is +6%, bank most
of it". That is why the live book shows the classic backwards asymmetry: winners sold on a
one-rank regime softening (+$3 avg), losers held until a full regime flip (-$16 avg). This
module supplies the missing half.

Three behaviours, from the user's spec ("stop loss gering, profit abgewogen, sonst stetig
abbauen wenn viel Profit"):

  1. TIGHT HARD STOP   -- underwater past stop_loss_pct -> flatten now, then a cooldown so
                          the rebalancer cannot immediately re-buy the same loser (that would
                          just re-arm the churn). This is the asymmetry fix.
  2. TRAILING GIVEBACK -- once a position has been meaningfully green (armed past
                          arm_profit_pct), give back at most trail_giveback_pct from its peak
                          before banking it. Lets winners run, refuses to let them round-trip
                          back to flat.
  3. SCALE-OUT LADDER  -- as unrealized profit climbs through tiers, cap exposure to a
                          shrinking fraction (0.7 -> 0.5 -> 0.3). "Steadily reduce when there
                          is a lot of profit." Ratcheted on the PEAK, so a dip never re-expands
                          the position.

VOLATILITY SCALING (the sound idea from the NNFX/forex playbook, done right): a FIXED-percent
stop whipsaws -- 1.2% is noise on a wild bar and a mile on a calm one. So the stop, the arm
level and the trailing giveback are multiplied by the symbol's CURRENT volatility relative to
its OWN normal (vol / ref_vol, clamped). Tight when calm, wide enough when wild -- and because
it is a RATIO it needs no assumption about the absolute size of the vol measure. This is the
one honest takeaway from the "tight stoploss" forex-robot genre; the 1-pip stops, 92%-win-rate
backtests and Sharpe-29 curve fits from those videos are deliberately NOT copied.

Design choices that matter:
  * PURE. evaluate() takes positions + config + state, returns decisions + new state. No
    broker, no I/O -> fully unit-testable. main.py executes the decisions.
  * Hard exits are IMPERATIVE (main calls close_position), because main's deadband gate
    would otherwise swallow a "target 0" and leave the loser open. Scale-out is a target
    MULTIPLIER (it stays above the deadband, so the normal reconcile does the trimming).
  * Cooldown state persists even while flat -- staying OUT is the whole point of a stop.
  * The exit block is LOCKED in config (learning.locked_prefixes): a system that may loosen
    its own stop-loss has no stop-loss.
"""
from datetime import datetime, timedelta, timezone

from market_data import pos_symbol


def _parse(iso):
    try:
        d = datetime.fromisoformat(str(iso).replace("Z", "+00:00"))
        return d if d.tzinfo else d.replace(tzinfo=timezone.utc)
    except Exception:
        return None


def _plpc(p):
    """Unrealized P&L as a signed fraction (+0.05 = 5% in profit). Prefer Alpaca's field;
    fall back to entry vs current price, sign-corrected for shorts."""
    v = p.get("unrealized_plpc")
    if v is not None:
        return float(v)
    entry, cur = p.get("avg_entry"), p.get("current_price")
    if entry and cur and entry > 0:
        r = cur / entry - 1.0
        return -r if p.get("side") == "short" else r
    return 0.0


def _scale_cap(peak, tiers):
    """Exposure multiplier from the scale-out ladder, chosen on the PEAK so it only ever
    ratchets down. tiers = [[threshold, cap], ...] with cap shrinking as threshold grows."""
    cap = 1.0
    for thr, c in sorted(tiers or [], key=lambda t: t[0]):
        if peak >= thr:
            cap = c
    return cap


def _clamp(x, lo, hi):
    return max(lo, min(hi, x))


def evaluate(positions, cfg, state, vol_ratios=None, now=None):
    """Returns (decisions, new_state).

    decisions: pos_symbol -> {close, block, cap, reason, plpc, peak}
      close = flatten this position at market NOW (hard stop or trailing giveback)
      block = do not (re)enter -- cooldown after a stop is still running
      cap   = exposure multiplier in [0,1] for the normal target (scale-out); None = 1.0
    new_state: pos_symbol -> {peak, cooldown_until} to persist for the next cycle.
    """
    now = now or datetime.now(timezone.utc)
    state = dict(state or {})
    vol_ratios = vol_ratios or {}
    if not cfg.get("enabled", False):
        return {}, state

    stop = float(cfg.get("stop_loss_pct", 0.015))
    cooldown = timedelta(minutes=float(cfg.get("cooldown_minutes", 20)))
    arm = float(cfg.get("arm_profit_pct", 0.02))
    give = float(cfg.get("trail_giveback_pct", 0.008))
    tiers = cfg.get("scale_out", [])
    vol_scaled = bool(cfg.get("vol_scaled", True))
    vr_lo = float(cfg.get("vol_ratio_min", 0.5))
    vr_hi = float(cfg.get("vol_ratio_max", 3.0))

    held = {pos_symbol(p["symbol"]): p for p in positions if abs(float(p.get("qty") or 0)) > 0}
    # Consider every held position AND any flat symbol still inside a cooldown window.
    keys = set(held) | {k for k, s in state.items() if _parse(s.get("cooldown_until")) and _parse(s["cooldown_until"]) > now}

    decisions, new_state = {}, {}
    for key in keys:
        prev = state.get(key) or {}
        cd_until = _parse(prev.get("cooldown_until"))
        cooling = bool(cd_until and cd_until > now)
        p = held.get(key)

        if p is None:                                   # flat but still cooling -> stay out
            if cooling:
                decisions[key] = {"close": False, "block": True, "cap": 0.0,
                                  "reason": f"Cooldown bis {cd_until:%H:%M} nach Stop", "plpc": None, "peak": 0.0}
                new_state[key] = {"peak": 0.0, "cooldown_until": prev.get("cooldown_until")}
            continue

        plpc = _plpc(p)
        peak = max(float(prev.get("peak", plpc)), plpc)

        # Volatility scaling: widen the tight base stop / arm / giveback in proportion to how
        # far current vol is above its own normal (and tighten below). A ratio -> no dependence
        # on the absolute vol scale. ratio 1.0 (or vol_scaled off) reproduces the fixed %.
        r = _clamp(float(vol_ratios.get(key, 1.0)), vr_lo, vr_hi) if vol_scaled else 1.0
        stop_e, arm_e, give_e = stop * r, arm * r, give * r

        if cooling:                                     # holding during cooldown -> flatten remainder
            decisions[key] = {"close": True, "block": True, "cap": 0.0,
                              "reason": "Cooldown aktiv -> flach", "plpc": round(plpc, 4), "peak": round(peak, 4)}
            new_state[key] = {"peak": 0.0, "cooldown_until": prev.get("cooldown_until")}
            continue

        if plpc <= -stop_e:                             # 1) tight, vol-scaled hard stop
            decisions[key] = {"close": True, "block": True, "cap": 0.0,
                              "reason": f"Stop-Loss {plpc:+.1%} <= -{stop_e:.1%} (Vol x{r:.1f}) -> flach + Cooldown",
                              "plpc": round(plpc, 4), "peak": round(peak, 4)}
            new_state[key] = {"peak": 0.0, "cooldown_until": (now + cooldown).isoformat()}
            continue

        if peak >= arm_e and plpc <= peak - give_e:     # 2) trailing giveback after being green
            decisions[key] = {"close": True, "block": True, "cap": 0.0,
                              "reason": f"Trailing: Peak {peak:+.1%}, jetzt {plpc:+.1%} -> Gewinn sichern",
                              "plpc": round(plpc, 4), "peak": round(peak, 4)}
            new_state[key] = {"peak": 0.0, "cooldown_until": (now + cooldown).isoformat()}
            continue

        cap = _scale_cap(peak, tiers)                   # 3) scale out as profit climbs
        reason = f"Halten (unreal {plpc:+.1%}, Peak {peak:+.1%})"
        if cap < 1.0:
            reason = f"Abbau auf {cap:.0%} (Peak {peak:+.1%} -> Gewinn stetig sichern)"
        decisions[key] = {"close": False, "block": False, "cap": round(cap, 3),
                          "reason": reason, "plpc": round(plpc, 4), "peak": round(peak, 4)}
        new_state[key] = {"peak": round(peak, 6), "cooldown_until": None}

    return decisions, new_state


if __name__ == "__main__":
    cfg = {"enabled": True, "stop_loss_pct": 0.015, "cooldown_minutes": 20,
           "arm_profit_pct": 0.02, "trail_giveback_pct": 0.008,
           "scale_out": [[0.03, 0.7], [0.05, 0.5], [0.08, 0.3]]}
    now = datetime(2026, 7, 28, 12, 0, tzinfo=timezone.utc)

    def pos(sym, plpc, qty=1.0, side="long"):
        return {"symbol": sym, "qty": qty, "unrealized_plpc": plpc, "side": side}

    # 1) tight stop fires, flattens, opens a cooldown
    d, st = evaluate([pos("BTCUSD", -0.02)], cfg, {}, now=now)
    assert d["BTCUSD"]["close"] and d["BTCUSD"]["block"], d
    assert _parse(st["BTCUSD"]["cooldown_until"]) > now, st

    # the cooldown blocks re-entry even once flat
    d2, st2 = evaluate([], cfg, st, now=now + timedelta(minutes=5))
    assert d2["BTCUSD"]["block"] and not d2["BTCUSD"]["close"], d2
    # ...and expires
    d3, _ = evaluate([], cfg, st, now=now + timedelta(minutes=25))
    assert "BTCUSD" not in d3, d3

    # 2) scale-out ratchets down as profit climbs, holds on the peak after a dip
    d, st = evaluate([pos("ETHUSD", 0.06)], cfg, {}, now=now)
    assert d["ETHUSD"]["cap"] == 0.5 and not d["ETHUSD"]["close"], d
    d, st = evaluate([pos("ETHUSD", 0.055)], cfg, st, now=now)      # dipped, peak stays 0.06
    assert d["ETHUSD"]["cap"] == 0.5, d                          # not re-expanded

    # 3) trailing giveback banks a runner that rolls over
    d, st = evaluate([pos("SOLUSD", 0.05)], cfg, {}, now=now)        # arm the peak at +5%
    d, st = evaluate([pos("SOLUSD", 0.038)], cfg, st, now=now)       # gave back >0.8% from peak
    assert d["SOLUSD"]["close"], d

    # 4) volatility scaling: at 2x normal vol the -1.5% loss must NOT stop (widened to -3%),
    #    while the same loss at normal vol DOES stop.
    d, _ = evaluate([pos("XRPUSD", -0.02)], cfg, {}, vol_ratios={"XRPUSD": 2.0}, now=now)
    assert not d.get("XRPUSD", {}).get("close"), "2x vol must widen the stop past -2%"
    d, _ = evaluate([pos("XRPUSD", -0.02)], cfg, {}, vol_ratios={"XRPUSD": 1.0}, now=now)
    assert d["XRPUSD"]["close"], "at normal vol the -2% loss must still stop"
    # ...and in calm vol the stop tightens
    d, _ = evaluate([pos("XRPUSD", -0.009)], cfg, {}, vol_ratios={"XRPUSD": 0.5}, now=now)
    assert d["XRPUSD"]["close"], "0.5x vol tightens the stop to ~-0.6% -> -0.9% stops"

    # disabled -> no decisions at all
    assert evaluate([pos("BTCUSD", -0.5)], {"enabled": False}, {}, now=now) == ({}, {})
    print("exit_manager self-check ok (Stop, Cooldown, Scale-Out, Trailing, Vol-Scaling)")
