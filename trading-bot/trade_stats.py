"""Round-trip analytics. Alpaca reports FILLS, not trades -- it tells you "bought 3 SPY"
and later "sold 3 SPY" but never that the pair made $12. This module matches fills FIFO
per symbol into closed round-trips so the dashboard can show real, non-invented numbers:
realized P&L, win rate, average win/loss, profit factor, best/worst trade.

Everything here derives from actual filled orders. If nothing has round-tripped yet the
result is empty -- never an estimate.

P&L is reported NET of trading fees. Both legs of a round-trip are charged the per-side fee
(settings.fee_bps_per_side, the one source shared with the optimizer), so the numbers the
dashboard shows are what the account actually keeps -- not a gross price difference that
flatters a coin-flip strategy the fees are quietly bleeding. `gross_pnl` and `fees` are kept
alongside so the churn tax is visible, not hidden."""
from collections import defaultdict, deque

import settings


def _fills(orders):
    """Filled orders only, oldest first, normalized to (ts, symbol, side, qty, price)."""
    out = []
    for o in orders or []:
        qty = _f(o.get("filled_qty") if o.get("filled_qty") is not None else o.get("qty"))
        price = _f(o.get("filled_avg_price") if o.get("filled_avg_price") is not None
                   else o.get("fill_price"))
        ts = o.get("filled_at") or o.get("submitted_at")
        if not qty or not price or not ts or not o.get("symbol"):
            continue
        status = (o.get("status") or "").lower()
        if status and status not in ("filled", "partially_filled", "closed"):
            continue
        out.append({"ts": ts, "symbol": o["symbol"], "side": (o.get("side") or "").lower(),
                    "qty": abs(qty), "price": price})
    return sorted(out, key=lambda f: f["ts"])


def realized_trades(orders):
    """FIFO-matched closed round-trips, newest first."""
    lots = defaultdict(deque)          # symbol -> deque of {qty(+long/-short), price, ts}
    closed = []
    for f in _fills(orders):
        sym, book = f["symbol"], lots[f["symbol"]]
        signed = f["qty"] if f["side"] == "buy" else -f["qty"]
        remaining = signed
        while remaining and book and (book[0]["qty"] > 0) != (remaining > 0):
            lot = book[0]
            match = min(abs(lot["qty"]), abs(remaining))
            long_side = lot["qty"] > 0
            gross = (f["price"] - lot["price"]) * match * (1 if long_side else -1)
            basis = lot["price"] * match
            # Fee on BOTH legs (entry lot + this exit fill), per-side bps on each leg's notional.
            # This is what turns a +$1 gross scalp into the -$0.x it really was.
            bps = settings.fee_bps_per_side(sym) / 1e4
            fees = (basis + f["price"] * match) * bps
            pnl = gross - fees
            closed.append({
                "symbol": sym, "side": "long" if long_side else "short",
                "qty": round(match, 6), "entry": round(lot["price"], 4),
                "exit": round(f["price"], 4), "opened": lot["ts"], "closed": f["ts"],
                "pnl": round(pnl, 2), "gross_pnl": round(gross, 2), "fees": round(fees, 2),
                "pnl_pct": round(pnl / basis, 4) if basis else None,
                "notional": round(basis, 2),
            })
            lot["qty"] -= match if long_side else -match
            remaining += match if long_side else -match
            if abs(lot["qty"]) < 1e-9:
                book.popleft()
        if abs(remaining) > 1e-9:
            book.append({"qty": remaining, "price": f["price"], "ts": f["ts"]})
    return closed[::-1]


def summarize(closed):
    """Headline numbers from the closed round-trips. All None/0 when nothing closed yet."""
    if not closed:
        return {"trades": 0, "wins": 0, "losses": 0, "win_rate": None, "realized_pnl": 0.0,
                "fees_paid": 0.0, "gross_pnl": 0.0,
                "avg_win": None, "avg_loss": None, "best": None, "worst": None,
                "profit_factor": None, "avg_pnl": None}
    wins = [t["pnl"] for t in closed if t["pnl"] > 0]
    losses = [t["pnl"] for t in closed if t["pnl"] <= 0]
    gross_win, gross_loss = sum(wins), abs(sum(losses))
    return {
        "trades": len(closed), "wins": len(wins), "losses": len(losses),
        "win_rate": round(len(wins) / len(closed), 4),
        "realized_pnl": round(sum(t["pnl"] for t in closed), 2),
        "fees_paid": round(sum(t.get("fees", 0.0) for t in closed), 2),
        "gross_pnl": round(sum(t.get("gross_pnl", t["pnl"]) for t in closed), 2),
        "avg_pnl": round(sum(t["pnl"] for t in closed) / len(closed), 2),
        "avg_win": round(gross_win / len(wins), 2) if wins else None,
        "avg_loss": round(-gross_loss / len(losses), 2) if losses else None,
        "best": round(max(t["pnl"] for t in closed), 2),
        "worst": round(min(t["pnl"] for t in closed), 2),
        "profit_factor": round(gross_win / gross_loss, 2) if gross_loss else None,
    }


def by_symbol(closed, positions=None):
    """Realized P&L per symbol, merged with the open position's unrealized P&L."""
    agg = defaultdict(lambda: {"trades": 0, "realized": 0.0, "wins": 0})
    for t in closed:
        a = agg[t["symbol"]]
        a["trades"] += 1
        a["realized"] += t["pnl"]
        a["wins"] += 1 if t["pnl"] > 0 else 0
    for p in positions or []:
        a = agg[p["symbol"]]
        a["unrealized"] = p.get("unrealized_pl")
        a["market_value"] = p.get("market_value")
    return {k: {**v, "realized": round(v["realized"], 2),
                "win_rate": round(v["wins"] / v["trades"], 4) if v["trades"] else None}
            for k, v in agg.items()}


def _f(v):
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


if __name__ == "__main__":
    orders = [
        {"symbol": "SPY", "side": "buy", "filled_qty": "10", "filled_avg_price": "100",
         "status": "filled", "filled_at": "2026-07-01T10:00:00Z"},
        {"symbol": "SPY", "side": "sell", "filled_qty": "10", "filled_avg_price": "105",
         "status": "filled", "filled_at": "2026-07-01T12:00:00Z"},
        {"symbol": "BTC/USD", "side": "buy", "filled_qty": "0.5", "filled_avg_price": "60000",
         "status": "filled", "filled_at": "2026-07-02T02:00:00Z"},
        {"symbol": "BTC/USD", "side": "sell", "filled_qty": "0.5", "filled_avg_price": "59000",
         "status": "filled", "filled_at": "2026-07-02T05:00:00Z"},
    ]
    tr = realized_trades(orders)
    s = summarize(tr)
    assert len(tr) == 2, tr
    # SPY leg is commission-free (gross +50 == net +50); the BTC leg pays 25bps on BOTH
    # notionals: (30000 + 29500) * 0.0025 = 148.75, turning gross -500 into net -648.75.
    assert s["gross_pnl"] == 50.0 - 500.0, s
    btc = next(t for t in tr if t["symbol"] == "BTC/USD")
    assert btc["fees"] == 148.75, btc
    assert s["fees_paid"] == 148.75, s
    assert s["realized_pnl"] == round(50.0 - 500.0 - 148.75, 2), s
    assert s["wins"] == 1 and s["losses"] == 1 and s["win_rate"] == 0.5
    print("trade_stats self-check ok:", s)
