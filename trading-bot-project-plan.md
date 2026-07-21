# Project Plan: Automated Regime-Trading Bot (Paper Trading → Server)

*A complete, step-by-step implementation plan based on the Medium guide by
Andrew Collins, rebuilt and expanded with the missing pieces (local environment,
market-data source, overfitting control, reproducibility, state persistence,
server hardening, log rotation, alerting, update workflow, failure handling).*

**Everything runs on simulated money until you deliberately choose otherwise.
This is an educational/engineering document, not financial advice.**

---

## 0. Read This First — Ground Rules

Internalise these before installing anything. They decide whether the project
costs you money and tokens, or almost nothing.

1. **The running bot costs 0 tokens.** Its "brain" is a Hidden Markov Model —
   pure local statistics. At runtime it does **not** call Claude or any LLM.
   Tokens are spent **once, while building**, because Claude Code writes the code.
2. **Testing has three stages, always in this order:** Backtest (offline,
   historical) → Paper trading (real prices, fake money) → *maybe, much later*
   Live. You never skip a stage.
3. **"Always be trading" is a bug, not a goal.** A good bot mostly observes and
   only acts on a real signal. Forced constant trading (overtrading) bleeds money
   through fees, slippage and bad entries. Trade count is not a quality metric.
4. **Nobody can "perfect" trading.** Even professionals with huge budgets rarely
   beat the market reliably over the long run. Treat this as a discipline and
   learning tool, not a money machine.

---

## 1. What You're Actually Building

Five layers, built bottom-up in this order. The backtester and data layer sit
under layers 1–2 and need **no** broker connection — that's why half the work is
testable before you ever touch an account.

| # | Layer | Job | Files |
|---|-------|-----|-------|
| 0 | **Data** | Fetch historical + live bars, compute features. | `market_data.py`, `feature_engineering.py` |
| 1 | **Brain** | Classify market regime (crash/bear/neutral/bull/euphoria) via HMM. Describes *conditions*, not the future. | `hmm_engine.py` |
| 2 | **Allocation** | Given the regime + confidence, decide *how much* capital to deploy. | `regime_strategies.py` |
| 3 | **Safety** | Circuit breakers that shut everything down on losses. The most important layer. | `risk_manager.py` |
| 4 | **Brokerage** | Connection to Alpaca (paper first). | `alpaca_broker.py`, `order_executor.py`, `position_tracker.py` |
| 5 | **Presentation** | Dashboard + alerts. | `dashboard.py`, `alerts.py` |

**Data flow each cycle:** fetch bars → build features → HMM returns regime +
confidence → allocation turns that into a target position → risk manager
validates/overrides → order executor places or skips the trade → everything is
logged to the journal.

---

## 2. Realistic Expectations (read before you start, not after)

- **"In one afternoon" and "134 tests passing" is marketing.** Expect debugging,
  error messages, and several iteration rounds. That is normal, not failure.
- **HMM regime detection is a legitimate technique** — but it labels *conditions*,
  it does not predict prices. Regimes also flicker; that's why a stability filter
  exists.
- **A good backtest is a ticket to the next stage, not a profit guarantee.**
  Walk-forward testing on blind data is more honest than a normal backtest, but
  the real future is always new.
- **The biggest self-inflicted risk is overfitting** (Section 10). If you keep
  tweaking parameters until the backtest looks great, you've memorised the past,
  not found an edge.
- This is **not financial advice.** All decisions, sizing, tax and compliance are
  your responsibility.

---

## 3. Prerequisites & Accounts

- [ ] **Visual Studio Code** — code.visualstudio.com
- [ ] **Claude Code** extension for VS Code. Installing is free; *using* it spends
      your Anthropic credit/subscription (modest for one build).
- [ ] **Python 3.11+** installed locally.
- [ ] **Git** installed locally, plus a **private** GitHub repo (for the deploy step).
- [ ] **Alpaca account (paper)** — alpaca.markets, email only, available globally.
- [ ] An empty project folder.

---

## PHASE 0 — Local Environment Setup (€0 · 0 tokens)

**0.1 Install tools**
1. Install and open VS Code. Create an empty folder `regime-trader`, open it
   (*File → Open Folder*).
2. Extensions panel → search "Claude Code" → install. The Claude Code panel
   appears on the right. From here you give instructions in plain language.

**0.2 Prepare a Python virtual environment**
You need this so the local tests in Phase 1 can actually run. In the VS Code
terminal, inside the project folder:
```
python3.11 -m venv .venv
# macOS/Linux:
source .venv/bin/activate
# Windows (PowerShell):
.venv\Scripts\Activate.ps1
```
Keep this venv active whenever you run code or tests. Tell Claude Code to install
into it (it will use `pip`); you'll also generate `requirements.txt` in Phase 1.

**0.3 Initialise git early**
```
git init
```
You'll add the `.gitignore` in Phase 1; committing as you go gives you rollback
points if a later prompt breaks something.

**0.4 Create the Alpaca paper account** (can also wait until Phase 2)
Register with email at alpaca.markets. You start in **paper mode** automatically —
no real money. Don't fetch the API keys yet; do that in Phase 2, right before use.

---

## PHASE 1 — Build to the Backtester (tokens once · €0 risk)

Goal: reach a working backtester and find out whether the strategy is worth
anything at all — **without** broker, dashboard, or any real risk.

### 1.1 Scaffold the project (one prompt to save tokens)

> "Create a Python project called regime-trader with the following file structure.
> No logic yet, just the skeleton. Include: settings.py, credentials via .env
> file, hmm_engine.py, regime_strategies.py, risk_manager.py, alpaca_broker.py,
> order_executor.py, position_tracker.py, market_data.py, feature_engineering.py,
> backtester.py, performance.py, dashboard.py, alerts.py, main.py,
> requirements.txt, and a tests folder. Add a .gitignore that excludes the .env
> file, the .venv folder, __pycache__, logs, and any local state/journal files."

Why the extended `.gitignore`: it keeps your future API keys (`.env`), your local
data, and your logs out of any repository — critical for the deploy step later.

Commit now: `git add -A && git commit -m "scaffold"`.

### 1.2 Build the data layer (this is missing from most guides — do it first)

The HMM has nothing to learn from without data. Build the fetch/feature layer
before the brain.

> "Implement market_data.py and feature_engineering.py. market_data.py should
> fetch historical daily bars (at least 2 years) and recent intraday bars for a
> configurable watchlist, using Alpaca's market data API, reading credentials
> from .env. Add a caching layer so repeated backtests reuse downloaded data
> instead of re-fetching. Handle missing data, splits, and gaps gracefully.
> feature_engineering.py should compute the inputs the HMM needs (e.g. log
> returns, realised volatility, volume z-score) with no look-ahead: every feature
> at bar t may only use data up to and including bar t. Include unit tests that
> assert no future data leaks into any feature."

Note on Alpaca's free data: the free tier uses the IEX feed and is fine for daily
bars and paper testing. Don't expect exchange-consolidated tick data for free;
that's not needed here.

### 1.3 Build the brain (HMM)

> "Implement the HMM regime detection engine in hmm_engine.py. Use a Gaussian HMM
> that tests between 3 and 7 regimes and automatically selects the best number
> using BIC scores. Sort regimes by mean return so they label automatically:
> 3 = bear/neutral/bull; 4 = crash/bear/bull/euphoria; 5 = crash/bear/neutral/
> bull/euphoria. Train on 2 years of daily data. IMPORTANT: use the forward
> algorithm only, NOT the model predict function, to avoid look-ahead bias. Set
> and expose a fixed random_state/seed so training is reproducible across runs.
> Add a stability filter: a regime must persist for at least 3 consecutive bars
> before the system acts on it; if it flickers more than 4 times in 20 bars, log a
> warning and reduce position sizes. Include validation tests for HMM fit,
> reproducibility with a fixed seed, and a dedicated look-ahead-bias test."

Two details that matter most:

- **Forward algorithm only.** Many HMM libraries' default `predict` processes the
  *entire* sequence at once, so the model effectively "sees" the future
  (look-ahead bias) and your backtest looks fake-good. The forward algorithm uses
  only data up to each point — honest. Skip this and you'll fool yourself.
- **Fixed seed / reproducibility.** HMM training has random initialisation.
  Without a fixed seed, retraining relabels regimes differently every run and your
  results aren't reproducible. Pin it.

Run until validation tests are green, then commit.

### 1.4 Build the allocation strategy (your signature)

> "Implement volatility-based allocation in regime_strategies.py. Base strategy:
> low volatility = 95% allocation with 1.25x leverage; medium volatility = stay
> invested if trend intact, 1.0x leverage; high volatility or crash regime = 20%
> allocation, 0.5x leverage. Add a strategy orchestrator that takes the current
> regime + confidence score and outputs a target position size. Add confidence
> bucketing: high-confidence signals get full allocation, low-confidence reduced.
> Include rebalancing logic with a minimum-change threshold so tiny target changes
> don't trigger churn. Run all existing tests plus new strategy tests."

**Leverage warning:** the base strategy uses up to **1.25x leverage**, which
magnifies losses as well as gains. For early testing, set leverage to `1.0x`
(none) in the config to stay conservative. The **minimum-change threshold** I
added above is an explicit anti-overtrading guard — without it the bot rebalances
on every micro-move.

This file is where you'll spend the most time. **The logic stays; the parameters
(percentages, leverage, thresholds) are yours.** Edit them **directly in the
editor** — that costs **0 tokens.**

### 1.5 Build the walk-forward backtester (the honest test)

> "Build a walk-forward backtesting engine in backtester.py and performance.py.
> Use rolling windows: 252 trading days in-sample training, 6 months
> out-of-sample evaluation, rolled forward. Include realistic slippage and a
> configurable commission model. Calculate total return, CAGR, Sharpe ratio, max
> drawdown, win rate, average win/loss, and total trades. Break performance down
> by regime and by confidence bucket. Compare against three benchmarks: buy &
> hold, 200-day SMA trend-following, and random entry using the same risk rules.
> Add stress tests injecting 10–15% single-day crash events. Output a summary
> table and save per-run results to a file so runs are comparable. Run all tests."

**How to read the output honestly:**

- **Beating buy & hold** is the key test. If all this machinery can't beat simply
  buying and holding, the complexity isn't justified.
- **Max drawdown** tells you what you'd have to stomach emotionally.
- **Sharpe** is return per unit of risk; higher is better but never sufficient alone.
- **Random-entry benchmark** is the honesty check: if your strategy barely beats
  random entries with the same risk rules, your "edge" is mostly the risk layer,
  not the brain.
- **Total trades** unusually high → suspect overtrading.

> ### ⛔ STOP POINT
> Stop here and iterate. Run → see where it breaks → adjust parameters in the
> editor (0 tokens) → re-run. **Only proceed to Phase 2 when the strategy
> convincingly beats the benchmarks on blind, out-of-sample data.** If it
> disappoints here, real money won't fix it. Read Section 10 on overfitting
> before you tune aggressively.

Commit a tagged version once you're satisfied: `git commit -am "backtester v1"`.

---

## PHASE 2 — Risk, Broker, Wiring, Dashboard, Alerts (tokens once · €0 while paper)

### 2.1 Risk management (not optional)

> "Implement the risk management layer in risk_manager.py. Circuit breakers:
> down 2% in a day = halve all position sizes; down 3% in a day = close all
> positions; down 5% in a week = resize down; down 10% from peak = stop the entire
> system and write an emergency lock file that must be manually deleted to resume.
> Per-trade risk: max 1% of portfolio. Add leverage limits, order validation, and
> correlation checks that block new positions correlated above 0.7 with existing
> ones. This layer must work completely independently of the HMM. On startup it
> must check for the lock file and refuse to run if present. Persist daily/weekly
> P&L and peak-equity state to disk so limits survive restarts. Run all tests."

The **−10% lock file** is the most important rule: after a hard loss the system
physically won't restart until you delete the file by hand — forcing you to sit
down and understand what happened. Note the addition above: risk state is
**persisted to disk**, so a restart doesn't reset your daily-loss counter to zero
(a subtle but dangerous bug in naive bots).

### 2.2 Connect Alpaca paper account (the security step)

1. In the Alpaca dashboard → **API Keys (paper)**. You need: **Base URL (paper)**,
   **API Key**, **Secret Key**.
2. **The single most important security rule: NEVER type your keys into the
   Claude Code chat.**
3. Open `.env` manually in VS Code and enter them:
```
ALPACA_API_KEY=your_api_key_here
ALPACA_SECRET_KEY=your_secret_key_here
ALPACA_PAPER=true
ALPACA_BASE_URL=https://paper-api.alpaca.markets
```
`ALPACA_PAPER=true` + the `paper-api` URL are your guarantee no real money is
involved. `.env` is already gitignored.

4. Then:

> "Implement the Alpaca broker integration in alpaca_broker.py, order_executor.py,
> and position_tracker.py. Read all credentials from .env only, never hardcode.
> Build broker connection, order submission (market + limit + bracket),
> cancellation, stop modification, position tracking, and a real-time data feed.
> position_tracker.py must persist open positions and pending orders to disk and
> reconcile them against Alpaca on startup, so a restart never loses track of
> state. Add error handling with retries and backoff for API downtime, data-feed
> drops, and partial fills. Place a small test buy order for NVDA to confirm it
> reaches the paper account."

5. Check the Alpaca dashboard — if the test order appears, the connection works.

### 2.3 Wire everything together

> "Build the main orchestration loop in main.py. On startup: load config, check
> the emergency lock file (refuse to start if present), connect to Alpaca, verify
> account status, reconcile persisted positions, check market hours, train the
> HMMs, initialise risk manager and position tracker, start data feeds, and write
> a heartbeat/health file. Main loop on each 5-minute bar close: fetch data, build
> features, get regime + confidence, get allocation signal, validate through the
> risk manager, execute required trades, update the heartbeat, log everything.
> Skip trading logic entirely when the market is closed, but keep the process
> alive. Include graceful shutdown (finish/records current cycle, close feeds
> cleanly on SIGTERM)."

The **heartbeat/health file** (added above) is what lets you verify from outside
that the bot is alive and looping — essential once it runs headless on a server.

### 2.4 Alerts (wire up the file the guide forgot)

> "Implement alerts.py. Send a notification when: a circuit breaker fires, the
> emergency lock file is written, the bot starts or stops, an order is rejected,
> or an unhandled error occurs. Make the transport configurable via .env (e.g. an
> SMTP email or a generic webhook URL) and no-op silently if not configured, so
> the bot never crashes because alerting failed. Rate-limit alerts so one bad loop
> can't send hundreds of messages."

Now the −10% lock event actually reaches you instead of sitting silently in a log.

### 2.5 Performance visualisation (dashboard)

This is the view you "call up" to see how the bot performs. It has two jobs:
show **live status** (what is it doing right now) and show **performance over
time** (is it actually any good). Design target — one clean page, grouped into
clearly labelled sections, top to bottom:

1. **Header bar** — bot name, a status pill (`running · paper`), the current
   regime + confidence badge, and a "last updated" timestamp. One glance tells you
   it's alive and what it thinks the market is doing.
2. **Metric cards row** (the headline numbers): portfolio value + % since start,
   outperformance vs buy & hold, Sharpe, max drawdown, win rate (with trade
   count), current exposure %. These are the "is it good?" numbers.
3. **Equity curve** (full width) — the single most important chart: bot equity vs
   a buy-and-hold benchmark on the same axis. If the solid line isn't above the
   dashed benchmark, the whole strategy is in question.
4. **Drawdown chart** — an "underwater" plot of % below the running peak. Shows
   the pain you'd have had to sit through, which the equity curve alone hides.
5. **Monthly returns** — a bar per month, green up / red down. Shows consistency:
   one lucky month vs steady performance look very different here.
6. **Time in each regime** — a doughnut of how much time the market spent in each
   regime (crash/bear/neutral/bull/euphoria), colour-coded consistently everywhere.
7. **Regime confidence over time** — a line of the model's confidence. Lets you
   see whether trades happened during high- or low-confidence periods.
8. **Risk status panel** — daily/weekly P&L, distance to each circuit breaker,
   drawdown from peak, whether the −10% kill switch is armed, and whether a lock
   file exists. Your safety readout.
9. **Recent activity feed** — per row: symbol, side, regime at the time,
   confidence, and P&L. Crucially, it also shows **skipped** cycles ("no trade —
   below threshold"), so you can see the bot correctly *not* trading.

**Design principles (keep it clear, not busy):** one accent colour plus semantic
green/red for gains/losses; a **single consistent colour per regime** reused in
every chart and badge; flat surfaces, thin hairline borders, generous spacing;
charts share one y-axis each (never dual-axis); every number rounded; sections
labelled so the eye lands where it needs to. Two-column chart rows collapse to one
column on narrow screens.

Build it with this prompt:

> "Build a clean, well-organised Streamlit dashboard in dashboard.py, grouped into
> labelled sections top-to-bottom: (1) header with bot name, running/paper status
> pill, current regime + confidence badge, and last-updated time; (2) a row of
> metric cards: portfolio value with % since inception, outperformance vs buy &
> hold, annualised Sharpe, max drawdown, win rate with trade count, exposure %;
> (3) a full-width equity-curve line chart of bot equity vs a buy-and-hold
> benchmark on one shared axis; (4) an underwater drawdown chart (% below running
> peak); (5) a monthly-returns bar chart, green for positive and red for negative;
> (6) a doughnut of time spent in each regime; (7) a regime-confidence line over
> time; (8) a risk-status panel with daily/weekly P&L, distance to each
> circuit-breaker threshold, drawdown from peak, kill-switch state, and lock-file
> presence; (9) a recent-activity table including skipped cycles with the reason.
> Use one consistent colour per regime across all charts and badges, one accent
> colour, and semantic green/red for gains/losses; flat design, thin borders,
> generous spacing, single y-axis per chart, all numbers rounded, responsive so
> chart rows stack on narrow screens. Pull live values from Alpaca and history
> from the local journal/state. Add a date-range selector and a refresh control.
> Bind the server to 127.0.0.1 only. Install required Streamlit dependencies and
> add them to requirements.txt."

**How you call it up — two modes:**

- **Locally (during the build/local test):** `streamlit run dashboard.py`, then
  open the URL it prints (usually `http://localhost:8501`).
- **On the server (once deployed):** never expose it publicly — reach it through
  an SSH tunnel. Full steps are in **Phase 3B.7**. Short version:
  `ssh -L 8501:localhost:8501 user@YOUR_SERVER_IP`, run the dashboard bound to
  `127.0.0.1` on the server, then open `http://localhost:8501` on your own machine.

**Optional — a self-contained HTML report (no server needed).** If you just want
to *check* performance occasionally rather than watch a live page, have the bot
also emit a static report:

> "Add a report generator that reads the journal and writes a standalone
> report.html with the same metrics and an equity-curve chart, using an embedded
> JS chart library so it opens in any browser with no server. Regenerate it at the
> end of each trading day."

You can then download `report.html` (or have it emailed via `alerts.py`) and open
it anywhere — zero attack surface, zero running dashboard.

Commit, then freeze dependencies: `pip freeze > requirements.txt` and commit again
(you'll reuse this exact file on the server).

### 2.6 Balance history & trade analytics (second view)

The dashboard in 2.5 answers "how is it doing right now?". This second view
answers "how has it traded over time?" — balance across selectable periods, plus
per-trade analytics. Group it as its own tab/page (or a section below), top to
bottom:

**Balance over time (with timeframe control).** A balance line with buttons for
`1M / 3M / 6M / 1Y / All`; clicking one reloads the chart for that window and
updates a headline figure (current balance + absolute and % change over the
window). This is the "am I up or down, and over what span?" view.

**Trade statistic cards:** total trades, average win, average loss, profit factor
(gross wins ÷ gross losses — above 1.0 means winners outweigh losers), and
expectancy (average P&L per trade — your edge per trade in currency).

**Trade charts:**
- **Cumulative P&L** — running total across trades (by trade number). A steadily
  rising line is what you want; long flat or falling stretches are losing streaks.
- **P&L per trade** — one bar per trade, green win / red loss. Reveals whether a
  few outliers carry the whole result.
- **P&L by regime** — total P&L grouped by regime, coloured with the same regime
  palette as everywhere else. Tells you *where* the edge (or bleeding) is: e.g. if
  all profit comes from `bull` and `bear` loses money, you've learned something
  actionable.
- **Return distribution** — a histogram of per-trade returns. A healthy shape has
  losses capped (thanks to the 1%-risk rule) and a right tail of larger winners.

Build it with this prompt:

> "Add a second dashboard view (a Streamlit tab or page) for balance history and
> trade analytics. (1) Balance-over-time line chart with timeframe buttons
> 1M/3M/6M/1Y/All that reload the window and update a headline showing current
> balance plus absolute and % change over that window. (2) Trade-statistic cards:
> total trades, average win, average loss, profit factor, expectancy. (3)
> Cumulative-P&L line by trade number. (4) P&L-per-trade bar chart, green for
> wins and red for losses. (5) P&L-by-regime bar chart using the same per-regime
> colours as the main dashboard. (6) A return-distribution histogram of per-trade
> P&L. Read everything from the trade journal. Reuse the shared regime colour map,
> keep one y-axis per chart, round all numbers, and make chart rows responsive."

A subtle but important reading tip for this view: **judge the strategy by the
by-regime and distribution charts, not the headline balance.** A rising balance
built entirely on one lucky regime, or on a couple of outsized trades, is fragile.
Consistent small edges across regimes are what survive going forward.

---

## PHASE 3 — Local Paper Run & Observation (€0 risk)

Run on paper and watch it. For every event ask: Why did it rebalance? Why did the
risk manager block a trade? What was happening in the market when a circuit
breaker nearly triggered?

**On "run 24/7 and always trade":** separate two things.

- **Running 24/7** (always on, watching): your laptop won't do this. For the first
  days of testing, running it locally during market hours is enough. For true
  continuous operation you need a server — that's **Phase 3B**. Recommendation:
  run locally a few days first, deploy once it starts cleanly and throws no obvious
  errors.
- **Trading 24/7** (nonstop orders): you do **not** want this. US stocks trade
  ~24/5 at most (closed weekends); truly around-the-clock would mean crypto, the
  most volatile asset class. And a bot that *must* trade is broken by definition.
  It should observe and act only on a signal.

Measure success by whether the few trades made sense in hindsight — not by how
many there were.

---

## PHASE 3B — Server Deployment (24/7 · still paper)

Goal: the bot runs continuously without your laptop, survives crashes and reboots,
still on **paper** until Phase 4. A server holding trading credentials is a real
attack surface, so security here is mandatory, not optional.

### 3B.1 Pick a server

A small **Linux VPS** is plenty: 1 CPU, 1–2 GB RAM, a few GB disk (roughly
€4–6/month at the usual providers). Use **Ubuntu LTS** (e.g. 24.04). The server's
physical location is irrelevant to market hours — your `main.py` handles market
timing in code; the server just needs a correct clock (see 3B.3).

### 3B.2 Lock down access before anything else

1. **SSH key login instead of passwords.** On your machine:
   ```
   ssh-keygen -t ed25519 -C "trading-bot-server"
   ssh-copy-id user@YOUR_SERVER_IP
   ```
2. On the server, in `/etc/ssh/sshd_config` set `PasswordAuthentication no`, then
   `sudo systemctl restart ssh`.
3. **Firewall — only SSH open:**
   ```
   sudo ufw allow OpenSSH
   sudo ufw enable
   ```
   The dashboard port stays **closed**. You'll reach the dashboard through an SSH
   tunnel (3B.7), never the open internet.
4. Create a non-root user for the bot and run everything as that user (not root).

### 3B.3 Install runtime + set the clock

```
sudo apt update && sudo apt upgrade -y
sudo apt install -y python3.11 python3.11-venv git
# ensure time is correct — market-hours logic depends on it:
timedatectl set-ntp true
```
Keep the server in **UTC** and let the code convert to US market time; this avoids
daylight-saving surprises (see Section 10).

### 3B.4 Get the project onto the server

Preferred: push to a **private** GitHub repo and clone it. The `.env` is gitignored,
so it will **not** be in the repo — that's intended; you recreate it on the server
next. Then:
```
cd ~/regime-trader
python3.11 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt     # the frozen file from 2.5 = identical deps
```

### 3B.5 Secrets on the server (the only place keys belong)

```
nano ~/regime-trader/.env
```
```
ALPACA_API_KEY=your_api_key_here
ALPACA_SECRET_KEY=your_secret_key_here
ALPACA_PAPER=true
ALPACA_BASE_URL=https://paper-api.alpaca.markets
```
Restrict permissions so only your user can read it:
```
chmod 600 ~/regime-trader/.env
```
Best practice: generate a **separate paper key pair** for the server, so if you
ever rotate or leak one, the others are unaffected.

### 3B.6 Run the bot as a service (autostart + restart on crash)

```
sudo nano /etc/systemd/system/regime-trader.service
```
```
[Unit]
Description=Regime Trading Bot (Paper)
After=network-online.target
Wants=network-online.target

[Service]
Type=simple
User=YOUR_USER
WorkingDirectory=/home/YOUR_USER/regime-trader
ExecStart=/home/YOUR_USER/regime-trader/.venv/bin/python main.py
Restart=always
RestartSec=10
StandardOutput=append:/home/YOUR_USER/regime-trader/logs/bot.log
StandardError=append:/home/YOUR_USER/regime-trader/logs/bot.err.log

[Install]
WantedBy=multi-user.target
```
```
mkdir -p ~/regime-trader/logs
sudo systemctl daemon-reload
sudo systemctl enable regime-trader
sudo systemctl start regime-trader
sudo systemctl status regime-trader
tail -f ~/regime-trader/logs/bot.log
```
**Lock file vs. Restart=always:** `Restart=always` brings the process back after a
*crash*, but the −10% lock file (2.1) is checked on startup and *blocks* a real
restart until you delete it manually. That's correct: after a hard loss the system
stays down regardless of systemd. Verify `main.py` actually performs the lock check
on startup.

### 3B.7 Reach the dashboard safely (never expose it)

The dashboard shows balances and runs next to your keys. **Do not expose it.**
Reach it via an SSH tunnel from your own machine:
```
ssh -L 8501:localhost:8501 user@YOUR_SERVER_IP
```
Run the dashboard as a second systemd service (same pattern) or in a `tmux`
session, bound to localhost:
```
streamlit run dashboard.py --server.address 127.0.0.1
```
Then open `http://localhost:8501` in your browser. Traffic is encrypted through
the tunnel; the port is never visible externally.

### 3B.8 Log rotation (or your disk fills up)

Append-mode logs grow forever and will eventually fill a small VPS. Add rotation:
```
sudo nano /etc/logrotate.d/regime-trader
```
```
/home/YOUR_USER/regime-trader/logs/*.log {
    daily
    rotate 14
    compress
    missingok
    notifempty
    copytruncate
}
```

### 3B.9 Back up the journal and state

The trade journal and state are your most valuable output (your learning
material). Back them up daily:
```
crontab -e
0 23 * * * tar -czf ~/backups/state-$(date +\%F).tar.gz ~/regime-trader/logs ~/regime-trader/state
```

### 3B.10 Update workflow (how to ship a fix safely)

1. Test the change locally and confirm backtests/tests still pass.
2. Commit and push to the private repo.
3. On the server:
   ```
   cd ~/regime-trader && git pull
   source .venv/bin/activate && pip install -r requirements.txt
   sudo systemctl restart regime-trader
   ```
4. **Rollback if it breaks:** `git checkout <previous-tag> && sudo systemctl restart regime-trader`.
   This is why you tag known-good versions.

### 3B.11 Post-deploy verification

- [ ] `systemctl status regime-trader` shows **active (running)**
- [ ] `bot.log` fills up, no crash-loop
- [ ] Heartbeat/health file updates each cycle
- [ ] Alerts arrive (trigger a harmless test alert)
- [ ] Alpaca paper dashboard balances match your own dashboard
- [ ] Reboot test (`sudo reboot`) → bot comes back on its own
- [ ] Lock-file test: create the lock file by hand → bot refuses to start until deleted

---

## PHASE 4 — Going Live (real money) — only with strong caveats

Only after you understand **every** decision the system makes and paper trading
convinced you over weeks. Then:

- Open an Alpaca **brokerage** (live) account — real identity onboarding.
- Switch `.env`: `ALPACA_PAPER=false` and the live base URL.
- Start with an amount whose **total loss** you'd be emotionally fine with.

**Live transition checklist:**
- [ ] ≥1 month of clean paper operation with results you understand
- [ ] Backtest still beats benchmarks on the latest out-of-sample data
- [ ] All circuit breakers tested and observed firing correctly on paper
- [ ] Alerts confirmed working end-to-end
- [ ] Leverage set deliberately (start at 1.0x)
- [ ] Position size floor small enough that one bad day is survivable
- [ ] You know your tax/reporting obligations for realised gains

For your stated goal (testing without money risk) this phase is **not required.**

---

## 10. Cross-Cutting Concerns (the "completely thought through" part)

**Overfitting — the number-one trap.** Every time you tune a parameter because the
backtest improved, you risk fitting noise. Guardrails: keep a final chunk of
history as a *hold-out* you never tune on; prefer fewer parameters; a strategy that
works across many tickers/periods is more trustworthy than one perfectly tuned to
one; be suspicious of "too good" Sharpe (>2–3 for a simple retail strategy is a red
flag, not a triumph).

**Market data limits.** Alpaca's free tier (IEX) is fine here but isn't full
consolidated data; don't build logic that assumes tick-perfect fills. Slippage and
partial fills are real — that's why the backtester models slippage and the executor
handles partial fills.

**Time zones & DST.** US markets follow US Eastern Time with daylight-saving
shifts. Keep the server in UTC, do all market-hour logic via a proper timezone
library (not fixed UTC offsets), and use Alpaca's market calendar/clock endpoints
rather than hardcoded hours (they also handle holidays and half-days).

**Reproducibility.** Fixed HMM seed (1.3), pinned `requirements.txt` (identical
locally and on the server), and tagged git versions mean a given commit behaves the
same everywhere. Without these you can't debug "it worked yesterday."

**State persistence.** Positions, pending orders, daily/weekly P&L, and peak equity
must survive restarts (2.1, 2.2). A bot that forgets its daily loss after a reboot
can blow through its own circuit breaker.

**Failure modes to expect.** API outage (retry/backoff, then pause), data-feed drop
(skip the cycle, don't trade on stale data), network loss mid-order (reconcile on
next startup), weekend/holiday (market-closed = observe only), unhandled exception
(alert + safe stop rather than silent death). The bot should fail *closed* (stop
trading) not *open* (keep firing orders blindly).

**Security recap.** Keys only in `.env` (never chat, never repo), `chmod 600`,
SSH-key login, firewall closed except SSH, dashboard via tunnel only, separate
paper keys, rotate if ever exposed.

---

## 11. Cost Summary

**Tokens (Claude Code):**
- Scaffold in one prompt, not file by file.
- Build module by module and let the **local tests** verify the work, instead of
  asking Claude to re-read all the code.
- Do parameter tuning **yourself in the editor** — 0 tokens.
- Don't paste large market-data tables into chat; the code fetches them.

**Money:**
- Keep `ALPACA_PAPER=true` until you deliberately go live.
- Backtest first — only compute time, no capital.
- Deploy the server (3B) only once the bot runs cleanly locally. The smallest VPS
  (~€4–6/month) is enough and is the only real running cost during the paper phase.

---

## 12. Troubleshooting Mindset

When something breaks: read the actual error in `bot.err.log`; reproduce it locally
with the same commit before touching the server; change one thing at a time; keep
the last known-good git tag ready to roll back to. Most "the bot did something
weird" issues are stale data, a timezone bug, or state that didn't persist — check
those three first.

---

## Master Checklist

- [ ] VS Code + Claude Code installed
- [ ] Python 3.11+, local venv active
- [ ] Git initialised; private repo ready for deploy
- [ ] Scaffold built, `.gitignore` covers `.env`/`.venv`/logs/state (1.1)
- [ ] Data layer built, no-look-ahead tests green (1.2)
- [ ] HMM brain built, seeded, look-ahead test green (1.3)
- [ ] Allocation built, leverage set to 1.0x for now (1.4)
- [ ] Backtester built, **beats benchmarks on blind data** (1.5) ← STOP POINT
- [ ] Overfitting guardrails understood (Section 10)
- [ ] Risk manager built, state persisted, lock-file check on startup (2.1)
- [ ] Alpaca paper account; keys **only** in `.env`; `PAPER=true` (2.2)
- [ ] Broker + position tracker; test order visible in Alpaca (2.2)
- [ ] main.py wired, heartbeat + market-hours skip + graceful shutdown (2.3)
- [ ] Alerts wired and tested (2.4)
- [ ] Dashboard: equity vs benchmark, drawdown, monthly returns, regime doughnut, confidence line, risk panel, activity feed; consistent regime colours; 127.0.0.1 only; `requirements.txt` frozen (2.5)
- [ ] Second view: balance-over-time with 1M/3M/6M/1Y/All, trade stat cards, cumulative P&L, per-trade P&L, P&L by regime, return distribution (2.6)
- [ ] (Optional) static `report.html` generator working (2.5)
- [ ] A few days of clean local paper operation (Phase 3)
- [ ] VPS (Ubuntu LTS), SSH-key login, firewall SSH-only (3B.1–3B.2)
- [ ] Runtime installed, UTC clock, project deployed, venv from frozen deps (3B.3–3B.4)
- [ ] `.env` on server only, `chmod 600`, separate paper keys (3B.5)
- [ ] systemd service: autostart + restart; lock-file honoured (3B.6)
- [ ] Dashboard via SSH tunnel only, never public (3B.7)
- [ ] Log rotation + daily backups (3B.8–3B.9)
- [ ] Update/rollback workflow understood (3B.10)
- [ ] Post-deploy verification incl. reboot + lock-file tests (3B.11)
- [ ] ≥1 month continuous paper observation (Phase 3/3B)
- [ ] Live only after full understanding + affordable amount (Phase 4)
