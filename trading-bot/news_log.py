"""Append-only news timeline, so the research loop can compare its OWN trade outcomes
against what the world looked like while each trade was open.

The live bot already lets news REDUCE position size (external_risk -> risk_radar). This
file is the audit trail of exactly that: one line per CHANGE in the external picture (news
level, or the set of active calendar events), written by the DETERMINISTIC trading loop --
never by an LLM. It is read only for attribution ("did the big losses cluster in stress
windows?"), never fed back as a trading signal. Same safety property as everywhere else in
this bot: news can explain a loss, it can never trigger a buy.

Why a step-function log and not one line per cycle: the external picture changes a handful
of times a day, not every 60 seconds. Recording only transitions keeps the file tiny and
still answers "which level was in force at 03:14" exactly."""
import json
from datetime import datetime, timezone

import settings


def _parse(iso):
    try:
        d = datetime.fromisoformat(str(iso).replace("Z", "+00:00"))
        return d if d.tzinfo else d.replace(tzinfo=timezone.utc)
    except Exception:
        return None


def _last():
    try:
        for line in reversed(settings.NEWS_HISTORY.read_text(encoding="utf-8").splitlines()):
            line = line.strip()
            if line:
                return json.loads(line)
    except Exception:
        pass
    return None


def _sig(ext):
    """(level, sorted_event_names) from an external_risk.assess() result. An unusable or
    absent news read collapses to level 0 -- silence is never an alarm."""
    news = (ext or {}).get("news") or {}
    level = int(news.get("level", 0) or 0) if news.get("usable") else 0
    events = sorted(e.get("name") for e in ((ext or {}).get("events") or []) if e.get("name"))
    return level, events


def append_if_changed(ext, now=None):
    """Record one snapshot only when the external picture differs from the last line.
    Returns the written entry, or None. NEVER raises: the trading loop must not die because
    a log append failed."""
    try:
        level, events = _sig(ext)
        prev = _last()
        if prev is not None and int(prev.get("level", 0)) == level \
                and sorted(prev.get("events") or []) == events:
            return None
        entry = {"ts": (now or datetime.now(timezone.utc)).isoformat(),
                 "level": level, "events": events,
                 "summary": str(((ext or {}).get("news") or {}).get("summary", ""))[:200]}
        with open(settings.NEWS_HISTORY, "a", encoding="utf-8") as f:
            f.write(json.dumps(entry) + "\n")
        return entry
    except Exception:
        return None


def load():
    """All snapshots, oldest first. [] when the file is absent or unreadable."""
    out = []
    try:
        for line in settings.NEWS_HISTORY.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if line:
                out.append(json.loads(line))
    except Exception:
        return []
    return out


def max_level_between(timeline, start, end):
    """Highest news level in force at any instant of [start, end]. The timeline is a step
    function: an entry's level holds until the next entry. Returns 0 when nothing is known
    for that window (e.g. the market-watch agent never ran)."""
    s, e = _parse(start), _parse(end)
    if not s:
        return 0
    if not e or e < s:
        e = s
    pts = sorted((t, l) for t, l in
                 ((_parse(x.get("ts")), int(x.get("level", 0) or 0)) for x in timeline) if t)
    cur = 0          # level already in force at the start of the window
    peak = 0         # highest level that begins inside the window
    for t, l in pts:
        if t <= s:
            cur = l
        elif t <= e:
            peak = max(peak, l)
        else:
            break
    return max(cur, peak)


if __name__ == "__main__":
    import tempfile
    from pathlib import Path
    settings.NEWS_HISTORY = Path(tempfile.mkdtemp()) / "news_history.jsonl"

    base = datetime(2026, 7, 28, 12, 0, tzinfo=timezone.utc)

    def ext(level, usable=True, events=()):
        return {"news": {"level": level, "usable": usable, "summary": f"L{level}"},
                "events": [{"name": n} for n in events]}

    assert append_if_changed(ext(0)) is not None            # first line always recorded
    assert append_if_changed(ext(0)) is None                # unchanged -> nothing
    # advance the clock and raise the level
    e2 = append_if_changed(ext(2), now=base)
    assert e2 and e2["level"] == 2
    e3 = append_if_changed(ext(0), now=base.replace(hour=13))
    assert e3 and e3["level"] == 0

    tl = load()
    assert len(tl) == 3, tl
    # a trade open across the stress spike sees level 2; one purely before/after sees 0
    assert max_level_between(tl, base.replace(hour=11, minute=59).isoformat(),
                             base.replace(hour=12, minute=30).isoformat()) == 2
    assert max_level_between(tl, base.replace(hour=13, minute=30).isoformat(),
                             base.replace(hour=14).isoformat()) == 0
    assert max_level_between([], base.isoformat(), base.isoformat()) == 0
    print("news_log self-check ok:", len(tl), "points")
