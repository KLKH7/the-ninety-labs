import json

import pytest

from ninety.intel.stats import (
    calculate_facts,
    control_vs_chaos,
    pass_facts,
    player_movement_facts,
    possession_facts,
    pressure_facts,
    shot_facts,
)
from ninety.sim.engine import simulate


def _by_id(facts):
    return {fact.id: fact for fact in facts}


def _event(id_, type_, team, t=0.0, **kw):
    return {"id": id_, "type": type_, "team": team, "t": t, "x": 0.0, "y": 0.0, "player": None,
            "end_x": None, "end_y": None, "outcome": None, "ball_speed_kmh": None, **kw}


def _frame(i, possessor=None, h1=(0.0, 0.0)):
    return {"frame": i, "t": i / 25, "possessor": possessor,
            "players": [{"id": "h1", "team": "home", "x": h1[0], "y": h1[1]}]}


# Hand-computed cases: each value below was worked out by hand from the input.

def test_pass_facts_by_hand():
    events = [
        _event("e1", "pass", "home", player="h2", x=10, y=10, end_x=13, end_y=14, outcome="success",
               ball_speed_kmh=40),
        _event("e2", "pass", "home", player="h2", x=0, y=0, end_x=0, end_y=10, outcome="fail",
               ball_speed_kmh=60),
        _event("e3", "pass", "away", player="a5", x=0, y=0, end_x=6, end_y=8, outcome="success"),
    ]
    f = _by_id(pass_facts(events))
    assert f["passes_attempted:team_home"].value == 2
    assert f["passes_completed:team_home"].value == 1
    assert f["passes_completed:team_home"].source_ids == ("e1",)
    assert f["pass_completion_rate:team_home"].value == 0.5
    assert f["pass_distance_mean:team_home"].value == 7.5  # (5 + 10) / 2
    assert f["pass_speed_mean:team_home"].value == 50
    assert f["pass_distance_mean:player_a5"].value == 10
    assert "pass_speed_mean:team_away" not in f  # no speed recorded, so no fact


def test_shot_facts_by_hand():
    events = [
        _event("s1", "shot", "away", player="a9", outcome="goal", ball_speed_kmh=100),
        _event("s2", "shot", "away", player="a9", outcome="off_target", ball_speed_kmh=80),
        _event("s3", "shot", "away", player="a10", outcome="on_target", ball_speed_kmh=90),
    ]
    f = _by_id(shot_facts(events))
    assert f["shots:team_away"].value == 3
    assert f["shots_on_target:team_away"].source_ids == ("s1", "s3")
    assert f["shot_accuracy:team_away"].value == 0.67
    assert f["goals:team_away"].value == 1
    assert f["shot_speed_max:team_away"].value == 100
    assert f["shots:team_home"].value == 0 and f["shots:team_home"].source_ids == ()


def test_possession_by_hand_ignores_loose_ball_frames():
    frames = [_frame(0, "h3"), _frame(1, "h3"), _frame(2, None), _frame(3, "a7")]
    f = _by_id(possession_facts(frames))
    assert f["possession_share:team_home"].value == 0.67
    assert f["possession_share:team_away"].value == 0.33
    assert f["possession_frames:team_home"].value == 2
    assert f["possession_share:team_home"].source_ids == ("frames:0-3",)


def test_movement_by_hand_and_never_capped():
    # 0.4 m per frame is 10 m/s, 36 km/h; then a 2 m jump in one frame is 180 km/h. The jump
    # must show up: a cap would hide a teleport in the data.
    frames = [_frame(0, h1=(0, 0)), _frame(1, h1=(0.4, 0)), _frame(2, h1=(0.8, 0)), _frame(3, h1=(2.8, 0))]
    f = _by_id(player_movement_facts(frames))
    assert f["distance_run:player_h1"].value == 2.8
    assert f["peak_speed:player_h1"].value == 180
    assert f["sprint_frames:player_h1"].value == 3
    assert f["peak_speed:player_h1"].source_ids == ("frames:0-3",)


def test_a_kickoff_reset_is_not_movement():
    # Everyone is put back in his own half at a kickoff (a legal case of the data contract), here
    # 50 m in one frame. Counted, it was a 4,500 km/h "peak speed".
    frames = [_frame(0, h1=(0, 0)), _frame(1, h1=(0.4, 0)), _frame(2, h1=(50.4, 0)), _frame(3, h1=(50.8, 0))]
    f = _by_id(player_movement_facts(frames, restarts=[2]))
    assert f["distance_run:player_h1"].value == 0.8
    assert f["peak_speed:player_h1"].value == 36
    # Only the step into the kickoff frame is skipped: the same jump anywhere else still shows.
    assert _by_id(player_movement_facts(frames, restarts=[3]))["peak_speed:player_h1"].value == 4500


def test_no_player_outruns_the_contract_over_a_restart_after_a_goal():
    # The engine's own restart after a goal, called 20 s into a match, so the case is in the data
    # whatever a seed draws (lessons 41 and 78). Since #156 nobody is reset: everyone walks back to
    # his kick-off spot, and that walk is real movement, measured like any other. (Before the
    # kickoff skip, a reset like the old one read as a 4,739 km/h peak speed.)
    from ninety.sim.engine import FPS, Engine
    from ninety.validate import MAX_PLAYER_MPS

    engine = Engine(7)
    engine.kickoff("home", setup=True)
    for _ in range(20 * FPS):
        engine.step()
    engine.kickoff("away")  # as after a goal
    start = engine.frame
    for _ in range(90 * FPS):  # bounded: the kick is taken once everyone is back
        engine.step()
        if [e for e in engine.match.events if e["type"] == "kickoff" and e["frame"] > start]:
            break
    match = engine.match
    kicked = [e["frame"] for e in match.events if e["type"] == "kickoff" and e["frame"] > start]
    assert kicked, "the restart after the goal is the case this test is about"
    before, after = match.frames[start], next(f for f in match.frames if f["frame"] == kicked[0])
    walked = max(abs(p["x"] - q["x"]) for p, q in zip(before["players"], after["players"], strict=True))
    assert walked > 10, "someone must walk a real distance back to his spot"
    peaks = [f for f in calculate_facts(match.events, match.frames) if f.metric == "peak_speed"]
    assert len(peaks) == 22 and max(f.value for f in peaks) <= MAX_PLAYER_MPS * 3.6


def test_pressure_reports_zero_for_a_team_without_pressure():
    f = _by_id(pressure_facts([_event("p1", "pressure", "home")]))
    assert f["pressure_events:team_home"].value == 1
    assert f["pressure_events:team_away"].value == 0


def test_control_vs_chaos_by_hand():
    events = [
        _event("e1", "pass", "home", t=1, outcome="success"),
        _event("e2", "pass", "home", t=2, outcome="success"),
        _event("e3", "pass", "home", t=3, outcome="fail"),
        _event("e4", "pass", "home", t=4, outcome="success"),
        _event("e5", "pressure", "away", t=5),
        _event("e6", "tackle", "away", t=6, outcome="success"),
        _event("e7", "tackle", "away", t=7, outcome="fail"),  # recovers nothing
        _event("e8", "kickoff", "home", t=0),  # does not contribute
    ]
    f = _by_id(control_vs_chaos(events))
    home = f["control_vs_chaos:team_home_window_0"]
    assert home.value == 0.25  # control 3/4, chaos (1 pressure + 1 recovery) / 4
    assert set(home.source_ids) == {"e1", "e2", "e3", "e4", "e5", "e6"}


def test_control_vs_chaos_counts_a_failed_tackle_as_no_recovery():
    """Planted defect: if failed tackles counted as recoveries, chaos would rise to 1."""
    events = [_event("e1", "pass", "home", t=1, outcome="success"),
              _event("e2", "tackle", "away", t=2, outcome="fail")]
    assert _by_id(control_vs_chaos(events))["control_vs_chaos:team_home_window_0"].value == 1


def test_control_vs_chaos_rejects_invalid_window():
    with pytest.raises(ValueError, match="positive"):
        control_vs_chaos([], 0)


# On engine output: the contract holds, whatever the engine does.

def test_engine_match_facts_are_deterministic_cited_and_compact():
    match = simulate(7, 5)
    first = calculate_facts(match.events, match.frames)
    assert first == calculate_facts(match.events, match.frames)
    ids = [fact.id for fact in first]
    assert len(ids) == len(set(ids))
    events = {e["id"] for e in match.events}
    for fact in first:
        if fact.value > 0 and fact.metric not in {"control_vs_chaos"}:
            assert fact.source_ids, fact
        for sid in fact.source_ids:
            assert sid in events or sid.startswith("frames:"), (fact, sid)
    # a fact list an agent can read: well under a megabyte for five minutes
    assert len(json.dumps([fact.as_dict() for fact in first])) < 1_000_000
