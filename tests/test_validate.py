"""Each contract check gets a clean clip that passes and planted defects that must fail it.
Check IDs match docs/GROUNDING.md."""

import json

import pytest

from ninety.validate import validate

FPS = 25
PASS_AT = 5  # h1 holds the ball for 5 frames, then passes 10 m to h2 over 1 s


def event(id_, frame, type_, team, player=None, receiver=None, x=40.0, y=30.0, **kw):
    return {
        "id": id_, "t": frame / FPS, "frame": frame, "type": type_, "team": team, "player": player,
        "receiver": receiver, "x": x, "y": y, "end_x": None, "end_y": None, "outcome": None,
        "ball_speed_kmh": None, "source": "truth", "confidence": None, **kw,
    }


def clean_clip() -> dict:
    """Six seconds: h1 passes to h2, who keeps it; a1 stands still. Everything consistent."""
    frames = []
    for n in range(150):
        u = min(max((n - PASS_AT) / 25, 0.0), 1.0)
        frames.append({
            "frame": n, "t": n / FPS,
            "ball": {"x": 40 + 10 * u, "y": 30.0, "z": 0.0},
            "possessor": "h1" if n < PASS_AT else ("h2" if u == 1 else None),
            "players": [
                {"id": "h1", "team": "home", "x": 40.0, "y": 30.0},
                {"id": "h2", "team": "home", "x": 50.0, "y": 30.0},
                {"id": "a1", "team": "away", "x": 60.0, "y": 40.0},
            ],
        })
    events = [event("e1", PASS_AT, "pass", "home", "h1", "h2", end_x=50.0, end_y=30.0,
                    outcome="success", ball_speed_kmh=36.0)]
    return {"events": events, "frames": frames, "meta": {"fps": FPS, "score": {"home": 0, "away": 0}}}


def write(tmp_path, clip):
    with open(tmp_path / "events.jsonl", "w") as f:
        f.writelines(json.dumps(e) + "\n" for e in clip["events"])
    with open(tmp_path / "frames.jsonl", "w") as f:
        f.writelines(json.dumps(fr) + "\n" for fr in clip["frames"])
    (tmp_path / "meta.json").write_text(json.dumps(clip["meta"]))
    return tmp_path


def run(tmp_path, clip):
    return validate(write(tmp_path, clip))


def test_clean_clip_passes(tmp_path):
    assert run(tmp_path, clean_clip()) == {}


# --- planted defects ---------------------------------------------------------------------------

def bad_schema(c):
    c["events"][0]["type"] = "dribble"


def not_truth(c):
    c["events"][0]["source"] = "vision"


def roster_changes(c):
    c["frames"][10]["players"][2]["id"] = "a2"


def teleport(c):
    c["frames"][60]["players"][2]["x"] = 70.0  # a1 jumps 10 m in one frame


def runs_then(c, speed: float, change: float, start: float = 1.0) -> None:
    """a1 runs at `speed` until `start` seconds, then changes speed at `change` m/s² until it
    stops (braking) or reaches 9 m/s (speeding up), then holds that speed."""
    x, v = 20.0, speed
    for n in range(150):
        t = n / FPS
        c["frames"][n]["players"][2]["x"] = x
        if t >= start:
            v = max(0.0, min(9.0, v + change / FPS))
        x += v / FPS


def stops_too_hard(c):
    runs_then(c, 8.0, -12.0)  # beyond any braking


def speeds_up_too_hard(c):
    runs_then(c, 3.0, 9.0)  # already running, then 9 m/s²: beyond any acceleration


def sudden_sprint(c):
    for n in range(60, 150):  # a1 goes from standing to 9 m/s instantly: legal speed, impossible start
        c["frames"][n]["players"][2]["x"] = 60.0 + 9 * (n - 60) / FPS


def ball_jump(c):
    c["frames"][40]["ball"]["x"] = 90.0


def ball_underground(c):
    c["frames"][20]["ball"]["z"] = -0.5


def ball_floats(c):
    for n in range(10, 25):  # hangs 1.5 m up with nobody touching it
        c["frames"][n]["ball"]["z"] = 1.5


def ball_away_from_holder(c):
    c["frames"][100]["possessor"] = "h1"  # h1 at x=40, ball with h2 at x=50


def wrong_team(c):
    c["events"][0]["team"] = "away"


def unknown_player(c):
    c["events"][0]["receiver"] = "h9"


def event_time_mismatch(c):
    c["events"][0]["t"] = 2.0


def event_far_from_ball(c):
    c["events"][0]["x"] = 20.0


def ball_never_arrives(c):
    c["events"][0]["end_x"] = 80.0


def pass_without_ball(c):
    c["events"][0]["player"] = "h2"
    c["events"][0]["receiver"] = "h1"


def interception_from_nowhere(c):
    c["events"].append(event("e2", 40, "interception", "away", "a1", x=50.0))


def goal_without_shot(c):
    c["events"].append(event("e2", 40, "goal", "home", "h2", x=105.0, y=34.0))
    c["meta"]["score"]["home"] = 1


def pass_to_himself(c):
    c["events"][0]["receiver"] = "h1"


def score_disagrees(c):
    c["meta"]["score"]["home"] = 1


@pytest.mark.parametrize("defect, check", [
    (bad_schema, "C1 event schema"),
    (not_truth, "C1 event schema"),
    (roster_changes, "C3 roster"),
    (teleport, "P1 player speed"),
    (sudden_sprint, "P2 player acceleration"),
    (stops_too_hard, "P2 player acceleration"),
    (speeds_up_too_hard, "P2 player acceleration"),
    (ball_jump, "P3 ball speed"),
    (ball_underground, "P4 ball below ground"),
    (ball_floats, "P5 ball flight"),
    (ball_away_from_holder, "P6 ball at feet"),
    (wrong_team, "C4 event players"),
    (unknown_player, "C4 event players"),
    (event_time_mismatch, "C5 event frame"),
    (event_far_from_ball, "C6 event location"),
    (ball_never_arrives, "C7 ball path"),
    (pass_without_ball, "C8 event order"),
    (interception_from_nowhere, "C8 event order"),
    (goal_without_shot, "C8 event order"),
    (pass_to_himself, "C8 event order"),
    (score_disagrees, "C9 score"),
])
def test_planted_defect_fails(tmp_path, defect, check):
    clip = clean_clip()
    defect(clip)
    assert check in run(tmp_path, clip)


# --- legal cases that must pass ----------------------------------------------------------------

def test_kickoff_restart_may_reset_positions(tmp_path):
    clip = clean_clip()
    teleport(clip)
    clip["events"].append(event("e2", 60, "kickoff", "away", "a1", x=70.0, y=40.0))
    assert "P1 player speed" not in run(tmp_path, clip)


def lofted(clip):
    """The pass goes through the air under gravity instead of along the ground."""
    flight = 25 / FPS
    v = 0.5 * 9.81 * flight
    for n in range(PASS_AT, PASS_AT + 26):
        t = (n - PASS_AT) / FPS
        clip["frames"][n]["ball"]["z"] = round(max(v * t - 0.5 * 9.81 * t * t, 0.0), 4)


def test_new_ball_placed_while_out_of_play_passes(tmp_path):
    clip = clean_clip()
    for n in range(100, 150):
        clip["frames"][n]["possessor"] = None
    for n in range(110, 150):
        clip["frames"][n]["ball"]["x"] = 5.5  # placed for a goal kick at the other end
    clip["events"].append(event("e2", 100, "out_of_play", "home", x=50.0))
    clip["events"].append(event("e3", 110, "set_piece", "away", "a1", x=5.5))
    assert "P3 ball speed" not in run(tmp_path, clip)


def test_keeper_may_hold_the_ball_at_arms_length_in_the_box(tmp_path):
    clip = clean_clip()
    for f in clip["frames"]:
        f["players"].append({"id": "a11", "team": "away", "x": 3.0, "y": 34.0})
    clip["meta"]["roster"] = [{"id": "a11", "team": "away", "role": "GK"}]
    clip["frames"][100]["possessor"] = "a11"
    clip["frames"][100]["ball"] = {"x": 4.8, "y": 34.0, "z": 1.0}  # 1.8 m: a dive, arms out
    assert "P6 ball at feet" not in run(tmp_path, clip)
    clip["frames"][100]["ball"]["x"] = 6.0  # 3 m: beyond any reach
    assert "P6 ball at feet" in run(tmp_path, clip)


def test_strong_braking_passes(tmp_path):
    clip = clean_clip()
    runs_then(clip, 9.0, -9.0)  # hard but legal braking, which a single 8 m/s² limit would fail
    assert "P2 player acceleration" not in run(tmp_path, clip)


def a1_in_the_path(clip):
    for f in clip["frames"]:
        f["players"][2].update(x=44.0, y=30.8)


def test_a_touch_in_the_air_is_not_judged_as_free_flight(tmp_path):
    clip = clean_clip()
    a1_in_the_path(clip)
    lofted(clip)
    clip["frames"][PASS_AT + 10]["ball"]["z"] += 0.4  # a defender's head meets it
    assert "P5 ball flight" in run(tmp_path, clip)  # unexplained: a defect
    clip["events"].append(event("e2", PASS_AT + 10, "deflection", "away", "a1", x=44.0))
    problems = run(tmp_path, clip)
    assert "P5 ball flight" not in problems and "P14 touch possible" not in problems


def test_a_touch_by_a_distant_player_fails(tmp_path):
    clip = clean_clip()  # a1 stands at (60, 40), about 19 m from the ball
    clip["events"].append(event("e2", PASS_AT + 10, "deflection", "away", "a1", x=44.0))
    assert "P14 touch possible" in run(tmp_path, clip)


def test_a_touch_on_a_ball_out_of_reach_and_moving_away_fails(tmp_path):
    clip = clean_clip()
    for f in clip["frames"]:
        f["players"][2].update(x=39.0, y=30.0)
    clip["frames"][PASS_AT + 5]["players"][2].update(x=40.5)  # suddenly beside it, 1.5 m on
    clip["events"].append(event("e2", PASS_AT + 5, "deflection", "away", "a1", x=42.0))
    assert "P14 touch possible" in run(tmp_path, clip)


def test_ball_under_gravity_passes(tmp_path):
    clip = clean_clip()
    lofted(clip)
    assert run(tmp_path, clip) == {}


def substitute(clip, frame, with_stoppage=True):
    """h2 (holding the ball) is replaced by h12 at `frame`; the ball goes out first if asked."""
    for n in range(frame - 10, 150):
        clip["frames"][n]["possessor"] = None
    for n in range(frame, 150):
        clip["frames"][n]["players"][1]["id"] = "h12"
    if with_stoppage:
        clip["events"].append(event("e2", frame - 10, "out_of_play", "home", x=50.0, y=30.0))
    clip["events"].append(event("e3", frame, "substitution", "home", "h2", "h12", x=50.0, y=0.0))


def test_substitution_at_a_stoppage_passes(tmp_path):
    clip = clean_clip()
    substitute(clip, 120)
    assert run(tmp_path, clip) == {}


def test_substitution_in_play_fails(tmp_path):
    clip = clean_clip()
    substitute(clip, 120, with_stoppage=False)
    assert "C3 roster" in run(tmp_path, clip)


def test_missing_file(tmp_path):
    assert "C1 files" in validate(tmp_path)


def test_an_own_goal_needs_no_shot(tmp_path):
    clip = clean_clip()
    clip["events"].append(event("e2", 40, "goal", "away", None, x=50.0, y=30.0))
    clip["meta"]["score"]["away"] = 1
    assert "C8 event order" not in run(tmp_path, clip)


def test_a_rebound_off_the_crossbar_is_not_judged_as_free_flight(tmp_path):
    clip = clean_clip()
    lofted(clip)
    for n in range(PASS_AT, PASS_AT + 26):
        clip["frames"][n]["ball"]["x"] += 64.6 - 40  # the same flight, ending at the far goal line
    clip["frames"][PASS_AT + 10]["ball"]["z"] += 0.4
    assert "P5 ball flight" in run(tmp_path, clip)  # in midfield: a defect
    for n in range(PASS_AT, PASS_AT + 26):
        clip["frames"][n]["ball"]["x"] = 104.8  # the same heights, at the goal mouth
    problems = run(tmp_path, clip)
    assert "P5 ball flight" not in problems


def test_a_ball_within_reach_can_be_touched_whichever_way_it_moves(tmp_path):
    clip = clean_clip()
    for f in clip["frames"]:
        f["players"][2].update(x=39.6, y=30.0)
    clip["events"].append(event("e2", PASS_AT + 1, "deflection", "away", "a1", x=40.4))
    clip["events"].append(event("e3", PASS_AT + 2, "deflection", "away", "a1", x=40.8))
    problems = run(tmp_path, clip)
    assert "P14 touch possible" not in problems


def test_a_first_time_shot_by_a_player_within_reach_of_the_ball_passes(tmp_path):
    clip = clean_clip()  # the pass reaches h2 at frame PASS_AT + 25; a frame earlier it is 0.4 m short
    clip["events"].append(event("e2", PASS_AT + 24, "shot", "home", "h2", x=49.6, y=30.0,
                                outcome="off_target", ball_speed_kmh=80.0))
    assert "C8 event order" not in run(tmp_path, clip)


def test_a_pass_by_a_player_near_a_ball_someone_else_holds_fails(tmp_path):
    clip = clean_clip()  # h1 has the ball until PASS_AT; a1 steps right next to it
    for n in range(PASS_AT - 2, PASS_AT + 1):
        clip["frames"][n]["players"][2].update(x=40.9, y=30.0)
    clip["events"][0]["player"] = "a1"
    clip["events"][0]["team"] = "away"
    assert "C8 event order" in run(tmp_path, clip)
