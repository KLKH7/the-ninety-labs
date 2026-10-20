"""--replay runs the real workflow and code checks with recorded model answers, so it needs no Azure.

The answers here are written by the test from the match's own events, not recorded from a model.
"""

import asyncio
import json
import warnings
from pathlib import Path

import pytest

from ninety.agents import slice as slice_mod
from ninety.agents.factcheck import Claim, Verdict, check
from ninety.agents.slice import (
    Recording,
    ReplayMismatch,
    StaleRecording,
    Turn,
    analyst_prompt,
    judge_prompt,
    replay_slice,
    tamper,
)
from ninety.match.facts import events_in

SEED, MINUTES = 7, 5
KNOWN = {e["id"]: e for e in events_in(SEED, MINUTES, 1, int(MINUTES) + 1)}
# A completed pass, so "finds" is true of it (lesson 23); the first pass of the minute may have failed.
# The minute is the first from the second on that has one, not a fixed minute: which minute has one
# is the seed's draw, and changes with the engine (lesson 47).
PASS = next(e for e in sorted(KNOWN.values(), key=lambda e: (e["minute"], e["second"]))
            if e["minute"] >= 2 and e["type"] == "pass"
            and e.get("outcome") == "success" and "receiver" in e and "distance_m" in e)
MINUTE = PASS["minute"]
CLAIM = Claim(f"{PASS['player']} finds {PASS['receiver']} with a {PASS['distance_m']} m pass.", [PASS["id"]])
REPLY = json.dumps({"text": CLAIM.text, "evidence": CLAIM.evidence})
FIRST = analyst_prompt("seed7", MINUTE)
WRITE = Turn("analyst", FIRST, REPLY)
SUPPORTED = Turn("judge", judge_prompt(CLAIM), json.dumps({"ok": True, "reasons": []}))


def recording(turns: list[Turn], plant: bool) -> Recording:
    stamp = "2026-10-13T00:00:00+00:00"
    return Recording(MINUTE, SEED, MINUTES, plant, "test", stamp, turns, list(KNOWN.values()))


def test_replay_accepts_a_true_claim():
    outcome = asyncio.run(replay_slice(recording([WRITE, SUPPORTED], plant=False)))
    assert outcome.accepted and outcome.attempts == 1
    assert "(replayed)" in outcome.trace[0] and outcome.trace[1] == "judge: supported (replayed)"


def test_replay_keeps_the_judges_rejection():
    reason = "unsupported fact: 'finds' (test)"
    held = Turn("judge", judge_prompt(CLAIM), json.dumps({"ok": False, "reasons": [reason]}))
    retry = FIRST + " Your previous claim was rejected: " + reason + ". Fix it."
    turns = [WRITE, held, Turn("analyst", retry, REPLY), SUPPORTED]
    outcome = asyncio.run(replay_slice(recording(turns, plant=False)))
    assert outcome.accepted and outcome.attempts == 2
    assert "judge: not supported (replayed)" in outcome.trace


def test_replay_runs_the_planted_rejection_and_rewrite():
    reasons = check(tamper(CLAIM), KNOWN).reasons
    assert reasons, "the planted number must be caught"
    retry = FIRST + " Your previous claim was rejected: " + "; ".join(reasons) + ". Fix it."
    turns = [WRITE, Turn("analyst", retry, REPLY), SUPPORTED]
    outcome = asyncio.run(replay_slice(recording(turns, plant=True)))
    assert outcome.accepted and outcome.attempts == 2
    assert any(line.startswith("fact_checker: rejected") for line in outcome.trace)


def test_replay_stops_when_the_prompt_no_longer_matches():
    with pytest.raises(ReplayMismatch):
        asyncio.run(
            replay_slice(recording([Turn("analyst", analyst_prompt("seed7", 9), REPLY)], plant=False))
        )


def test_replay_stops_when_replies_run_out():
    # Planted, so the fact-checker asks for a rewrite the recording does not have.
    with pytest.raises(ReplayMismatch):
        asyncio.run(replay_slice(recording([WRITE], plant=True)))


def test_recording_round_trips(tmp_path):
    original = recording([WRITE, SUPPORTED], plant=False)
    path = tmp_path / "slice.json"
    original.save(path)
    assert Recording.load(path) == original


def test_unknown_format_is_refused(tmp_path):
    path = tmp_path / "slice.json"
    path.write_text(json.dumps({"format": 99}))
    with pytest.raises(ValueError):
        Recording.load(path)


def test_a_format_2_recording_is_refused_with_how_to_fix_it(tmp_path):
    # Format 2 carried no events, so it can only be replayed against today's engine: refuse it.
    path = tmp_path / "slice.json"
    old = {k: v for k, v in vars(recording([WRITE, SUPPORTED], plant=False)).items() if k != "events"}
    path.write_text(json.dumps({"format": 2, **old, "turns": [vars(t) for t in old["turns"]]}))
    with pytest.raises(ValueError, match="format 2 .*no match events.*--record"):
        Recording.load(path)


def test_a_replay_on_the_engine_it_was_recorded_on_does_not_warn():
    with warnings.catch_warnings():
        warnings.simplefilter("error", StaleRecording)
        asyncio.run(replay_slice(recording([WRITE, SUPPORTED], plant=False)))


REPLAYS = sorted((Path(__file__).resolve().parent.parent / "replays").glob("*.json"))


def test_there_are_committed_replays():
    assert REPLAYS, "replays/ holds no recordings, so the test below checks nothing"


@pytest.mark.parametrize("path", REPLAYS, ids=lambda p: p.name)
def test_every_committed_replay_still_replays(path):
    # A recording no test replays rots silently when a prompt changes (lessons 32 and 44).
    outcome = asyncio.run(replay_slice(Recording.load(path)))
    assert outcome.attempts >= 1


PLANT = REPLAYS[0].parent / "slice-minute2-plant.json"
ENGINE = slice_mod.events_in


def engine_changed(seed, minutes, first, last):
    """A planted engine change: different speeds and distances, ids renumbered, one event fewer."""
    events = ENGINE(seed, minutes, first, last)[1:]
    return [{**e, "id": "x" + e["id"], **{k: e[k] + 1 for k in ("ball_speed_kmh", "distance_m") if k in e}}
            for e in events]


def test_the_committed_replay_survives_an_engine_change(monkeypatch):
    # Lesson 80: a replay pins the agents' interface, not the engine underneath.
    before = asyncio.run(replay_slice(Recording.load(PLANT)))
    monkeypatch.setattr(slice_mod, "events_in", engine_changed)
    with pytest.warns(StaleRecording, match="Record it again"):
        after = asyncio.run(replay_slice(Recording.load(PLANT)))
    assert after == before and any(line.startswith("fact_checker: rejected") for line in after.trace)


def speeds_only(seed, minutes, first, last):
    """Same ids, same count; only the measured numbers move, the most likely engine drift."""
    return [{**e, **{k: e[k] + 1 for k in ("ball_speed_kmh", "distance_m") if k in e}}
            for e in ENGINE(seed, minutes, first, last)]


def test_a_drift_in_numbers_alone_warns(monkeypatch):
    monkeypatch.setattr(slice_mod, "events_in", speeds_only)
    with pytest.warns(StaleRecording):
        asyncio.run(replay_slice(Recording.load(PLANT)))


def test_a_changed_analyst_prompt_still_fails_the_committed_replay(monkeypatch):
    # Lesson 44 still holds: a prompt the models never answered is not paired with an old answer.
    monkeypatch.setattr(slice_mod, "analyst_prompt", lambda *a: analyst_prompt(*a) + " Be brief.")
    with pytest.raises(ReplayMismatch):
        asyncio.run(replay_slice(Recording.load(PLANT)))


def test_a_changed_fact_check_message_still_fails_the_committed_replay(monkeypatch):
    def reworded(claim, known):
        v = check(claim, known)
        return Verdict(v.ok, [r.replace(" not ", " never ") for r in v.reasons], v.category)

    monkeypatch.setattr(slice_mod, "check", reworded)
    with pytest.raises(ReplayMismatch):
        asyncio.run(replay_slice(Recording.load(PLANT)))
