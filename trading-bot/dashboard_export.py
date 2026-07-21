"""Builds state/dashboard.json -- the single file the Node dashboard's Trading tab reads
(served at /trading.json). Merges the latest backtest result (performance + analytics)
with live status (heartbeat, risk state, positions). Everything honest: if the bot has
never run live, status is 'idle' and the live fields are null, not faked."""
import json
from datetime import datetime, timezone

import settings


def _read(path, fallback):
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return fallback


def build(symbol=None):
    cfg = settings.load_config()
    risk = _read(settings.RISK_STATE, {})
    heartbeat = _read(settings.HEARTBEAT, {})
    positions = _read(settings.POSITIONS, {"open": [], "pending": []})
    orders = _read(settings.ORDERS, [])
    signals = _read(settings.SIGNALS, [])

    live = {
        "last_cycle": heartbeat.get("ts"),
        "market_open": heartbeat.get("market_open"),
        "longs": heartbeat.get("longs", 0),
        "shorts": heartbeat.get("shorts", 0),
    } if heartbeat else None

    export = {
        "generated": datetime.now(timezone.utc).isoformat(),
        "watchlist": cfg["watchlist"],
        "mode": "paper",                       # never 'live' until Phase 4
        "status": "running" if heartbeat.get("alive") else "idle",
        "data_source": "alpaca" if heartbeat.get("broker") == "connected" else "n/a",
        "regime_colors": settings.REGIME_COLORS,
        "live": live,
        "signals": signals,                     # per-symbol HMM regime + target exposure
        "risk": {
            "equity": risk.get("equity"),
            "peak_equity": risk.get("peak_equity"),
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
            "equity": heartbeat.get("account_equity"),
            "open_positions": positions.get("open", []),
            "orders_placed": heartbeat.get("orders_placed", 0),
            "trading_enabled": cfg["execution"].get("trading_enabled", False),
            "per_trade_cap": cfg["execution"]["max_notional_per_trade"],
            "max_margin": cfg["execution"].get("max_margin", 0),
            "budget": cfg["execution"]["max_notional_per_trade"] * len(cfg["watchlist"]),
            "deployed": round(sum(abs(float(p.get("market_value", 0))) for p in positions.get("open", [])), 2),
            "longs": heartbeat.get("longs", 0),
            "shorts": heartbeat.get("shorts", 0),
        },
        "orders": orders,                       # real filled/placed orders (clickable detail)
        "journal_tail": _journal_tail(20),      # real bot decisions incl. skips (no orders yet)
        "equity_history": _equity_history(1000),  # real account balance over time (the live chart)
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


def _equity_history(n):
    """Real account equity snapshots [[iso, equity], ...] -- the live balance chart."""
    if not settings.EQUITY_HISTORY.exists():
        return []
    out = []
    for line in settings.EQUITY_HISTORY.read_text(encoding="utf-8").splitlines():
        try:
            e = json.loads(line)
            out.append([e["ts"], round(float(e["equity"]), 2)])
        except Exception:
            continue
    return out[-n:]


def _journal_tail(n):
    """Last n 'cycle' decisions from the journal -- the bot's real observe/act log."""
    if not settings.JOURNAL.exists():
        return []
    out = []
    for line in settings.JOURNAL.read_text(encoding="utf-8").splitlines():
        try:
            e = json.loads(line)
        except Exception:
            continue
        if e.get("type") == "cycle":
            out.append({"ts": e.get("ts"), "decision": e.get("decision"), "regime": e.get("regime"),
                        "confidence": e.get("confidence"), "reason": e.get("reason")})
    return out[-n:][::-1]


def _dd(equity, base):
    if not equity or not base:
        return None
    return round(equity / base - 1, 4)


if __name__ == "__main__":
    e = build("SPY")
    print(f"dashboard export -> {settings.DASHBOARD_EXPORT}")
    print(f"status={e['status']} mode={e['mode']} account_connected={e['account']['connected']} "
          f"positions={len(e['account']['open_positions'])} orders={e['account']['orders_placed']}")
