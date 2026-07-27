"""Risk inputs the price tape cannot contain.

The HMM sees only price and volume. It therefore cannot know that tariffs were announced
at 14:00, or that a war started -- those are exogenous shocks that are genuinely not in
the price at 13:59. This module is the honest answer to that gap, and it comes in two
strictly separated parts:

  1. CALENDAR (0 tokens, no judgement)   FOMC, CPI, NFP, tariff deadlines, earnings.
     Dates, not opinions -- not manipulable, not interpretable. The professional handling
     is to reduce size going into them.
  2. NEWS LEVEL (written by an LLM agent, read here as a plain number)
     The agent reads a fixed source list on a schedule and outputs ONE integer 0-3.
     Nothing else. No symbols, no direction, no order.

THE RULE BOTH OBEY: they can only ever REDUCE exposure. Multiplier in [0, 1], clamped
by construction and covered by tests.

Why that clamp is what makes an LLM safe here at all:

  * A prompt injection in a news article can, at absolute worst, push the bot flat. That
    costs opportunity, never capital. It cannot be steered into BUYING anything, because
    the only thing it can influence is a number between 0 and 3.
  * Speed: by the time anything is readable, HFT has already traded it. Entering on news
    makes you the exit liquidity. Exiting on news five minutes late is merely late.
    So: risk-off yes, risk-on never.
  * The trading loop stays deterministic. The LLM writes a file; the loop reads a
    parameter. No language model runs per cycle, per symbol, or anywhere near an order.

If the agent never runs, or its file is stale, or its content is malformed, this module
returns 1.0 and the bot behaves exactly as it did before -- silence is never treated as
an alarm, and never as an all-clear either. It is simply ignored."""
import json
from datetime import datetime, timedelta, timezone

import settings

EVENTS_FILE = settings.BASE / "market_events.json"
LEVELS = {0: "ruhig", 1: "erhoeht", 2: "stress", 3: "krise"}


def _now(now=None):
    return now or datetime.now(timezone.utc)


def _parse(iso):
    try:
        d = datetime.fromisoformat(str(iso).replace("Z", "+00:00"))
        return d if d.tzinfo else d.replace(tzinfo=timezone.utc)
    except Exception:
        return None


def _read(path, fallback):
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return fallback


# ---------------------------------------------------------------- calendar (0 tokens)
def active_events(now=None, cfg=None):
    """Scheduled high-impact events whose risk window contains `now`."""
    cfg = cfg if cfg is not None else _read(EVENTS_FILE, {})
    now = _now(now)
    pre = timedelta(minutes=cfg.get("pre_minutes", 60))
    post = timedelta(minutes=cfg.get("post_minutes", 30))
    out = []
    for e in cfg.get("events", []):
        ts = _parse(e.get("ts"))
        if not ts:
            continue
        if ts - pre <= now <= ts + post:
            out.append({"name": e.get("name", "?"), "ts": e.get("ts"),
                        "impact": e.get("impact", "high"),
                        "scope": e.get("scope", "all"),
                        "minutes_away": int((ts - now).total_seconds() // 60)})
    return out


def event_multiplier(now=None, cfg=None):
    """(multiplier, active_events). Worst active event governs -- three medium events at
    once are not reassuring, so the minimum is taken rather than a product or average."""
    cfg = cfg if cfg is not None else _read(EVENTS_FILE, {})
    if not cfg.get("enabled", True):
        return 1.0, []
    events = active_events(now, cfg)
    if not events:
        return 1.0, []
    mults = cfg.get("multipliers", {"high": 0.5, "medium": 0.75})
    m = min(float(mults.get(e["impact"], 0.75)) for e in events)
    return max(0.0, min(1.0, m)), events


# ---------------------------------------------------------------- news level (LLM output)
def read_news(now=None, ncfg=None):
    """The agent's last verdict, validated. Returns a dict that is ALWAYS safe to use:
    an unreadable, stale or malformed file yields level 0 with a stated reason."""
    ncfg = ncfg if ncfg is not None else settings.load_config().get("radar", {}).get("news", {})
    if not ncfg.get("enabled", True):
        return {"level": 0, "usable": False, "why": "news.enabled ist false"}

    raw = _read(settings.NEWS_RISK, None)
    if not isinstance(raw, dict):
        return {"level": 0, "usable": False, "why": "keine Einschaetzung vorhanden"}

    ts = _parse(raw.get("ts"))
    if not ts:
        return {"level": 0, "usable": False, "why": "kein Zeitstempel"}
    age = (_now(now) - ts).total_seconds() / 60.0
    max_age = ncfg.get("max_age_minutes", 90)
    if age > max_age:
        # A stale file must never keep throttling the bot forever -- if the agent stops
        # running, the system returns to normal instead of silently staying defensive.
        return {"level": 0, "usable": False, "age_minutes": round(age, 1),
                "why": f"veraltet ({round(age)} min > {max_age} min)"}

    level = raw.get("level")
    if not isinstance(level, int) or isinstance(level, bool) or not 0 <= level <= 3:
        return {"level": 0, "usable": False, "why": f"ungueltige Stufe {level!r}"}

    return {
        "level": level,
        "label": LEVELS.get(level, "?"),
        "usable": True,
        "age_minutes": round(age, 1),
        "summary": str(raw.get("summary", ""))[:400],
        "reasons": [str(r)[:200] for r in (raw.get("reasons") or [])][:6],
        "sources": [str(s)[:200] for s in (raw.get("sources") or [])][:8],
        "ts": raw.get("ts"),
    }


def news_multiplier(now=None, ncfg=None):
    """(multiplier, news). Level 0 or unusable -> 1.0, i.e. no effect at all."""
    ncfg = ncfg if ncfg is not None else settings.load_config().get("radar", {}).get("news", {})
    news = read_news(now, ncfg)
    if not news.get("usable") or not news["level"]:
        return 1.0, news
    mults = ncfg.get("multipliers", {"1": 0.8, "2": 0.55, "3": 0.3})
    m = float(mults.get(str(news["level"]), 1.0))
    return max(0.0, min(1.0, m)), news


# ---------------------------------------------------------------- combined
def assess(now=None):
    """Both external inputs folded into ONE multiplier. Minimum, not product: the worst
    single signal governs, matching how the tape radar escalates. Guaranteed <= 1.0."""
    cfg = settings.load_config().get("radar", {})
    ev_m, events = event_multiplier(now, _read(EVENTS_FILE, {}))
    nw_m, news = news_multiplier(now, cfg.get("news", {}))
    m = max(0.0, min(1.0, min(ev_m, nw_m)))
    reasons = []
    for e in events:
        when = "in %d min" % e["minutes_away"] if e["minutes_away"] > 0 else "laeuft"
        reasons.append(f"Termin: {e['name']} ({when})")
    if news.get("usable") and news["level"]:
        reasons.append(f"Nachrichten: {news['label']} (Stufe {news['level']})")
    return {"multiplier": round(m, 3), "event_multiplier": round(ev_m, 3),
            "news_multiplier": round(nw_m, 3), "events": events, "news": news,
            "reasons": reasons}


if __name__ == "__main__":
    base = datetime(2026, 7, 29, 18, 0, tzinfo=timezone.utc)
    cfg = {"enabled": True, "pre_minutes": 60, "post_minutes": 30,
           "multipliers": {"high": 0.5, "medium": 0.75},
           "events": [{"ts": base.isoformat(), "name": "FOMC", "impact": "high"}]}

    assert event_multiplier(base - timedelta(hours=3), cfg)[0] == 1.0, "weit davor: kein Effekt"
    assert event_multiplier(base - timedelta(minutes=30), cfg)[0] == 0.5, "im Vorfenster"
    assert event_multiplier(base + timedelta(minutes=20), cfg)[0] == 0.5, "im Nachfenster"
    assert event_multiplier(base + timedelta(hours=2), cfg)[0] == 1.0, "danach wieder normal"

    ncfg = {"enabled": True, "max_age_minutes": 90,
            "multipliers": {"1": 0.8, "2": 0.55, "3": 0.3}}
    now = datetime(2026, 7, 29, 12, 0, tzinfo=timezone.utc)
    import tempfile
    from pathlib import Path
    settings.NEWS_RISK = Path(tempfile.mkdtemp()) / "news_risk.json"

    assert news_multiplier(now, ncfg)[0] == 1.0, "keine Datei -> kein Effekt"
    settings.NEWS_RISK.write_text(json.dumps(
        {"ts": (now - timedelta(minutes=5)).isoformat(), "level": 3,
         "summary": "Zoelle angekuendigt"}), encoding="utf-8")
    m, n = news_multiplier(now, ncfg)
    assert m == 0.3 and n["usable"] and n["label"] == "krise", (m, n)
    # veraltet -> zurueck auf normal, statt ewig defensiv zu bleiben
    assert news_multiplier(now + timedelta(hours=4), ncfg)[0] == 1.0
    # boesartige Eingaben duerfen nie erhoehen
    for bad in ({"ts": now.isoformat(), "level": -5}, {"ts": now.isoformat(), "level": 99},
                {"ts": now.isoformat(), "level": "hoch"}, {"level": 3}, {"junk": True}):
        settings.NEWS_RISK.write_text(json.dumps(bad), encoding="utf-8")
        assert news_multiplier(now, ncfg)[0] == 1.0, bad
    print("external_risk self-check ok (Kalender + Nachrichten, nur senkend)")
