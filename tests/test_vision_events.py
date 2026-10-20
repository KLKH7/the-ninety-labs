"""Event detection's pure-Python stages: tracking, teams, possession, passes, shots, out of play.

Every scene is built here, frame by frame, as observations (what ninety.vision.observe writes), so
each test's premise holds by construction (docs/LESSONS.md, lesson 47). Constants come from the
modules they test (lesson 36).
"""

from __future__ import annotations

import json
import math

from ninety.vision import events as ev
from ninety.vision import track as tr

RED, BLUE, GREEN_KEEPER = [200.0, 30.0, 40.0], [40.0, 60.0, 190.0], [60.0, 230.0, 170.0]
FPS = tr.FPS


def row(frame, players, ball=None, ok=True):
    """players: (x, y, rgb); ball: (x, y) or None."""
    return {
        "frame": frame, "t": round(frame / FPS, 2),
        "camera": {"ok": ok, "median_px": 0.5, "points": 500, "P": None},
        # Boxes apart from each other: only the out-of-play test draws the ball over a player.
        "players": [{"bbox": [20 * i, 0, 20 * i + 10, 30], "score": 0.9, "x": x, "y": y, "rgb": c}
                    for i, (x, y, c) in enumerate(players)],
        "ball": [] if ball is None else [{"bbox": [0, 500, 8, 508], "score": 0.8,
                                          "x": ball[0], "y": ball[1]}],
    }


def crowd(frame):
    """Four outfield players of each side standing still, red deeper toward x = 105 (so red
    defends that goal and is away), well away from the action at y about 60."""
    return [(70 + 3 * k, 60.0, BLUE) for k in range(4)] + [(85 + 3 * k, 62.0, RED) for k in range(4)]


def pass_scene(receiver_colour, frames=60, kick=20, speed=12.0):
    """A blue (home) player at (50, 34) holds the ball, strikes it toward +x at `speed` m/s on
    frame `kick`, and a player of `receiver_colour` 12 m away at (62, 34) takes it and keeps it."""
    rows, bx = [], 50.3
    for f in range(frames):
        if f > kick:
            bx = min(bx + speed / FPS, 61.7)
        rows.append(row(f, crowd(f) + [(50.0, 34.0, BLUE), (62.0, 34.0, receiver_colour)], (bx, 34.0)))
    return rows


def test_a_player_walking_keeps_one_track_and_a_frame_with_a_bad_camera_is_skipped():
    rows = [row(f, [(10 + 0.2 * f, 10.0, RED), (10 + 0.2 * f, 13.0, BLUE)], ok=(f != 5)) for f in range(20)]
    rows[7]["players"][0]["x"] = 500.0  # a wild position on a frame whose camera is not ok
    rows[7]["camera"]["ok"] = False
    tracks = tr.track_players(rows)
    assert len(tracks) == 2
    assert all(len(t.frames) == 18 for t in tracks)  # 20 frames minus the two bad ones


def test_a_detection_beyond_the_gate_starts_a_new_track():
    step = tr.GATE_M * 1.5
    rows = [row(0, [(10.0, 10.0, RED)]), row(1, [(10.0 + step, 10.0, RED)])]
    assert len(tr.track_players(rows)) == 2


def test_the_side_defending_x_105_is_away_and_a_third_colour_in_a_box_is_its_keeper():
    rows = [row(f, crowd(f) + [(101.0, 34.0, GREEN_KEEPER)]) for f in range(30)]
    tracks = tr.track_players(rows)
    info = tr.assign_teams(tracks)
    by_colour = {tuple(t.rgb[0]): t for t in tracks}
    assert by_colour[tuple(RED)].team == "away" and by_colour[tuple(BLUE)].team == "home"
    keeper = by_colour[tuple(GREEN_KEEPER)]
    assert keeper.keeper and keeper.team == "away"
    assert info["keepers"] == 1


def test_the_side_naming_follows_depth_not_colour_order():
    # Same scene with the colours swapped: blue is now the deeper side, so blue is away.
    def swapped(f):
        return [(x, y, RED if c is BLUE else BLUE) for x, y, c in crowd(f)]
    tracks = tr.track_players([row(f, swapped(f)) for f in range(30)])
    tr.assign_teams(tracks)
    assert {tuple(t.rgb[0]): t.team for t in tracks} == {tuple(RED): "home", tuple(BLUE): "away"}


def test_a_pass_to_a_team_mate_is_one_successful_pass_struck_where_the_ball_left_him():
    events, summary = ev.detect(pass_scene(BLUE))
    passes = [e for e in events if e["type"] == "pass"]
    assert len(passes) == 1, events
    p = passes[0]
    assert p["team"] == "home" and p["outcome"] == "success" and p["source"] == "vision"
    # Struck after frame 20; velocities span SPEED_FRAMES either side, so the last frame he
    # still has it is up to that many frames before the strike.
    assert 20 - ev.SPEED_FRAMES <= p["frame"] <= 20 and math.hypot(p["x"] - 50.3, p["y"] - 34.0) < 0.5
    assert 0 < p["confidence"] <= 1
    assert p["ball_speed_kmh"] == round(12.0 * 3.6, 1)


def test_a_pass_won_by_an_opponent_fails():
    events, _ = ev.detect(pass_scene(RED))
    assert [(e["type"], e["team"], e["outcome"]) for e in events] == [("pass", "home", "fail")]


def test_a_completed_pass_names_its_passer_and_receiver_by_side_and_track():
    events, summary = ev.detect(pass_scene(BLUE))
    p = next(e for e in events if e["type"] == "pass")
    # Tracks are numbered as they start: the crowd's eight, then the passer, then the receiver.
    assert (p["player"], p["receiver"], p["interceptor"]) == ("h-t9", "h-t10", None)
    assert summary["named"] == {"player": 1, "receiver": 1, "interceptor": 0}


def test_a_pass_the_other_side_takes_names_the_interceptor_not_a_receiver():
    events, _ = ev.detect(pass_scene(RED))
    p = next(e for e in events if e["type"] == "pass")
    assert (p["player"], p["receiver"], p["interceptor"]) == ("h-t9", None, "a-t10")


def rival_scene(gap):
    """pass_scene(BLUE) with an away player standing still at the strike spot's side, `gap` metres
    farther from the ball (at 50.3, 34) than the passer (0.3 m from it) is."""
    rows = pass_scene(BLUE)
    for r in rows:
        r["players"].append({"bbox": [400, 0, 410, 30], "score": 0.9, "x": 50.3, "y": 34.0 + 0.3 + gap,
                             "rgb": RED})
    return rows


def test_a_rival_within_the_position_error_leaves_the_passer_unnamed_and_keeps_the_side():
    events, _ = ev.detect(rival_scene(ev.RIVAL_M - 0.05))
    p = next(e for e in events if e["type"] == "pass")
    assert p["player"] is None and p["team"] == "home" and p["outcome"] == "success"
    assert p["receiver"] == "h-t10"  # nobody near the receiver: he is still named


def test_a_rival_beyond_the_position_error_does_not():
    events, _ = ev.detect(rival_scene(ev.RIVAL_M + 0.05))
    assert next(e for e in events if e["type"] == "pass")["player"] == "h-t9"


def test_a_track_the_companion_does_not_draw_is_never_named():
    ball = tr.BallPoint(2, 10.0, 10.0, 0.9)

    def track(id_, n, team="home"):
        return tr.Track(id_, frames=list(range(n)), xy=[(10.2, 10.0)] * n, team=team)

    assert ev.attribute(track(1, ev.MIN_TRACK_FRAMES), ball, []) == "h-t1"
    assert ev.attribute(track(1, ev.MIN_TRACK_FRAMES - 1), ball, []) is None  # a fragment
    assert ev.attribute(track(1, ev.MIN_TRACK_FRAMES, team=None), ball, []) is None  # no side
    assert ev.attribute(track(1, 3), tr.BallPoint(9, 10.0, 10.0, 0.9), []) is None  # not seen then


def test_a_dribbler_the_tracker_loses_and_picks_up_again_is_not_a_pass_to_himself():
    # A blue player runs with the ball at 5 m/s; on frame 30 his detection jumps 1.5 m sideways
    # (past the tracker's gate), so the tracker ends his track and starts another: two spells, one
    # player. Without the rule this reads as a completed pass from him to himself.
    rows = []
    for f in range(60):
        x, y = 40.0 + 5.0 * f / FPS, 34.0 + (1.5 if f >= 30 else 0.0)
        rows.append(row(f, crowd(f) + [(x, y, BLUE)], (x + 0.3, y)))
    tracks = tr.track_players(rows)
    assert len([t for t in tracks if t.xy[0][1] < 50]) == 2  # the scene does split him
    events, _ = ev.detect(rows)
    assert [e for e in events if e["type"] == "pass"] == []


def test_a_new_track_may_continue_an_old_one_only_when_never_seen_together_and_within_reach():
    def track(first, last, x):
        n = last - first + 1
        return tr.Track(1, frames=list(range(first, last + 1)), xy=[(x, 0.0)] * n, team="home")
    a = track(0, 10, 0.0)
    reach_1 = ev.REACH_MPS / FPS + ev.RIVAL_M  # one frame later
    assert ev.may_continue(a, track(11, 20, reach_1 - 0.01))
    assert not ev.may_continue(a, track(11, 20, reach_1 + 0.01))
    assert not ev.may_continue(a, track(10, 20, 0.0))  # seen in the same frame: two players
    assert not ev.may_continue(a, track(11 + tr.MAX_GAP_FRAMES, 40, 0.0))  # lost too long
    # Five frames on, 10 m away: farther than a player runs in 0.2 s at any speed (P9), however
    # large the position error is taken to be within reason.
    assert not ev.may_continue(a, track(15, 20, 10.0))


def test_out_of_play_names_nobody():
    events, _ = ev.detect(pass_scene(BLUE, speed=30.0)[:21] + [
        row(f, crowd(f) + [(50.0, 34.0, BLUE)], (106.0, 34.0)) for f in range(21, 30)])
    outs = [e for e in events if e["type"] == "out_of_play"]
    assert outs and all(e["player"] is None for e in outs)


def test_a_ball_rolling_past_a_player_is_not_his():
    # The ball runs at 12 m/s straight past a red player standing on its line: without the
    # relative-speed test he would have a spell, and the pass would be cut in two.
    rows, bx = [], 50.3
    for f in range(80):  # 19.4 m at 12 m/s is about 40 frames
        if f > 20:
            bx = min(bx + 12.0 / FPS, 69.7)
        line = [(50.0, 34.0, BLUE), (60.0, 34.0, RED), (70.0, 34.0, BLUE)]
        rows.append(row(f, crowd(f) + line, (bx, 34.0)))
    events, _ = ev.detect(rows)
    assert [(e["type"], e["outcome"]) for e in events] == [("pass", "success")]
    assert ev.CARRY_MPS < 12.0


def test_a_strike_toward_the_goal_home_attacks_is_a_shot_and_the_same_strike_by_away_is_not():
    def scene(colour):
        rows, bx = [], 90.3
        for f in range(40):
            if f > 10:
                bx += 25.0 / FPS
            rows.append(row(f, crowd(f) + [(90.0, 34.0, colour)], (bx, 34.0)))
        return rows
    home = [e["type"] for e in ev.detect(scene(BLUE))[0]]
    away = [e["type"] for e in ev.detect(scene(RED))[0]]
    assert home == ["shot", "out_of_play"]  # it goes on over the goal line
    assert "shot" not in away and away[0] == "pass"


def test_the_ball_over_a_line_for_out_frames_is_out_of_play_and_one_frame_is_not():
    def scene(out_for):
        rows = []
        for f in range(40):
            y = 66.0 if f < 20 else (68.0 + 1.0 if f < 20 + out_for else 66.0)
            holder = (50.0, 66.2 if f < 12 else 60.0, BLUE)
            rows.append(row(f, crowd(f)[:4] + [holder], (50.2 if f < 12 else 50.0, y)))
        return rows
    long_ = [e for e in ev.detect(scene(ev.OUT_FRAMES))[0] if e["type"] == "out_of_play"]
    short = [e for e in ev.detect(scene(1))[0] if e["type"] == "out_of_play"]
    assert len(long_) == 1 and long_[0]["team"] == "home" and long_[0]["frame"] == 20
    assert short == []


def test_a_ball_drawn_over_a_player_beyond_the_line_is_not_out_of_play():
    # A keeper holds the ball at his chest on his line; placed on the ground it lands metres behind
    # him, over the line. Its box centre is inside his box, so it is not judged.
    rows = []
    for f in range(30):
        r = row(f, crowd(f) + [(104.0, 34.0, BLUE)], (106.0, 34.0))
        r["players"][-1]["bbox"] = [600, 300, 640, 400]
        r["ball"][0]["bbox"] = [615, 330, 625, 340]
        rows.append(r)
    assert ev.out_of_play(tr.ball_path(rows)) == []
    for r in rows:
        r["ball"][0]["bbox"] = [700, 330, 710, 340]  # the same ball, drawn clear of him
    assert ev.out_of_play(tr.ball_path(rows)) == [0]


def test_a_clip_where_nobody_has_the_ball_gives_no_events_and_no_error():
    # Found by the runtime truth guard (a synthetic clip with no ball): with no spells, pairing
    # each spell with the next raised instead of returning nothing.
    events, summary = ev.detect([row(f, crowd(f)) for f in range(10)])
    assert events == [] and summary["spells"] == 0


def test_every_detected_event_is_a_valid_match_event_the_scorer_accepts(tmp_path):
    import jsonschema

    schema = json.loads((tr.Path(__file__).parents[1] / "schemas" / "match_event.schema.json").read_text())
    events = ev.detect(pass_scene(BLUE))[0] + ev.detect(pass_scene(RED))[0]
    assert events
    for e in events:
        jsonschema.validate(e, schema)
        assert e["source"] == "vision"


def test_the_cli_writes_the_events_and_the_summary(tmp_path):
    obs = tmp_path / "observations.jsonl"
    obs.write_text("".join(json.dumps(r) + "\n" for r in pass_scene(BLUE)))
    ev.main([str(obs), "--out", str(tmp_path / "d.jsonl"), "--summary", str(tmp_path / "s.json")])
    lines = (tmp_path / "d.jsonl").read_text().splitlines()
    assert [json.loads(x)["type"] for x in lines] == ["pass"]
    assert json.loads((tmp_path / "s.json").read_text())["events"]["pass"] == 1


FIXTURES = tr.Path(__file__).parent / "fixtures"


def test_the_committed_fixture_is_what_the_code_detects_from_the_committed_observations():
    # The agents (R4) and the viewer (R5) read tests/fixtures/detected-seed900001.jsonl. It must come
    # from this code (docs/LESSONS.md, lesson 77): regenerate it with
    #   uv run python -m ninety.vision.events tests/fixtures/observations-seed900001.jsonl \
    #       --out tests/fixtures/detected-seed900001.jsonl
    rows = tr.read_observations(FIXTURES / "observations-seed900001.jsonl")
    lines = (FIXTURES / "detected-seed900001.jsonl").read_text().splitlines()
    committed = [json.loads(x) for x in lines if x]
    assert ev.detect(rows)[0] == committed
    assert {e["type"] for e in committed} <= {"pass", "shot", "out_of_play"}


def test_one_kit_in_sun_and_in_shadow_is_one_side():
    # Shadow scales a shirt's three channels together. These kits are dark, as seed 900001's are:
    # clustered by raw colour, the bright away shirts are one group and everything else the other
    # (lesson 98); by chromaticity, each kit is one group whatever the light.
    home_sun, home_shade = [60.0, 25.0, 25.0], [18.0, 7.5, 7.5]
    away_sun, away_shade = [40.0, 50.0, 90.0], [12.0, 15.0, 27.0]
    def scene(f):
        return ([(60 + 3 * k, 20.0, home_sun) for k in range(3)]
                + [(60 + 3 * k, 50.0, home_shade) for k in range(3)]
                + [(80 + 3 * k, 22.0, away_sun) for k in range(3)]
                + [(80 + 3 * k, 52.0, away_shade) for k in range(3)])
    tracks = tr.track_players([row(f, scene(f)) for f in range(30)])
    tr.assign_teams(tracks)
    teams = {tuple(t.rgb[0]): t.team for t in tracks}
    assert teams[tuple(home_sun)] == teams[tuple(home_shade)] == "home"
    assert teams[tuple(away_sun)] == teams[tuple(away_shade)] == "away"
