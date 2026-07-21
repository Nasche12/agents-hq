"""Orchestration loop. Phase 1-3 runs in PAPER/dry mode: on startup it checks the
emergency lock (refuses to start if present), connects to the broker (offline stub until
keys), trains the HMMs, then each cycle computes regime -> allocation -> risk validation,
writes a heartbeat + the dashboard export, and journals the decision (including SKIPs, so
you can see the bot correctly NOT trading). Real order submission is Phase 2 -- it slots
into the marked spot once paper keys exist.

Run one cycle:   python main.py --once
Run continuously: python main.py   (5-min bar cadence; skips logic when market closed)"""
import json
import sys
import time
from datetime import datetime, timezone

import settings
import market_data
import hmm_engine
import alerts
import dashboard_export
import order_executor
from feature_engineering import build_features
from regime_strategies import directional_exposure
from risk_manager import RiskManager
from alpaca_broker import Broker

CYCLE_SECONDS = 300


def _heartbeat(**kw):
    kw["ts"] = datetime.now(timezone.utc).isoformat()
    settings.HEARTBEAT.write_text(json.dumps(kw, indent=2), encoding="utf-8")


def _order_row(o):
    """Map an Alpaca order to the fields the dashboard trade-detail card shows."""
    qty = float(o.get("filled_qty") or o.get("qty") or 0)
    price = float(o["filled_avg_price"]) if o.get("filled_avg_price") else None
    return {
        "id": o.get("id"), "symbol": o.get("symbol"), "side": o.get("side"),
        "qty": qty, "fill_price": price, "notional": round(qty * price, 2) if price else None,
        "status": o.get("status"), "type": o.get("type"),
        "submitted_at": o.get("submitted_at"), "filled_at": o.get("filled_at"),
    }


def _journal(entry):
    entry["ts"] = datetime.now(timezone.utc).isoformat()
    with open(settings.JOURNAL, "a", encoding="utf-8") as f:
        f.write(json.dumps(entry) + "\n")


def _signal_for(symbol, model, ref_vol):
    """HMM regime -> signed target exposure for one symbol, on INTRADAY bars (15-min by
    default) so regimes shift and trades happen within the day, not once per week.
    Returns (info, exposure, reason, price)."""
    hcfg = settings.load_config()["hmm"]
    df = market_data.get_bars(symbol, days=hcfg["live_days"], timeframe=hcfg["live_timeframe"])
    info = model.latest(df)
    vol = float(build_features(df)["realized_vol"].iloc[-1])
    expo, reason = directional_exposure(info["regime_rank"], info["n_regimes"],
                                        info["confidence"], vol, ref_vol, info["flickering"])
    price = float(df["close"].iloc[-1])
    return info, expo, reason, price


def cycle(models, risk, broker):
    """One pass over the whole watchlist: per symbol -> HMM signal -> signed target ->
    risk gate -> reconcile (long/short) -> journal. Then read real account state once."""
    cfg = settings.load_config()
    exec_cfg = cfg["execution"]
    trading_enabled = exec_cfg.get("trading_enabled", False)
    deadband = cfg["allocation"]["min_change_threshold"]
    symbols = list(models)
    mkt_open = market_is_open(broker)

    acct = broker.account()
    equity = acct.get("equity") or cfg["starting_equity"]
    # Whole account is tradable, but: (a) no single trade/position above the hard cap,
    # (b) total deployable never beyond equity + max_margin (the $-bounded leverage).
    deployable = equity + exec_cfg.get("max_margin", 0)
    per_budget = min(exec_cfg["max_notional_per_trade"], deployable / max(1, len(symbols)))
    rstate = risk.update_equity(equity)
    mult = rstate["multiplier"]                          # risk throttle (0 = flat everything)

    signals = []
    for sym in symbols:
        m = models[sym]
        info, expo, reason, price = _signal_for(sym, m["model"], m["ref_vol"])
        target = 0.0 if rstate["killed"] else expo * mult
        want = info["stable"] and abs(target) >= deadband
        will_trade = want and trading_enabled and mkt_open and broker.connected
        decision = "TRADE" if will_trade else ("FLAT" if rstate["killed"] else "SKIP")
        parts = [reason]
        if not info["stable"]:
            parts.append("not yet stable")
        if rstate["breakers"]:
            parts.append("breakers: " + ",".join(rstate["breakers"]))
        if not trading_enabled:
            parts.append("observe only")

        order_info = None
        if will_trade or (rstate["killed"] and broker.connected and mkt_open):
            try:
                order_info = order_executor.reconcile_to_target(broker=broker, symbol=sym,
                                                                target_exposure=target,
                                                                price=price, budget=per_budget)
                if order_info.get("order_id"):
                    parts.append(f"{order_info['action']} {order_info['qty']} @~{order_info['price_ref']}")
            except Exception as e:
                parts.append(f"order error: {str(e)[:60]}")
                alerts.log_event("order_error", f"{sym}: {str(e)[:180]}")

        reason_full = " · ".join(parts)
        _journal({"type": "cycle", "symbol": sym, "decision": decision, "regime": info["regime"],
                  "confidence": info["confidence"], "exposure": round(target, 4),
                  "order": order_info, "reason": reason_full})
        signals.append({"symbol": sym, "regime": info["regime"], "regime_rank": info["regime_rank"],
                        "n_regimes": info["n_regimes"], "confidence": info["confidence"],
                        "exposure": round(target, 4), "price": round(price, 2),
                        "direction": "long" if target > 0 else ("short" if target < 0 else "flat"),
                        "decision": decision, "stable": info["stable"], "reason": reason_full})

    if broker.connected and trading_enabled and mkt_open:
        time.sleep(2)                                    # let market orders fill before read-back
    positions_live = broker.positions() if broker.connected else []
    raw_orders = broker.list_orders(status="all", limit=200) if broker.connected else []
    acct = broker.account() if broker.connected else acct
    settings.ORDERS.write_text(json.dumps([_order_row(o) for o in raw_orders], indent=2), encoding="utf-8")
    settings.POSITIONS.write_text(json.dumps({"open": positions_live, "pending": []}, indent=2), encoding="utf-8")
    settings.SIGNALS.write_text(json.dumps(signals, indent=2), encoding="utf-8")
    if broker.connected and acct.get("equity") is not None:
        with open(settings.EQUITY_HISTORY, "a", encoding="utf-8") as f:
            f.write(json.dumps({"ts": datetime.now(timezone.utc).isoformat(),
                                "equity": acct["equity"], "cash": acct.get("cash")}) + "\n")

    _heartbeat(alive=True, market_open=mkt_open, killed=rstate["killed"],
               cash=acct.get("cash"), account_equity=acct.get("equity"),
               broker=("connected" if broker.connected else "offline"),
               open_positions=len(positions_live), orders_placed=len(raw_orders),
               longs=sum(1 for s in signals if s["direction"] == "long"),
               shorts=sum(1 for s in signals if s["direction"] == "short"))
    if rstate["breakers"]:
        alerts.log_event("circuit_breaker", ",".join(rstate["breakers"]))
        alerts.send("breaker", f"breakers {rstate['breakers']}")
    dashboard_export.build()
    return signals


def _market_open_heuristic():
    """Fallback US-equity session gate (Mon-Fri, 13:30-20:00 UTC) when offline."""
    now = datetime.now(timezone.utc)
    if now.weekday() >= 5:
        return False
    mins = now.hour * 60 + now.minute
    return 13 * 60 + 30 <= mins <= 20 * 60


def market_is_open(broker):
    """Authoritative market status via Alpaca's clock (handles DST + holidays);
    falls back to the UTC heuristic only when offline."""
    if broker is not None and broker.connected:
        try:
            return bool(broker.clock().get("is_open"))
        except Exception:
            pass
    return _market_open_heuristic()


def startup():
    cfg = settings.load_config()
    symbols = cfg["watchlist"]
    risk = RiskManager()
    risk.require_unlocked()                         # refuse to start if -10% lock present
    broker = Broker()
    alerts.log_event("start", f"symbols={symbols} broker={'connected' if broker.connected else 'offline'}")
    models = _train_models(symbols, cfg)
    return models, risk, broker


def _train_models(symbols, cfg):
    """One HMM per symbol on INTRADAY bars (live_timeframe), so regimes are re-estimated
    from recent intraday structure. Called at startup and re-run once per day."""
    hcfg = cfg["hmm"]
    models = {}
    for sym in symbols:
        df = market_data.get_bars(sym, days=hcfg["live_days"], timeframe=hcfg["live_timeframe"])
        df.attrs["symbol"] = sym
        models[sym] = {"model": hmm_engine.train(df),
                       "ref_vol": float(build_features(df)["realized_vol"].median()) or 0.012}
    return models


def main():
    once = "--once" in sys.argv
    models, risk, broker = startup()
    print(f"started: {list(models)} | broker {'connected' if broker.connected else 'offline stub'} "
          f"| mode paper")
    trained_day = datetime.now(timezone.utc).date()
    try:
        while True:
            today = datetime.now(timezone.utc).date()
            if today != trained_day:                     # fresh intraday HMMs once per day
                models = _train_models(list(models), settings.load_config())
                trained_day = today
            if market_is_open(broker) or once:
                sigs = cycle(models, risk, broker)
                longs = sum(1 for s in sigs if s["direction"] == "long")
                shorts = sum(1 for s in sigs if s["direction"] == "short")
                traded = sum(1 for s in sigs if s["decision"] == "TRADE")
                print(f"{datetime.now().strftime('%H:%M')} {len(sigs)} signals | "
                      f"{longs} long {shorts} short | {traded} traded")
            else:
                _heartbeat(alive=True, market_open=False, note="market closed - observing")
                dashboard_export.build()             # keep the tab fresh while closed
            if once:
                break
            time.sleep(CYCLE_SECONDS)
    except KeyboardInterrupt:
        alerts.log_event("stop", "keyboard interrupt")
        print("stopped.")


if __name__ == "__main__":
    main()
