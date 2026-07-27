"""The agent's memory. Append-only ledger of every hypothesis it ever tested, each
stored WITH the numbers that decided it -- never with an opinion.

Three properties make this a memory rather than a diary:

1. Every entry is falsifiable: a hypothesis is a concrete parameter change, and the
   verdict carries the out-of-sample metrics that produced it.
2. Rejections are kept forever. Knowing what does NOT work is most of the value, and it
   stops the agent proposing the same dead end every week.
3. Accepted lessons EXPIRE. A market edge decays; a lesson that is never re-tested turns
   into dogma. Each accepted entry carries recheck_after, and due entries are handed
   back to the agent as "prove this still holds".
"""
import json
from datetime import datetime, timedelta, timezone

import settings

ACCEPTED = "accepted"
REJECTED = "rejected"
EXPIRED = "expired"


def _now():
    return datetime.now(timezone.utc)


def _iso(dt):
    return dt.isoformat()


def _parse(iso):
    try:
        return datetime.fromisoformat(str(iso).replace("Z", "+00:00"))
    except Exception:
        return None


def load():
    """All entries, oldest first."""
    if not settings.MEMORY.exists():
        return []
    out = []
    for line in settings.MEMORY.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            out.append(json.loads(line))
        except Exception:
            continue
    return out


def record(hypothesis, rationale, changes, verdict, evidence, source="agent",
           recheck_days=90):
    """Append one verdict. `changes` is the flat parameter dict that was tested,
    `evidence` the measured out-of-sample numbers that decided it."""
    now = _now()
    entry = {
        "id": f"{now.strftime('%Y-%m-%dT%H%M%S')}-{abs(hash(json.dumps(changes, sort_keys=True))) % 9973:04d}",
        "ts": _iso(now),
        "source": source,
        "hypothesis": hypothesis,
        "rationale": rationale,
        "changes": changes,
        "verdict": verdict,
        "evidence": evidence,
        "recheck_after": _iso(now + timedelta(days=recheck_days)) if verdict == ACCEPTED else None,
    }
    with open(settings.MEMORY, "a", encoding="utf-8") as f:
        f.write(json.dumps(entry) + "\n")
    return entry


def already_tested(changes, within_days=180):
    """Has this exact parameter set been judged recently? Stops the agent burning a
    slot every week re-proposing something the data already rejected."""
    key = json.dumps(changes, sort_keys=True)
    cutoff = _now() - timedelta(days=within_days)
    for e in reversed(load()):
        ts = _parse(e.get("ts"))
        if ts and ts < cutoff:
            break
        if json.dumps(e.get("changes") or {}, sort_keys=True) == key:
            return e
    return None


def due_for_recheck():
    """Accepted lessons whose recheck date has passed and that were not superseded."""
    latest = {}
    for e in load():                       # later entries win for the same change set
        latest[json.dumps(e.get("changes") or {}, sort_keys=True)] = e
    now = _now()
    out = []
    for e in latest.values():
        if e.get("verdict") != ACCEPTED or not e.get("recheck_after"):
            continue
        due = _parse(e["recheck_after"])
        if due and due <= now:
            out.append(e)
    return out


def lessons(limit=40):
    """Compact view for the LLM: what was tried, what happened, why."""
    out = []
    for e in load()[-limit:][::-1]:
        ev = e.get("evidence") or {}
        out.append({
            "id": e.get("id"), "ts": e.get("ts"), "verdict": e.get("verdict"),
            "hypothesis": e.get("hypothesis"), "changes": e.get("changes"),
            "objective": ev.get("objective"), "champion": ev.get("champion_objective"),
            "buy_hold": ev.get("buy_hold_objective"), "reason": ev.get("reason"),
        })
    return out


def summary():
    entries = load()
    acc = [e for e in entries if e.get("verdict") == ACCEPTED]
    rej = [e for e in entries if e.get("verdict") == REJECTED]
    return {
        "total": len(entries), "accepted": len(acc), "rejected": len(rej),
        "due_recheck": len(due_for_recheck()),
        "first": entries[0]["ts"] if entries else None,
        "last": entries[-1]["ts"] if entries else None,
    }


def write_markdown(path=None):
    """Human-readable index next to the ledger, so you can read the agent's history
    without parsing JSONL."""
    path = path or (settings.STATE_DIR / "MEMORY.md")
    s = summary()
    lines = ["# Trading-Bot — Forschungsgedächtnis", "",
             f"{s['total']} Hypothesen getestet · {s['accepted']} übernommen · "
             f"{s['rejected']} verworfen · {s['due_recheck']} zur Nachprüfung fällig", ""]
    for e in load()[::-1]:
        ev = e.get("evidence") or {}
        mark = {ACCEPTED: "✅", REJECTED: "❌", EXPIRED: "⌛"}.get(e.get("verdict"), "·")
        lines.append(f"## {mark} {e.get('hypothesis', '?')}")
        lines.append(f"*{e.get('ts', '')} · {e.get('verdict', '?')}*")
        lines.append("")
        lines.append(f"- Änderung: `{json.dumps(e.get('changes') or {})}`")
        if e.get("rationale"):
            lines.append(f"- Begründung: {e['rationale']}")
        if ev:
            lines.append(f"- Out-of-Sample: {ev.get('objective')} · Champion {ev.get('champion_objective')} "
                         f"· Buy&Hold {ev.get('buy_hold_objective')}")
            if ev.get("reason"):
                lines.append(f"- Urteil: {ev['reason']}")
        lines.append("")
    path.write_text("\n".join(lines), encoding="utf-8")
    return path


if __name__ == "__main__":
    import tempfile
    from pathlib import Path
    tmp = Path(tempfile.mkdtemp())
    settings.MEMORY = tmp / "memory.jsonl"
    settings.STATE_DIR = tmp

    record("Deadband enger", "mehr Rebalances moeglich", {"allocation.min_change_threshold": 0.015},
           REJECTED, {"objective": 0.9, "champion_objective": 1.2, "reason": "schlaegt Champion nicht"})
    record("Timeframe 15Min", "weniger Rauschen", {"hmm.live_timeframe": "15Min"},
           ACCEPTED, {"objective": 1.4, "champion_objective": 1.2, "buy_hold_objective": 1.0},
           recheck_days=-1)
    assert len(load()) == 2
    assert already_tested({"allocation.min_change_threshold": 0.015}) is not None
    assert already_tested({"hmm.stability_min_bars": 3}) is None
    due = due_for_recheck()
    assert len(due) == 1 and due[0]["changes"] == {"hmm.live_timeframe": "15Min"}, due
    s = summary()
    assert s == {**s, "total": 2, "accepted": 1, "rejected": 1, "due_recheck": 1}
    write_markdown()
    print("memory self-check ok:", s)
