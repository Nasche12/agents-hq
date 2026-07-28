"""Deep, per-trade forensics for the self-improvement loop -- the "look at every detail"
layer the research agent reasons over.

It turns raw fills into the patterns a human trader would eyeball by hand:

  * churn signature   -- how much of the P&L is being eaten alive by over-trading
  * loss clusters     -- where the damage concentrates (worst trades, hour, direction)
  * regime attribution-- which HMM regime the bot was in when a trade was opened
  * news attribution  -- was the money lost while the world was calm or under stress?

Everything is derived from files that already exist: orders.json (fills), journal.jsonl
(the per-cycle decision log) and the news timeline (news_log). No market opinions, no
estimates, no internet. News is used to EXPLAIN outcomes, never as a signal -- it can tell
you a loss happened during a Fed shock, it can never tell the bot to buy. Pure stdlib so
it runs in the token-free evidence step without the numeric stack."""
from collections import defaultdict
from datetime import datetime, timezone

import trade_stats
import news_log

LEVEL_LABELS = {0: "ruhig", 1: "erhoeht", 2: "stress", 3: "krise"}


def _parse(iso):
    try:
        d = datetime.fromisoformat(str(iso).replace("Z", "+00:00"))
        return d if d.tzinfo else d.replace(tzinfo=timezone.utc)
    except Exception:
        return None


def _hold_minutes(t):
    a, b = _parse(t.get("opened")), _parse(t.get("closed"))
    return round((b - a).total_seconds() / 60.0, 1) if a and b else None


def churn(closed):
    """The over-trading signature. A 'scalp' = a round-trip held under 15 minutes that
    closed inside +-0.2%: it never had room to be anything but spread noise. A high scalp
    count with negative scalp P&L is the churn tax made visible."""
    holds = [h for h in (_hold_minutes(t) for t in closed) if h is not None]
    scalps = [t for t in closed
              if (_hold_minutes(t) or 1e9) < 15 and abs(t.get("pnl_pct") or 0) < 0.002]
    return {
        "round_trips": len(closed),
        "median_hold_min": round(sorted(holds)[len(holds) // 2], 1) if holds else None,
        "under_15min_share": round(sum(1 for h in holds if h < 15) / len(holds), 3) if holds else None,
        "scalps": len(scalps),
        "scalp_pnl": round(sum(t["pnl"] for t in scalps), 2),
        "note": "scalps = kurze Round-Trips ohne Raum fuer mehr als Spread-Rauschen",
    }


def loss_clusters(closed, top=8):
    """Where the damage sits: the single worst round-trips, P&L by close-hour (UTC) and by
    direction. Concentration is the signal -- if all the pain is one symbol in one hour,
    that is a lead, not noise."""
    by_hour = defaultdict(lambda: {"pnl": 0.0, "trades": 0})
    side = defaultdict(lambda: {"pnl": 0.0, "trades": 0, "wins": 0})
    for t in closed:
        c = _parse(t.get("closed"))
        if c:
            by_hour[c.hour]["pnl"] += t["pnl"]
            by_hour[c.hour]["trades"] += 1
        s = side[t.get("side", "?")]
        s["pnl"] += t["pnl"]; s["trades"] += 1; s["wins"] += 1 if t["pnl"] > 0 else 0
    worst = sorted(closed, key=lambda t: t["pnl"])[:top]
    return {
        "worst_trades": [{"symbol": t["symbol"], "side": t.get("side"), "pnl": t["pnl"],
                          "pnl_pct": t.get("pnl_pct"), "hold_min": _hold_minutes(t),
                          "opened": t.get("opened")} for t in worst],
        "by_hour_utc": {str(k): {"pnl": round(v["pnl"], 2), "trades": v["trades"]}
                        for k, v in sorted(by_hour.items())},
        "by_side": {k: {"pnl": round(v["pnl"], 2), "trades": v["trades"],
                        "win_rate": round(v["wins"] / v["trades"], 3) if v["trades"] else None}
                    for k, v in side.items()},
    }


def _journal_index(journal):
    """symbol -> sorted [(ts, regime)] from the per-cycle decision log."""
    idx = defaultdict(list)
    for e in journal or []:
        if e.get("type") != "cycle" or not e.get("symbol") or not e.get("regime"):
            continue
        ts = _parse(e.get("ts"))
        if ts:
            idx[e["symbol"]].append((ts, e["regime"]))
    for sym in idx:
        idx[sym].sort()
    return idx


def _regime_at(idx, symbol, opened):
    """Best-effort: the regime the bot last saw for `symbol` at/just before the open."""
    o = _parse(opened)
    if not o:
        return None
    best = None
    for ts, regime in idx.get(symbol, []):
        if ts <= o:
            best = regime
        else:
            break
    return best


def by_regime(closed, journal):
    """Realized P&L grouped by the HMM regime that was live when the trade opened. Answers
    'is the edge actually in the regime the model claims, or does it lose in bull too?'."""
    idx = _journal_index(journal)
    agg = defaultdict(lambda: {"pnl": 0.0, "trades": 0, "wins": 0})
    for t in closed:
        a = agg[_regime_at(idx, t["symbol"], t.get("opened")) or "unbekannt"]
        a["pnl"] += t["pnl"]; a["trades"] += 1; a["wins"] += 1 if t["pnl"] > 0 else 0
    return {k: {"pnl": round(v["pnl"], 2), "trades": v["trades"],
                "win_rate": round(v["wins"] / v["trades"], 3) if v["trades"] else None}
            for k, v in agg.items()}


def news_attribution(closed, timeline):
    """Split realized P&L by the WORST news level active while each trade was open. This is
    the 'always compare with news' requirement done honestly: as attribution, not as a
    signal. An empty timeline (market-watch agent never ran) drops everything into level 0
    -- which is itself the finding: 'we have no news context yet, enable markt-waechter'."""
    buckets = defaultdict(lambda: {"pnl": 0.0, "trades": 0, "wins": 0})
    for t in closed:
        lvl = news_log.max_level_between(timeline, t.get("opened"), t.get("closed"))
        b = buckets[lvl]
        b["pnl"] += t["pnl"]; b["trades"] += 1; b["wins"] += 1 if t["pnl"] > 0 else 0
    out = {LEVEL_LABELS.get(k, str(k)): {
        "level": k, "pnl": round(v["pnl"], 2), "trades": v["trades"],
        "win_rate": round(v["wins"] / v["trades"], 3) if v["trades"] else None}
        for k, v in sorted(buckets.items())}
    return {
        "buckets": out,
        "timeline_points": len(timeline),
        "note": ("kein Nachrichten-Verlauf vorhanden -> markt-waechter aktivieren, sonst "
                 "landet alles in 'ruhig'") if not timeline else
                "P&L nach hoechster aktiver Nachrichtenstufe waehrend der Haltedauer",
    }


def analyze(orders, journal=None, timeline=None, top=8):
    """The full forensic pack from raw fills + decision log + news timeline."""
    closed = trade_stats.realized_trades(orders)
    timeline = timeline if timeline is not None else news_log.load()
    return {
        "round_trips_analyzed": len(closed),
        "churn": churn(closed),
        "loss_clusters": loss_clusters(closed, top=top),
        "by_regime_at_entry": by_regime(closed, journal or []),
        "news_attribution": news_attribution(closed, timeline),
    }


if __name__ == "__main__":
    # Two round-trips: a BTC long that loses during a stress spike, an ETH long that wins
    # while calm. Forensics must attribute the loss to the stress window, not the calm one.
    orders = [
        {"symbol": "BTC/USD", "side": "buy", "filled_qty": "1", "filled_avg_price": "100",
         "status": "filled", "filled_at": "2026-07-28T12:00:00Z"},
        {"symbol": "BTC/USD", "side": "sell", "filled_qty": "1", "filled_avg_price": "90",
         "status": "filled", "filled_at": "2026-07-28T12:05:00Z"},
        {"symbol": "ETH/USD", "side": "buy", "filled_qty": "1", "filled_avg_price": "100",
         "status": "filled", "filled_at": "2026-07-28T14:00:00Z"},
        {"symbol": "ETH/USD", "side": "sell", "filled_qty": "1", "filled_avg_price": "100.1",
         "status": "filled", "filled_at": "2026-07-28T14:05:00Z"},   # +0.1% in 5 min = Scalp
    ]
    timeline = [
        {"ts": "2026-07-28T11:59:00Z", "level": 2},   # stress in force over the BTC trade
        {"ts": "2026-07-28T13:00:00Z", "level": 0},   # calm again before the ETH trade
    ]
    journal = [
        {"type": "cycle", "symbol": "BTC/USD", "regime": "bull", "ts": "2026-07-28T11:59:30Z"},
        {"type": "cycle", "symbol": "ETH/USD", "regime": "bull", "ts": "2026-07-28T13:59:30Z"},
    ]
    r = analyze(orders, journal=journal, timeline=timeline)
    na = r["news_attribution"]["buckets"]
    assert na["stress"]["pnl"] == -10.0 and na["stress"]["trades"] == 1, na
    assert na["ruhig"]["pnl"] == 0.1 and na["ruhig"]["trades"] == 1, na
    assert r["churn"]["scalps"] == 1, r["churn"]        # the +0.1% ETH win is a scalp
    assert r["by_regime_at_entry"]["bull"]["trades"] == 2, r["by_regime_at_entry"]
    assert r["loss_clusters"]["worst_trades"][0]["symbol"] == "BTC/USD"
    print("trade_forensics self-check ok:", r["news_attribution"]["buckets"])
