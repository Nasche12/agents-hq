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
| `market_data.py` | equity **and crypto** bars from Alpaca (cached), **synthetic fallback** with no keys |
| `sessions.py` | per-symbol "can this trade right now?" — crypto 24/7, equities session-bound |
| `trade_stats.py` | FIFO round-trip matching → realized P&L, win rate, profit factor |
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

## Krisen, Pumps und Streuung

`risk_radar.py` schaut jeden Zyklus auf das **Portfolio**, nicht nur auf Einzelsymbole — und darf **ausschließlich Risiko wegnehmen** (Multiplikator ≤ 1.0, konstruktiv garantiert, in `tests/test_radar.py` festgenagelt). Das ist die Auflösung des Konflikts zwischen „sofort reagieren" und „nichts Ungeprüftes live schalten": Risiko senken darf sofort passieren, Risiko aufbauen bleibt hinter dem Walk-Forward-Gate.

| Signal | Was es erkennt |
|--------|----------------|
| Volatilitätsschock | aktuelle Vol gegen den **eigenen** Median je Symbol — Krypto liest sich so nicht als Dauerkrise |
| Korrelationsanstieg | Streuung hört auf zu wirken, wenn alles gegen 1 korreliert. Die klassische Krisensignatur |
| Marktbreite | Anteil der Symbole im schwachen Regime |
| Anomalie je Symbol | abnormales Volumen **plus** Kurssprung → **deckelt** die Position auf 30 % |

Warum aus dem Tape statt aus News: Wenn eine Krise in den Schlagzeilen steht, ist der Kurs schon gefallen — für Makro-Ereignisse sind Nachrichten ein *nachlaufender* Indikator. Und wer von außen sieht, dass etwas gepusht wird, ist die Ausstiegsliquidität; Pump-Schemata brauchen genau den Käufer, der auf das Signal reagiert. Deshalb wird die Anomalie erkannt und **gekappt statt verfolgt**.

**Streuung wird jetzt auch durchgesetzt.** `config.risk.max_correlation` existierte, wurde aber nie aufgerufen — toter Code. `risk_radar.diversify()` halbiert eine Position, die stark mit einer bereits größeren Position **in dieselbe Richtung** korreliert. Gegenläufige Positionen bleiben unangetastet, die sind ein Hedge und keine Klumpenbildung.

Die Watchlist ist entsprechend umgebaut: vorher waren SPY/QQQ/AAPL/MSFT/NVDA fünf Varianten derselben Tech-Wette. Jetzt US-Breite, Tech, Small Caps, Anleihen, Gold, Energie, Finanzwerte plus ein 12er-Krypto-Korb für den 24/7-Betrieb.

## Selbstverbesserung

Der Bot lernt aus **seinen eigenen gemessenen Ergebnissen** — nie aus Texten. Die Regel: *Das LLM schlägt vor, die Daten entscheiden.*

```
research_cycle.py evidence  →  Agent liest, schreibt candidates.json  →  research_cycle.py evaluate
   (0 Token)                        (Token, 1× pro Woche)                    (0 Token)
                                                                                  ↓
                              Walk-Forward → Holdout → Allowlist → config.local.json
```

- `memory.py` — jede Hypothese mit den Zahlen, die sie entschieden haben. Ablehnungen bleiben für immer; angenommene Erkenntnisse **verfallen** und müssen neu bewiesen werden.
- `optimizer.py` / `optimizer_gate.py` — Median-Sharpe über mehrere Symbole (Median, damit kein Glückssymbol eine schlechte Idee trägt), Holdout wird nur einmal vom Sieger berührt.
- `promote.py` — **Allowlist**. Risikoschwellen, Radar-Grenzen, Ordergrößen, `trading_enabled` und die Watchlist sind gesperrt. Schreibt nach `config.local.json` (git-ignoriert), nie nach `config.json`.

```bash
python promote.py status        # was ist gelernt aktiv
python promote.py revert        # alles zurueck auf config.json
python research_cycle.py evaluate   # token-frei, mit Gitter-Fallback
```

## 24/7 operation — what is and isn't possible

The loop runs continuously (`execution.cycle_seconds`, default 60s), but a market being open
is not something software can decide:

* **Crypto pairs** (`BTC/USD`, `ETH/USD`, `SOL/USD`, `LTC/USD`) trade **24/7/365** on Alpaca.
  These are what keep the bot busy at 3am and on weekends. Alpaca has **no crypto shorting**,
  so a short signal on a crypto pair collapses to flat instead of erroring out.
* **US equities** trade Mon–Fri only. With `execution.extended_hours: true` the bot also works
  pre-market (04:00–09:30 ET) and after-hours (16:00–20:00 ET) — those must be **limit orders
  on whole shares**, which the broker layer builds automatically. Nights and weekends they are
  reported as `CLOSED`, never faked.

`sessions.py` decides this **per symbol, every cycle**, so the dashboard can show BTC trading
while SPY is correctly marked shut.
