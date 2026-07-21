"""Layer 4 -- order execution (Phase 2). Turns a target exposure (fraction of equity)
into a share count and reconciles the account to it with a single market order for the
delta. Paper only; the broker refuses live orders. Kept deliberately small: one symbol,
market orders, no bracket/limit yet (those extend here once paper behaviour is trusted)."""


def target_shares(target_exposure, price, budget):
    """Signed target quantity = HMM exposure scaled INTO the per-symbol budget. Positive =
    long (FRACTIONAL, so small budgets still produce a position on high-priced stocks),
    negative = short (WHOLE shares -- Alpaca has no fractional shorts). |notional| <= budget,
    so it never trades large amounts, yet exposure drives both size and direction."""
    if price <= 0 or budget <= 0:
        return 0.0
    expo = max(-1.0, min(1.0, target_exposure))
    q = expo * budget / price
    return float(int(q)) if q < 0 else round(q, 4)


def current_qty(broker, symbol):
    for p in broker.positions():
        if p["symbol"] == symbol:
            return float(p["qty"])
    return 0.0


def reconcile_to_target(broker, symbol, target_exposure, price, budget):
    """Move the position to the HMM-driven, budget-scaled target. Buys/sells the delta;
    if the target flips sides (long<->short) it flattens this cycle and re-enters next.
    Anti-churn: holds when the change is below ~5% of the per-symbol budget."""
    cur = current_qty(broker, symbol)
    want = target_shares(target_exposure, price, budget)

    if cur != 0 and want != 0 and (cur > 0) != (want > 0):   # crossing sides -> flatten first
        broker.close_position(symbol)
        return {"action": "flatten", "from": cur, "target": want,
                "qty": round(abs(cur), 4), "price_ref": round(price, 2),
                "notional": round(abs(cur) * price, 2), "budget": budget, "order_id": "flatten"}

    delta = want - cur
    if abs(delta) * price < max(1.0, 0.05 * budget):         # anti-churn deadband
        return {"action": "hold", "qty": cur, "target": want}

    side = "buy" if delta > 0 else "sell"
    order = broker.submit_order(symbol, abs(delta), side)
    return {"action": side, "delta": round(delta, 4), "from": round(cur, 4), "target": want,
            "order_id": order.get("id"), "status": order.get("status"),
            "qty": round(abs(delta), 4), "price_ref": round(price, 2),
            "notional": round(abs(delta) * price, 2), "budget": budget}
