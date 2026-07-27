"""Market sessions -- the honest answer to "can this symbol trade RIGHT NOW?".

There is no 24/7 for US equities. They trade Mon-Fri only:
    pre-market   04:00-09:30 ET   (extended, limit orders only)
    regular      09:30-16:00 ET
    after-hours  16:00-20:00 ET   (extended, limit orders only)
Crypto on Alpaca trades 24/7/365 -- that is what actually keeps the bot busy at night
and on weekends. This module answers per symbol, never globally, so the bot can be
long BTC at 3am while every equity in the watchlist is correctly marked closed."""
from datetime import datetime, time as dtime, timedelta, timezone

import market_data

try:                                        # stdlib on 3.9+, needs system tzdata
    from zoneinfo import ZoneInfo
    _ET = ZoneInfo("America/New_York")
except Exception:                           # pragma: no cover - fallback for bare images
    _ET = None

PRE_OPEN = dtime(4, 0)
REG_OPEN = dtime(9, 30)
REG_CLOSE = dtime(16, 0)
POST_CLOSE = dtime(20, 0)


def _now_et(now=None):
    now = now or datetime.now(timezone.utc)
    if now.tzinfo is None:
        now = now.replace(tzinfo=timezone.utc)
    if _ET is not None:
        return now.astimezone(_ET)
    # crude DST fallback when tzdata is missing (Mar-Oct -> UTC-4, else UTC-5)
    offset = -4 if 3 <= now.month <= 10 else -5
    return now.astimezone(timezone(timedelta(hours=offset)))


def equity_session(clock=None, now=None):
    """'regular' | 'pre' | 'after' | 'closed'.
    Alpaca's clock is authoritative for 'regular' (it knows holidays + DST); the ET
    wall-clock window decides pre/after, which the clock endpoint does not report."""
    if clock and clock.get("is_open"):
        return "regular"
    et = _now_et(now)
    if et.weekday() >= 5:
        return "closed"
    t = et.time()
    if clock and not clock.get("is_open") and PRE_OPEN <= t < REG_OPEN:
        return "pre"
    if clock and not clock.get("is_open") and REG_CLOSE <= t < POST_CLOSE:
        return "after"
    if clock:
        return "closed"
    # no broker clock (offline): fall back to the pure wall-clock windows
    if REG_OPEN <= t < REG_CLOSE:
        return "regular"
    if PRE_OPEN <= t < REG_OPEN:
        return "pre"
    if REG_CLOSE <= t < POST_CLOSE:
        return "after"
    return "closed"


def symbol_session(symbol, clock=None, allow_extended=True, now=None):
    """(session, tradable, extended) for one symbol.
      crypto  -> ('crypto', True, False)   always, 24/7
      equity  -> ('regular'|'pre'|'after'|'closed', bool, bool)
    extended=True means the order must be a LIMIT order flagged extended_hours."""
    if market_data.is_crypto(symbol):
        return "crypto", True, False
    s = equity_session(clock, now)
    if s == "regular":
        return s, True, False
    if s in ("pre", "after"):
        return s, bool(allow_extended), bool(allow_extended)
    return "closed", False, False


SESSION_LABEL = {
    "crypto": "24/7 crypto", "regular": "regular hours", "pre": "pre-market",
    "after": "after-hours", "closed": "closed",
}


def market_overview(clock=None, allow_extended=True, now=None):
    """Everything the dashboard needs to explain WHY something is or isn't trading."""
    eq = equity_session(clock, now)
    return {
        "equity_session": eq,
        "equity_label": SESSION_LABEL.get(eq, eq),
        "equity_tradable": eq == "regular" or (allow_extended and eq in ("pre", "after")),
        "extended_enabled": bool(allow_extended),
        "crypto_session": "crypto",
        "crypto_tradable": True,
        "next_open": (clock or {}).get("next_open"),
        "next_close": (clock or {}).get("next_close"),
        "now_et": _now_et(now).strftime("%Y-%m-%d %H:%M ET"),
    }


if __name__ == "__main__":
    assert symbol_session("BTC/USD")[1] is True, "crypto must always be tradable"
    assert symbol_session("SPY", {"is_open": True})[0] == "regular"
    assert symbol_session("SPY", {"is_open": False}, allow_extended=False)[1] is False
    mid = datetime(2026, 7, 27, 6, 0, tzinfo=timezone.utc)      # 02:00 ET, Monday
    assert symbol_session("SPY", {"is_open": False}, now=mid)[0] == "closed"
    assert symbol_session("BTC/USD", {"is_open": False}, now=mid)[1] is True
    pre = datetime(2026, 7, 27, 12, 0, tzinfo=timezone.utc)     # 08:00 ET, Monday
    assert symbol_session("SPY", {"is_open": False}, now=pre)[0] == "pre"
    print("sessions self-check ok:", market_overview({"is_open": False}))
