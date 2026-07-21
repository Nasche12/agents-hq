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

The loop wakes every 5 minutes, uses Alpaca's market clock (handles DST/holidays), trades only
while the market is open, and keeps the dashboard fresh when it's closed. `Restart=always` brings
it back after a crash; the -10% lock file still blocks a restart after a hard loss (by design).

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
