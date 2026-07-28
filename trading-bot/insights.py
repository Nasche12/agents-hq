"""The 24/7 observation layer -- the part of the memory that finds CONNECTIONS.

The hypothesis ledger (memory.py) records "we tried parameter X, the holdout said Y". This
file records something different and cheaper: "trades that share these CONDITIONS keep
losing". It mines every closed round-trip for co-occurring tags -- symbol, direction, the
HMM regime at entry, the news level during the hold, whether it was a scalp -- and surfaces
the single tags AND the PAIRS ("verknüpfungen") whose win-rate departs hardest from the
baseline.

Two deliberate boundaries, because they are what keep this honest:

  * It OBSERVES, it does not ACT. An insight is descriptive knowledge, not a parameter
    change. It becomes a real change only after the research loop turns it into a hypothesis
    and the walk-forward + holdout gate approves it. Auto-applying a pattern the moment it
    "looks good" is exactly the overfitting this whole system exists to prevent.
  * It is pure and deterministic. Same trades in -> same insights out. It can run every
    cycle without a model, a network call, or a token.

Persistence gives the "learns over time" property: insights.json holds the current picture
(rewritten each pass), and insights.jsonl appends a dated line the FIRST time a connection
becomes significant -- so the memory of "when did we first notice this" accrues 24/7."""
import json
from collections import defaultdict
from datetime import datetime, timezone
from itertools import combinations

import settings
import trade_stats
import news_log
import trade_forensics

DIMENSIONS = ("symbol", "side", "regime", "news", "hold")


def _now_iso():
    return datetime.now(timezone.utc).isoformat()


def _tags(trade, journal_index, timeline):
    """The condition tags for one round-trip. Missing values are dropped, never guessed."""
    hold_min = trade_forensics._hold_minutes(trade)
    scalp = (hold_min is not None and hold_min < 15
             and abs(trade.get("pnl_pct") or 0) < 0.002)
    hold = "scalp" if scalp else ("kurz" if (hold_min or 1e9) < 60 else "gehalten")
    regime = trade_forensics._regime_at(journal_index, trade["symbol"], trade.get("opened"))
    lvl = news_log.max_level_between(timeline, trade.get("opened"), trade.get("closed"))
    tags = {"symbol": trade["symbol"], "side": trade.get("side"),
            "hold": hold, "news": trade_forensics.LEVEL_LABELS.get(lvl, str(lvl))}
    if regime:
        tags["regime"] = regime
    return {k: v for k, v in tags.items() if v is not None}


def _stat():
    return {"trades": 0, "wins": 0, "pnl": 0.0}


def _fold(acc, trade):
    acc["trades"] += 1
    acc["wins"] += 1 if trade["pnl"] > 0 else 0
    acc["pnl"] += trade["pnl"]


def mine(closed, journal, timeline, min_support=None, min_lift=0.15):
    """Single-tag and pairwise associations whose win-rate departs from the baseline by at
    least `min_lift`, backed by at least `min_support` trades. Pairs are the connections."""
    if not closed:
        return {"baseline_win_rate": None, "n_trades": 0, "insights": []}
    idx = trade_forensics._journal_index(journal)
    baseline = sum(1 for t in closed if t["pnl"] > 0) / len(closed)
    min_support = min_support if min_support is not None else max(8, int(0.05 * len(closed)))

    singles = defaultdict(_stat)      # ("regime=bull",) -> stat
    pairs = defaultdict(_stat)        # ("hold=scalp","news=ruhig") -> stat
    for t in closed:
        tg = _tags(t, idx, timeline)
        items = [f"{k}={v}" for k, v in tg.items()]
        for it in items:
            _fold(singles[(it,)], t)
        for a, b in combinations(sorted(items), 2):
            if a.split("=")[0] == b.split("=")[0]:
                continue                      # never pair a dimension with itself
            _fold(pairs[(a, b)], t)

    out = []
    for kind, store in (("einzeln", singles), ("verknuepfung", pairs)):
        for key, s in store.items():
            if s["trades"] < min_support:
                continue
            wr = s["wins"] / s["trades"]
            lift = wr - baseline
            if abs(lift) < min_lift:
                continue
            out.append({
                "key": " & ".join(key), "kind": kind,
                "conditions": list(key),
                "trades": s["trades"], "win_rate": round(wr, 3),
                "avg_pnl": round(s["pnl"] / s["trades"], 2), "total_pnl": round(s["pnl"], 2),
                "lift": round(lift, 3),
                "signal": "verliert" if lift < 0 else "gewinnt",
            })
    # Rank by realised impact: how much money the pattern moved, worst first.
    out.sort(key=lambda i: (i["total_pnl"], -i["trades"]))
    return {"baseline_win_rate": round(baseline, 3), "n_trades": len(closed), "insights": out}


def _seen_keys():
    keys = set()
    try:
        for line in settings.INSIGHTS_LOG.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if line:
                try:
                    keys.add(json.loads(line)["key"])
                except Exception:
                    continue
    except Exception:
        pass
    return keys


def refresh(top=14, min_abs_pnl=25.0):
    """Recompute the current picture from live files and persist it. Cheap and idempotent:
    if the number of closed round-trips has not changed since the last pass, it does
    nothing. Safe to call every cycle -- never raises, never blocks the trading loop."""
    try:
        orders = json.loads(settings.ORDERS.read_text(encoding="utf-8"))
    except Exception:
        return None
    closed = trade_stats.realized_trades(orders)

    prev = {}
    try:
        prev = json.loads(settings.INSIGHTS.read_text(encoding="utf-8"))
    except Exception:
        prev = {}
    if prev.get("n_trades") == len(closed) and closed:
        return None                            # nothing new closed -> nothing to learn

    journal = []
    try:
        journal = [json.loads(l) for l in
                   settings.JOURNAL.read_text(encoding="utf-8").splitlines()[-20000:] if l.strip()]
    except Exception:
        journal = []
    timeline = news_log.load()

    res = mine(closed, journal, timeline)
    strong = res["insights"][:top]
    payload = {"generated": _now_iso(), "baseline_win_rate": res["baseline_win_rate"],
               "n_trades": res["n_trades"], "insights": strong}
    try:
        settings.INSIGHTS.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    except Exception:
        return None

    # The "learned over time" trail: the FIRST time a materially-impactful connection turns
    # significant, stamp it. A recurring loss connection is exactly what the researcher
    # should be handed as a hypothesis seed next run.
    seen, new = _seen_keys(), 0
    for ins in strong:
        if ins["key"] in seen or abs(ins["total_pnl"]) < min_abs_pnl:
            continue
        try:
            with open(settings.INSIGHTS_LOG, "a", encoding="utf-8") as f:
                f.write(json.dumps({"ts": _now_iso(), **ins}) + "\n")
            new += 1
        except Exception:
            break
    return {"n_trades": res["n_trades"], "strong": len(strong), "new": new}


def current(top=14):
    """The strongest current connections, for the evidence pack and the dashboard."""
    try:
        return json.loads(settings.INSIGHTS.read_text(encoding="utf-8"))
    except Exception:
        return {"n_trades": 0, "insights": [], "baseline_win_rate": None}


if __name__ == "__main__":
    import tempfile
    from pathlib import Path
    tmp = Path(tempfile.mkdtemp())
    settings.INSIGHTS = tmp / "insights.json"
    settings.INSIGHTS_LOG = tmp / "insights.jsonl"

    # 20 losing scalps + 20 winning holds -> the connection "hold=scalp verliert" must surface.
    closed = []
    for i in range(20):
        closed.append({"symbol": "LINK/USD", "side": "long", "pnl": -5.0, "pnl_pct": -0.001,
                       "opened": "2026-07-28T02:00:00Z", "closed": "2026-07-28T02:05:00Z"})
    for i in range(20):
        closed.append({"symbol": "BTC/USD", "side": "long", "pnl": +8.0, "pnl_pct": 0.02,
                       "opened": "2026-07-28T02:00:00Z", "closed": "2026-07-28T04:00:00Z"})
    res = mine(closed, [], [])
    keys = {i["key"]: i for i in res["insights"]}
    assert "hold=scalp" in keys and keys["hold=scalp"]["signal"] == "verliert", keys
    # a connection (pair) must appear and point at the losing scalps
    pairs = [i for i in res["insights"] if i["kind"] == "verknuepfung"]
    assert any("hold=scalp" in i["key"] and i["signal"] == "verliert" for i in pairs), pairs
    assert res["insights"][0]["total_pnl"] < 0, "worst-impact insight ranks first"
    print("insights self-check ok · baseline", res["baseline_win_rate"],
          "· top:", res["insights"][0]["key"], res["insights"][0]["total_pnl"])
