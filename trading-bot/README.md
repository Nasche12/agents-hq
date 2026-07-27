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

## Chartanalyse — Muster als Detektoren

`chart_patterns.py` erkennt die klassischen Formationen algorithmisch, `chart_features.py` liefert die Einzelindikatoren. Alles als Zahl in `[-1, +1]`, alles look-ahead-frei, alles vom Walk-Forward beurteilbar.

| Formation | Regel | Signal |
|---|---|---|
| Doppeltop / -boden | zwei Extreme innerhalb 3 %, Gegenpivot dazwischen, Schluss jenseits davon | −1 / +1 |
| Kopf-Schulter (+ invers) | drei Extreme, mittleres am extremsten, äußere innerhalb 3 %, Nackenlinienbruch | −1 / +1 |
| Dreieck | flache Seite + konvergierende Seite, Ausbruch | ±1 (aufsteigend/absteigend) |
| Flagge / Wimpel | Impuls > 2 ATR, ruhige Konsolidierung, Fortsetzung | ±1 |
| Strukturbruch (BOS) | Schluss jenseits des letzten bestätigten Swings | ±1 |
| RSI-Divergenz | höheres Hoch bei schwächerem RSI (und umgekehrt) | ∓1 |

**Der entscheidende Punkt: nicht-repaintend.** Ein Swing-Hoch bei Bar *i* ist bei Bar *i* nicht bekannt — erst wenn *k* weitere Bars es nicht überboten haben. Genau deshalb repainten ZigZag-Indikatoren: Sie zeichnen die Historie neu, wenn neue Bars kommen. Ein Backtest darauf testet ein System, das die Zukunft liest.

Zwei Regeln verhindern das hier: Pivots sind **append-only** (kein Zusammenfassen gleichartiger Läufe — genau dieser Bequemlichkeitsschritt macht ZigZag repaintend), und ein Muster darf frühestens an dem Bar feuern, an dem *jeder* beteiligte Pivot bestätigt ist. Der Nackenlinienbruch wird strikt vorwärts gesucht.

Feature-Sets: `patterns` (3 Detektoren), `patterns_wide` (alle 6 — höchstes Überanpassungsrisiko), `combo` (Trend + Range + gebündelter `pattern_score`). Auswählbar über `hmm.feature_set`, für den Forscher-Agenten freigegeben.

**Quellen** — Regeln aus den gängigen veröffentlichten Definitionen: [IG](https://www.ig.com/en/trading-strategies/comprehensive-guide-on-the-head-and-shoulders-chart-pattern-for--240919) und [OANDA](https://www.oanda.com/us-en/trade-tap-blog/analysis/technical/chart-patterns-how-to-trade-head-and-shoulders-pattern/) (Kopf-Schulter, Nackenlinie, Measured Move), [FXOpen](https://fxopen.com/blog/en/trading-the-double-top-pattern-structure-signals-and-strategy/) und [TradingSim](https://www.tradingsim.com/blog/double-top) (Doppeltop-Toleranz 2–6 %, Bulkowski 6 %, Volumenregel), [TradingView](https://www.tradingview.com/scripts/zigzagindicator/) (Repainting-Verhalten von ZigZag). Wissenschaftliche Einordnung der Musterevidenz: Lo/Mamaysky/Wang 2000, *Journal of Finance*.

## Was im Kursverlauf nicht steht: Termine und Nachrichten

Das HMM sieht nur Preis und Volumen. Eine Zollankündigung um 14:00 ist um 13:59 **nicht** im Kurs — solche Schocks kann kein Blick auf Bars vorwegnehmen. `external_risk.py` schließt diese Lücke, in zwei streng getrennten Teilen:

**1. Ereigniskalender** (`market_events.json`, 0 Token) — FOMC, CPI, NFP, Zolltermine, Earnings. Das sind **Termine, keine Meinungen**: nicht manipulierbar, nicht interpretationsbedürftig. Der Bot verkleinert sich im Fenster davor und danach. Die Datei wird **absichtlich leer ausgeliefert** — erfundene Daten in einem Livesystem wären schlimmer als gar keine. Quellen zum Eintragen stehen in der Datei.

**2. Nachrichten-Stufe** (Agent `markt-waechter`) — liest alle 15 Minuten Reuters, AP, Bloomberg, FT, WSJ, CNBC und die Notenbankseiten und schreibt **eine ganze Zahl 0–3** nach `state/news_risk.json`. Keine Symbole, keine Richtung, keine Order.

| Stufe | | Faktor |
|---|---|---|
| 0 | ruhig — der Normalfall | ×1.0 |
| 1 | erhöht | ×0.8 |
| 2 | Stress | ×0.55 |
| 3 | Krise | ×0.3 |

### Warum ein LLM hier unbedenklich ist

- **Er kann nur senken.** Multiplikator in `[0, 1]`, konstruktiv geklammert und in `tests/test_external_risk.py` gegen jede Eingabe geprüft. Eine Prompt-Injection in einem Artikel kann den Bot schlimmstenfalls flach stellen — das kostet Gelegenheit, nie Kapital, und kann ihn niemals zum **Kaufen** bewegen.
- **Nur `level` wird gelesen.** Schreibt der Agent zusätzlich `symbols`, `side` oder `multiplier` in die Datei, wird das ignoriert.
- **Ausfall heilt sich selbst.** Nach 90 Minuten gilt die Datei als veraltet und der Bot handelt wieder normal, statt dauerhaft defensiv zu bleiben.
- **Die Handelsschleife bleibt deterministisch.** Der Agent schreibt eine Datei, die Schleife liest einen Parameter. Kein Sprachmodell im Minutentakt, keins in der Nähe einer Order.

### Warum nur risk-off

Beim Wissen liegt kein Vorteil — die Nachricht kennen nach Millisekunden alle. Der Vorteil läge in der Geschwindigkeit, und dieses Rennen verliert ein LLM gegen HFT kategorisch. Fünf Minuten zu spät **verkleinern** ist bloß spät. Fünf Minuten zu spät auf eine Nachricht **kaufen** heißt, die Ausstiegsliquidität der Schnelleren zu sein.

Beide Signale werden per **Minimum** mit dem Tape-Radar verrechnet — das schlechteste Signal regiert, nichts hebt sich auf.

```bash
# Agent einschalten: config/schedule.json -> markt-waechter enabled: true
python -c "import external_risk,json;print(json.dumps(external_risk.assess(),indent=2,ensure_ascii=False))"
```

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
