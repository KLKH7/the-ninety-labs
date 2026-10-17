"""--replay runs the real workflow and code checks with recorded model answers, so it needs no Azure.

The answers here are written by the test from the match's own events, not recorded from a model.
"""

import asyncio
import json
from pathlib import Path

import pytest

from ninety.agents.factcheck import Claim, check
from ninety.agents.slice import (
    Recording,
    ReplayMismatch,
    Turn,
    analyst_prompt,
    judge_prompt,
    replay_slice,
    tamper,
)
from ninety.match.facts import events_in

SEED, MINUTES, MINUTE = 7, 5, 2
KNOWN = {e["id"]: e for e in events_in(SEED, MINUTES, 1, int(MINUTES) + 1)}
# A completed pass, so "finds" is true of it (lesson 23); the first pass of the minute may have failed.
PASS = next(e for e in KNOWN.values() if e["minute"] == MINUTE and e["type"] == "pass"
            and e.get("outcome") == "success" and "receiver" in e and "distance_m" in e)
CLAIM = Claim(f"{PASS['player']} finds {PASS['receiver']} with a {PASS['distance_m']} m pass.", [PASS["id"]])
REPLY = json.dumps({"text": CLAIM.text, "evidence": CLAIM.evidence})
FIRST = analyst_prompt("seed7", MINUTE)
WRITE = Turn("analyst", FIRST, REPLY)
SUPPORTED = Turn("judge", judge_prompt(CLAIM), json.dumps({"ok": True, "reasons": []}))


def recording(turns: list[Turn], plant: bool) -> Recording:
    return Recording(MINUTE, SEED, MINUTES, plant, "test", "2026-10-13T00:00:00+00:00", turns)


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


REPLAYS = sorted((Path(__file__).resolve().parent.parent / "replays").glob("*.json"))


def test_there_are_committed_replays():
    assert REPLAYS, "replays/ holds no recordings, so the test below checks nothing"


@pytest.mark.parametrize("path", REPLAYS, ids=lambda p: p.name)
def test_every_committed_replay_still_replays(path):
    # A recording no test replays rots silently when a prompt changes (lessons 32 and 44).
    outcome = asyncio.run(replay_slice(Recording.load(path)))
    assert outcome.attempts >= 1
