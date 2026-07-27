"""The self-improvement loop, end to end.

    python research_cycle.py evidence   # 0 tokens. Builds the pack the agent reads.
    python research_cycle.py evaluate   # 0 tokens. Judges candidates, promotes a winner.
    python research_cycle.py evaluate --quick   # same pipeline, tiny scope: verify it
                                        # works end to end before spending hours on it.
    python research_cycle.py grid       # 0 tokens. Candidate fallback without an LLM.
    python research_cycle.py status     # what is currently promoted, and why.

The LLM sits BETWEEN evidence and evaluate: it reads state/evidence.json and writes
state/candidates.json. It never touches config, never touches the broker, never runs in
the trading loop. Its entire influence is a list of hypotheses that then have to survive
walk-forward, a holdout it has never seen, and the allowlist in promote.py.

Which means: if the agent has a bad week, the worst case is that nothing gets promoted."""
import json
import sys
from datetime import datetime, timezone

import settings
import memory
import promote

# optimizer (and with it hmmlearn/pandas) is imported lazily inside evaluate():
# evidence/grid/status are pure bookkeeping and must stay runnable without the
# numeric stack -- e.g. in the HQ agent context, which only reads and writes JSON.


def _read(path, fallback):
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return fallback


def _lcfg():
    return settings.load_config().get("learning", {})


def load_backlog():
    """Curated START queue of UNTESTED hypotheses. Not knowledge -- a work list, so the
    first runs work through vetted ideas instead of guessing blind. Every entry still
    has to survive walk-forward and holdout like any other candidate."""
    try:
        data = json.loads((settings.BASE / "research_backlog.json").read_text(encoding="utf-8"))
    except Exception:
        return []
    out = []
    for e in sorted(data.get("backlog", []), key=lambda x: x.get("priority", 99)):
        if memory.already_tested(e.get("changes") or {}):
            continue                       # done once, never queued again
        out.append(e)
    return out


# ---------------------------------------------------------------- evidence (0 tokens)
def build_evidence():
    """Everything the agent is allowed to reason over: its own measured results, what it
    already tried, and the exact sandbox it may move in. No market news, no opinions."""
    cfg = settings.load_config()
    lcfg = cfg.get("learning", {})
    dash = _read(settings.DASHBOARD_EXPORT, {})
    tunable = sorted(lcfg.get("bounds", {}))

    pack = {
        "generated": datetime.now(timezone.utc).isoformat(),
        "instructions": (
            "Schlage 1-5 Parameteraenderungen vor, die die risikoadjustierte Rendite "
            "verbessern koennten. Nur Schluessel aus 'tunable_parameters'. Jede Hypothese "
            "muss auf einer Beobachtung in 'live_performance' oder 'memory' beruhen. "
            "Aendere pro Kandidat moeglichst wenige Parameter - je mehr, desto "
            "wahrscheinlicher ist Ueberanpassung. Wiederhole nichts aus 'already_rejected'."
        ),
        "current_values": {k: settings.flat_get(cfg, k) for k in tunable},
        "tunable_parameters": {k: lcfg["bounds"][k] for k in tunable},
        "locked_parameters": lcfg.get("locked_prefixes", []),
        "live_performance": {
            "trade_stats": dash.get("trade_stats"),
            "per_symbol": dash.get("per_symbol"),
            "account": {k: (dash.get("account") or {}).get(k)
                        for k in ("equity", "total_change_pct", "day_change_pct", "deployed")},
            "bot": dash.get("bot"),
        },
        "memory": memory.lessons(40),
        "backlog": load_backlog(),   # kuratierte, UNGEPRUEFTE Startideen mit Evidenzstufe
        "already_rejected": [e["changes"] for e in memory.load()
                             if e.get("verdict") == memory.REJECTED],
        "due_for_recheck": [{"hypothesis": e.get("hypothesis"), "changes": e.get("changes")}
                            for e in memory.due_for_recheck()],
        "memory_summary": memory.summary(),
        "last_run": _read(settings.LEARNING_REPORT, None),
    }
    settings.EVIDENCE.write_text(json.dumps(pack, indent=2), encoding="utf-8")
    return pack


# ---------------------------------------------------------------- grid (0 tokens)
def grid_candidates():
    """Deterministic fallback so the loop still improves without spending a token.
    One parameter at a time, one step up and down from the current value -- the least
    overfitting-prone search there is."""
    cfg = settings.load_config()
    bounds = _lcfg().get("bounds", {})
    out = []
    for key in ("allocation.min_change_threshold", "execution.rebalance_min_pct",
                "hmm.stability_min_bars", "hmm.live_timeframe"):
        spec = bounds.get(key)
        cur = settings.flat_get(cfg, key)
        if not spec or cur is None:
            continue
        if "choices" in spec:
            options = [c for c in spec["choices"] if c != cur][:1]
            for o in options:
                out.append({"hypothesis": f"{key} = {o}", "rationale": "Gitter-Fallback",
                            "changes": {key: o}})
            continue
        for factor in (0.6, 1.6):
            v = cur * factor
            v = max(spec.get("min", v), min(spec.get("max", v), v))
            v = int(round(v)) if isinstance(cur, int) else round(v, 4)
            if v != cur:
                out.append({"hypothesis": f"{key} = {v}", "rationale": "Gitter-Fallback",
                            "changes": {key: v}})
    return out


# ---------------------------------------------------------------- evaluate (0 tokens)
QUICK = {"eval_days": 20, "in_sample_bars": 600, "out_sample_bars": 200,
         "max_candidates": 2, "min_trades": 5, "min_symbols": 1}


def evaluate(candidates=None, auto_promote=True, quick=False):
    """quick=True shrinks the scope drastically (fewer days, shorter windows, 2
    candidates, one symbol). It proves the pipeline runs end to end in minutes instead
    of hours -- but its verdicts are NOT trustworthy and are never promoted, because a
    600-bar window over 20 days cannot support a real out-of-sample claim."""
    import optimizer                      # heavy (pandas + hmmlearn) -- only needed here
    lcfg = _lcfg()
    if quick:
        lcfg = dict(lcfg, **QUICK)
        lcfg["eval_symbols"] = (lcfg.get("eval_symbols") or ["SPY"])[:1]
        auto_promote = False              # a smoke run must never change the live config
        print("QUICK-Modus: verkleinerter Umfang, KEINE Promotion, kein Gedaechtnis-Eintrag")
    if not lcfg.get("enabled", False):
        return {"skipped": "learning.enabled ist false"}

    candidates = candidates if candidates is not None else _read(settings.CANDIDATES, [])
    if not candidates:
        # No LLM run: work through the curated backlog first, only then the blind grid.
        candidates = load_backlog()[: lcfg.get("max_candidates", 5)]
        print(f"keine Kandidaten -> {len(candidates)} aus dem Backlog"
              if candidates else "keine Kandidaten -> Gitter-Fallback")
        if not candidates:
            candidates = grid_candidates()

    usable, skipped = [], []
    for c in candidates:
        changes = c.get("changes") or {}
        clean, problems = promote.validate(changes)
        if problems:
            skipped.append({**c, "reason": "; ".join(problems)})
            if not quick:
                memory.record(c.get("hypothesis", "?"), c.get("rationale", ""), changes,
                              memory.REJECTED, {"reason": "abgewiesen: " + "; ".join(problems)})
            continue
        seen = memory.already_tested(clean)
        if seen:
            skipped.append({**c, "reason": f"schon getestet ({seen['id']}: {seen['verdict']})"})
            continue
        usable.append({**c, "changes": clean})

    print(f"{len(usable)} Kandidaten zu testen, {len(skipped)} uebersprungen")
    if not usable:
        return _finish({"champion": None, "candidates": [], "winner": None, "holdout": None},
                       skipped, None)

    symbols = lcfg.get("eval_symbols") or settings.load_config()["watchlist"][:4]
    print(f"bewerte auf {symbols} · {lcfg['eval_days']} Tage · "
          f"Holdout {int(lcfg['holdout_frac'] * 100)}% ...")
    results = optimizer.run(usable, lcfg, symbols)

    promoted = None
    for ev in results["candidates"]:
        if ev is results.get("winner") or quick:
            continue
        memory.record(ev.get("hypothesis", "?"), ev.get("rationale", ""), ev["changes"],
                      memory.REJECTED, _evidence_of(ev, results["champion"]))

    win, hold = results.get("winner"), results.get("holdout")
    if quick:
        print(f"QUICK fertig · Champion {(results.get('champion') or {}).get('objective')} · "
              f"Gewinner {(win or {}).get('objective')} · Holdout "
              f"{(hold or {}).get('passes')} — nichts gespeichert, nichts uebernommen")
        return {"quick": True, "champion": (results.get("champion") or {}).get("objective"),
                "candidates": [{k: c.get(k) for k in ("hypothesis", "objective", "reason")}
                               for c in results["candidates"]],
                "holdout": (hold or {}).get("passes")}
    if win and hold:
        ev = _evidence_of(win, results["champion"])
        ev["holdout_objective"] = (hold["candidate"] or {}).get("objective")
        ev["holdout_champion"] = (hold["champion"] or {}).get("objective")
        ev["reason"] = hold["reason"]
        if hold["passes"]:
            entry = memory.record(win.get("hypothesis", "?"), win.get("rationale", ""),
                                  win["changes"], memory.ACCEPTED, ev,
                                  recheck_days=lcfg.get("recheck_days", 90))
            if auto_promote:
                promoted = promote.apply(win["changes"],
                                         reason=win.get("hypothesis", ""),
                                         memory_id=entry["id"])
                print("PROMOTED:", json.dumps(promoted["changes"]))
        else:
            memory.record(win.get("hypothesis", "?"), win.get("rationale", ""),
                          win["changes"], memory.REJECTED, ev)
            print("Gewinner faellt im Holdout durch ->", hold["reason"])

    return _finish(results, skipped, promoted)


def _evidence_of(ev, champ):
    return {
        "objective": ev.get("objective"),
        "champion_objective": (champ or {}).get("objective"),
        "buy_hold_objective": ev.get("buy_hold_objective"),
        "max_drawdown": ev.get("max_drawdown"),
        "trades": ev.get("trades"),
        "symbols_scored": ev.get("symbols_scored"),
        "reason": ev.get("reason"),
    }


def _finish(results, skipped, promoted):
    report = {
        "generated": datetime.now(timezone.utc).isoformat(),
        "champion_objective": (results.get("champion") or {}).get("objective"),
        "tested": len(results.get("candidates") or []),
        "skipped": skipped,
        "candidates": [{k: v for k, v in c.items() if k != "per_symbol"}
                       for c in (results.get("candidates") or [])],
        "holdout": {k: v for k, v in (results.get("holdout") or {}).items()
                    if k in ("passes", "reason")} if results.get("holdout") else None,
        "promoted": promoted,
        "active_overrides": promote.active_overrides(),
        "memory": memory.summary(),
    }
    settings.LEARNING_REPORT.write_text(json.dumps(report, indent=2), encoding="utf-8")
    memory.write_markdown()
    return report


def status():
    print(f"Gedaechtnis: {memory.summary()}")
    promote._print_status()
    due = memory.due_for_recheck()
    if due:
        print(f"{len(due)} Erkenntnis(se) zur Nachpruefung faellig:")
        for e in due:
            print("  -", e.get("hypothesis"))
    last = _read(settings.LEARNING_REPORT, None)
    if last:
        print(f"letzter Lauf: {last['generated']} · getestet {last['tested']} · "
              f"promotet: {bool(last.get('promoted'))}")


if __name__ == "__main__":
    cmd = sys.argv[1] if len(sys.argv) > 1 else "status"
    if cmd == "evidence":
        p = build_evidence()
        print(f"Evidenzpaket -> {settings.EVIDENCE} "
              f"({len(p['tunable_parameters'])} Parameter frei, "
              f"{len(p['memory'])} Erkenntnisse, {len(p['due_for_recheck'])} faellig)")
    elif cmd == "evaluate":
        quick = "--quick" in sys.argv
        r = evaluate(auto_promote="--dry-run" not in sys.argv and not quick, quick=quick)
        print(json.dumps({k: r.get(k) for k in ("champion_objective", "tested", "holdout",
                                                "promoted")}, indent=2, default=str))
    elif cmd == "grid":
        print(json.dumps(grid_candidates(), indent=2))
    else:
        status()
