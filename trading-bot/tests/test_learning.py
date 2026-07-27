"""Verification for the self-improvement loop. The properties tested here are the ones
that stand between "the agent learns" and "the agent quietly breaks the bot":

  * the allowlist holds against hostile input (this is the important one)
  * safety limits, order caps and the watchlist can NEVER be changed by the agent
  * config.json is never written -- promotions land in git-ignored config.local.json
  * a promotion is fully reversible to the exact previous values
  * memory keeps rejections and expires accepted lessons
  * the gate rejects candidates that don't clear champion, buy & hold or drawdown

Free of hmmlearn on purpose, so it runs everywhere. Run: pytest -q"""
import json
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import settings
import memory
import promote


@pytest.fixture(autouse=True)
def isolated(tmp_path, monkeypatch):
    """Never touch the real state dir or the real config.local.json."""
    monkeypatch.setattr(settings, "CONFIG_LOCAL", tmp_path / "config.local.json")
    monkeypatch.setattr(settings, "CONFIG_HISTORY", tmp_path / "config_history.jsonl")
    monkeypatch.setattr(settings, "MEMORY", tmp_path / "memory.jsonl")
    monkeypatch.setattr(settings, "STATE_DIR", tmp_path)
    settings._FILE_CACHE.clear()
    yield tmp_path
    settings._FILE_CACHE.clear()


# ---------------------------------------------------------------- allowlist
HOSTILE = [
    {"risk.kill_from_peak_pct": 0.95},              # widen its own kill switch
    {"risk.day_flat_pct": 0.5},
    {"execution.trading_enabled": False},
    {"execution.max_notional_per_trade": 1_000_000},
    {"execution.max_margin": 500_000},
    {"allocation.leverage": 10},
    {"watchlist": ["DOGE/USD"]},
    {"starting_equity": 1},
    {"learning.bounds": {}},                        # rewrite its own sandbox
    {"learning.locked_prefixes": []},
    {"backtest.slippage_bps": 0},                   # flatter its own backtest
    {"totally.made.up": 1},
    {"allocation.min_change_threshold": 0.99},      # in the allowlist, out of range
    {"allocation.min_change_threshold": -1},
    {"hmm.live_timeframe": "1Min"},                 # not an allowed choice
    {"execution.cycle_seconds": 5},
]


@pytest.mark.parametrize("changes", HOSTILE)
def test_hostile_changes_are_refused(changes):
    with pytest.raises(promote.Rejected):
        promote.apply(changes, dry_run=True)
    clean, problems = promote.validate(changes)
    assert problems and not clean


def test_partial_hostile_batch_is_refused_entirely():
    """A valid change smuggled in next to a forbidden one must not slip through."""
    with pytest.raises(promote.Rejected):
        promote.apply({"allocation.min_change_threshold": 0.03,
                       "risk.kill_from_peak_pct": 0.9}, dry_run=True)


def test_allowed_change_passes():
    rec = promote.apply({"allocation.min_change_threshold": 0.03}, dry_run=True)
    assert rec["changes"] == {"allocation.min_change_threshold": 0.03}
    assert rec["before"]["allocation.min_change_threshold"] is not None


def test_int_parameters_stay_int():
    rec = promote.apply({"execution.cycle_seconds": 120.0}, dry_run=True)
    v = rec["changes"]["execution.cycle_seconds"]
    assert v == 120 and isinstance(v, int) and not isinstance(v, bool)


# ---------------------------------------------------------------- promotion mechanics
def test_promotion_writes_local_not_baseline(isolated):
    baseline_before = settings.CONFIG_FILE.read_text(encoding="utf-8")
    promote.apply({"allocation.min_change_threshold": 0.03}, reason="test")
    assert settings.CONFIG_LOCAL.exists(), "promotion must create config.local.json"
    assert settings.CONFIG_FILE.read_text(encoding="utf-8") == baseline_before, \
        "config.json is owned by git pull and must never be written"
    assert settings.load_config()["allocation"]["min_change_threshold"] == 0.03
    assert settings.load_baseline()["allocation"]["min_change_threshold"] != 0.03


def test_revert_all_restores_baseline():
    base = settings.load_baseline()["allocation"]["min_change_threshold"]
    promote.apply({"allocation.min_change_threshold": 0.03})
    assert settings.load_config()["allocation"]["min_change_threshold"] == 0.03
    assert promote.revert_all() is True
    assert settings.load_config()["allocation"]["min_change_threshold"] == base


def test_revert_last_restores_exact_previous_value():
    base = settings.load_baseline()["allocation"]["min_change_threshold"]
    promote.apply({"allocation.min_change_threshold": 0.03})
    promote.apply({"allocation.min_change_threshold": 0.06})
    assert settings.load_config()["allocation"]["min_change_threshold"] == 0.06
    promote.revert_last()
    assert settings.load_config()["allocation"]["min_change_threshold"] == 0.03
    promote.revert_last()
    assert settings.load_config()["allocation"]["min_change_threshold"] == base


def test_back_to_back_writes_are_visible_immediately():
    """Regression: the config parse cache was keyed on mtime alone. Filesystems quantise
    timestamps, so two writes inside the same tick shared a key and the second one stayed
    invisible -- which made promote.apply() record the WRONG previous value and corrupted
    the rollback. Reproduced on Linux, hidden on Windows by finer timestamps."""
    for i, value in enumerate((0.03, 0.04, 0.05, 0.06), start=1):
        promote.apply({"allocation.min_change_threshold": value})
        assert settings.load_config()["allocation"]["min_change_threshold"] == value,             f"write #{i} was not visible immediately"
        assert promote.history()[0]["changes"]["allocation.min_change_threshold"] == value


def test_survives_a_filesystem_with_frozen_timestamps(monkeypatch):
    """Proves the FIX, not the platform. On Windows this scenario cannot occur (fine
    timestamps) so the test above would pass even with the bug. Here every stat() reports
    the same mtime and size -- the exact behaviour of a coarse-granularity filesystem --
    so only the explicit cache invalidation can keep the reads correct."""
    import os
    real_stat = Path.stat

    class Frozen:
        st_mtime_ns = 1_000_000_000
        st_size = 4242

    def fake_stat(self, *a, **kw):
        if self in (settings.CONFIG_LOCAL, settings.CONFIG_FILE):
            return Frozen()
        return real_stat(self, *a, **kw)

    monkeypatch.setattr(Path, "stat", fake_stat)
    for value in (0.03, 0.05, 0.07):
        promote.apply({"allocation.min_change_threshold": value})
        got = settings.load_config()["allocation"]["min_change_threshold"]
        assert got == value, f"stale read under frozen timestamps: {got} != {value}"


def test_promotion_records_the_true_previous_value():
    promote.apply({"allocation.min_change_threshold": 0.03})
    promote.apply({"allocation.min_change_threshold": 0.06})
    assert promote.history()[0]["before"]["allocation.min_change_threshold"] == 0.03,         "a stale read here would make revert restore the wrong value"


def test_active_overrides_diffs_against_baseline():
    promote.apply({"execution.cycle_seconds": 180})
    act = promote.active_overrides()
    assert act["execution.cycle_seconds"]["now"] == 180
    assert act["execution.cycle_seconds"]["baseline"] != 180


def test_history_records_previous_value():
    promote.apply({"allocation.min_change_threshold": 0.03}, reason="warum")
    h = promote.history()
    assert h[0]["reason"] == "warum"
    assert "allocation.min_change_threshold" in h[0]["before"]


# ---------------------------------------------------------------- config overlay
def test_override_is_scoped_and_leaves_no_trace():
    before = settings.load_config()["allocation"]["min_change_threshold"]
    with settings.config_override({"allocation.min_change_threshold": 0.077}):
        assert settings.load_config()["allocation"]["min_change_threshold"] == 0.077
    assert settings.load_config()["allocation"]["min_change_threshold"] == before


def test_override_survives_exceptions():
    before = settings.load_config()["allocation"]["min_change_threshold"]
    with pytest.raises(ValueError):
        with settings.config_override({"allocation.min_change_threshold": 0.077}):
            raise ValueError("boom")
    assert settings.load_config()["allocation"]["min_change_threshold"] == before


def test_returned_config_is_not_shared_state():
    a = settings.load_config()
    a["allocation"]["min_change_threshold"] = 0.999
    assert settings.load_config()["allocation"]["min_change_threshold"] != 0.999


# ---------------------------------------------------------------- memory
def test_memory_keeps_rejections_and_prevents_repeats():
    changes = {"allocation.min_change_threshold": 0.015}
    memory.record("enger", "weil", changes, memory.REJECTED,
                  {"objective": 0.8, "champion_objective": 1.1})
    assert memory.already_tested(changes) is not None
    assert memory.already_tested({"hmm.stability_min_bars": 4}) is None
    assert memory.summary()["rejected"] == 1


def test_accepted_lessons_expire():
    memory.record("timeframe", "weil", {"hmm.live_timeframe": "15Min"}, memory.ACCEPTED,
                  {"objective": 1.4}, recheck_days=-1)
    due = memory.due_for_recheck()
    assert len(due) == 1 and due[0]["changes"] == {"hmm.live_timeframe": "15Min"}


def test_rejected_lessons_are_never_due_for_recheck():
    memory.record("x", "y", {"hmm.live_days": 30}, memory.REJECTED, {}, recheck_days=-1)
    assert memory.due_for_recheck() == []


def test_later_verdict_supersedes_earlier():
    ch = {"hmm.live_timeframe": "30Min"}
    memory.record("a", "b", ch, memory.ACCEPTED, {}, recheck_days=-1)
    memory.record("a", "b", ch, memory.REJECTED, {"reason": "hielt nicht"})
    assert memory.due_for_recheck() == [], "a superseded lesson must not resurface"


# ---------------------------------------------------------------- the gate
def _lcfg(**over):
    base = {"min_trades": 40, "min_symbols": 3, "min_improvement": 0.10,
            "drawdown_tolerance": 0.03, "max_candidates": 5}
    base.update(over)
    return base


def _cand(**over):
    base = {"ok": True, "objective": 2.0, "buy_hold_objective": 1.0,
            "max_drawdown": -0.10, "trades": 100, "symbols_scored": 4}
    base.update(over)
    return base


def test_gate_accepts_a_clear_winner():
    import optimizer_gate as g
    ok, _ = g.gate(_cand(), _cand(objective=1.0), _lcfg())
    assert ok


@pytest.mark.parametrize("cand,champ,why", [
    (_cand(objective=1.02), _cand(objective=1.0), "marginal beat must not count"),
    (_cand(trades=5), _cand(objective=1.0), "too few trades"),
    (_cand(symbols_scored=1), _cand(objective=1.0), "too few symbols"),
    (_cand(objective=0.9, buy_hold_objective=1.5), _cand(objective=0.1), "loses to buy & hold"),
    (_cand(max_drawdown=-0.40), _cand(objective=1.0, max_drawdown=-0.10), "deepens drawdown"),
    (_cand(ok=False, reason="kaputt"), _cand(objective=1.0), "unscoreable"),
])
def test_gate_rejects(cand, champ, why):
    import optimizer_gate as g
    ok, reason = g.gate(cand, champ, _lcfg())
    assert not ok, f"should have been rejected: {why}"
    assert reason
