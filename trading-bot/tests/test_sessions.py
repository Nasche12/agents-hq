"""24/7 verification. These are the invariants that make "the bot trades around the
clock" true rather than a slogan: crypto is always tradable, equities are honestly
closed at night and on weekends, crypto is never shorted (Alpaca can't), extended-hours
equity orders are whole-share limit orders, and round-trip P&L is matched from real
fills. Deliberately free of hmmlearn so it runs anywhere. Run: pytest -q"""
import sys
from datetime import datetime, timezone
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import sessions
import order_executor as ox
import trade_stats
from market_data import is_crypto, pos_symbol

SUN_NIGHT = datetime(2026, 7, 26, 3, 0, tzinfo=timezone.utc)     # Sunday, 23:00 ET Sat
MON_PRE = datetime(2026, 7, 27, 12, 0, tzinfo=timezone.utc)      # Monday, 08:00 ET
MON_POST = datetime(2026, 7, 27, 22, 0, tzinfo=timezone.utc)     # Monday, 18:00 ET
CLOSED_CLOCK = {"is_open": False}


# ---------------------------------------------------------------- sessions
def test_crypto_is_always_tradable():
    for now in (SUN_NIGHT, MON_PRE, MON_POST):
        s, tradable, extended = sessions.symbol_session("BTC/USD", CLOSED_CLOCK, now=now)
        assert s == "crypto" and tradable and not extended


def test_equities_are_closed_on_the_weekend():
    s, tradable, _ = sessions.symbol_session("SPY", CLOSED_CLOCK, now=SUN_NIGHT)
    assert s == "closed" and tradable is False, "equities cannot trade on a Sunday night"


def test_extended_hours_toggle():
    s, tradable, extended = sessions.symbol_session("SPY", CLOSED_CLOCK, now=MON_PRE)
    assert s == "pre" and tradable and extended
    s, tradable, extended = sessions.symbol_session("SPY", CLOSED_CLOCK,
                                                    allow_extended=False, now=MON_PRE)
    assert s == "pre" and tradable is False and extended is False
    assert sessions.symbol_session("SPY", CLOSED_CLOCK, now=MON_POST)[0] == "after"


def test_regular_session_beats_the_wall_clock():
    assert sessions.symbol_session("SPY", {"is_open": True})[0] == "regular"


def test_market_overview_reports_both_asset_classes():
    ov = sessions.market_overview(CLOSED_CLOCK, True, now=SUN_NIGHT)
    assert ov["crypto_tradable"] is True
    assert ov["equity_tradable"] is False
    assert ov["equity_session"] == "closed"


# ---------------------------------------------------------------- symbols
def test_symbol_helpers():
    assert is_crypto("BTC/USD") and not is_crypto("SPY")
    assert pos_symbol("BTC/USD") == "BTCUSD" and pos_symbol("SPY") == "SPY"


# ---------------------------------------------------------------- execution
class FakeBroker:
    def __init__(self, held=0, symbol="BTC/USD"):
        self._held, self._symbol = held, symbol
        self.orders, self.closed = [], []

    def positions(self):
        # deliberately the broker's own spelling ('BTCUSD'), not the order spelling
        return [{"symbol": pos_symbol(self._symbol), "qty": self._held}] if self._held else []

    def submit_order(self, symbol, qty, side, extended=False, price_ref=None):
        self.orders.append({"symbol": symbol, "qty": qty, "side": side,
                            "extended": extended, "price_ref": price_ref})
        return {"id": "x", "status": "accepted"}

    def close_position(self, symbol):
        self.closed.append(symbol)
        return {"id": "c"}


def test_crypto_never_shorts():
    assert ox.target_shares(-0.9, 60000.0, 5000.0, allow_short=False) == 0.0
    b = FakeBroker(0, "BTC/USD")
    r = ox.reconcile_to_target(b, "BTC/USD", -0.9, 60000.0, 5000.0)
    assert r["action"] == "hold" and b.orders == [], "Alpaca has no crypto shorts"


def test_crypto_position_lookup_matches_broker_spelling():
    b = FakeBroker(0.08, "BTC/USD")            # broker says 'BTCUSD'
    assert ox.current_qty(b, "BTC/USD") == 0.08


def test_crypto_uses_fractional_quantities():
    b = FakeBroker(0, "BTC/USD")
    r = ox.reconcile_to_target(b, "BTC/USD", 0.9, 60000.0, 5000.0)
    assert r["action"] == "buy" and 0 < b.orders[0]["qty"] < 1, "fractional crypto expected"
    assert r["session"] == "crypto"


def test_extended_hours_orders_are_whole_share_limits():
    b = FakeBroker(0, "SPY")
    r = ox.reconcile_to_target(b, "SPY", 0.9, 100.0, 5000.0, extended=True)
    assert r["action"] == "buy" and r["session"] == "extended"
    o = b.orders[0]
    assert o["extended"] is True and o["price_ref"] == 100.0
    assert float(o["qty"]) == int(o["qty"]), "extended hours cannot take fractional shares"


def test_side_flip_flattens_first():
    b = FakeBroker(40, "SPY")
    r = ox.reconcile_to_target(b, "SPY", -0.9, 100.0, 5000.0)
    assert r["action"] == "flatten" and b.closed == ["SPY"] and b.orders == []


def test_tighter_deadband_trades_more(monkeypatch):
    """The whole point of the 'trade more' change: a move that used to be held now trades."""
    monkeypatch.setattr(ox, "_rebalance_min_pct", lambda: 0.05)
    held = FakeBroker(46, "SPY")          # target 47.5 -> a $150 gap
    assert ox.reconcile_to_target(held, "SPY", 0.95, 100.0, 5000.0)["action"] == "hold"
    monkeypatch.setattr(ox, "_rebalance_min_pct", lambda: 0.01)
    held2 = FakeBroker(46, "SPY")
    assert ox.reconcile_to_target(held2, "SPY", 0.95, 100.0, 5000.0)["action"] == "buy"


# ---------------------------------------------------------------- round-trip P&L
def _fill(sym, side, qty, price, ts):
    return {"symbol": sym, "side": side, "filled_qty": qty, "filled_avg_price": price,
            "status": "filled", "filled_at": ts}


def test_realized_pnl_matches_fifo():
    orders = [_fill("SPY", "buy", 10, 100, "2026-07-01T10:00:00Z"),
              _fill("SPY", "buy", 10, 110, "2026-07-01T11:00:00Z"),
              _fill("SPY", "sell", 15, 120, "2026-07-01T12:00:00Z")]
    closed = trade_stats.realized_trades(orders)
    # FIFO: 10 @100 -> +200, then 5 of the 110 lot -> +50
    assert round(sum(t["pnl"] for t in closed), 2) == 250.0
    assert trade_stats.summarize(closed)["win_rate"] == 1.0


def test_short_round_trip_is_profitable_when_price_falls():
    orders = [_fill("SPY", "sell", 10, 100, "2026-07-01T10:00:00Z"),
              _fill("SPY", "buy", 10, 90, "2026-07-01T12:00:00Z")]
    closed = trade_stats.realized_trades(orders)
    assert len(closed) == 1 and closed[0]["side"] == "short" and closed[0]["pnl"] == 100.0


def test_open_position_is_not_counted_as_a_trade():
    orders = [_fill("BTC/USD", "buy", 0.5, 60000, "2026-07-01T10:00:00Z")]
    assert trade_stats.realized_trades(orders) == []
    assert trade_stats.summarize([])["trades"] == 0


def test_unfilled_orders_are_ignored():
    orders = [{"symbol": "SPY", "side": "buy", "qty": 5, "status": "canceled",
               "submitted_at": "2026-07-01T10:00:00Z"}]
    assert trade_stats.realized_trades(orders) == []
