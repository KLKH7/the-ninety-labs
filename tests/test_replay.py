"""The replayer, moved out of slice.py and open to any role (ninety/agents/replay.py).

It stays strict (lessons 32 and 44): the next recorded answer must be for the same role and the
exact same prompt, in order. Never make it tolerant.
"""

import asyncio
import json
from pathlib import Path

import pytest

from ninety.agents import replay, slice
from ninety.agents.factcheck import Claim
from ninety.agents.replay import (
    WORKFLOW_REPLAY_FORMAT,
    Recording,
    Replayer,
    ReplayMismatch,
    Turn,
    WorkflowRecording,
    judge_prompt,
)

TURNS = [
    Turn("tactician", "why does m1 matter?", "because"),
    Turn("challenger", "challenge: because", '{"agree": true}'),
]


def ask(r: Replayer, role: str, prompt: str) -> str:
    return asyncio.run(r.ask(role)(prompt))


def test_answers_each_role_in_recorded_order():
    r = Replayer(TURNS)
    assert ask(r, "tactician", "why does m1 matter?") == "because"
    assert r.remaining == 1
    assert ask(r, "challenger", "challenge: because") == '{"agree": true}'
    assert r.remaining == 0


def test_refuses_a_changed_prompt():
    with pytest.raises(ReplayMismatch, match="changed since recording"):
        ask(Replayer(TURNS), "tactician", "why does m1 matter? ")


def test_refuses_another_roles_answer():
    with pytest.raises(ReplayMismatch):
        ask(Replayer(TURNS), "companion", "why does m1 matter?")


def test_refuses_a_call_out_of_order():
    # The second turn's exact call, asked first: a replayer that searched instead of taking the
    # next turn would answer it.
    with pytest.raises(ReplayMismatch):
        ask(Replayer(TURNS), "challenger", "challenge: because")


def test_refuses_a_call_after_the_recording_ran_out():
    r = Replayer(TURNS[:1])
    ask(r, "tactician", "why does m1 matter?")
    with pytest.raises(ReplayMismatch, match="no tactician answer"):
        ask(r, "tactician", "why does m1 matter?")


def test_a_judge_replay_is_keyed_by_the_claim():
    claim = Claim("a7 wins the ball.", ["e00046"])
    verdict = {"ok": False, "reasons": ["judge timeout; claim held back"], "category": "timeout"}
    turns = [Turn("judge", judge_prompt(claim), json.dumps(verdict))]
    got = asyncio.run(Replayer(turns).judge()(claim, []))
    assert (got.ok, got.category) == (False, "timeout")
    with pytest.raises(ReplayMismatch):
        asyncio.run(Replayer(turns).judge()(Claim("a7 wins the ball!", ["e00046"]), []))


def test_the_slice_imports_the_moved_names_back():
    for name in ("Turn", "Recording", "ReplayMismatch", "replayer", "judge_prompt", "REPLAY_FORMAT"):
        assert getattr(slice, name) is getattr(replay, name)
    assert replay.REPLAY_FORMAT == 2


def test_the_committed_slice_recording_round_trips_byte_for_byte(tmp_path):
    for path in sorted((Path(__file__).resolve().parent.parent / "replays").glob("*.json")):
        out = tmp_path / path.name
        Recording.load(path).save(out)
        assert out.read_bytes() == path.read_bytes(), path.name


def test_a_workflow_recording_keeps_its_commit_and_pins(tmp_path):
    original = WorkflowRecording(
        "moment", "51a8790", {"ninety-tactician": "1", "ninety-judge": "2"}, {"seed": 7, "minutes": 5},
        "2026-10-18T00:00:00+00:00", list(TURNS),
    )
    path = tmp_path / "w.json"
    original.save(path)
    assert json.loads(path.read_text())["format"] == WORKFLOW_REPLAY_FORMAT == 1
    assert WorkflowRecording.load(path) == original


def test_each_format_refuses_the_other(tmp_path):
    slice_file = sorted((Path(__file__).resolve().parent.parent / "replays").glob("*.json"))[0]
    with pytest.raises(ValueError, match="workflow recording"):
        WorkflowRecording.load(slice_file)
    path = tmp_path / "w.json"
    WorkflowRecording("moment", "abc", {}, {}, "t", []).save(path)
    with pytest.raises(ValueError, match="slice recording"):
        Recording.load(path)
