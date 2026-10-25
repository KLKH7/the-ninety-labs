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
    events, _ = ev.detect(pass_scene(RED), kinds=())  # the interception it also is: below
    assert [(e["type"], e["team"], e["outcome"]) for e in events] == [
        ("pass", "home", "fail"), ("possession_change", "away", None)]


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


def test_side_confidence_is_the_weaker_of_the_kit_and_the_side_vote():
    # Identical shirts: each kit sits on its own colour (margin 1). Red is deeper toward x = 105 in
    # 20 frames; in the last 6 the sides swap places (new tracks), so the vote is 14 of 26.
    def swapped(f):
        return [(x, y, RED if c is BLUE else BLUE) for x, y, c in crowd(f)]
    rows = [row(f, crowd(f) if f < 20 else swapped(f)) for f in range(26)]
    for r in rows[20:]:  # keep each colour on its own y, so the swap is of ends, not of rows
        for d in r["players"]:
            d["y"] = 60.0 if d["rgb"] is BLUE else 62.0
    tracks = tr.track_players(rows)
    info = tr.assign_teams(tracks)
    assert info["frames_voting"] == 26 and abs(info["vote_margin"]) == 14
    assert {t.side_confidence for t in tracks if t.team} == {round(14 / 26, 3)}


def test_a_kit_nearer_the_other_side_is_less_sure_and_a_keeper_is_as_sure_as_he_is_deep():
    off_blue = [45.0, 60.0, 185.0]  # near the blue kit, a little toward red: still blue, less surely
    rows = [row(f, crowd(f) + [(60.0, 50.0, off_blue), (101.0, 34.0, GREEN_KEEPER)]) for f in range(30)]
    tracks = tr.track_players(rows)
    tr.assign_teams(tracks)
    by_colour = {tuple(t.rgb[0]): t for t in tracks}
    assert 0 < by_colour[tuple(off_blue)].side_confidence < by_colour[tuple(BLUE)].side_confidence
    assert by_colour[tuple(off_blue)].team == "home"
    assert by_colour[tuple(GREEN_KEEPER)].side_confidence == round((101.0 - 52.5) / 52.5, 3)


def test_a_detected_event_carries_its_holders_side_confidence():
    events, _ = ev.detect(pass_scene(BLUE))
    tracks = tr.track_players(pass_scene(BLUE))
    tr.assign_teams(tracks)
    passer = next(t for t in tracks if t.xy[0] == (50.0, 34.0))
    assert [e["team_confidence"] for e in events if e["type"] == "pass"] == [passer.side_confidence]


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
            # Both kits on the pitch, so which side is home is decided (blue: crowd's docstring).
            rows.append(row(f, crowd(f) + [holder], (50.2 if f < 12 else 50.0, y)))
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
    assert {e["type"] for e in committed} <= {"pass", "shot", "out_of_play", "possession_change", *ev.WRITTEN}


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


def kit_scene(home_kits, away_kits, frames=30):
    """Home players at x 30 to 45, away players deeper toward x = 105 (so away), one kit colour
    each, standing still; each list holds one rgb per player."""
    def scene(f):
        return ([(30 + 4 * k, 10.0 + 5 * k, c) for k, c in enumerate(home_kits)]
                + [(70 + 4 * k, 12.0 + 5 * k, c) for k, c in enumerate(away_kits)])
    tracks = tr.track_players([row(f, scene(f)) for f in range(frames)])
    info = tr.assign_teams(tracks)
    return {tuple(t.rgb[0]): t.team for t in tracks}, info


def test_a_white_kit_and_a_black_kit_are_told_apart_by_brightness():
    # Both grey by chromaticity; one is in shadow, so brightness varies within each kit too.
    white, white_shade, black, black_sun = [235.0, 235.0, 232.0], [120.0, 120.0, 118.0], \
        [22.0, 22.0, 24.0], [40.0, 40.0, 42.0]
    teams, info = kit_scene([white, white_shade, white, white_shade], [black, black_sun, black, black_sun])
    assert info["feature"] == "brightness"
    assert teams[tuple(white)] == teams[tuple(white_shade)] == "home"
    assert teams[tuple(black)] == teams[tuple(black_sun)] == "away"


def test_the_side_nearer_x_105_on_average_defends_it_even_when_the_deepest_player_is_the_other_sides():
    # Away (red) defends x = 105 and stands around x = 65; home (blue) is mostly at 30 to 40 but one
    # home forward has run on to x = 95. The deepest player toward 105 is home's, which named home as
    # the side defending it; each side's mean x does not (GROUNDING T2, O6).
    def scene(f):
        return ([(60.0 + 3 * k, 20.0 + 6 * k, RED) for k in range(4)]
                + [(30.0 + 3 * k, 25.0 + 6 * k, BLUE) for k in range(3)] + [(95.0, 40.0, BLUE)])
    tracks = tr.track_players([row(f, scene(f)) for f in range(30)])
    tr.assign_teams(tracks)
    assert {tuple(t.rgb[0]): t.team for t in tracks} == {tuple(RED): "away", tuple(BLUE): "home"}


def cut_scene(goes_out: bool):
    """A blue (home) player holds the ball at (50, 34) for 30 frames; with `goes_out` he then plays
    it over the near touchline. The broadcast cuts away (frames 30 to 529 are not in the clip:
    ninety/render/edit.py) and comes back on a blue team-mate at (40, 10) with the ball at his feet."""
    rows = []
    for f in range(30):
        bx, by = (50.3, 34.0) if not goes_out or f < 10 else (50.3, max(34.0 - 2.0 * (f - 9), -2.0))
        rows.append(row(f, crowd(f) + [(50.0, 34.0, BLUE)], (bx, by)))
    for f in range(530, 560):
        rows.append(row(f, crowd(f) + [(40.0, 10.0, BLUE)], (40.3, 10.0)))
    return rows


def test_play_across_a_broadcast_cut_is_not_a_pass():
    """Old: the spell before the cut and the team-mate's after it made a completed pass, which no
    one played: the picture had cut from the foul to the free kick."""
    events, _ = ev.detect(cut_scene(goes_out=False))
    assert [e for e in events if e["type"] == "pass"] == []


def test_a_ball_seen_going_out_before_a_cut_is_still_a_failed_pass():
    events, _ = ev.detect(cut_scene(goes_out=True))
    passes = [(e["type"], e["team"], e["outcome"]) for e in events if e["type"] == "pass"]
    assert passes == [("pass", "home", "fail")]
    assert any(e["type"] == "out_of_play" for e in events)


# Possession changes (docs/eval/possession-change-plan.md): a spell of the other side, the ball in
# play between the two as far as the picture shows.


def changes(rows, **kw):
    return [e for e in ev.detect(rows, **kw)[0] if e["type"] == "possession_change"]


def test_a_pass_the_other_side_takes_is_a_possession_change_where_and_when_he_has_it():
    rows = pass_scene(RED)
    (c,) = changes(rows)
    (spell,) = [s for s in ev.spells(tr.ball_path(rows), tr.track_players(rows)) if s.first > 20]
    assert (c["team"], c["player"], c["frame"]) == ("away", "a-t10", spell.first)
    ball = next(r["ball"][0] for r in rows if r["frame"] == spell.first)
    assert (c["x"], c["y"]) == (round(ball["x"], 2), round(ball["y"], 2))
    assert c["confidence"] == 0.8  # the ball's score, his spell long enough to count in full
    assert c["source"] == "vision" and c["outcome"] is None


def test_a_pass_to_a_team_mate_is_no_possession_change():
    assert changes(pass_scene(BLUE)) == []


def restart_scene(goes_out: bool):
    """A blue player near the touchline plays the ball toward it at frame 12. With `goes_out` it
    lies over the line (y 69) for frames 20 to 27; then a red player stands with it at his feet on
    the line, as a throw-in's taker. Without, it stops short of the line, where the red player is."""
    rows = []
    for f in range(60):
        if f < 12:
            ball, blue = (50.2, 66.0), (50.0, 66.2)
        elif f < 20 or not goes_out:
            ball, blue = (50.0, min(66.0 + 0.4 * (f - 11), 67.9)), (50.0, 60.0)
        elif f < 28:
            ball, blue = (50.0, 69.0), (50.0, 60.0)
        else:
            ball, blue = (50.0, 67.9), (50.0, 60.0)
        red = (50.0, 68.0) if f >= 28 or not goes_out else (45.0, 66.0)
        rows.append(row(f, crowd(f) + [(*blue, BLUE), (*red, RED)], ball))
    return rows


def test_after_the_ball_went_out_the_taker_of_the_restart_is_no_possession_change():
    events, _ = ev.detect(restart_scene(goes_out=True))
    assert any(e["type"] == "out_of_play" for e in events)  # the premise: the scene's ball went out
    assert changes(restart_scene(goes_out=True)) == []


def test_the_same_ball_won_in_play_is_one():
    events, _ = ev.detect(restart_scene(goes_out=False))
    assert not any(e["type"] == "out_of_play" for e in events)
    assert [c["team"] for c in changes(restart_scene(goes_out=False))] == ["away"]


def two_sides_scene(gap: int):
    """A blue player holds the ball at (50, 34) for 30 frames; `gap` frames later (a broadcast cut
    when gap > 1) a red player has it at his feet at (40, 10) for 30 frames."""
    rows = [row(f, crowd(f) + [(50.0, 34.0, BLUE)], (50.3, 34.0)) for f in range(30)]
    start = 29 + gap
    rows += [row(f, crowd(f) + [(40.0, 10.0, RED)], (40.3, 10.0)) for f in range(start, start + 30)]
    return rows


def test_across_a_broadcast_cut_a_change_of_side_is_not_told():
    assert changes(two_sides_scene(gap=500)) == []


def test_without_the_cut_the_same_change_of_side_is():
    assert [c["team"] for c in changes(two_sides_scene(gap=1))] == ["away"]


def misread_scene():
    """The dribbler of test_a_dribbler_the_tracker_loses...: on frame 30 his detection jumps 1.5 m
    sideways and from then on his kit is read red. One player, two tracks, two sides."""
    rows = []
    for f in range(60):
        x, y = 40.0 + 5.0 * f / FPS, 34.0 + (1.5 if f >= 30 else 0.0)
        rows.append(row(f, crowd(f) + [(x, y, BLUE if f < 30 else RED)], (x + 0.3, y)))
    return rows


def test_one_player_whose_kit_is_read_two_ways_in_two_tracks_is_no_possession_change():
    tracks = tr.track_players(misread_scene())
    tr.assign_teams(tracks)
    assert {t.team for t in tracks if t.xy[0][1] < 50} == {"home", "away"}  # the premise
    assert changes(misread_scene()) == []


def test_measured_without_the_rule_it_would_be_one():
    assert [c["team"] for c in changes(misread_scene(), join_breaks=False)] == ["away"]


def test_a_spell_of_a_track_with_no_side_is_passed_over():
    # Blue passes to a player of a third colour in midfield (no side: not a keeper in his box), who
    # passes on to blue. Possession never left blue's side; a sideless spell must not reset it.
    rows, bx = [], 50.3
    for f in range(100):
        if 20 < f <= 45:
            bx = min(bx + 12.0 / FPS, 61.7)
        elif f > 60:
            bx = min(bx + 12.0 / FPS, 73.7)
        line = [(50.0, 34.0, BLUE), (62.0, 34.0, GREEN_KEEPER), (74.0, 34.0, BLUE)]
        rows.append(row(f, crowd(f) + line, (bx, 34.0)))
    tracks = tr.track_players(rows)
    tr.assign_teams(tracks)
    middle = next(t for t in tracks if t.xy[0] == (62.0, 34.0))
    assert middle.team is None  # the premise
    assert len([s for s in ev.spells(tr.ball_path(rows), tracks) if s.track is middle]) == 1
    assert changes(rows) == []


def test_a_change_seen_on_a_short_spell_is_less_sure():
    rows = pass_scene(RED, frames=48)  # the clip ends a few frames after the red player has it
    (spell,) = [s for s in ev.spells(tr.ball_path(rows), tr.track_players(rows)) if s.first > 20]
    assert spell.frames < 2 * ev.MIN_SPELL_FRAMES  # the premise: a spell too short to count in full
    (c,) = changes(rows)
    assert c["confidence"] == round(0.8 * spell.frames / (2 * ev.MIN_SPELL_FRAMES), 3)


# The engine's definitions, copied into the live path (which imports no engine): each copy is held to
# the engine's own value here (docs/eval/interception-plan.md, pressure-plan.md, tackle-plan.md).


def test_every_copied_engine_value_is_the_engines():
    import inspect

    from ninety.agents import factcheck
    from ninety.sim import ball, decisions, engine

    assert ev.INTERCEPT_SHARE == engine.INTERCEPT_SHARE
    assert ev.DRAG_K == ball.DRAG_K and ev.ROLL_DECEL == ball.ROLL_DECEL
    assert ev.ARRIVE_MPS == decisions.ARRIVE_MPS
    assert sorted(ev.STAND_INS.values()) == sorted((0.0, *decisions.PASS_PACES))
    assert ev.TARGET_PACE in ev.STAND_INS.values()
    # The pressure emit is written with literals: read them from the engine's own line.
    src = inspect.getsource(engine.Engine)
    line = f"if gap < {ev.PRESSURE_M} and self.t - self.pressed.get(opp, -99) > {ev.PRESSURE_REPEAT_S:g}:"
    assert line in src
    assert ev.HELD < factcheck.MIN_CONFIDENCE and round(factcheck.MIN_CONFIDENCE - ev.HELD, 6) == 0.01


def test_the_roll_is_the_engines_a_ground_pass_struck_for_a_pace_reaches_its_target_at_it():
    from ninety.sim import ball, decisions

    for distance, pace in ((12.0, 6.0), (25.0, 10.0), (35.0, 14.0)):
        v0 = ball.ground_pass(distance, pace, decisions.DT)
        # One frame of the ball's travel at most: the engine's own step size.
        assert abs(ev.roll_distance(v0, pace) - distance) <= v0 / tr.FPS
    assert ev.roll_distance(5.0, 6.0) == 0.0  # struck slower than the pace: no way to go


# Interceptions: a failed pass taken short of INTERCEPT_SHARE of the way to the stand-in target.


def lane_scene(share, speed=None, frames=90, kick=20, colour=RED, metres=None):
    """pass_scene's strike from (50.3, 34) toward +x at `speed` (TARGET_PACE + 6 m/s by default),
    taken by a player of `colour` where the ball stops: `share` of the stand-in target's distance,
    or `metres` from the strike."""
    speed = ev.TARGET_PACE + 6.0 if speed is None else speed
    stop = 50.3 + (metres if metres is not None else share * ev.roll_distance(speed, ev.TARGET_PACE))
    rows, bx = [], 50.3
    for f in range(frames):
        if f > kick:
            bx = min(bx + speed / FPS, stop)
        rows.append(row(f, crowd(f) + [(50.0, 34.0, BLUE), (stop + 0.3, 34.0, colour)], (bx, 34.0)))
    return rows


def kinds_of(rows, kind, **kw):
    return [e for e in ev.detect(rows, kinds=ev.TURNOVERS, **kw)[0] if e["type"] == kind]


def test_a_pass_cut_out_short_of_where_it_was_going_is_an_interception_at_the_possession_change():
    rows = lane_scene(ev.INTERCEPT_SHARE - 0.05)
    (i,) = kinds_of(rows, "interception")
    (c,) = kinds_of(rows, "possession_change")
    (p,) = kinds_of(rows, "pass")
    assert (i["team"], i["frame"], i["x"], i["y"]) == (c["team"], c["frame"], c["x"], c["y"])
    assert i["player"] == p["interceptor"] == "a-t10" and i["confidence"] == c["confidence"]


def test_an_interception_is_as_sure_as_the_control_not_the_pass():
    rows = lane_scene(ev.INTERCEPT_SHARE - 0.05)
    for r in rows[:17]:
        r["ball"] = []  # the passer seen with the ball for only a few frames before he strikes it
    (p,) = kinds_of(rows, "pass")
    (i,) = kinds_of(rows, "interception")
    assert p["confidence"] < i["confidence"] == kinds_of(rows, "possession_change")[0]["confidence"]


def test_the_same_pass_collected_beyond_the_share_is_a_recovery_only():
    rows = lane_scene(ev.INTERCEPT_SHARE + 0.05)
    assert kinds_of(rows, "interception") == []
    assert [c["team"] for c in kinds_of(rows, "possession_change")] == ["away"]


def test_a_pass_to_a_team_mate_short_of_the_target_is_no_interception():
    assert kinds_of(lane_scene(0.5, colour=BLUE), "interception") == []


def test_a_ball_struck_no_faster_than_the_pace_has_its_target_at_the_kick_so_any_take_is_in_the_lane():
    # The engine's in_the_lane: a target at the kick's own spot counts as in the lane.
    # With the stopping point as the target (pace 0) no ball is that slow, so there is no such case.
    slow = ev.TARGET_PACE - 0.5
    if slow > 0:
        assert ev.roll_distance(slow, ev.TARGET_PACE) == 0.0  # the premise
        rows = lane_scene(None, speed=slow, metres=8.0)
        assert [i["team"] for i in kinds_of(rows, "interception")] == ["away"]


def test_with_the_ball_unseen_after_the_strike_no_interception_is_told():
    rows = lane_scene(ev.INTERCEPT_SHARE - 0.05)
    (p,) = kinds_of(rows, "pass")
    for r in rows:
        if p["frame"] < r["frame"] <= p["frame"] + ev.SHOT_LOOK_S * FPS:
            r["ball"] = []  # hidden for the strike's first SHOT_LOOK_S: no speed, no direction
    assert [(e["type"], e["outcome"]) for e in kinds_of(rows, "pass")] == [("pass", "fail")]  # the premise
    assert kinds_of(rows, "possession_change") and kinds_of(rows, "interception") == []


def test_an_interception_is_written_only_when_its_kind_is():
    rows = lane_scene(ev.INTERCEPT_SHARE - 0.05)
    assert kinds_of(rows, "interception") and not [
        e for e in ev.detect(rows, kinds=())[0] if e["type"] == "interception"]


# Pressure: the nearest opponent closer than PRESSURE_M to the player on the ball, once in
# PRESSURE_REPEAT_S for each side.


def press_scene(distances, presser_y0=34.0, frames=None, second=None):
    """A blue player stands with the ball at his feet at (50, 34) throughout; a red player stands at
    (50, 34 + d) for d in `distances`, one per frame (None: not seen). `second` adds another red
    player the same way."""
    rows = []
    for f, d in enumerate(distances):
        line = [(50.0, 34.0, BLUE)]
        if d is not None:
            line.append((50.0, presser_y0 + d, RED))
        if second and second[f] is not None:
            line.append((50.0, presser_y0 - second[f], RED))
        rows.append(row(f, crowd(f) + line, (50.3, 34.0)))
    return rows


def approach(start, end, frames):
    return [start + (end - start) * f / (frames - 1) for f in range(frames)]


def test_an_opponent_coming_closer_than_two_metres_is_one_pressure_at_him_when_he_does():
    ds = approach(4.0, 1.0, 76)  # 4 cm a frame, from 4 m to 1 m in 3 s
    (p,) = kinds_of(press_scene(ds), "pressure")
    first = next(f for f, d in enumerate(ds) if d < ev.PRESSURE_M)
    assert (p["frame"], p["team"], p["x"], p["y"]) == (first, "away", 50.0, round(34.0 + ds[first], 2))
    assert p["receiver"] == "h-t9" and p["player"] == "a-t10"


def test_an_opponent_held_at_exactly_two_metres_is_no_pressure():
    assert kinds_of(press_scene([2.0] * 60), "pressure") == []
    assert len(kinds_of(press_scene([1.99] * 60), "pressure")) == 1


def test_a_side_presses_once_in_eight_seconds_and_again_after():
    # In at 1 m, out to 5 m, back in: at 6 s after the first (too soon), and at 9 s (another).
    def scene(back_s):
        n = round(back_s * FPS)
        return press_scene([1.0] * 25 + [5.0] * (n - 25) + [1.0] * 50)
    assert len(kinds_of(scene(6.0), "pressure")) == 1
    assert len(kinds_of(scene(9.0), "pressure")) == 2


def test_the_eight_seconds_are_the_sides_not_the_pressers():
    # A second red player comes in 3 s after the first: the engine's memory is the side's.
    first = [1.0] * 40 + [6.0] * 100
    other = [None] * 75 + [1.0] * 65
    assert len(kinds_of(press_scene(first, second=other), "pressure")) == 1


def test_a_pressure_within_the_position_error_of_the_line_is_half_as_sure():
    near, edge = kinds_of(press_scene([0.5] * 60), "pressure"), kinds_of(press_scene([1.9] * 60), "pressure")
    assert near[0]["confidence"] == 0.8 and edge[0]["confidence"] == 0.4
    assert 1.9 > ev.PRESSURE_M - ev.RIVAL_M > 0.5  # the premise: one each side of the error band


def test_two_pressers_as_near_as_each_other_leave_the_presser_unnamed():
    (p,) = kinds_of(press_scene([1.0] * 60, second=[1.2] * 60), "pressure")
    assert p["player"] is None and p["team"] == "away"


def test_a_ball_rolling_past_a_player_is_no_one_to_press():
    # pass_scene's ball between the two: nobody has it while it runs.
    rows = pass_scene(RED)
    for r in rows:
        r["players"].append({"bbox": [400, 0, 410, 30], "score": 0.9, "x": 56.0, "y": 35.0, "rgb": RED})
    presses = kinds_of(rows, "pressure")
    assert all(not 20 < p["frame"] < 45 for p in presses)


# Tackles: a spell that ends with the ball leaving slower than ARRIVE_MPS and an opponent at it.


def tackle_scene(knock=5.0, taker=RED, tackler_gap=1.0, tackler_gone_after=None, frames=70, y=34.0):
    """A blue player dribbles along +x at 3 m/s at `y`, the ball 0.3 m ahead; at frame 30 a red
    player stands `tackler_gap` metres ahead of the ball, and the ball is knocked sideways (+y) at
    `knock` m/s for 3 m, where a player of `taker` (None: nobody) stands and keeps it."""
    rows = []
    stop_x = 50.0 + 3.0 * 30 / FPS + 0.3
    for f in range(frames):
        cx = 50.0 + 3.0 * min(f, 30) / FPS
        if f <= 30:
            ball = (cx + 0.3, y)
        else:
            ball = (stop_x, min(y + knock * (f - 30) / FPS, y + 3.0))
        line = [(cx, y, BLUE)]
        if tackler_gone_after is None or f <= tackler_gone_after:
            line.append((stop_x + tackler_gap, y, RED))
        if taker is not None:
            line.append((stop_x, y + 3.3, taker))
        rows.append(row(f, crowd(f) + line, ball))
    return rows


def test_a_ball_knocked_off_the_dribbler_and_won_is_a_tackle_won_at_the_contact():
    (t,) = kinds_of(tackle_scene(), "tackle")
    assert (t["team"], t["outcome"]) == ("away", "success")
    assert abs(t["frame"] - 30) <= ev.SPEED_FRAMES and abs(t["y"] - 34.0) < 0.5
    assert t["confidence"] == 0.8


def test_knocked_off_him_but_picked_up_by_his_team_mate_is_a_tackle_lost():
    (t,) = kinds_of(tackle_scene(taker=BLUE), "tackle")
    assert (t["team"], t["outcome"]) == ("away", "fail")


def test_knocked_loose_and_nobody_has_it_by_the_end_leaves_the_outcome_open():
    (t,) = kinds_of(tackle_scene(taker=None), "tackle")
    assert t["outcome"] is None


def test_knocked_out_of_play_and_taken_for_the_restart_leaves_the_outcome_open():
    # Near the touchline the ball runs over it (y 68) and comes to rest beyond, where the red player
    # stands to take the throw-in: the next spell is a restart, not who came away with it.
    rows = tackle_scene(y=66.0)
    assert any(e["type"] == "out_of_play" for e in ev.detect(rows)[0])  # the premise
    (t,) = kinds_of(rows, "tackle")
    assert t["outcome"] is None


def test_a_ball_struck_away_is_a_pass_not_a_tackle():
    assert kinds_of(tackle_scene(knock=ev.ARRIVE_MPS + 0.2), "tackle") == []
    assert len(kinds_of(tackle_scene(knock=ev.ARRIVE_MPS - 0.2), "tackle")) == 1


def test_with_no_opponent_at_the_ball_a_slow_ball_leaving_him_is_no_tackle():
    assert kinds_of(tackle_scene(tackler_gap=ev.CONTROL_M + 0.6), "tackle") == []


def test_a_tackle_whose_tackler_the_tracker_loses_in_the_contact_is_held_under_the_gate():
    (contact,) = kinds_of(tackle_scene(), "tackle")
    (t,) = kinds_of(tackle_scene(tackler_gone_after=contact["frame"]), "tackle")
    assert t["frame"] == contact["frame"] and t["confidence"] == ev.HELD
