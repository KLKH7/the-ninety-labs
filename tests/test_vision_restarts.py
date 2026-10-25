"""Restart detection from observations: set pieces, kick-offs and their kind (ninety.vision.restarts).

Every scene is built here, frame by frame, as observations, so each test's premise holds by
construction (lesson 47); constants come from the module under test (lesson 36). Each scene opens on
open play and, unless it says otherwise, the picture cuts (the frame numbers jump) to the restart.
"""

from __future__ import annotations

import json

from ninety.vision import events as ev
from ninety.vision import restarts as rs
from ninety.vision import track as tr

RED, BLUE = [200.0, 30.0, 40.0], [40.0, 60.0, 190.0]  # red defends x = 105 (away), blue is home
FPS = tr.FPS
AFTER = 600  # the first frame after the cut


def row(frame, players, ball=None, held_by=None, at_feet=False):
    """players: (x, y, rgb), boxes apart; ball: (x, y), drawn apart from every player, or with
    `held_by` (a player's index) at the top of that player's box, in his hands over his head (with
    `at_feet`, at the bottom of it instead)."""
    out = {"frame": frame, "t": round(frame / FPS, 2),
           "camera": {"ok": True, "median_px": 0.5, "points": 500, "P": None},
           "players": [{"bbox": [20 * i, 0, 20 * i + 10, 30], "score": 0.9, "x": x, "y": y, "rgb": c}
                       for i, (x, y, c) in enumerate(players)],
           "ball": []}
    if ball is not None:
        top = 21 if at_feet else 1
        box = [0, 500, 8, 508] if held_by is None else [20 * held_by + 1, top, 20 * held_by + 9, top + 8]
        out["ball"] = [{"bbox": box, "score": 0.8, "x": ball[0], "y": ball[1]}]
    return out


def crowd():
    """Four outfield players of each side standing still, red deeper toward x = 105."""
    return [(70 + 3 * k, 45.0, BLUE) for k in range(4)] + [(85 + 3 * k, 47.0, RED) for k in range(4)]


def open_play(frames=30):
    """A blue player at (30, 30) with the ball at his feet: no dead ball."""
    return [row(f, crowd() + [(30.0, 30.0, BLUE)], (30.3, 30.0)) for f in range(frames)]


def set_ball(spot, taker, colour=BLUE, at=AFTER, still=20, toward=(52.5, 34.0), speed=15.0, after=20,
             at_feet=False):
    """After the cut, the ball still at `spot` for `still` frames with a taker of `colour` at
    `taker`, then struck toward `toward` at `speed` m/s for `after` frames. With `at_feet` the ball
    is drawn at the bottom of the taker's box while it is set (from the gantry, over his boots)."""
    out = []
    dx, dy = toward[0] - spot[0], toward[1] - spot[1]
    n = (dx * dx + dy * dy) ** 0.5
    for k in range(still + after):
        s = max(0, k - still + 1) * speed / FPS
        ball = (spot[0] + dx / n * s, spot[1] + dy / n * s)
        feet = 8 if at_feet and k < still else None
        out.append(row(at + k, crowd() + [(taker[0], taker[1], colour)], ball, held_by=feet, at_feet=at_feet))
    return out


def run(rows):
    found, _ = ev.detect(rows)
    events, report = rs.detect(rows, found)
    return events, report["restarts"]


def kinds(rows):
    return [(r["kind"]) for r in run(rows)[1]]


def test_a_throw_in_is_the_ball_held_up_by_a_player_at_a_touchline_then_let_go():
    rows = open_play()
    for k in range(10):  # held over his head, behind the far touchline; on the ground it lands far off
        rows.append(row(AFTER + k, crowd() + [(40.0, 68.4, RED)], (40.0, 80.0), held_by=8))
    for k in range(1, 15):  # thrown in, toward a team-mate
        rows.append(row(AFTER + 9 + k, crowd() + [(40.0, 68.4, RED)], (40.0, 66.0 - 0.5 * k)))
    events, report = run(rows)
    assert [(e["type"], e["team"]) for e in events] == [("set_piece", "away")]
    assert [r["kind"] for r in report] == ["throw_in"]
    assert (events[0]["x"], events[0]["y"], events[0]["frame"]) == (40.0, 68.0, AFTER + 9)


def throw_near(held=10):
    """A throw-in from the near touchline, the thrower just inside it: from the gantry the ball over
    his head lands on the ground well inside the field, still while he holds it."""
    rows = open_play()
    feet, mate = (40.0, rs.LINE_TOL_M / 2), (40.6, 5.4, RED)  # a team-mate stands where it lands
    for k in range(held):
        rows.append(row(AFTER + k, crowd() + [(*feet, RED), mate], (40.0, 5.0), held_by=8))
    for k in range(1, 15):
        rows.append(row(AFTER + held - 1 + k, crowd() + [(*feet, RED), mate], (40.0, 6.0 + 0.5 * k)))
    return rows


def test_a_throw_in_from_the_near_touchline_is_on_the_line_and_not_a_set_ball_where_it_lands():
    events, report = run(throw_near(held=rs.STILL_FRAMES + 5))  # long enough to pass for a set ball
    assert [r["kind"] for r in report] == ["throw_in"]
    assert (events[0]["x"], events[0]["y"]) == (40.0, 0.0)


def test_a_ball_over_a_head_at_a_touchline_for_fewer_than_held_frames_is_no_throw_in():
    assert kinds(throw_near(held=rs.HELD_FRAMES - 1)) == []
    assert kinds(throw_near(held=rs.HELD_FRAMES)) == ["throw_in"]


def test_a_ball_held_at_a_touchline_until_the_picture_cuts_away_is_no_throw_in():
    """Out over the near touchline, a player holds it up there, the picture cuts away, and comes
    back on play elsewhere: nobody was seen throwing it."""
    rows = [row(f, crowd() + [(30.0, 8.0, BLUE)], (30.3, max(8.0 - 0.5 * max(0, f - 10), -2.0)))
            for f in range(30)]
    rows += [row(30 + k, crowd() + [(36.0, -0.3, RED)], (36.0, 5.0), held_by=8) for k in range(10)]
    rows += [row(AFTER + k, crowd() + [(50.0, 30.0, BLUE)], (50.3 + 0.6 * k, 30.0)) for k in range(20)]
    assert kinds(rows) == []


def test_a_ball_still_on_both_sides_of_a_cut_is_set_only_from_the_cut():
    """Still before the cut (open play: the clip's start admits only a kick-off) and still at the
    same place after it: the run after the cut has the cut for its cue."""
    rows = [row(f, crowd() + [(59.2, 20.4, BLUE)], (60.0, 20.0)) for f in range(15)]
    assert kinds(rows + set_ball((60.0, 20.0), (59.2, 20.4))) == ["free_kick"]


def test_a_ball_held_up_by_two_players_in_turn_is_one_players_throw_only_if_he_holds_it():
    """Two at the touchline, the ball over each one's head for fewer than HELD_FRAMES frames."""
    rows = open_play()
    first = rs.HELD_FRAMES - 1
    for k in range(2 * first):
        rows.append(row(AFTER + k, crowd() + [(40.0, 68.4, RED), (40.4, 68.4, RED)], (40.0, 80.0),
                        held_by=8 if k < first else 9))
    for k in range(1, 15):
        rows.append(row(AFTER + 2 * first - 1 + k, crowd() + [(40.0, 68.4, RED), (40.4, 68.4, RED)],
                        (40.0, 66.0 - 0.5 * k)))
    assert kinds(rows) == []


def test_a_set_ball_nobody_is_seen_striking_is_no_restart():
    """Nobody within CONTROL_M of the ball when it moves off (the taker is not detected)."""
    far = (60.0 - ev.CONTROL_M - 1.0, 20.0)
    assert kinds(open_play() + set_ball((60.0, 20.0), far)) == []


def test_a_taker_of_neither_side_gives_no_event():
    """A third colour outside both boxes (the referee's) is no side's player."""
    yellow = [230.0, 220.0, 40.0]
    assert kinds(open_play() + set_ball((60.0, 20.0), (59.2, 20.4), colour=yellow)) == []


def test_a_set_ball_drawn_over_the_takers_boots_is_still_set():
    """From the gantry the set ball's box can lie inside the taker's, below his hips: not held."""
    assert kinds(open_play() + set_ball((104.5, 67.5), (104.0, 66.6), at_feet=True)) == ["corner"]


def test_a_ball_held_up_away_from_a_touchline_is_no_throw_in():
    """A keeper's catch in his area: held over his head, nowhere near a touchline."""
    rows = open_play()
    for k in range(10):
        rows.append(row(AFTER + k, crowd() + [(3.0, 34.0, BLUE)], (3.0, 40.0), held_by=8))
    for k in range(1, 15):
        rows.append(row(AFTER + 9 + k, crowd() + [(3.0, 34.0, BLUE)], (4.0 + 0.6 * k, 34.0)))
    assert kinds(rows) == []


def test_each_kind_is_read_from_where_the_ball_is_set():
    scenes = {
        "corner": ((104.5, 67.5), (104.0, 66.6)),
        "goal_kick": ((5.5, 34.0), (5.0, 34.6)),
        "penalty_kick": ((94.0, 34.0), (93.2, 34.4)),
        "free_kick": ((60.0, 20.0), (59.2, 20.4)),
    }
    for kind, (spot, taker) in scenes.items():
        rows = open_play() + set_ball(spot, taker)
        events, report = run(rows)
        assert [r["kind"] for r in report] == [kind], kind
        assert [(e["type"], e["team"]) for e in events] == [("set_piece", "home")], kind
        assert (events[0]["x"], events[0]["y"]) == spot, kind


def test_a_zone_holds_within_the_ball_tolerance_and_not_past_it():
    inside, outside = rs.BALL_TOL_M * 0.9, rs.BALL_TOL_M * 1.1
    assert rs.kind_of(52.5 + inside, 34.0)[0] == "kick_off"
    assert rs.kind_of(52.5 + outside, 34.0)[0] == "free_kick"
    assert rs.kind_of(11.0, 34.0 + inside)[0] == "penalty_kick"
    assert rs.kind_of(105.0 - 1.0 - inside, 68.0)[0] == "corner"
    assert rs.kind_of(105.0 - 1.0 - outside - 0.01, 68.0)[0] == "free_kick"
    assert rs.kind_of(5.5 + inside, 40.0)[0] == "goal_kick"
    assert rs.kind_of(5.5 + outside, 40.0)[0] == "free_kick"
    assert rs.kind_of(100.0, 34.0 + 9.16 + inside)[0] == "goal_kick"


def test_a_kick_off_at_the_clips_start_is_placed_at_its_taker():
    rows = set_ball((52.5, 34.0), (52.0, 34.4), at=0, toward=(40.0, 34.0))
    events, report = run(rows)
    assert [(e["type"], e["team"]) for e in events] == [("kickoff", "home")]
    assert [r["kind"] for r in report] == ["kick_off"]
    assert (events[0]["x"], events[0]["y"]) == (52.0, 34.4)


def test_the_clips_start_admits_a_kick_off_and_nothing_else():
    """A clip that opens on a still ball away from the centre spot may be open play."""
    assert kinds(set_ball((60.0, 20.0), (59.2, 20.4), at=0)) == []


def test_a_dead_ball_with_no_restart_seen_gives_none():
    """Out over a line, the cut, and the clip ends with the ball set but never struck."""
    rows = [row(f, crowd() + [(30.0, 60.0, BLUE)], (30.3, min(60.0 + 0.5 * max(0, f - 10), 70.0)))
            for f in range(30)]
    assert any(e["type"] == "out_of_play" for e in ev.detect(rows)[0])
    rows += [row(AFTER + k, crowd() + [(59.2, 20.4, BLUE)], (60.0, 20.0)) for k in range(40)]
    assert kinds(rows) == []


def test_an_out_of_play_is_a_cue_without_a_cut():
    """The ball over the touchline, then (no cut) set at a free kick's spot and struck."""
    rows = [row(f, crowd() + [(30.0, 60.0, BLUE)], (30.3, min(60.0 + 0.5 * max(0, f - 10), 70.0)))
            for f in range(30)]
    rows += set_ball((60.0, 20.0), (59.2, 20.4), at=30)
    assert kinds(rows) == ["free_kick"]
    assert kinds(open_play() + set_ball((60.0, 20.0), (59.2, 20.4), at=30)) == []


def test_a_set_ball_the_picture_cuts_away_from_is_not_seen_struck():
    """Still before the cut, already moving after it: nobody was seen striking it."""
    rows = open_play() + [row(AFTER + k, crowd() + [(59.2, 20.4, BLUE)], (60.0, 20.0)) for k in range(20)]
    rows += [row(AFTER + 500 + k, crowd() + [(40.0, 30.0, BLUE)], (45.0 + 0.6 * k, 30.0)) for k in range(20)]
    assert kinds(rows) == []


def test_the_kind_does_not_depend_on_how_long_the_cut_was():
    short = open_play() + set_ball((104.5, 67.5), (104.0, 66.6), at=40)
    long = open_play() + set_ball((104.5, 67.5), (104.0, 66.6), at=2000)
    assert kinds(short) == kinds(long) == ["corner"]


def test_a_set_ball_whose_place_jitters_within_its_error_is_still_set():
    """The ball's box rounds to the pixel, so a still ball's place moves by up to twice its error
    from frame to frame, and one point in ten may lie further (BALL_TOL_M is a 90th percentile)."""
    rows = open_play() + set_ball((52.5, 34.0), (52.0, 34.4), toward=(40.0, 34.0))
    for k, r in enumerate(r for r in rows if r["frame"] >= AFTER and r["frame"] < AFTER + 20):
        off = 0.9 * rs.BALL_TOL_M * (1 if k % 2 else -1)  # within its error of the spot, so twice it apart
        r["ball"][0]["y"] = 34.0 + (5 * rs.BALL_TOL_M if k in (7, 15) else off)  # two in twenty further
    assert kinds(rows) == ["kick_off"]


def test_a_ball_merely_slow_in_open_play_is_no_restart():
    """After a restart, a player stops the ball and stands over it, then passes: no new cue."""
    rows = open_play() + set_ball((60.0, 20.0), (59.2, 20.4), after=10)
    at = rows[-1]["frame"] + 1
    rows += set_ball((70.0, 30.0), (69.2, 30.4), at=at)  # the same frames go on: no cut
    assert kinds(rows) == ["free_kick"]


def test_a_ball_dribbled_at_a_jog_after_a_cue_is_not_set():
    """After the cut a player carries the ball at 3 m/s (under CARRY_MPS), then passes it."""
    rows = open_play()
    for k in range(30):
        x = 40.0 + 3.0 * k / FPS
        rows.append(row(AFTER + k, crowd() + [(x - 0.3, 30.0, BLUE)], (x, 30.0)))
    for k in range(1, 15):
        rows.append(row(AFTER + 29 + k, crowd() + [(43.3, 30.0, BLUE)], (43.6 + 0.6 * k, 30.0)))
    assert 3.0 < ev.CARRY_MPS and kinds(rows) == []


def test_a_set_ball_walked_off_its_spot_is_not_struck():
    """Set, then carried away at a walk (1.5 m/s, with him): nobody kicked it."""
    rows = open_play() + [row(AFTER + k, crowd() + [(59.2, 20.4, BLUE)], (60.0, 20.0)) for k in range(20)]
    for k in range(1, 25):
        x = 60.0 + 1.5 * k / FPS
        rows.append(row(AFTER + 19 + k, crowd() + [(x - 0.3, 20.4, BLUE)], (x, 20.0)))
    assert 1.5 < ev.CARRY_MPS and kinds(rows) == []


def test_under_a_looser_tolerance_a_ball_run_at_pace_is_still_not_set(monkeypatch):
    """The rule holds for whatever tolerance a camera's reading measures: with a live fit's metre or
    so, a ball run along at 5 m/s (over CARRY_MPS) stays within it over a few frames but is moving."""
    monkeypatch.setattr(rs, "BALL_TOL_M", 1.5)
    rows = open_play()
    for k in range(30):
        x = 40.0 + 5.0 * k / FPS
        rows.append(row(AFTER + k, crowd() + [(x - 0.3, 30.0, BLUE)], (x, 30.0)))
    for k in range(1, 15):
        rows.append(row(AFTER + 29 + k, crowd() + [(45.7, 30.0, BLUE)], (46.0 + 0.6 * k, 30.0)))
    assert 5.0 > ev.CARRY_MPS and kinds(rows) == []


def test_a_dead_ball_stopped_off_the_field_is_not_set():
    """Before the cut, the dead ball stopped 3 m past the touchline and knocked back."""
    off = -(rs.BALL_TOL_M + 1.0)
    rows = open_play() + set_ball((60.0, off), (60.0, off - 0.8), toward=(60.0, 10.0))
    assert kinds(rows) == []


def test_one_cue_admits_one_restart():
    rows = open_play() + set_ball((60.0, 20.0), (59.2, 20.4), after=10)
    at = rows[-1]["frame"] + 1
    rows += set_ball((80.0, 20.0), (79.2, 20.4), at=at + 0)
    assert len(kinds(rows)) == 1


def test_a_corner_after_the_ball_went_out_over_a_touchline_keeps_half_its_confidence():
    over_touch = [row(f, crowd() + [(100.0, 60.0, BLUE)], (100.3, min(60.0 + 0.5 * max(0, f - 10), 70.0)))
                  for f in range(30)]
    events, report = run(over_touch + set_ball((104.5, 67.5), (104.0, 66.6)))
    plain, _ = run(open_play() + set_ball((104.5, 67.5), (104.0, 66.6)))
    assert report[0]["kind"] == "corner" and report[0]["contradicted"]
    assert events[0]["confidence"] == round(plain[0]["confidence"] * rs.CONTRADICTED, 3)


def test_a_short_still_run_scores_lower_and_a_too_short_one_is_nothing():
    full, _ = run(open_play() + set_ball((60.0, 20.0), (59.2, 20.4), still=2 * rs.STILL_FRAMES + 2))
    short, _ = run(open_play() + set_ball((60.0, 20.0), (59.2, 20.4), still=rs.STILL_FRAMES + 3))
    assert full[0]["confidence"] > short[0]["confidence"]
    assert kinds(open_play() + set_ball((60.0, 20.0), (59.2, 20.4), still=rs.STILL_FRAMES - 3)) == []


def test_a_change_of_shot_is_a_cut():
    """With observe --cuts the frames run on and `camera.shot` changes at the cut."""
    rows = open_play()
    rows += set_ball((60.0, 20.0), (59.2, 20.4), at=30)
    for r in rows[30:]:
        r["camera"]["shot"] = 1
    assert kinds(rows) == ["free_kick"]


def test_every_restart_event_is_a_valid_match_event(tmp_path):
    from ninety.match.detected import load

    events, _ = run(open_play() + set_ball((104.5, 67.5), (104.0, 66.6)))
    path = tmp_path / "detected.jsonl"
    path.write_text("".join(json.dumps(e) + "\n" for e in events))
    assert [e["type"] for e in load(path)] == ["set_piece"]


def test_the_cli_writes_the_events_and_the_kinds(tmp_path):
    rows = open_play() + set_ball((5.5, 34.0), (5.0, 34.6))
    obs, found = tmp_path / "observations.jsonl", tmp_path / "detected.jsonl"
    obs.write_text("".join(json.dumps(r) + "\n" for r in rows))
    found.write_text("".join(json.dumps(e) + "\n" for e in ev.detect(rows)[0]))
    out, report = tmp_path / "restart-events.jsonl", tmp_path / "restarts.json"
    rs.main([str(obs), "--events", str(found), "--out", str(out), "--report", str(report)])
    assert [json.loads(x)["type"] for x in out.read_text().splitlines()] == ["set_piece"]
    assert json.loads(report.read_text())["restarts"][0]["kind"] == "goal_kick"
