"""The gate between "the data approved it" and "the live bot uses it".

Design rules, in order of importance:

1. ALLOWLIST, not blocklist. A parameter is changeable only if it appears in
   learning.bounds with an explicit range. Anything else is refused -- including
   anything the agent invents. Risk thresholds, order caps, trading_enabled and the
   watchlist are deliberately absent: a system allowed to loosen its own safety limits
   has none.
2. It writes config.local.json, NOT config.json. config.json is tracked in git and owned
   by `git pull`; if the agent edited it, every deploy would collide. Deleting
   config.local.json is a complete rollback to the human baseline.
3. Every promotion is logged with the PREVIOUS value, so any single change can be undone
   without guessing what it used to be.
"""
import json
import sys
from datetime import datetime, timezone

import settings


class Rejected(Exception):
    """A change that must never reach the live bot."""


def _lcfg():
    return settings.load_config().get("learning", {})


def validate(changes):
    """(clean_changes, problems). Raises nothing -- the caller decides what to do."""
    lcfg = _lcfg()
    bounds = lcfg.get("bounds", {})
    locked = tuple(lcfg.get("locked_prefixes", []))
    clean, problems = {}, []

    for key, value in (changes or {}).items():
        key = str(key)
        if key.startswith(locked) or any(key == p.rstrip(".") for p in locked):
            problems.append(f"{key}: gesperrt (Sicherheits-/Strukturparameter)")
            continue
        spec = bounds.get(key)
        if spec is None:
            problems.append(f"{key}: nicht in der Allowlist")
            continue
        if "choices" in spec:
            if value not in spec["choices"]:
                problems.append(f"{key}={value!r}: erlaubt sind {spec['choices']}")
                continue
            clean[key] = value
            continue
        if not isinstance(value, (int, float)) or isinstance(value, bool):
            problems.append(f"{key}={value!r}: Zahl erwartet")
            continue
        lo, hi = spec.get("min"), spec.get("max")
        if (lo is not None and value < lo) or (hi is not None and value > hi):
            problems.append(f"{key}={value}: ausserhalb [{lo}, {hi}]")
            continue
        # keep ints int (cycle_seconds, stability_min_bars, ...)
        cur = settings.flat_get(settings.load_config(), key)
        clean[key] = int(value) if isinstance(cur, int) and not isinstance(cur, bool) else float(value)

    return clean, problems


def apply(changes, reason="", memory_id=None, dry_run=False):
    """Write approved changes to config.local.json. Returns the promotion record."""
    clean, problems = validate(changes)
    if problems:
        raise Rejected("; ".join(problems))
    if not clean:
        raise Rejected("keine anwendbaren Aenderungen")

    before = {k: settings.flat_get(settings.load_config(), k) for k in clean}
    merged = settings._deep_merge(settings.load_local_overrides(), settings.expand_flat(clean))
    record = {
        "ts": datetime.now(timezone.utc).isoformat(),
        "changes": clean, "before": before, "reason": reason, "memory_id": memory_id,
        "dry_run": bool(dry_run),
    }
    if dry_run:
        return record

    settings.CONFIG_LOCAL.write_text(json.dumps(merged, indent=2) + "\n", encoding="utf-8")
    settings.invalidate_config_cache()      # coarse mtime granularity would hide this write
    with open(settings.CONFIG_HISTORY, "a", encoding="utf-8") as f:
        f.write(json.dumps(record) + "\n")
    return record


def history(limit=50):
    if not settings.CONFIG_HISTORY.exists():
        return []
    out = []
    for line in settings.CONFIG_HISTORY.read_text(encoding="utf-8").splitlines():
        try:
            out.append(json.loads(line))
        except Exception:
            continue
    return out[-limit:][::-1]


def active_overrides():
    """What the agent has changed versus the human baseline, as a flat diff."""
    local = settings.flatten(settings.load_local_overrides())
    base = settings.load_baseline()
    return {k: {"now": v, "baseline": settings.flat_get(base, k)} for k, v in local.items()}


def revert_all():
    """Full rollback to config.json. One file removed, nothing else touched."""
    existed = settings.CONFIG_LOCAL.exists()
    settings.CONFIG_LOCAL.unlink(missing_ok=True)
    settings.invalidate_config_cache()
    if existed:
        with open(settings.CONFIG_HISTORY, "a", encoding="utf-8") as f:
            f.write(json.dumps({"ts": datetime.now(timezone.utc).isoformat(),
                                "action": "revert_all"}) + "\n")
    return existed


def _unset(nested, dotted):
    """Remove a dotted key from a nested dict (used when a parameter had no previous
    value at all -- restoring it means dropping the override, not writing None)."""
    parts = dotted.split(".")
    node = nested
    for p in parts[:-1]:
        if not isinstance(node.get(p), dict):
            return
        node = node[p]
    node.pop(parts[-1], None)


def revert_last():
    """Undo the most recent promotion that is still in effect, restoring the exact
    previous values. Repeated calls walk further back one promotion at a time --
    each revert marks the promotion it consumed, so nothing is undone twice."""
    pending = 0                       # reverts seen but not yet matched to a promotion
    for rec in history(1000):         # newest first
        if rec.get("action") == "revert_all":
            return None               # everything below this line is already rolled back
        if rec.get("action") == "revert_last":
            pending += 1
            continue
        if rec.get("dry_run"):
            continue
        if pending:                   # this promotion was already undone by an earlier revert
            pending -= 1
            continue

        before = rec.get("before") or {}
        merged = settings.load_local_overrides()
        restore = {}
        for key, value in before.items():
            if value is None:
                _unset(merged, key)
            else:
                merged = settings._deep_merge(merged, settings.expand_flat({key: value}))
                restore[key] = value
        settings.CONFIG_LOCAL.write_text(json.dumps(merged, indent=2) + "\n", encoding="utf-8")
        settings.invalidate_config_cache()
        with open(settings.CONFIG_HISTORY, "a", encoding="utf-8") as f:
            f.write(json.dumps({"ts": datetime.now(timezone.utc).isoformat(),
                                "action": "revert_last", "restored": restore,
                                "undid": rec.get("changes")}) + "\n")
        return restore
    return None


def _print_status():
    act = active_overrides()
    if not act:
        print("Keine Agent-Overrides aktiv — der Bot laeuft exakt auf config.json.")
        return
    print(f"{len(act)} aktive Agent-Overrides (config.local.json):")
    for k, v in act.items():
        print(f"  {k}: {v['baseline']}  ->  {v['now']}")


if __name__ == "__main__":
    arg = sys.argv[1] if len(sys.argv) > 1 else "status"
    if arg == "status":
        _print_status()
    elif arg == "revert":
        print("zurueckgesetzt" if revert_all() else "nichts zu tun (kein config.local.json)")
    elif arg == "revert-last":
        print("wiederhergestellt:", revert_last())
    elif arg == "selftest":
        # the allowlist must hold even against deliberately hostile input
        for bad in ({"risk.kill_from_peak_pct": 0.9},
                    {"execution.trading_enabled": False},
                    {"execution.max_notional_per_trade": 999999},
                    {"watchlist": ["DOGE/USD"]},
                    {"allocation.min_change_threshold": 0.99},
                    {"hmm.live_timeframe": "1Min"},
                    {"learning.bounds": {}},
                    {"totally.made.up": 1}):
            try:
                apply(bad, dry_run=True)
                raise AssertionError(f"MUST have been rejected: {bad}")
            except Rejected:
                pass
        ok = apply({"allocation.min_change_threshold": 0.03}, dry_run=True)
        assert ok["changes"] == {"allocation.min_change_threshold": 0.03}, ok
        assert ok["before"]["allocation.min_change_threshold"] is not None
        i = apply({"execution.cycle_seconds": 120.0}, dry_run=True)
        assert i["changes"]["execution.cycle_seconds"] == 120 and isinstance(
            i["changes"]["execution.cycle_seconds"], int), "int params must stay int"
        print("promote self-check ok (alle gesperrten Aenderungen abgewiesen)")
    else:
        print(__doc__)
