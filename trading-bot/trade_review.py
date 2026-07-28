"""Per-trade retrospective -- runs on EVERY closed round-trip, deterministically, so you can
see what was done right or wrong without waiting for the weekly research run.

It is NOT the parameter optimizer (that is gated by walk-forward + holdout). This is the
plain-language post-mortem a human would write next to each trade: was this a clean winner,
a churn loss from over-trading, or a loss the whole world caused (a geopolitical shock that
moved oil, not a strategy mistake)? The world-context comparison is the point the user
asked for: a loss made while the news level was Stress/Crisis is flagged as EXOGENOUS --
you do not tune that away, the news throttle already handles it.

Pure stdlib, no LLM, no network. It reads the same recorded facts everything else does:
the round-trip, the HMM regime at entry (from the journal), and the news level in force
while the position was open (from the news timeline)."""
from datetime import datetime, timezone

LEVEL_LABEL = {0: "ruhig", 1: "erhöht", 2: "Stress", 3: "Krise"}


def _parse(iso):
    try:
        d = datetime.fromisoformat(str(iso).replace("Z", "+00:00"))
        return d if d.tzinfo else d.replace(tzinfo=timezone.utc)
    except Exception:
        return None


def _hold_min(t):
    a, b = _parse(t.get("opened")), _parse(t.get("closed"))
    return round((b - a).total_seconds() / 60.0, 1) if a and b else None


def review(t, regime=None, news_level=0, news_summary="", strong_regimes=("strong", "bull", "euphoria", "mania")):
    """Return {grade, verdict, reasons[], lesson, news_level} for one closed round-trip.
    grade: 'gut' | 'schlecht' | 'neutral'."""
    pnl = t.get("pnl") or 0.0
    pct = t.get("pnl_pct") or 0.0
    hold = _hold_min(t)
    win = pnl > 0
    scalp = hold is not None and hold < 15 and abs(pct) < 0.002
    nl = int(news_level or 0)
    reasons = []
    if regime:
        reasons.append(f"Regime bei Einstieg: {regime}")
    if nl >= 1:
        note = f"Weltlage {LEVEL_LABEL.get(nl, nl)}" + (f": {news_summary}" if news_summary else "")
        reasons.append(note)

    if not win and nl >= 2:
        grade, verdict = "neutral", "Exogener Schock"
        reasons.append("Verlust in einer Stress-/Krisenlage — nicht der Strategie anzulasten")
        lesson = "Kein Parameter-Fix: der Nachrichten-Schutz senkt hier bereits die Größe. Solche Verluste NICHT wegoptimieren (unwiederholbares Ereignis)."
    elif not win and scalp:
        grade, verdict = "schlecht", "Churn-Verlust"
        reasons.append(f"Nur {hold} min gehalten bei {pct:+.2%} — Spread/Slippage gefressen")
        lesson = "Überhandeln. Rebalance-Band/Deadband weiter stellen → weniger Mikro-Trades."
    elif not win and pct <= -0.02:
        grade, verdict = "schlecht", "Großer Verlust"
        reasons.append(f"{pct:+.2%} — der Stop hat spät oder gar nicht gegriffen")
        if regime in strong_regimes:
            reasons.append("… und das trotz starkem Regime → das Signal war fraglich")
        lesson = "Vola-skalierten Stop prüfen; ggf. Basis enger. Regime-Trennung hinterfragen."
    elif not win:
        grade, verdict = "schlecht", "Verlust"
        reasons.append(f"{pct:+.2%} bei {hold if hold is not None else '?'} min")
        lesson = "Einzelverlust im Rahmen. Erst im Muster (Verknüpfungen) beurteilen, nicht überreagieren."
    elif scalp:
        grade, verdict = "neutral", "Scalp-Gewinn"
        reasons.append("Winziger Gewinn ohne Substanz — im Grunde Spread-Rauschen")
        lesson = "Zählt kaum als Edge. Wenn viele davon: Handelsfrequenz senken, echte Bewegungen abwarten."
    elif pct >= 0.01:
        grade, verdict = "gut", "Sauberer Gewinner"
        reasons.append(f"+{pct:.2%} in {hold if hold is not None else '?'} min gehalten")
        lesson = "So soll es sein: Gewinner laufen lassen bis zum Abbau-/Trailing-Level."
    else:
        grade, verdict = "gut", "Gewinn"
        reasons.append(f"{pct:+.2%}")
        lesson = "Solider Treffer."

    return {"grade": grade, "verdict": verdict, "reasons": reasons, "lesson": lesson, "news_level": nl}


if __name__ == "__main__":
    base = {"opened": "2026-07-28T02:00:00Z", "closed": "2026-07-28T02:05:00Z"}
    # loss during a stress window -> exogenous, not a mistake
    r = review({**base, "pnl": -50, "pnl_pct": -0.03}, regime="bull", news_level=2, news_summary="USA-Iran Eskalation, Öl +6%")
    assert r["grade"] == "neutral" and r["verdict"] == "Exogener Schock", r
    assert any("Iran" in x for x in r["reasons"]), r
    # tiny quick loss in calm -> churn
    r = review({**base, "pnl": -3, "pnl_pct": -0.001}, regime="bull", news_level=0)
    assert r["grade"] == "schlecht" and r["verdict"] == "Churn-Verlust", r
    # clean winner
    r = review({"opened": "2026-07-28T02:00:00Z", "closed": "2026-07-28T03:00:00Z", "pnl": 40, "pnl_pct": 0.02},
               regime="bull", news_level=0)
    assert r["grade"] == "gut" and r["verdict"] == "Sauberer Gewinner", r
    # big loss despite strong regime -> flags the signal
    r = review({**base, "pnl": -80, "pnl_pct": -0.025}, regime="bull", news_level=0)
    assert r["grade"] == "schlecht" and any("fraglich" in x for x in r["reasons"]), r
    print("trade_review self-check ok")
