"""Verification for the external risk inputs (event calendar + LLM news level).

This is the only place where an LLM's output reaches anything that moves money, so the
properties below are the ones that make that safe:

  * the multiplier can NEVER exceed 1.0 -- not for any level, not for any file content,
    not for any combination. An injected news article can at worst push the bot flat,
    which costs opportunity, never capital, and can never make it BUY something.
  * a missing, stale or malformed verdict is ignored (factor 1.0), so a dead agent
    returns the bot to normal instead of leaving it permanently defensive.
  * combination is by MINIMUM, so the worst signal governs and nothing cancels out.

No hmmlearn needed. Run: pytest -q"""
import json
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import settings
import external_risk as ex

NOW = datetime(2026, 7, 29, 12, 0, tzinfo=timezone.utc)
NCFG = {"enabled": True, "max_age_minutes": 90,
        "multipliers": {"1": 0.8, "2": 0.55, "3": 0.3}}
ECFG = {"enabled": True, "pre_minutes": 60, "post_minutes": 30,
        "multipliers": {"high": 0.5, "medium": 0.75},
        "events": [{"ts": "2026-07-29T18:00:00Z", "name": "FOMC", "impact": "high"}]}
EVENT_TS = datetime(2026, 7, 29, 18, 0, tzinfo=timezone.utc)


@pytest.fixture(autouse=True)
def isolated(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "NEWS_RISK", tmp_path / "news_risk.json")
    return tmp_path


def write_news(**kw):
    settings.NEWS_RISK.write_text(json.dumps(kw), encoding="utf-8")


# ---------------------------------------------------------------- the core guarantee
@pytest.mark.parametrize("level", [0, 1, 2, 3])
def test_news_never_increases_exposure(level):
    write_news(ts=NOW.isoformat(), level=level, summary="x")
    m, _ = ex.news_multiplier(NOW, NCFG)
    assert 0.0 <= m <= 1.0


@pytest.mark.parametrize("payload", [
    {"ts": "2026-07-29T12:00:00Z", "level": 99},
    {"ts": "2026-07-29T12:00:00Z", "level": -3},
    {"ts": "2026-07-29T12:00:00Z", "level": "krise"},
    {"ts": "2026-07-29T12:00:00Z", "level": 2.5},
    {"ts": "2026-07-29T12:00:00Z", "level": True},
    {"ts": "kaputt", "level": 3},
    {"level": 3},
    {"junk": True},
    {},
])
def test_malformed_verdict_is_ignored(payload):
    """Garbage must never throttle and never crash -- it is simply not used."""
    write_news(**payload)
    m, news = ex.news_multiplier(NOW, NCFG)
    assert m == 1.0 and not news["usable"]


def test_missing_file_is_ignored():
    m, news = ex.news_multiplier(NOW, NCFG)
    assert m == 1.0 and not news["usable"]


def test_stale_verdict_returns_to_normal():
    """A dead agent must not leave the bot permanently small."""
    write_news(ts=NOW.isoformat(), level=3, summary="Krieg")
    assert ex.news_multiplier(NOW, NCFG)[0] == 0.3
    assert ex.news_multiplier(NOW + timedelta(minutes=91), NCFG)[0] == 1.0
    assert ex.news_multiplier(NOW + timedelta(days=3), NCFG)[0] == 1.0


def test_levels_map_monotonically():
    seen = []
    for lvl in (0, 1, 2, 3):
        write_news(ts=NOW.isoformat(), level=lvl)
        seen.append(ex.news_multiplier(NOW, NCFG)[0])
    assert seen == sorted(seen, reverse=True), seen
    assert seen[0] == 1.0


def test_disabled_news_has_no_effect():
    write_news(ts=NOW.isoformat(), level=3)
    assert ex.news_multiplier(NOW, dict(NCFG, enabled=False))[0] == 1.0


def test_agent_cannot_smuggle_extra_fields_into_effect():
    """Only `level` is read. Anything else the agent writes is display text at most."""
    write_news(ts=NOW.isoformat(), level=1, multiplier=5.0, exposure=2.0,
               symbols=["NVDA"], side="buy", override=True)
    m, news = ex.news_multiplier(NOW, NCFG)
    assert m == 0.8, "only the level may influence the factor"
    assert "symbols" not in news and "side" not in news


def test_long_text_is_truncated():
    write_news(ts=NOW.isoformat(), level=2, summary="x" * 5000,
               reasons=["y" * 5000] * 50, sources=["z" * 5000] * 50)
    news = ex.read_news(NOW, NCFG)
    assert len(news["summary"]) <= 400
    assert len(news["reasons"]) <= 6 and len(news["sources"]) <= 8


# ---------------------------------------------------------------- calendar
@pytest.mark.parametrize("delta,expected", [
    (timedelta(hours=-5), 1.0),          # long before
    (timedelta(minutes=-61), 1.0),       # just outside the pre-window
    (timedelta(minutes=-59), 0.5),       # inside the pre-window
    (timedelta(0), 0.5),                 # at the event
    (timedelta(minutes=29), 0.5),        # inside the post-window
    (timedelta(minutes=31), 1.0),        # past it
])
def test_event_window(delta, expected):
    assert ex.event_multiplier(EVENT_TS + delta, ECFG)[0] == expected


def test_worst_event_governs():
    cfg = dict(ECFG, events=[
        {"ts": EVENT_TS.isoformat(), "name": "CPI", "impact": "medium"},
        {"ts": EVENT_TS.isoformat(), "name": "FOMC", "impact": "high"},
    ])
    m, events = ex.event_multiplier(EVENT_TS, cfg)
    assert m == 0.5 and len(events) == 2, "the worst active event decides"


def test_empty_calendar_is_a_no_op():
    assert ex.event_multiplier(NOW, {"events": []})[0] == 1.0
    assert ex.event_multiplier(NOW, {})[0] == 1.0


def test_disabled_calendar_has_no_effect():
    assert ex.event_multiplier(EVENT_TS, dict(ECFG, enabled=False))[0] == 1.0


def test_shipped_calendar_is_empty_and_valid():
    """The file ships EMPTY on purpose: invented dates in a live system are worse than
    none. It must still parse and must not silently throttle anything."""
    cfg = json.loads(ex.EVENTS_FILE.read_text(encoding="utf-8"))
    assert cfg["events"] == [], "no fabricated dates may ship"
    assert ex.event_multiplier(NOW, cfg)[0] == 1.0


# ---------------------------------------------------------------- combined
def patch_calendar(monkeypatch, cfg):
    """Swap ONLY the calendar file. Everything else must still read normally --
    intercepting all of _read would silently disable the news path too."""
    real = ex._read
    monkeypatch.setattr(ex, "_read", lambda p, f: cfg if p == ex.EVENTS_FILE else real(p, f))


def test_combined_takes_the_minimum(monkeypatch):
    patch_calendar(monkeypatch, ECFG)
    monkeypatch.setattr(settings, "load_config",
                        lambda: {"radar": {"news": NCFG}})
    write_news(ts=EVENT_TS.isoformat(), level=1)        # 0.8
    out = ex.assess(EVENT_TS)                            # event 0.5 -> min 0.5
    assert out["multiplier"] == 0.5
    assert out["event_multiplier"] == 0.5 and out["news_multiplier"] == 0.8
    assert len(out["reasons"]) == 2


def test_combined_is_bounded(monkeypatch):
    """Even with absurd configured multipliers the result stays in [0, 1]."""
    patch_calendar(monkeypatch, dict(ECFG, multipliers={"high": 99}))
    monkeypatch.setattr(settings, "load_config",
                        lambda: {"radar": {"news": dict(NCFG, multipliers={"1": 42})}})
    write_news(ts=EVENT_TS.isoformat(), level=1)
    assert 0.0 <= ex.assess(EVENT_TS)["multiplier"] <= 1.0


def test_quiet_world_changes_nothing(monkeypatch):
    patch_calendar(monkeypatch, {"events": []})
    monkeypatch.setattr(settings, "load_config", lambda: {"radar": {"news": NCFG}})
    out = ex.assess(NOW)
    assert out["multiplier"] == 1.0 and out["reasons"] == []
