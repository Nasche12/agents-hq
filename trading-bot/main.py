"""Orchestration loop -- the 24/7 engine.

The loop itself never sleeps through a market: it runs every `execution.cycle_seconds`
around the clock. What changes is WHICH symbols are actionable in this second:

    crypto (BTC/USD, ...)  -> tradable 24/7/365
    equities (SPY, ...)    -> regular 09:30-16:00 ET, plus pre/after-hours when
                              execution.extended_hours is true; closed nights + weekends

So at 03:00 on a Sunday the bot is fully awake, trading crypto, and honestly reporting
every equity as 'closed' instead of pretending. Each cycle: per symbol -> HMM regime ->
signed target exposure -> risk gate -> reconcile -> journal, then one account read-back,
a heartbeat and the dashboard export.

Run one cycle:   python main.py --once
Run continuously: python main.py"""
import json
import math
import sys
import time
from datetime import datetime, timezone, timedelta

import settings
import market_data
import hmm_engine
import alerts
import sessions
import risk_radar
import news_log
import insights
import exit_manager
import dashboard_export
import order_executor
import chart_features
from feature_engineering import build_features
from regime_strategies import directional_exposure
from risk_manager import RiskManager
from alpaca_broker import Broker

DEFAULT_CYCLE_SECONDS = 60

# In-memory guard against an order that keeps getting rejected (e.g. Alpaca's crypto
# wash-trade 403 when churn re-submits the same pair): after repeated failures we pause
# that symbol for a while instead of hammering the API every cycle. Resets on restart.
_ORDER_ERR = {}          # symbol -> consecutive order errors
_ORDER_COOLDOWN = {}     # symbol -> datetime until which orders are skipped
ORDER_ERR_LIMIT = 2      # this many consecutive errors -> pause
ORDER_ERR_PAUSE_MIN = 15


def _cycle_seconds(cfg):
    return max(15, int(cfg["execution"].get("cycle_seconds", DEFAULT_CYCLE_SECONDS)))


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
        "asset_class": "crypto" if market_data.is_crypto(o.get("symbol") or "") else "us_equity",
        "extended_hours": bool(o.get("extended_hours")),
        "submitted_at": o.get("submitted_at"), "filled_at": o.get("filled_at"),
    }


def _journal(entry):
    entry["ts"] = datetime.now(timezone.utc).isoformat()
    with open(settings.JOURNAL, "a", encoding="utf-8") as f:
        f.write(json.dumps(entry) + "\n")


# ---------------------------------------------------------------- manual commands
def _process_commands(broker, exit_state, cfg):
    """Execute pending manual commands the dashboard dropped as files (the dashboard owns
    no broker connection -- the bot is the single writer to the account). A 'close' flattens
    the position at market AND sets an exit cooldown, so the same/next cycle does not just
    re-open it against the user's intent. Returns the set of pos_symbol keys closed, so the
    caller can drop them from this cycle's snapshot. Each command file is deleted after it
    runs (directory-as-queue: race-free, the dashboard only ever creates files here)."""
    cmd_dir = settings.STATE_DIR / "commands"
    if not cmd_dir.exists():
        return set()
    cooldown_min = float(cfg.get("exits", {}).get("cooldown_minutes", 30))
    closed = set()
    for f in sorted(cmd_dir.glob("*.json")):
        try:
            cmd = json.loads(f.read_text(encoding="utf-8"))
        except Exception:
            cmd = None
        try:
            if cmd and cmd.get("action") == "close" and cmd.get("symbol"):
                sym = str(cmd["symbol"])
                if broker.connected:
                    try:
                        broker.close_position(sym)
                    except Exception as e:
                        alerts.log_event("order_error", f"manual close {sym}: {str(e)[:150]}")
                key = market_data.pos_symbol(sym)
                exit_state[key] = {"peak": 0.0,
                                   "cooldown_until": (datetime.now(timezone.utc)
                                                      + timedelta(minutes=cooldown_min)).isoformat()}
                closed.add(key)
                _journal({"type": "cycle", "symbol": sym, "decision": "MANUAL_CLOSE",
                          "reason": f"manuell geschlossen (Dashboard) + {int(cooldown_min)} min Cooldown",
                          "factors": ["manueller Klick im Dashboard",
                                      f"Cooldown {int(cooldown_min)} min gegen sofortiges Re-Buy"]})
                alerts.log_event("manual_close", sym)
        finally:
            try:
                f.unlink()
            except Exception:
                pass
    return closed


# ---------------------------------------------------------------- bot counters
def _load_bot_state():
    try:
        return json.loads(settings.BOT_STATE.read_text(encoding="utf-8"))
    except Exception:
        return {"cycles": 0, "orders_sent": 0, "errors": 0, "started": None,
                "last_order": None, "last_error": None}


def _save_bot_state(s):
    settings.BOT_STATE.write_text(json.dumps(s, indent=2), encoding="utf-8")


def _fetch_bars(symbols, hcfg):
    """One bar fetch per symbol per cycle, memoised for half a bar period. With a
    20-symbol watchlist this is the heaviest thing in the loop, and a 5-minute bar
    simply does not change every 60 seconds."""
    bars = {}
    for sym in symbols:
        try:
            bars[sym] = market_data.get_bars(sym, days=hcfg["live_days"],
                                             timeframe=hcfg["live_timeframe"], use_memo=True)
        except Exception as e:
            alerts.log_event("data_error", f"{sym}: {str(e)[:180]}")
    return bars


def _signal_for(symbol, model, ref_vol, df):
    """HMM regime -> signed target exposure for one symbol, on INTRADAY bars (5-min by
    default) so regimes shift and trades happen within the hour, not once per week.
    Returns (info, exposure, reason, price)."""
    info = model.latest(df)
    vol = float(build_features(df)["realized_vol"].iloc[-1])
    trend = _trend_of(df)
    expo, reason = directional_exposure(info["regime_rank"], info["n_regimes"],
                                        info["confidence"], vol, ref_vol, info["flickering"],
                                        trend=trend)
    price = float(df["close"].iloc[-1])
    return info, expo, reason, price, vol


def _trend_of(df):
    """Signed price-trend measure (MA slope) for the trend-confirmation filter. None when it
    cannot be computed yet (too little history) -> the filter then does not block."""
    try:
        s = float(chart_features.ma_slope(df).iloc[-1])
        return s if math.isfinite(s) else None
    except Exception:
        return None


def cycle(models, risk, broker):
    """One pass over the whole watchlist. Per symbol: session gate -> HMM signal ->
    signed target -> risk gate -> reconcile (long/short) -> journal. Then one real
    account read-back. Runs 24/7; symbols whose market is shut are marked CLOSED."""
    cfg = settings.load_config()
    exec_cfg = cfg["execution"]
    trading_enabled = exec_cfg.get("trading_enabled", False)
    allow_extended = exec_cfg.get("extended_hours", True)
    deadband = cfg["allocation"]["min_change_threshold"]
    symbols = list(models)
    bot = _load_bot_state()

    clock = {}
    if broker.connected:
        try:
            clock = broker.clock()
        except Exception:
            clock = {}
    overview = sessions.market_overview(clock, allow_extended)

    acct = broker.account()
    equity = acct.get("equity") or cfg["starting_equity"]
    # Whole account is tradable, but: (a) no single trade/position above the hard cap,
    # (b) total deployable never beyond equity + max_margin (the $-bounded leverage).
    deployable = equity + exec_cfg.get("max_margin", 0)
    per_budget = min(exec_cfg["max_notional_per_trade"], deployable / max(1, len(symbols)))
    rstate = risk.update_equity(equity)
    mult = rstate["multiplier"]                          # risk throttle (0 = flat everything)

    # ONE positions snapshot for the whole cycle -- each symbol only ever reads its own
    # row, and re-fetching per symbol would cost 20 extra API calls every single minute.
    held_now = broker.positions() if broker.connected else []

    # Manual commands from the dashboard (close a position on user click). Processed here,
    # before anything else acts, so a just-closed symbol is out of this cycle's snapshot and
    # the cooldown blocks an immediate re-buy. exit_state is loaded ONCE here and threaded
    # through PASS 2b (re-loading it later would drop the cooldown we just set).
    try:
        exit_state = json.loads(settings.EXITS_STATE.read_text(encoding="utf-8"))
    except Exception:
        exit_state = {}
    closed_keys = _process_commands(broker, exit_state, cfg)
    if closed_keys:
        held_now = [p for p in held_now if market_data.pos_symbol(p["symbol"]) not in closed_keys]

    # ONE bar fetch per symbol, shared by the HMM signal AND the portfolio radar.
    bars = _fetch_bars(symbols, cfg["hmm"])

    # PASS 1: what does each symbol want on its own?
    raw, meta = {}, {}
    for sym in symbols:
        crypto = market_data.is_crypto(sym)
        session, tradable, extended = sessions.symbol_session(sym, clock, allow_extended)
        m = models[sym]
        if sym not in bars:
            meta[sym] = {"error": "keine Kursdaten", "session": session,
                         "tradable": tradable, "extended": extended, "crypto": crypto}
            continue
        try:
            info, expo, reason, price, vol = _signal_for(sym, m["model"], m["ref_vol"], bars[sym])
        except Exception as e:
            bot["errors"] += 1
            bot["last_error"] = f"{sym}: {str(e)[:120]}"
            alerts.log_event("data_error", f"{sym}: {str(e)[:180]}")
            meta[sym] = {"error": str(e)[:80], "session": session,
                         "tradable": tradable, "extended": extended, "crypto": crypto}
            continue
        target = 0.0 if rstate["killed"] else expo * mult
        notes = [reason]
        if crypto and target < 0:
            target = 0.0                                  # Alpaca cannot short crypto
            notes.append("crypto: no shorts -> flat")
        raw[sym] = target
        meta[sym] = {"info": info, "price": price, "notes": notes, "session": session,
                     "tradable": tradable, "extended": extended, "crypto": crypto,
                     "vol": vol, "ref_vol": m["ref_vol"]}

    # keep the per-symbol target BEFORE the portfolio adjustments, so the journal can show
    # "the symbol wanted +0.95, the radar and the correlation cap left +0.24"
    raw_expo = dict(raw)

    # PASS 2: portfolio view. The radar may ONLY take risk off (multiplier <= 1.0), and
    # the correlation limit finally does what config.risk.max_correlation always claimed.
    weak = [1 for s, mm in meta.items() if mm.get("info")
            and mm["info"]["n_regimes"] > 1
            and mm["info"]["regime_rank"] <= (mm["info"]["n_regimes"] - 1) / 3]
    weak_share = len(weak) / max(1, len([m for m in meta.values() if m.get("info")]))
    radar = risk_radar.assess(bars, weak_share=weak_share)
    # Persist the external picture (news level + calendar events) as a step-function log, so
    # the research loop can later attribute trade outcomes to the world they happened in.
    # Deterministic, written here and nowhere near an LLM; a failed append never breaks the cycle.
    try:
        news_log.append_if_changed(radar.get("external") or {})
    except Exception:
        pass
    if radar.get("multiplier", 1.0) < 1.0:
        raw = {s: round(t * radar["multiplier"], 4) for s, t in raw.items()}
    for sym in list(raw):
        capped, note = risk_radar.cap_for_anomaly(raw[sym], sym, radar)
        if note:
            raw[sym] = capped
            meta[sym]["notes"].append(note)
    raw, corr_notes = risk_radar.diversify(raw, radar.get("corr_matrix") or {},
                                           cfg["risk"].get("max_correlation"))
    for sym, note in corr_notes.items():
        meta[sym]["notes"].append(note)
    if radar.get("reasons"):
        alerts.log_event("radar", f"{radar['level']}: {'; '.join(radar['reasons'])}")

    # PASS 2b: per-position exits (tight stop / trailing / scale-out). Scale-out trims the
    # target here (the normal reconcile then sells the delta); hard stops and trailing exits
    # are executed IMPERATIVELY in the loop below, because main's deadband gate would swallow
    # a "target 0" and leave a loser open. exit_state was loaded at the top of the cycle
    # (with any manual-close cooldowns already applied) and persists across cycles.
    # current vol vs. each symbol's own normal -> lets the stop widen in wild vol, tighten in calm
    vol_ratios = {}
    for s, mm in meta.items():
        rv = mm.get("ref_vol") or 0
        if mm.get("vol") is not None and rv > 0:
            vol_ratios[market_data.pos_symbol(s)] = mm["vol"] / rv
    exit_dec, exit_state = exit_manager.evaluate(held_now, cfg.get("exits", {}), exit_state,
                                                 vol_ratios=vol_ratios)
    for sym in list(raw):
        d = exit_dec.get(market_data.pos_symbol(sym))
        if d and d.get("cap") is not None and d["cap"] < 1.0 and not d.get("close") and not d.get("block"):
            raw[sym] = round(raw[sym] * d["cap"], 4)
            meta[sym]["notes"].append(d["reason"])
    try:
        settings.EXITS_STATE.write_text(json.dumps(exit_state, indent=2), encoding="utf-8")
    except Exception:
        pass

    signals, orders_this_cycle = [], 0
    for sym in symbols:
        mm = meta.get(sym) or {}
        crypto, session = mm.get("crypto", False), mm.get("session", "closed")
        tradable, extended = mm.get("tradable", False), mm.get("extended", False)
        if mm.get("error") or sym not in raw:
            signals.append({"symbol": sym, "asset_class": "crypto" if crypto else "us_equity",
                            "session": session, "regime": None, "confidence": None,
                            "exposure": 0.0, "price": None, "direction": "flat",
                            "decision": "ERROR", "stable": False,
                            "reason": f"data error: {mm.get('error', 'unbekannt')}"})
            continue

        info, price = mm["info"], mm["price"]
        target, parts = raw[sym], list(mm["notes"])
        if radar.get("multiplier", 1.0) < 1.0:
            parts.append(f"Radar {radar['level']} x{radar['multiplier']}")

        want = info["stable"] and abs(target) >= deadband
        will_trade = want and trading_enabled and tradable and broker.connected
        if rstate["killed"]:
            decision = "FLAT"
        elif not tradable:
            decision = "CLOSED"
        elif will_trade:
            decision = "TRADE"
        else:
            decision = "SKIP"

        if not info["stable"]:
            parts.append("not yet stable")
        if not tradable:
            parts.append(f"{sessions.SESSION_LABEL.get(session, session)} — no orders")
        elif extended:
            parts.append("extended hours (limit order)")
        if rstate["breakers"]:
            parts.append("breakers: " + ",".join(rstate["breakers"]))
        if not trading_enabled:
            parts.append("observe only")

        # Per-position exit takes priority over the model's target: a hard stop / trailing
        # exit flattens now, a cooldown keeps it flat -- overriding "the HMM still wants this".
        exd = exit_dec.get(market_data.pos_symbol(sym))
        order_info = None
        did_exit = False
        if exd and (exd.get("close") or exd.get("block")) and tradable:
            parts.append(exd["reason"])
            did_exit = True
            if exd.get("close") and broker.connected and trading_enabled:
                try:
                    broker.close_position(sym)
                    order_info = {"action": "exit", "reason": exd["reason"], "order_id": "exit",
                                  "plpc": exd.get("plpc"), "peak": exd.get("peak")}
                    orders_this_cycle += 1
                    bot["orders_sent"] += 1
                    bot["last_order"] = datetime.now(timezone.utc).isoformat()
                except Exception as e:
                    bot["errors"] += 1
                    bot["last_error"] = f"{sym}: {str(e)[:120]}"
                    parts.append(f"exit error: {str(e)[:60]}")
                    alerts.log_event("order_error", f"{sym} exit: {str(e)[:180]}")
            decision = "EXIT" if exd.get("close") else "COOLDOWN"

        now_utc = datetime.now(timezone.utc)
        paused = _ORDER_COOLDOWN.get(sym)
        if not did_exit and paused and paused > now_utc:
            parts.append(f"Order pausiert (wiederholte Fehler, bis {paused:%H:%M})")
        elif not did_exit and (will_trade or (rstate["killed"] and broker.connected and tradable)) and tradable:
            try:
                order_info = order_executor.reconcile_to_target(broker=broker, symbol=sym,
                                                               target_exposure=target,
                                                               price=price, budget=per_budget,
                                                               extended=extended,
                                                               positions=held_now)
                if order_info.get("order_id"):
                    orders_this_cycle += 1
                    bot["orders_sent"] += 1
                    bot["last_order"] = datetime.now(timezone.utc).isoformat()
                    parts.append(f"{order_info['action']} {order_info['qty']} @~{order_info['price_ref']}")
                _ORDER_ERR[sym] = 0                       # a clean pass clears the error streak
            except Exception as e:
                bot["errors"] += 1
                bot["last_error"] = f"{sym}: {str(e)[:120]}"
                _ORDER_ERR[sym] = _ORDER_ERR.get(sym, 0) + 1
                parts.append(f"order error: {str(e)[:60]}")
                alerts.log_event("order_error", f"{sym}: {str(e)[:180]}")
                if _ORDER_ERR[sym] >= ORDER_ERR_LIMIT:    # stop hammering a rejecting symbol
                    _ORDER_COOLDOWN[sym] = now_utc + timedelta(minutes=ORDER_ERR_PAUSE_MIN)
                    alerts.log_event("order_pause",
                                     f"{sym}: {ORDER_ERR_PAUSE_MIN} min pausiert nach {_ORDER_ERR[sym]} Fehlern")

        reason_full = " · ".join(parts)
        # The journal is the audit trail: `factors` keeps the reasons SEPARATE instead of
        # glued into one string, and every input that moved the decision is stored next to
        # it. Six months from now "why did it buy NVDA at 14:32" has to be answerable
        # without re-deriving anything.
        _journal({"type": "cycle", "symbol": sym, "decision": decision, "regime": info["regime"],
                  "confidence": info["confidence"], "exposure": round(target, 4),
                  "session": session, "order": order_info, "reason": reason_full,
                  "factors": parts,
                  "raw_exposure": round(raw_expo.get(sym, target), 4),
                  "price": round(price, 2), "budget": round(per_budget, 2),
                  "target_notional": round(abs(target) * per_budget, 2),
                  "stable": info["stable"], "regime_rank": info["regime_rank"],
                  "n_regimes": info["n_regimes"], "tradable": tradable, "extended": extended,
                  "risk_multiplier": mult, "breakers": rstate["breakers"],
                  "radar_level": radar.get("level"), "radar_multiplier": radar.get("multiplier"),
                  "deadband": deadband})
        signals.append({"symbol": sym, "asset_class": "crypto" if crypto else "us_equity",
                        "session": session, "session_label": sessions.SESSION_LABEL.get(session, session),
                        "tradable": tradable, "regime": info["regime"],
                        "regime_rank": info["regime_rank"], "n_regimes": info["n_regimes"],
                        "confidence": info["confidence"], "exposure": round(target, 4),
                        "price": round(price, 2), "target_notional": round(abs(target) * per_budget, 2),
                        "direction": "long" if target > 0 else ("short" if target < 0 else "flat"),
                        "decision": decision, "stable": info["stable"], "reason": reason_full,
                        "stop_price": (exit_dec.get(market_data.pos_symbol(sym)) or {}).get("stop_price"),
                        "stop_pct": (exit_dec.get(market_data.pos_symbol(sym)) or {}).get("stop_pct"),
                        "targets": (exit_dec.get(market_data.pos_symbol(sym)) or {}).get("targets")})

    if broker.connected and orders_this_cycle:
        time.sleep(2)                                    # let market orders fill before read-back
    positions_live = broker.positions() if broker.connected else []
    raw_orders = broker.list_orders(status="all", limit=500) if broker.connected else []
    acct = broker.account() if broker.connected else acct
    settings.ORDERS.write_text(json.dumps([_order_row(o) for o in raw_orders], indent=2), encoding="utf-8")
    # 24/7 observation layer: re-mine the loss/win CONNECTIONS from the fresh order book.
    # Self-skips when nothing new closed, never raises -- the memory keeps learning between
    # the (gated) parameter runs, without ever touching the trading decision.
    try:
        insights.refresh()
    except Exception:
        pass
    settings.POSITIONS.write_text(json.dumps({"open": positions_live, "pending": []}, indent=2), encoding="utf-8")
    settings.SIGNALS.write_text(json.dumps(signals, indent=2), encoding="utf-8")
    if broker.connected and acct.get("equity") is not None:
        _append_equity(acct, exec_cfg)

    _write_prices(bars)
    bot["cycles"] += 1
    bot["started"] = bot.get("started") or datetime.now(timezone.utc).isoformat()
    _save_bot_state(bot)

    _heartbeat(alive=True, market_open=overview["equity_tradable"] or overview["crypto_tradable"],
               equity_session=overview["equity_session"], crypto_open=True,
               session_overview=overview, radar=radar,
               killed=rstate["killed"], cash=acct.get("cash"), account_equity=acct.get("equity"),
               buying_power=acct.get("buying_power"),
               broker=("connected" if broker.connected else "offline"),
               open_positions=len(positions_live), orders_placed=len(raw_orders),
               orders_this_cycle=orders_this_cycle, cycles=bot["cycles"],
               longs=sum(1 for s in signals if s["direction"] == "long"),
               shorts=sum(1 for s in signals if s["direction"] == "short"),
               tradable_now=sum(1 for s in signals if s.get("tradable")))
    if rstate["breakers"]:
        alerts.log_event("circuit_breaker", ",".join(rstate["breakers"]))
        alerts.send("breaker", f"breakers {rstate['breakers']}")
    dashboard_export.build()
    return signals


PRICE_BARS = 240          # bars kept per symbol for the dashboard trade chart


def _write_prices(bars):
    """Recent bars per symbol so the dashboard can draw where each trade happened.
    Separate file, lazily fetched by the browser -- inlining this into trading.json
    would triple every dashboard poll for data that is only needed on demand."""
    out = {}
    for sym, df in bars.items():
        tail = df.tail(PRICE_BARS)
        if not len(tail):
            continue
        out[sym] = [[t.isoformat(), round(float(o), 4), round(float(h), 4),
                     round(float(lo), 4), round(float(c), 4)]
                    for t, o, h, lo, c in zip(tail.index, tail["open"], tail["high"],
                                              tail["low"], tail["close"])]
    payload = json.dumps({"generated": datetime.now(timezone.utc).isoformat(),
                          "bars": out}, separators=(",", ":"))
    settings.PRICES.write_text(payload, encoding="utf-8")
    try:
        if settings.PUBLIC_PRICES.parent.exists():
            settings.PUBLIC_PRICES.write_text(payload, encoding="utf-8")
    except Exception:
        pass


def _append_equity(acct, exec_cfg):
    """Append one equity snapshot and keep the file from growing without bound --
    at a 60s cycle this file gains ~1440 lines per day, forever."""
    with open(settings.EQUITY_HISTORY, "a", encoding="utf-8") as f:
        f.write(json.dumps({"ts": datetime.now(timezone.utc).isoformat(),
                            "equity": acct["equity"], "cash": acct.get("cash")}) + "\n")
    cap = int(exec_cfg.get("equity_history_max", 200000))
    try:
        if settings.EQUITY_HISTORY.stat().st_size > cap * 90:      # ~90 bytes per line
            lines = settings.EQUITY_HISTORY.read_text(encoding="utf-8").splitlines()
            if len(lines) > cap:
                settings.EQUITY_HISTORY.write_text("\n".join(lines[-int(cap * 0.8):]) + "\n",
                                                   encoding="utf-8")
    except Exception:
        pass


def market_is_open(broker):
    """Kept for compatibility: true when ANYTHING in the universe can trade. With crypto
    in the watchlist this is always true -- per-symbol gating happens in cycle()."""
    cfg = settings.load_config()
    if any(market_data.is_crypto(s) for s in cfg["watchlist"]):
        return True
    clock = {}
    if broker is not None and broker.connected:
        try:
            clock = broker.clock()
        except Exception:
            clock = {}
    return sessions.equity_session(clock) != "closed"


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
    from recent intraday structure. Called at startup and re-run once per day. Bars are
    capped by hmm.train_bars_max because 24/7 crypto produces ~3.7x the bars an equity
    does over the same calendar window."""
    hcfg = cfg["hmm"]
    cap = int(hcfg.get("train_bars_max", 4000))
    models = {}
    for sym in symbols:
        try:
            df = market_data.get_bars(sym, days=hcfg["live_days"], timeframe=hcfg["live_timeframe"])
            df = df.tail(cap)
            df.attrs["symbol"] = sym
            models[sym] = {"model": hmm_engine.train(df),
                           "ref_vol": float(build_features(df)["realized_vol"].median()) or 0.012}
        except Exception as e:
            alerts.log_event("train_error", f"{sym}: {str(e)[:180]}")
            print(f"  ! training failed for {sym}: {str(e)[:120]}")
    return models


def main():
    once = "--once" in sys.argv
    models, risk, broker = startup()
    cfg = settings.load_config()
    crypto_n = sum(1 for s in models if market_data.is_crypto(s))
    print(f"started: {list(models)} | broker {'connected' if broker.connected else 'offline stub'} "
          f"| mode paper | {crypto_n} crypto symbols trade 24/7 | cycle {_cycle_seconds(cfg)}s",
          flush=True)
    trained_day = datetime.now(timezone.utc).date()
    try:
        while True:
            cfg = settings.load_config()
            today = datetime.now(timezone.utc).date()
            if today != trained_day:                     # fresh intraday HMMs once per day
                models = _train_models(list(models), cfg)
                trained_day = today
            sigs = cycle(models, risk, broker)            # runs 24/7 -- never skipped
            longs = sum(1 for s in sigs if s["direction"] == "long")
            shorts = sum(1 for s in sigs if s["direction"] == "short")
            traded = sum(1 for s in sigs if s["decision"] == "TRADE")
            closed = sum(1 for s in sigs if s["decision"] == "CLOSED")
            # flush=True: unter systemd ist stdout kein Terminal und wuerde blockweise
            # gepuffert -- das Log haengt dann Stunden hinterher. Die Unit setzt zusaetzlich
            # PYTHONUNBUFFERED, aber verlassen wollen wir uns darauf nicht.
            print(f"{datetime.now().strftime('%H:%M:%S')} {len(sigs)} signals | "
                  f"{longs} long {shorts} short | {traded} traded | {closed} market closed",
                  flush=True)
            if once:
                break
            time.sleep(_cycle_seconds(cfg))
    except KeyboardInterrupt:
        alerts.log_event("stop", "keyboard interrupt")
        print("stopped.")


if __name__ == "__main__":
    main()
