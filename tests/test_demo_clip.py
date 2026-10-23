"""The demo clip rule (docs/eval/demo-clip.md): the first qualifying window, from the events only."""

import importlib.util
from pathlib import Path

spec = importlib.util.spec_from_file_location(
    "demo_clip", Path(__file__).resolve().parents[1] / "scripts/demo_clip.py")
demo = importlib.util.module_from_spec(spec)
spec.loader.exec_module(demo)


def ev(t, kind):
    return {"t": t, "type": kind}


PASSES = [ev(t, "pass") for t in (102, 108, 115)]


def test_the_first_window_with_a_goal_a_set_piece_and_passes():
    events = [ev(100, "set_piece"), *PASSES, ev(130, "goal")]
    # Every window from 70 s to 100 s holds them all with the goal 15 s or more in; 70 is first.
    assert demo.first_window(events) == 70.0


def test_a_goal_too_early_in_the_window_or_a_kickoff_alone_does_not_qualify():
    assert demo.first_window([ev(100, "kickoff"), *PASSES, ev(130, "goal")]) is None
    # A goal 10 s after kick-off is never 15 s into a window that starts at or after kick-off.
    early = [ev(2, "set_piece"), ev(4, "pass"), ev(6, "pass"), ev(8, "pass"), ev(10, "goal")]
    assert demo.first_window(early) is None
    assert demo.first_window([*early[:-1], ev(16, "goal")]) == 0.0


def test_two_passes_is_not_enough():
    two = [ev(100, "set_piece"), ev(102, "pass"), ev(108, "pass"), ev(130, "goal")]
    assert demo.first_window(two) is None
    assert demo.first_window([ev(100, "set_piece"), *PASSES[:1], ev(130, "goal")]) is None


def test_the_range_starts_after_the_watched_demo_seed_and_the_doc_gives_the_same_command():
    assert 8001 < demo.FIRST_SEED <= demo.LAST_SEED < 9000
    doc = (Path(__file__).resolve().parents[1] / "docs/eval/demo-clip.md").read_text()
    assert f"Seeds {demo.FIRST_SEED} to {demo.LAST_SEED}" in doc
    cmd = demo.render_command(8002, 70)
    assert "stadium=broadcast" in cmd
    assert demo.RENDER_FLAGS in doc  # the doc's command and the script's flags cannot drift apart
