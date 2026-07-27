# Deploy the trading bot as a service (server)

Runs `main.py` continuously as a systemd service on the same box as agents-hq. Paper only.
The bot writes `state/dashboard.json`, which the HQ dashboard already serves at `/trading.json`,
so the **Trading** tab works on the server with no extra wiring.

Do these on the server (I can't reach it from here). Replace `USER` and `BASE` with your layout,
e.g. `USER=agents`, `BASE=/home/agents/agents-hq` (or your Plesk vhost path).

## 1. Code + venv + deps

```bash
cd BASE/trading-bot
python3.11 -m venv .venv
.venv/bin/pip install -r requirements.txt
mkdir -p logs
```

## 2. Secrets (never in the repo)

The bot reads `BASE/trading-bot/.env` first, then falls back to `BASE/.env`. If your Alpaca
keys already live in the repo-root `.env` on the server, nothing to do. Otherwise:

```bash
cat > BASE/trading-bot/.env <<'EOF'
ALPACA_API_KEY=...
ALPACA_SECRET_KEY=...
ALPACA_PAPER=true
ALPACA_BASE_URL=https://paper-api.alpaca.markets
EOF
chmod 600 BASE/trading-bot/.env
```

## 3. Smoke test before installing the service

```bash
.venv/bin/python main.py --once      # one cycle: trains, checks clock, may place a paper order
.venv/bin/python dashboard_export.py # writes state/dashboard.json
```

## 4. Install the service

```bash
sudo cp deploy/regime-trader.service /etc/systemd/system/regime-trader.service
sudo sed -i "s#/CHANGE_ME/agents-hq#BASE#g; s#User=CHANGE_ME#User=USER#" /etc/systemd/system/regime-trader.service
sudo systemctl daemon-reload
sudo systemctl enable --now regime-trader
systemctl status regime-trader
tail -f logs/bot.log
```

The loop wakes every `execution.cycle_seconds` (default **60s**) and runs **around the clock** —
it never sleeps through a session. What changes is which symbols are actionable:

* **crypto** (`BTC/USD`, `ETH/USD`, …) — tradable **24/7/365**, so the bot works nights and weekends
* **equities** (`SPY`, `NVDA`, …) — Mon–Fri only: regular 09:30–16:00 ET, plus pre-market
  04:00–09:30 and after-hours 16:00–20:00 when `execution.extended_hours` is true (limit orders,
  whole shares). Outside that they show up as `CLOSED` in the dashboard instead of being faked.

Alpaca's market clock stays authoritative for the regular session (DST + holidays). `Restart=always`
brings the service back after a crash; the -10% lock file still blocks a restart after a hard loss
(by design).

### Wenn das Log stillzustehen scheint

`logs/bot.log` ist nur so aktuell wie Pythons stdout-Puffer. Die Unit setzt deshalb
`PYTHONUNBUFFERED=1` und `main.py` druckt mit `flush=True` -- ohne beides haengt das Log
stunden- bis tagelang hinterher und verliert beim Neustart alles, was noch im Puffer
stand. Faellt dir ein stehendes Log auf, pruefe NICHT das Log, sondern den Herzschlag:

```bash
cd BASE/trading-bot
python -c "import json,datetime as d;h=json.load(open('state/heartbeat.json'));print('letzter Zyklus vor', round((d.datetime.now(d.timezone.utc)-d.datetime.fromisoformat(h['ts'])).total_seconds()), 's')"
cat state/bot_state.json          # cycles, orders_sent, errors
```

Das Journal (`state/journal.jsonl`) wird pro Zeile geoeffnet und geschlossen, ist also
immer aktuell -- im Zweifel ist es die verlaessliche Quelle, nicht bot.log.

### Making it trade more or less

Everything lives in `config.json`, no redeploy needed (the loop re-reads it every cycle):

| Key | Effect |
|-----|--------|
| `execution.cycle_seconds` | how often it looks. 60 = busy, 300 = calm |
| `execution.rebalance_min_pct` | drift needed to send an order. 0.02 = busy, 0.05 = calm |
| `allocation.min_change_threshold` | neutral deadband on the signal. Lower = more trades |
| `hmm.live_timeframe` | `5Min` reacts fast, `15Min`/`1Hour` are steadier |
| `watchlist` | add/remove crypto pairs to change how much 24/7 activity there is |

More trades is **not** automatically better: every extra rebalance pays spread and slippage, and
5-minute regimes carry more noise than signal. Start where it is and watch the win rate and profit
factor in the Trading tab before turning it up further.

## Update / rollback

```bash
cd BASE && git pull && BASE/trading-bot/.venv/bin/pip install -r trading-bot/requirements.txt
sudo systemctl restart regime-trader
# rollback: git checkout <last-good-tag> && sudo systemctl restart regime-trader
```

## Turn trading off (back to observe-only)

The bot places orders whenever a cycle decides TRADE while the market is open. To pause real
orders without stopping the service, set the emergency lock (it refuses to trade) — or stop the
service: `sudo systemctl stop regime-trader`.
