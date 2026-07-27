"""Layer 4 -- order execution. Turns a target exposure (fraction of the per-symbol
budget) into a share count and reconciles the account to it with a single market order
for the delta. Paper only; the broker refuses live orders.

Asset-class rules live here so the caller stays simple:
  * crypto  -> fractional quantities, NO shorting (Alpaca has no crypto shorts), so a
               negative target collapses to flat instead of failing at the API.
  * equity  -> fractional longs, whole-share shorts; extended hours forces whole shares.
The anti-churn deadband is configurable (execution.rebalance_min_pct) -- lower it to
trade more often, raise it to trade less."""
import settings
from market_data import is_crypto, pos_symbol


def _rebalance_min_pct():
    return settings.load_config()["execution"].get("rebalance_min_pct", 0.02)


def target_shares(target_exposure, price, budget, allow_short=True, whole_only=False):
    """Signed target quantity = HMM exposure scaled INTO the per-symbol budget. Positive =
    long (FRACTIONAL, so small budgets still produce a position on high-priced assets),
    negative = short (WHOLE shares -- Alpaca has no fractional shorts). |notional| <= budget,
    so it never trades large amounts, yet exposure drives both size and direction."""
    if price <= 0 or budget <= 0:
        return 0.0
    expo = max(-1.0, min(1.0, target_exposure))
    if not allow_short and expo < 0:
        return 0.0                                   # crypto: short signal -> stay flat
    q = expo * budget / price
    if whole_only:
        return float(int(q))
    return float(int(q)) if q < 0 else round(q, 6)


def current_qty(broker, symbol, positions=None):
    """Held quantity, matching 'BTC/USD' against Alpaca's 'BTCUSD' position spelling.
    Pass `positions` to reuse one snapshot for the whole cycle -- at a 60s cadence with
    a 9-symbol watchlist, re-fetching per symbol would be 9 needless API calls a minute."""
    want = pos_symbol(symbol)
    for p in (broker.positions() if positions is None else positions):
        if pos_symbol(p["symbol"]) == want:
            return float(p["qty"])
    return 0.0


def reconcile_to_target(broker, symbol, target_exposure, price, budget, extended=False,
                        positions=None):
    """Move the position to the HMM-driven, budget-scaled target. Buys/sells the delta;
    if the target flips sides (long<->short) it flattens this cycle and re-enters next.
    Anti-churn: holds when the change is below rebalance_min_pct of the per-symbol budget."""
    crypto = is_crypto(symbol)
    allow_short = not crypto
    whole_only = bool(extended) and not crypto
    cur = current_qty(broker, symbol, positions)
    want = target_shares(target_exposure, price, budget,
                         allow_short=allow_short, whole_only=whole_only)

    if cur != 0 and want != 0 and (cur > 0) != (want > 0):   # crossing sides -> flatten first
        broker.close_position(symbol)
        return {"action": "flatten", "from": cur, "target": want,
                "qty": round(abs(cur), 6), "price_ref": round(price, 2),
                "notional": round(abs(cur) * price, 2), "budget": budget, "order_id": "flatten"}

    delta = want - cur
    floor = max(1.0, _rebalance_min_pct() * budget)          # anti-churn deadband
    if abs(delta) * price < floor:
        return {"action": "hold", "qty": cur, "target": want,
                "gap": round(abs(delta) * price, 2), "floor": round(floor, 2)}

    if whole_only:
        delta = float(int(delta))
        if delta == 0:
            return {"action": "hold", "qty": cur, "target": want, "note": "extended: <1 share"}

    side = "buy" if delta > 0 else "sell"
    order = broker.submit_order(symbol, abs(delta), side, extended=extended, price_ref=price)
    return {"action": side, "delta": round(delta, 6), "from": round(cur, 6), "target": want,
            "order_id": order.get("id"), "status": order.get("status"),
            "qty": round(abs(delta), 6), "price_ref": round(price, 2),
            "notional": round(abs(delta) * price, 2), "budget": budget,
            "session": "extended" if extended else ("crypto" if crypto else "regular")}
