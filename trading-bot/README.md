# Regime Trading Bot (paper)

A local, token-free regime-trading bot built from `../trading-bot-project-plan.md`, Phase 1
(data → HMM brain → allocation → risk → walk-forward backtester) plus a **Trading tab** in
the HQ dashboard. Everything is **simulated / paper** until you deliberately go live.

The running bot costs **0 tokens** — its brain is a Hidden Markov Model, pure local
statistics. Tokens were spent once while building.

## What's here (Phase 1 — done, offline-testable)

| File | Job |
|------|-----|
| `settings.py` | config + paths + regime colours; secrets from `.env` only |
| `market_data.py` | daily bars from Alpaca (cached), **synthetic fallback** with no keys |
| `feature_engineering.py` | log return, realized vol, volume z-score — **no look-ahead** |
| `hmm_engine.py` | Gaussian HMM, BIC picks #regimes, **forward-only** inference, fixed seed |
| `regime_strategies.py` | vol-based allocation, confidence bucketing, anti-churn threshold |
| `risk_manager.py` | circuit breakers + **−10% kill switch/lock file**, state persisted |
| `backtester.py` / `performance.py` | walk-forward + benchmarks (B&H, SMA200, random) |
| `dashboard_export.py` | writes `state/dashboard.json` → served by the dashboard as `/trading.json` |
| `alerts.py` | webhook alerts, no-op if unconfigured, rate-limited |
| `alpaca_broker.py` | **offline stub** until paper keys exist (safe: refuses live orders) |
| `main.py` | orchestration loop (paper/dry): regime → allocation → risk → journal + heartbeat |

## Setup

```bash
cd trading-bot
python -m venv .venv
.venv/Scripts/Activate.ps1        # Windows PowerShell   (macOS/Linux: source .venv/bin/activate)
pip install -r requirements.txt
pytest -q                          # 8 tests, all green
```

## Run

```bash
# 1) walk-forward backtest -> state/backtest_SPY.json
.venv/Scripts/python backtester.py

# 2) build the dashboard export -> state/dashboard.json  (the Trading tab reads this)
.venv/Scripts/python dashboard_export.py

# 3) (optional) one paper/dry cycle -> heartbeat + journal + export
.venv/Scripts/python main.py --once
```

Open the HQ dashboard → **Trading** tab. With no Alpaca keys it runs on **synthetic data**
(clearly flagged in the UI) so the whole pipeline is exercisable offline.

## Going further (Phase 2, needs your Alpaca paper keys)

1. Create an Alpaca **paper** account, then put the keys in `trading-bot/.env` (never in chat,
   never committed — `.env` is gitignored):
   ```
   ALPACA_API_KEY=...
   ALPACA_SECRET_KEY=...
   ALPACA_PAPER=true
   ALPACA_BASE_URL=https://paper-api.alpaca.markets
   ```
2. `market_data.py` then pulls real bars; `alpaca_broker.py` connects to the paper account.
3. Order submission / position reconciliation / retries slot into the marked spot in
   `main.py` (`# Phase 2 slot`). See the plan §2.2–2.4 and §3B for the server deploy.

Parameters live in `config.json` — edit them directly (0 tokens). Keep `leverage` at `1.0`
to start. **This is an engineering/educational tool, not financial advice.**
