"""Builds state/dashboard.json -- the single file the Node dashboard's Trading tab reads
(served at /trading.json). It is the complete picture of the bot: market sessions, the
real paper account, per-symbol HMM signals merged with positions and P&L, closed
round-trips with win rate and profit factor, risk breakers, the order book, the decision
journal and the equity curve at two resolutions (fine for hours, coarse for months).

Everything honest: if the bot has never run live, status is 'idle' and live fields are
null, never faked. Numbers that cannot be derived from real fills stay None."""
import json
from datetime import datetime, timedelta, timezone

import settings
import sessions
import trade_stats
from market_data import is_crypto, pos_symbol

FINE_POINTS = 3000        # raw snapshots kept for the 1h/6h/24h windows
COARSE_POINTS = 1200      # downsampled curve for 7d/30d/all


def _read(path, fallback):
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return fallback


def build(symbol=None):
    cfg = settings.load_config()
    exec_cfg = cfg["execution"]
    risk = _read(settings.RISK_STATE, {})
    heartbeat = _read(settings.HEARTBEAT, {})
    positions = _read(settings.POSITIONS, {"open": [], "pending": []})
    orders = _read(settings.ORDERS, [])
    signals = _read(settings.SIGNALS, [])
    bot = _read(settings.BOT_STATE, {})
    open_pos = positions.get("open", [])

    journal = _read_journal()
    orders = _attach_reasons(orders, journal)     # every order carries its own reasoning
    closed = trade_stats.realized_trades(orders)
    stats = trade_stats.summarize(closed)
    per_sym_pnl = trade_stats.by_symbol(closed, open_pos)

    market = heartbeat.get("session_overview") or sessions.market_overview(
        None, exec_cfg.get("extended_hours", True))
    watchlist = cfg["watchlist"]
    crypto_syms = [s for s in watchlist if is_crypto(s)]
    equity_syms = [s for s in watchlist if not is_crypto(s)]

    fine, coarse = _equity_series()
    eq_now = heartbeat.get("account_equity")
    day_open = _equity_at(fine or coarse, hours=24)

    live = {
        "last_cycle": heartbeat.get("ts"),
        "market_open": heartbeat.get("market_open"),
        "longs": heartbeat.get("longs", 0),
        "shorts": heartbeat.get("shorts", 0),
        "tradable_now": heartbeat.get("tradable_now", 0),
        "orders_this_cycle": heartbeat.get("orders_this_cycle", 0),
        "stale_seconds": _age_seconds(heartbeat.get("ts")),
    } if heartbeat else None

    export = {
        "generated": datetime.now(timezone.utc).isoformat(),
        "watchlist": watchlist,
        "universe": {"crypto": crypto_syms, "equity": equity_syms,
                     "crypto_count": len(crypto_syms), "equity_count": len(equity_syms)},
        "mode": "paper",                       # never 'live' until Phase 4
        "status": "running" if heartbeat.get("alive") else "idle",
        "data_source": "alpaca" if heartbeat.get("broker") == "connected" else "n/a",
        "regime_colors": settings.REGIME_COLORS,
        "market": market,                      # which session each asset class is in, right now
        "radar": heartbeat.get("radar") or {},  # crisis / anomaly read, acts instantly (risk-off only)
        "external_risk": _external_risk(),      # calendar + news level, both risk-off only
        "live": live,
        "bot": {
            "cycles": bot.get("cycles", 0),
            "orders_sent": bot.get("orders_sent", 0),
            "errors": bot.get("errors", 0),
            "started": bot.get("started"),
            "last_order": bot.get("last_order"),
            "last_error": bot.get("last_error"),
            "cycle_seconds": exec_cfg.get("cycle_seconds", 60),
            "uptime_hours": _hours_since(bot.get("started")),
            "runs_247": bool(crypto_syms),
        },
        "signals": _merge_signals(signals, open_pos, per_sym_pnl),
        "risk": {
            "equity": risk.get("equity"),
            "peak_equity": risk.get("peak_equity"),
            "day_start_equity": risk.get("day_start_equity"),
            "week_start_equity": risk.get("week_start_equity"),
            "day_dd": _dd(risk.get("equity"), risk.get("day_start_equity")),
            "week_dd": _dd(risk.get("equity"), risk.get("week_start_equity")),
            "peak_dd": _dd(risk.get("equity"), risk.get("peak_equity")),
            "size_multiplier": risk.get("size_multiplier", 1.0),
            "killed": risk.get("killed", False),
            "lock_file": settings.LOCK_FILE.exists(),
            "thresholds": cfg["risk"],
        },
        "positions": positions,
        "account": {                            # the REAL paper account (not the backtest)
            "connected": heartbeat.get("broker") == "connected",
            "cash": heartbeat.get("cash"),
            "equity": eq_now,
            "buying_power": heartbeat.get("buying_power"),
            "day_change": _delta(eq_now, day_open),
            "day_change_pct": _dd(eq_now, day_open),
            "total_change": _delta(eq_now, cfg.get("starting_equity")),
            "total_change_pct": _dd(eq_now, cfg.get("starting_equity")),
            "starting_equity": cfg.get("starting_equity"),
            "open_positions": open_pos,
            "orders_placed": heartbeat.get("orders_placed", 0),
            "trading_enabled": exec_cfg.get("trading_enabled", False),
            "per_trade_cap": exec_cfg["max_notional_per_trade"],
            "max_margin": exec_cfg.get("max_margin", 0),
            "rebalance_min_pct": exec_cfg.get("rebalance_min_pct", 0.02),
            "extended_hours": exec_cfg.get("extended_hours", True),
            "budget": exec_cfg["max_notional_per_trade"] * len(watchlist),
            "deployed": round(sum(abs(float(p.get("market_value", 0))) for p in open_pos), 2),
            "unrealized_pl": round(sum(float(p.get("unrealized_pl") or 0) for p in open_pos), 2),
            "longs": heartbeat.get("longs", 0),
            "shorts": heartbeat.get("shorts", 0),
        },
        "orders": orders,                       # real filled/placed orders (clickable detail)
        "trades": closed[:200],                 # FIFO-matched closed round-trips
        "trade_stats": dict(stats, **_activity_counts(orders, closed)),
        "per_symbol": per_sym_pnl,
        "learning": _learning(cfg),             # what the research agent changed, and why
        "journal_tail": _journal_tail(120, journal),   # real bot decisions incl. skips
        "decisions_by_symbol": _decisions_by_symbol(journal),  # per-asset audit trail
        "equity_history": fine,                 # [[iso, equity, cash], ...] fine resolution
        "equity_history_coarse": coarse,        # downsampled, for long time ranges
    }
    payload = json.dumps(export, indent=2)
    settings.DASHBOARD_EXPORT.write_text(payload, encoding="utf-8")
    # mirror to the public docroot so Plesk serves it statically at /trading.json
    try:
        if settings.PUBLIC_TRADING.parent.exists():
            settings.PUBLIC_TRADING.write_text(payload, encoding="utf-8")
    except Exception:
        pass
    return export


def _external_risk():
    """Scheduled events and the news agent's level, read fresh so the dashboard shows the
    CURRENT state even between bot cycles. Never triggers anything -- reading only."""
    try:
        import external_risk
        out = external_risk.assess()
        return {k: out[k] for k in ("multiplier", "event_multiplier", "news_multiplier",
                                    "events", "news", "reasons")}
    except Exception as e:
        return {"multiplier": 1.0, "error": str(e)[:120]}


def _learning(cfg):
    """Self-improvement status: which parameters the agent changed versus the human
    baseline, the last research verdict, and the memory counters. Reading only --
    the dashboard never triggers a run."""
    lcfg = cfg.get("learning", {})
    report = _read(settings.LEARNING_REPORT, None)
    baseline = settings.load_baseline()
    overrides = {k: {"now": v, "baseline": _flat_get(baseline, k)}
                 for k, v in settings.flatten(settings.load_local_overrides()).items()}
    mem = _memory_summary()
    return {
        "enabled": bool(lcfg.get("enabled")),
        "tunable": sorted(lcfg.get("bounds", {})),
        "locked": lcfg.get("locked_prefixes", []),
        "overrides": overrides,
        "override_count": len(overrides),
        "memory": mem,
        "last_run": {
            "generated": (report or {}).get("generated"),
            "tested": (report or {}).get("tested"),
            "champion_objective": (report or {}).get("champion_objective"),
            "promoted": (report or {}).get("promoted"),
            "holdout": (report or {}).get("holdout"),
            "candidates": [{k: c.get(k) for k in
                            ("hypothesis", "objective", "reason", "passes_selection", "trades")}
                           for c in ((report or {}).get("candidates") or [])],
        } if report else None,
    }


def _memory_summary():
    """Counters straight from the ledger. Kept dependency-light so the export never
    fails just because the research stack is missing."""
    if not settings.MEMORY.exists():
        return {"total": 0, "accepted": 0, "rejected": 0}
    total = accepted = rejected = 0
    for line in settings.MEMORY.read_text(encoding="utf-8").splitlines():
        try:
            e = json.loads(line)
        except Exception:
            continue
        total += 1
        accepted += e.get("verdict") == "accepted"
        rejected += e.get("verdict") == "rejected"
    return {"total": total, "accepted": accepted, "rejected": rejected}


def _flat_get(cfg, dotted):
    node = cfg
    for p in dotted.split("."):
        if not isinstance(node, dict) or p not in node:
            return None
        node = node[p]
    return node


def _merge_signals(signals, open_pos, per_sym):
    """One row per symbol carrying EVERYTHING: regime, target, session, live position
    and its P&L -- so the dashboard table never has to join anything client-side."""
    held = {pos_symbol(p["symbol"]): p for p in open_pos}
    out = []
    for s in signals:
        p = held.get(pos_symbol(s.get("symbol", "")))
        pl = per_sym.get(s.get("symbol"), {})
        out.append(dict(s, **{
            "held_qty": p["qty"] if p else 0,
            "market_value": p.get("market_value") if p else None,
            "unrealized_pl": p.get("unrealized_pl") if p else None,
            "unrealized_plpc": p.get("unrealized_plpc") if p else None,
            "avg_entry": p.get("avg_entry") if p else None,
            "realized_pl": pl.get("realized"),
            "closed_trades": pl.get("trades", 0),
        }))
    return out


def _activity_counts(orders, closed):
    """How busy the bot actually is -- the answer to 'is it trading enough?'."""
    now = datetime.now(timezone.utc)
    d1 = now - timedelta(hours=24)
    d7 = now - timedelta(days=7)
    filled = [o for o in orders or [] if (o.get("status") or "").lower() == "filled"]
    t24 = [o for o in filled if _after(o.get("filled_at") or o.get("submitted_at"), d1)]
    t7 = [o for o in filled if _after(o.get("filled_at") or o.get("submitted_at"), d7)]
    return {
        "orders_total": len(orders or []),
        "orders_filled": len(filled),
        "orders_24h": len(t24),
        "orders_7d": len(t7),
        "volume_24h": round(sum(float(o.get("notional") or 0) for o in t24), 2),
        "volume_total": round(sum(float(o.get("notional") or 0) for o in filled), 2),
        "buys": sum(1 for o in filled if o.get("side") == "buy"),
        "sells": sum(1 for o in filled if o.get("side") == "sell"),
        "crypto_orders": sum(1 for o in filled if is_crypto(o.get("symbol") or "")),
        "equity_orders": sum(1 for o in filled if not is_crypto(o.get("symbol") or "")),
        "closed_24h": sum(1 for t in closed if _after(t.get("closed"), d1)),
    }


def _equity_series():
    """Two resolutions of the real account balance:
       fine   -> the last FINE_POINTS raw snapshots (minute detail for 1h/6h/24h views)
       coarse -> the whole history downsampled to COARSE_POINTS (7d/30d/all views)
    Rows are [iso, equity, cash]."""
    if not settings.EQUITY_HISTORY.exists():
        return [], []
    rows = []
    for line in settings.EQUITY_HISTORY.read_text(encoding="utf-8").splitlines():
        try:
            e = json.loads(line)
            cash = e.get("cash")
            rows.append([e["ts"], round(float(e["equity"]), 2),
                         round(float(cash), 2) if cash is not None else None])
        except Exception:
            continue
    fine = rows[-FINE_POINTS:]
    if len(rows) <= COARSE_POINTS:
        return fine, rows
    step = len(rows) / float(COARSE_POINTS)
    coarse = [rows[int(i * step)] for i in range(COARSE_POINTS)]
    if coarse[-1] is not rows[-1]:
        coarse.append(rows[-1])
    return fine, coarse


def _equity_at(rows, hours):
    """Equity value roughly `hours` ago -- the baseline for the day-change number."""
    if not rows:
        return None
    cutoff = datetime.now(timezone.utc) - timedelta(hours=hours)
    for r in rows:
        t = _parse(r[0])
        if t and t >= cutoff:
            return r[1]
    return rows[0][1]


JOURNAL_SCAN = 20000      # lines read from the tail of the journal
PER_SYMBOL_DECISIONS = 60  # decisions kept per symbol for the drill-down


def _read_journal():
    """Cycle entries from the tail of the journal, oldest first."""
    if not settings.JOURNAL.exists():
        return []
    out = []
    for line in settings.JOURNAL.read_text(encoding="utf-8").splitlines()[-JOURNAL_SCAN:]:
        try:
            e = json.loads(line)
        except Exception:
            continue
        if e.get("type") == "cycle":
            out.append(e)
    return out


def _decision_row(e):
    """One auditable decision. `factors` is the reasoning kept SEPARATE, so the UI can
    list what moved the outcome instead of showing one glued-together sentence."""
    return {
        "ts": e.get("ts"), "symbol": e.get("symbol"), "decision": e.get("decision"),
        "regime": e.get("regime"), "regime_rank": e.get("regime_rank"),
        "n_regimes": e.get("n_regimes"), "confidence": e.get("confidence"),
        "session": e.get("session"), "exposure": e.get("exposure"),
        "raw_exposure": e.get("raw_exposure"), "price": e.get("price"),
        "target_notional": e.get("target_notional"), "budget": e.get("budget"),
        "stable": e.get("stable"), "tradable": e.get("tradable"),
        "risk_multiplier": e.get("risk_multiplier"), "breakers": e.get("breakers") or [],
        "radar_level": e.get("radar_level"), "radar_multiplier": e.get("radar_multiplier"),
        "deadband": e.get("deadband"),
        "factors": e.get("factors") or ([e["reason"]] if e.get("reason") else []),
        "reason": e.get("reason"),
        "order": e.get("order"),
        "order_id": (e.get("order") or {}).get("order_id"),
    }


def _journal_tail(n, entries=None):
    """Last n decisions across all symbols -- the bot's real observe/act log."""
    src = entries if entries is not None else _read_journal()
    return [_decision_row(e) for e in src[-n:]][::-1]


def _decisions_by_symbol(entries):
    """Every symbol's own history, newest first. This is what makes "why did it do that
    with NVDA" answerable without grepping a JSONL file on the server."""
    out = {}
    for e in entries:
        out.setdefault(e.get("symbol") or "?", []).append(e)
    return {sym: [_decision_row(e) for e in rows[-PER_SYMBOL_DECISIONS:]][::-1]
            for sym, rows in out.items()}


def _attach_reasons(orders, entries):
    """Join each real order to the decision that produced it, via the Alpaca order id.
    An order in the UI must never be a bare number -- the reasoning that caused it has
    to travel with it."""
    by_id = {}
    for e in entries:
        oid = (e.get("order") or {}).get("order_id")
        if oid:
            by_id[str(oid)] = e
    out = []
    for o in orders or []:
        e = by_id.get(str(o.get("id")))
        why = None
        if e:
            why = {
                "ts": e.get("ts"), "decision": e.get("decision"), "regime": e.get("regime"),
                "confidence": e.get("confidence"), "exposure": e.get("exposure"),
                "raw_exposure": e.get("raw_exposure"), "session": e.get("session"),
                "risk_multiplier": e.get("risk_multiplier"),
                "radar_level": e.get("radar_level"),
                "radar_multiplier": e.get("radar_multiplier"),
                "target_notional": e.get("target_notional"), "budget": e.get("budget"),
                "factors": e.get("factors") or [],
                "reason": e.get("reason"),
                "action": (e.get("order") or {}).get("action"),
                "from_qty": (e.get("order") or {}).get("from"),
                "to_qty": (e.get("order") or {}).get("target"),
            }
        out.append(dict(o, why=why))
    return out


def _dd(equity, base):
    if not equity or not base:
        return None
    return round(equity / base - 1, 4)


def _delta(a, b):
    if a is None or b is None:
        return None
    return round(a - b, 2)


def _parse(iso):
    try:
        return datetime.fromisoformat(str(iso).replace("Z", "+00:00"))
    except Exception:
        return None


def _after(iso, cutoff):
    t = _parse(iso)
    return bool(t and t >= cutoff)


def _age_seconds(iso):
    t = _parse(iso)
    if not t:
        return None
    return int((datetime.now(timezone.utc) - t).total_seconds())


def _hours_since(iso):
    s = _age_seconds(iso)
    return round(s / 3600.0, 1) if s is not None else None


if __name__ == "__main__":
    e = build("SPY")
    print(f"dashboard export -> {settings.DASHBOARD_EXPORT}")
    print(f"status={e['status']} mode={e['mode']} account_connected={e['account']['connected']} "
          f"positions={len(e['account']['open_positions'])} orders={e['account']['orders_placed']} "
          f"closed_trades={e['trade_stats']['trades']} 24/7={e['bot']['runs_247']}")
    print(f"market: equity={e['market']['equity_label']} crypto=24/7 · "
          f"equity_points fine={len(e['equity_history'])} coarse={len(e['equity_history_coarse'])}")
