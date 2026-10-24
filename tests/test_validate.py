"""Each contract check gets a clean clip that passes and planted defects that must fail it.
Check IDs match docs/GROUNDING.md."""

import json
import math

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


def receiver_of_a_failed_pass(c):
    c["events"][0]["outcome"] = "fail"


def interceptor_on_his_own_team(c):
    c["events"][0].update(receiver=None, outcome="fail", interceptor="h2")


def intended_for_an_opponent(c):
    c["events"][0]["intended"] = "a1"


def intercepted_pass_completed(c):
    c["events"][0]["interceptor"] = "a1"


def interception_of_a_pass_cut_out_by_someone_else(c):
    c["events"][0].update(receiver=None, outcome="fail", interceptor="a1")
    c["events"].append(event("e2", 40, "interception", "home", "h2", x=50.0))


def receiver_on_the_other_team(c):
    c["events"][0]["receiver"] = "a1"


def deflector_on_his_own_team(c):
    c["events"][0].update(receiver=None, outcome="fail", deflected_by="h2")


def deflected_pass_completed(c):
    c["events"][0]["deflected_by"] = "a1"


def pass_both_won_and_only_touched(c):
    c["events"][0].update(receiver=None, outcome="fail", interceptor="a1", deflected_by="a1")


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
    (receiver_of_a_failed_pass, "C4 event players"),
    (interceptor_on_his_own_team, "C4 event players"),
    (intended_for_an_opponent, "C4 event players"),
    (intercepted_pass_completed, "C4 event players"),
    (interception_of_a_pass_cut_out_by_someone_else, "C8 event order"),
    (receiver_on_the_other_team, "C4 event players"),
    (deflector_on_his_own_team, "C4 event players"),
    (deflected_pass_completed, "C4 event players"),
    (pass_both_won_and_only_touched, "C4 event players"),
    (score_disagrees, "C9 score"),
])
def test_planted_defect_fails(tmp_path, defect, check):
    clip = clean_clip()
    defect(clip)
    assert check in run(tmp_path, clip)


# --- legal cases that must pass ----------------------------------------------------------------

def test_an_interception_of_the_pass_its_interceptor_won_passes(tmp_path):
    """C8 reads who won a failed pass from `interceptor`; the pass has no receiver."""
    clip = clean_clip()
    for f in clip["frames"]:  # a1 stands where the pass was going and takes it
        f["players"][1].update(x=50.0, y=45.0)
        f["players"][2].update(x=50.0, y=30.0)
        if f["possessor"] == "h2":
            f["possessor"] = "a1"
    clip["events"][0].update(receiver=None, outcome="fail", interceptor="a1")
    clip["events"].append(event("e2", PASS_AT + 25, "interception", "away", "a1", x=50.0))
    assert run(tmp_path, clip) == {}


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


# Where a jolt in flight happens, relative to the goal at x = 105 (its net as the renderer draws
# it: 2 m deep, its back 2 m high, the roof sloping down to it from the 2.44 m crossbar), and
# whether the net can be what stopped the ball there. The engine holds a ball against the net with
# its centre a radius (0.11 m) from the back or a side, or its top at the roof, from inside; from
# outside, its centre a radius off the back or a side, or its lowest point on the roof.
NET_CASES = [
    ("in the middle of the goal", 105.9, 34.0, None, False),
    ("against the back of the net", 106.89, 34.0, None, True),
    ("against the side netting", 105.9, 37.55, None, True),
    ("against the net's roof", 106.0, 34.0, 2.0, True),  # roof 2.22 m there, less the ball's 0.22
    ("a few centimetres off the back of the net", 106.85, 34.0, None, False),
    ("against the back of the net from behind it", 107.11, 34.0, None, True),  # lesson 200
    ("against the side netting from beside the goal", 105.9, 37.77, None, True),
    ("lying on the net's roof", 106.0, 34.0, 2.22, True),  # its lowest point on the roof
    ("a few centimetres behind the back of the net", 107.16, 34.0, None, False),
    ("a few centimetres beside the side netting", 105.9, 37.82, None, False),
    ("beside the goal, above the side netting", 105.9, 37.77, 2.5, False),
    ("above the roof", 106.0, 34.0, 2.5, False),
    ("4 m above the back of the net", 106.89, 34.0, 4.8, False),
]


@pytest.mark.parametrize(("where", "x", "y", "z", "contact"), NET_CASES)
def test_a_ball_the_net_stops_is_not_judged_as_free_flight(tmp_path, where, x, y, z, contact):
    """Lessons 184 and 200: a ball touching a goal's net, inside it or out, meets a contact, as at
    the woodwork. The same jolt anywhere the net cannot be touching the ball is a defect. The ball
    flies in the middle of the goal; on the jolt's frame it is where the case puts it."""
    clip = clean_clip()
    lofted(clip)
    for n in range(PASS_AT, PASS_AT + 26):
        clip["frames"][n]["ball"]["x"], clip["frames"][n]["ball"]["y"] = 105.9, 34.0
    jolt = clip["frames"][PASS_AT + 10]["ball"]
    jolt["x"], jolt["y"] = x, y
    jolt["z"] = z if z is not None else jolt["z"] - 0.4
    assert ("P5 ball flight" in run(tmp_path, clip)) is not contact, where


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


# --- a window cut from a longer match (a rendered clip) ----------------------------------------


def fails(problems: dict, check: str, text: str) -> bool:
    """The check failed for the reason named, not for another problem filed under the same key."""
    return any(text in m for m in problems.get(check, []))


def cut(clip: dict, first: int, last: int) -> dict:
    """Keep frames first..last and the events in them, as the renderer cuts a clip from a match."""
    clip["frames"] = [f for f in clip["frames"] if first <= f["frame"] <= last]
    clip["events"] = [e for e in clip["events"] if first <= e["frame"] <= last]
    clip["meta"]["window"] = {"first_frame": first, "last_frame": last}
    return clip


def intercepted_clip() -> dict:
    """The pass is cut out by a1, who stands where it was going (as in the interception test above)."""
    clip = clean_clip()
    for f in clip["frames"]:
        f["players"][1].update(x=50.0, y=45.0)
        f["players"][2].update(x=50.0, y=30.0)
        if f["possessor"] == "h2":
            f["possessor"] = "a1"
    clip["events"][0].update(receiver=None, outcome="fail", interceptor="a1")
    clip["events"].append(event("e2", PASS_AT + 25, "interception", "away", "a1", x=50.0))
    return clip


def test_a_pass_still_travelling_when_the_window_ends_passes(tmp_path):
    """C7: the ball reaches (50, 30) at frame 30, after the cut; what it did next is not in the clip."""
    assert run(tmp_path, cut(clean_clip(), 0, 20)) == {}


def test_the_same_cut_pass_fails_in_a_clip_that_is_not_a_window(tmp_path):
    clip = cut(clean_clip(), 0, 20)
    del clip["meta"]["window"]
    assert fails(run(tmp_path, clip), "C7 ball path", "ball never reaches")


def test_a_pass_received_short_of_its_end_point_fails_in_a_window(tmp_path):
    """The ball reaches h2 at x=50 and he holds it to the last frame, so it never gets to x=80."""
    clip = clean_clip()
    clip["events"][0]["end_x"] = 80.0
    assert fails(run(tmp_path, cut(clip, 0, 149)), "C7 ball path", "ball never reaches")


def test_a_loose_pass_moving_away_from_its_end_point_at_the_cut_fails(tmp_path):
    """Nobody has it at the last frame (x=46), but it went by (45, 36), 6 m wide, and is moving away."""
    clip = clean_clip()
    clip["events"][0].update(end_x=45.0, end_y=36.0)
    assert fails(run(tmp_path, cut(clip, 0, 20)), "C7 ball path", "ball never reaches")


def test_a_pass_that_never_arrives_before_a_later_event_in_the_window_fails(tmp_path):
    """C7 is withheld only at the cut: a later on-ball event inside the window still bounds the pass."""
    clip = clean_clip()
    clip["events"][0]["end_x"] = 80.0
    clip["events"].append(event("e2", 60, "tackle", "away", "a1", x=50.0))
    assert fails(run(tmp_path, cut(clip, 0, 149)), "C7 ball path", "ball never reaches")


def test_an_interception_whose_pass_was_before_the_window_passes(tmp_path):
    assert run(tmp_path, cut(intercepted_clip(), 10, 149)) == {}


def test_an_interception_while_a_player_holds_the_ball_in_the_window_fails(tmp_path):
    """No pass in the window, but h1 holds the ball for 120 frames before a1 'intercepts' it."""
    clip = clean_clip()
    clip["events"] = []
    for f in clip["frames"]:
        f["ball"]["x"], f["possessor"] = 40.0, "h1"
        f["players"][2].update(x=40.5, y=30.0)
    for f in clip["frames"][120:]:
        f["ball"]["x"], f["possessor"] = 40.5, "a1"
    clip["events"].append(event("e2", 120, "interception", "away", "a1", x=40.0))
    assert fails(run(tmp_path, cut(clip, 1, 149)), "C8 event order", "intercepted no failed pass")


def ball_rolling_from_the_first_frame(clip: dict) -> dict:
    """Nobody holds the ball; it rolls 0.2 m a frame along y=30 from frame 0. a1 stands at x=50, where it
    passes at frame 100, and takes it."""
    for f in clip["frames"]:
        f["ball"]["x"], f["possessor"] = 30.0 + 0.2 * f["frame"], "a1" if f["frame"] >= 100 else None
        f["players"][2].update(x=50.0, y=30.0)
    clip["events"] = [event("e2", 100, "interception", "away", "a1", x=50.0)]
    return clip


def test_a_window_from_the_kickoff_has_nothing_before_it(tmp_path):
    """A window that opens at frame 0 starts with the match, so a loose, moving ball there is no pass
    from before the cut: the interception is judged."""
    problems = run(tmp_path, cut(ball_rolling_from_the_first_frame(clean_clip()), 0, 149))
    assert fails(problems, "C8 event order", "intercepted no failed pass")


def test_the_same_rolling_ball_in_a_window_opening_after_the_kickoff_passes_c8(tmp_path):
    """The same frames from frame 1: the pass may have been struck before the cut."""
    problems = run(tmp_path, cut(ball_rolling_from_the_first_frame(clean_clip()), 1, 149))
    assert not fails(problems, "C8 event order", "intercepted no failed pass")


def test_an_interception_from_nowhere_in_a_window_that_holds_the_pass_fails(tmp_path):
    clip = clean_clip()
    interception_from_nowhere(clip)
    assert fails(run(tmp_path, cut(clip, 0, 149)), "C8 event order", "intercepted no failed pass")


def loose(clip: dict, first: int, last: int) -> dict:
    """Nobody holds the ball from frame first to frame last."""
    for f in clip["frames"]:
        if first <= f["frame"] <= last:
            f["possessor"] = None
    return clip


def shot_running_in(clip: dict) -> dict:
    """A shot struck before frame 20 runs from (80, 34) at 25 m/s into the goal at frame 45, nobody on
    it; in the net it creeps on 0.01 m a frame."""
    loose(clip, 20, 149)
    for f in clip["frames"][20:]:
        n = f["frame"]
        f["ball"]["x"] = 80 + 25 * min(n - 20, 25) / FPS + (0.01 * (n - 45) if n > 45 else 0.0)
        f["ball"]["y"] = 34.0
    clip["events"].append(event("e2", 45, "goal", "home", "h2", x=105.0, y=34.0))
    clip["meta"]["score"]["home"] = 1
    return clip


def test_a_goal_whose_shot_was_before_the_window_passes(tmp_path):
    """The shot was struck before the cut; the ball runs loose into the goal from the first frame."""
    assert run(tmp_path, cut(shot_running_in(clean_clip()), 20, 149)) == {}


def test_a_goal_without_a_shot_while_a_player_holds_the_ball_in_the_window_fails(tmp_path):
    """h2 has held the ball since frame 30, inside the window, so no shot before the cut is in flight."""
    clip = clean_clip()
    goal_without_shot(clip)
    assert fails(run(tmp_path, cut(clip, 20, 149)), "C8 event order", "without a scoring shot")


def test_a_substitution_whose_stoppage_was_before_the_window_passes(tmp_path):
    """The ball went dead before the cut: nobody holds it from the first frame to the substitution."""
    clip = clean_clip()
    substitute(clip, 120, with_stoppage=False)
    assert run(tmp_path, cut(loose(clip, 100, 149), 100, 149)) == {}


def test_a_substitution_while_a_player_holds_the_ball_in_the_window_fails(tmp_path):
    """No event before it in the window, but h2 holds the ball until frame 110: the ball is in play."""
    clip = clean_clip()
    substitute(clip, 120, with_stoppage=False)
    assert fails(run(tmp_path, cut(clip, 100, 149)), "C3 roster", "substitution while the ball is in play")


def test_a_substitution_in_play_inside_a_window_fails(tmp_path):
    clip = clean_clip()
    substitute(clip, 120, with_stoppage=False)
    assert fails(run(tmp_path, cut(clip, 0, 149)), "C3 roster", "substitution while the ball is in play")


def test_a_window_that_does_not_match_its_frames_fails(tmp_path):
    clip = cut(clean_clip(), 0, 20)
    clip["meta"]["window"]["first_frame"] = 3
    assert fails(run(tmp_path, clip), "C1 files", "does not match the frames")


def dead_ball_clip(teleport_at: int | None = None) -> dict:
    """The ball goes out at frame 100 and is placed 44.5 m away for a goal kick at frame 110."""
    clip = clean_clip()
    for n in range(100, 150):
        clip["frames"][n]["possessor"] = None
    for n in range(110, 150):
        clip["frames"][n]["ball"]["x"] = 5.5
    if teleport_at is not None:  # the ball jumps 20 m in one frame while in play
        clip["frames"][teleport_at]["ball"]["x"] += 20.0
    clip["events"].append(event("e2", 100, "out_of_play", "home", x=50.0))
    clip["events"].append(event("e3", 110, "set_piece", "away", "a1", x=5.5))
    return clip


def test_a_window_that_opens_on_a_dead_ball_may_place_a_new_one(tmp_path):
    """P3: the ball went out before the cut; the restart in the window places a new one."""
    assert run(tmp_path, cut(dead_ball_clip(), 105, 149)) == {}


def test_a_ball_placed_with_no_stoppage_in_a_whole_clip_fails(tmp_path):
    clip = cut(dead_ball_clip(), 105, 149)
    del clip["meta"]["window"]
    assert fails(run(tmp_path, clip), "P3 ball speed", "ball moved at")


def test_a_ball_too_fast_before_a_stoppage_in_the_window_fails(tmp_path):
    """The window holds the stoppage, so the ball was in play until then and P3 judges it."""
    assert fails(run(tmp_path, cut(dead_ball_clip(teleport_at=60), 0, 149)), "P3 ball speed", "ball moved at")


def test_a_ball_too_fast_before_a_goal_and_its_kickoff_in_the_window_fails(tmp_path):
    """A goal is a stoppage too: the kickoff after it does not mean the window opened on a dead ball."""
    clip = clean_clip()
    clip["frames"][60]["ball"]["x"] += 20.0
    clip["events"].append(event("e2", 100, "goal", "home", None, x=105.0, y=34.0))
    clip["events"].append(event("e3", 110, "kickoff", "away", "a1", x=52.5, y=34.0))
    clip["meta"]["score"]["home"] = 1
    assert fails(run(tmp_path, cut(clip, 0, 149)), "P3 ball speed", "ball moved at")


def drifts_toward_80(clip: dict, possessor: str | None) -> dict:
    """After h2 gets the ball at frame 30 it keeps moving toward x=80, 0.05 m a frame, to the last frame."""
    for f in clip["frames"][31:]:
        x = 50.0 + 0.05 * (f["frame"] - 30)
        f["ball"]["x"], f["possessor"] = x, possessor
        if possessor:
            f["players"][1]["x"] = x
    return clip


def test_a_pass_dribbled_toward_its_end_point_at_the_cut_fails(tmp_path):
    """C7: h2 has the ball at the last frame; a held ball is no longer the pass, even closing on (80, 30)."""
    clip = drifts_toward_80(clean_clip(), "h2")
    clip["events"][0]["end_x"] = 80.0
    assert fails(run(tmp_path, cut(clip, 0, 149)), "C7 ball path", "ball never reaches")


def test_a_pass_cut_off_by_a_later_event_in_the_window_fails_even_if_loose_at_the_cut(tmp_path):
    """C7: a tackle at frame 60 ends the pass inside the window. Nobody ever holds the ball, and at the
    cut it is loose and heading for (80, 30), but it is no longer the pass."""
    clip = loose(drifts_toward_80(clean_clip(), None), PASS_AT, 149)
    clip["events"][0]["end_x"] = 80.0
    clip["events"].append(event("e2", 60, "tackle", "away", "a1", x=51.5))
    assert fails(run(tmp_path, cut(clip, 0, 149)), "C7 ball path", "ball never reaches")


def test_a_substitution_after_an_in_play_event_in_the_window_fails(tmp_path):
    """C3: the ball is loose from the cut, but a deflection inside the window shows it was in play."""
    clip = clean_clip()
    substitute(clip, 120, with_stoppage=False)
    clip["events"].append(event("e4", 105, "deflection", "away", "a1", x=50.0))
    clip["events"].sort(key=lambda e: e["frame"])
    problems = run(tmp_path, cut(loose(clip, 100, 149), 100, 149))
    assert fails(problems, "C3 roster", "substitution while the ball is in play")


def restart_after_a_jump(clip: dict) -> dict:
    """The ball jumps 20 m at frame 60; a set piece at frame 140 is the window's first restart."""
    clip["frames"][60]["ball"]["x"] += 20.0
    clip["events"].append(event("e9", 140, "set_piece", "home", "h2", x=50.0))
    return clip


def test_a_jump_while_a_player_holds_the_ball_before_the_first_restart_fails(tmp_path):
    """P3: h2 holds the ball from the cut, so the window did not open on a dead ball."""
    clip = restart_after_a_jump(clean_clip())
    assert fails(run(tmp_path, cut(clip, 40, 149)), "P3 ball speed", "ball moved at")


def test_a_jump_after_an_in_play_event_before_the_first_restart_fails(tmp_path):
    """P3: nobody holds the ball, but a deflection at frame 50 shows it was in play."""
    clip = restart_after_a_jump(loose(clean_clip(), 40, 149))
    clip["events"].append(event("e4", 50, "deflection", "away", "a1", x=50.0))
    clip["events"].sort(key=lambda e: e["frame"])
    assert fails(run(tmp_path, cut(clip, 40, 149)), "P3 ball speed", "ball moved at")


# --- R1's review: defects whose evidence is inside the window, and the mutants they kill ------


def test_a_pass_heading_wide_of_its_end_point_at_the_cut_fails(tmp_path):
    """C7: the ball leaves h1 at 60 degrees to the line to (50, 30) and never comes within 2.5 m of it.
    At the last frame it is loose and still getting closer, but its path misses the end point."""
    clip = clean_clip()
    a = math.radians(60)
    for f in clip["frames"][PASS_AT:]:
        d = min((f["frame"] - PASS_AT) / 25, 1.0) * 10
        f["ball"]["x"], f["ball"]["y"], f["possessor"] = 40 + d * math.cos(a), 30 + d * math.sin(a), None
    assert fails(run(tmp_path, cut(clip, 0, 12)), "C7 ball path", "ball never reaches")


def test_a_pass_held_by_its_receiver_then_let_go_toward_the_end_point_fails(tmp_path):
    """C7: h2 holds the ball from frame 30 to 99, inside the window, then it rolls on toward x=80 with
    nobody on it. The pass was over when h2 held it."""
    clip = loose(drifts_toward_80(clean_clip(), "h2"), 100, 149)
    clip["events"][0]["end_x"] = 80.0
    assert fails(run(tmp_path, cut(clip, 0, 149)), "C7 ball path", "ball never reaches")


def test_a_pass_that_stopped_short_and_lies_loose_at_the_cut_fails(tmp_path):
    """C7: the pass to (80, 30) stops dead at x=50 at frame 30 and lies there, nobody on it, to the cut."""
    clip = loose(clean_clip(), 30, 149)
    clip["events"][0]["end_x"] = 80.0
    assert fails(run(tmp_path, cut(clip, 0, 149)), "C7 ball path", "ball never reaches")


def test_a_substitution_followed_by_open_play_without_a_restart_fails(tmp_path):
    """C3: loose from the cut to the substitution at 120, then h12 takes the ball at 130 and passes at
    140 with no restart between: the ball was never dead (Law 3)."""
    clip = clean_clip()
    substitute(clip, 120, with_stoppage=False)
    for f in clip["frames"][130:]:
        f["possessor"] = "h12"
    clip["events"].append(event("e4", 140, "pass", "home", "h12", x=50.0, outcome="fail"))
    problems = run(tmp_path, cut(loose(clip, 100, 129), 100, 149))
    assert fails(problems, "C3 roster", "substitution while the ball is in play")


def test_an_interception_of_a_ball_at_rest_since_the_cut_fails(tmp_path):
    """C8: the ball lies still at (50, 30), nobody on it, from the first frame (40) to frame 140, when
    a1 'intercepts' it. A ball at rest for four seconds is no pass from before the cut."""
    clip = loose(clean_clip(), 30, 149)
    for f in clip["frames"]:
        f["players"][2].update(x=50.5, y=30.0)
    for f in clip["frames"][140:]:
        f["possessor"] = "a1"
    clip["events"].append(event("e2", 140, "interception", "away", "a1", x=50.0))
    assert fails(run(tmp_path, cut(clip, 40, 149)), "C8 event order", "intercepted no failed pass")


def test_a_goal_from_a_ball_at_rest_since_the_cut_fails(tmp_path):
    """C8: the ball lies still at (50, 30), 55 m out, from the first frame to the goal at frame 40."""
    clip = loose(clean_clip(), 20, 149)
    goal_without_shot(clip)
    assert fails(run(tmp_path, cut(clip, 20, 149)), "C8 event order", "without a scoring shot")


def test_an_interception_of_a_successful_pass_at_the_start_of_the_window_fails(tmp_path):
    """C8: the window opens on h1's pass to h2, which succeeds; a1 'intercepts' at frame 20."""
    clip = clean_clip()
    for f in clip["frames"]:
        f["players"][2].update(x=46.0, y=30.0)
    clip["events"].append(event("e2", 20, "interception", "away", "a1", x=46.0))
    assert fails(run(tmp_path, cut(clip, 5, 149)), "C8 event order", "intercepted no failed pass")


def test_the_goal_after_someone_elses_shot_in_the_window_is_judged_itself(tmp_path):
    """C8: the shot by h1 in the window is not h2's scoring shot, so the goal itself must fail."""
    clip = shot_running_in(clean_clip())
    clip["events"].append(event("e3", 30, "shot", "home", "h1", outcome="off_target", x=86.0, y=34.0))
    clip["events"].sort(key=lambda e: e["frame"])
    assert fails(run(tmp_path, cut(clip, 20, 149)), "C8 event order", "goal by h2 without a scoring shot")


def test_an_interception_from_a_player_dribbling_since_the_cut_fails(tmp_path):
    """C8: the ball moves every frame, but h1 has it at his feet from the first frame: no pass in flight."""
    clip = clean_clip()
    clip["events"] = []
    for f in clip["frames"]:
        x = 30.0 + 0.1 * f["frame"]
        f["ball"]["x"], f["possessor"] = x, "a1" if f["frame"] >= 120 else "h1"
        f["players"][0]["x"] = x
        f["players"][2].update(x=42.0, y=30.0)
    clip["events"].append(event("e2", 120, "interception", "away", "a1", x=42.0))
    assert fails(run(tmp_path, cut(clip, 1, 149)), "C8 event order", "intercepted no failed pass")


def test_a_pass_running_away_from_its_end_point_at_the_cut_fails(tmp_path):
    """C7: the pass is labelled to (35, 30), behind h1, but the ball runs toward x=50, straight away
    from it; carried on, its path only meets the end point behind it."""
    clip = clean_clip()
    clip["events"][0]["end_x"] = 35.0
    assert fails(run(tmp_path, cut(clip, 0, 20)), "C7 ball path", "ball never reaches")


def test_a_substitution_then_open_play_then_a_restart_fails(tmp_path):
    """C3: h12 plays the ball at 140, before the first restart (a set piece at 145), so it was in play."""
    clip = clean_clip()
    substitute(clip, 120, with_stoppage=False)
    for f in clip["frames"][130:]:
        f["possessor"] = "h12"
    clip["events"].append(event("e4", 140, "pass", "home", "h12", x=50.0, outcome="fail"))
    clip["events"].append(event("e5", 145, "set_piece", "home", "h12", x=50.0))
    problems = run(tmp_path, cut(loose(clip, 100, 129), 100, 149))
    assert fails(problems, "C3 roster", "substitution while the ball is in play")


def test_a_pass_heading_4m_wide_of_its_end_point_at_the_cut_fails(tmp_path):
    """C7: the ball is aimed at (50, 34), so its line passes 4 m from (50, 30): outside NEAR_M (2.5),
    inside twice it."""
    clip = clean_clip()
    a = math.atan2(4.0, 10.0)
    for f in clip["frames"][PASS_AT:]:
        d = min((f["frame"] - PASS_AT) / 25, 1.0) * 10
        f["ball"]["x"], f["ball"]["y"], f["possessor"] = 40 + d * math.cos(a), 30 + d * math.sin(a), None
    assert fails(run(tmp_path, cut(clip, 0, 12)), "C7 ball path", "ball never reaches")


def test_an_interception_of_a_ball_at_rest_whose_stored_position_jitters_fails(tmp_path):
    """C8: the ball lies at rest at (50, 30), but each stored position rounds to the nearest
    millimetre, so x and y can each flip by 1 mm between frames (about 1.4 mm in all). That is
    rounding, not flight, so the interception at 140 is judged."""
    clip = loose(clean_clip(), 30, 149)
    for f in clip["frames"]:
        f["players"][2].update(x=50.5, y=30.0)
        if f["frame"] >= 40:
            step = 0.001 * (f["frame"] % 2)
            f["ball"]["x"], f["ball"]["y"] = 50.0 + step, 30.0 + step
    for f in clip["frames"][140:]:
        f["possessor"] = "a1"
    clip["events"].append(event("e2", 140, "interception", "away", "a1", x=50.0))
    assert fails(run(tmp_path, cut(clip, 40, 149)), "C8 event order", "intercepted no failed pass")


def test_an_interception_of_a_slow_pass_from_before_the_cut_passes_c8(tmp_path):
    """A pass struck before the cut, nearly spent: the ball rolls 1 cm a frame (0.25 m/s), far more than
    rounding can show, into a1's path at frame 100. It is still in flight, so C8 is withheld."""
    clip = ball_rolling_from_the_first_frame(clean_clip())
    for f in clip["frames"]:
        f["ball"]["x"] = 49.0 + 0.01 * f["frame"]
    problems = run(tmp_path, cut(clip, 1, 149))
    assert not fails(problems, "C8 event order", "intercepted no failed pass")


def test_an_interception_of_a_ball_at_rest_jittering_on_all_three_axes_fails(tmp_path):
    """C8: rounding can flip x, y and z by 1 mm each between frames (sqrt(3) mm in space): still at rest."""
    clip = loose(clean_clip(), 30, 149)
    for f in clip["frames"]:
        f["players"][2].update(x=50.5, y=30.0)
        if f["frame"] >= 40:
            step = 0.001 * (f["frame"] % 2)
            f["ball"]["x"], f["ball"]["y"], f["ball"]["z"] = 50.0 + step, 30.0 + step, step
    for f in clip["frames"][140:]:
        f["possessor"] = "a1"
    clip["events"].append(event("e2", 140, "interception", "away", "a1", x=50.0))
    assert fails(run(tmp_path, cut(clip, 40, 149)), "C8 event order", "intercepted no failed pass")


def test_a_ball_rolling_2mm_a_frame_is_in_flight_for_c8(tmp_path):
    """C8: 2 mm a frame on one axis (5 cm/s) is more than rounding can show (sqrt(3) mm): still moving."""
    clip = ball_rolling_from_the_first_frame(clean_clip())
    for f in clip["frames"]:
        f["ball"]["x"] = round(49.0 + 0.002 * f["frame"], 3)
    problems = run(tmp_path, cut(clip, 1, 149))
    assert not fails(problems, "C8 event order", "intercepted no failed pass")


def struck_away_from_its_end_point(strike: int) -> dict:
    """h1 dribbles toward x=50 and, at frame `strike`, plays a pass to (10, 20), behind him and wide:
    the ball's motion up to the strike points 45 degrees off the end point."""
    clip = clean_clip()
    for f in clip["frames"]:
        x = 40.0 + 0.1 * min(f["frame"], strike)
        f["ball"]["x"], f["players"][0]["x"] = x, x
        f["possessor"] = "h1" if f["frame"] < strike else None
        if f["frame"] > strike:  # the struck ball runs back toward (10, 20)
            u = (f["frame"] - strike) * 0.6
            f["ball"]["x"], f["ball"]["y"] = 40.0 + 0.1 * strike - u, 30.0 - u / 3
    x = 40.0 + 0.1 * strike
    clip["events"] = [event("e1", strike, "pass", "home", "h1", x=x, end_x=10.0, end_y=20.0,
                            outcome="fail", ball_speed_kmh=54.0)]
    return clip


def test_a_pass_struck_on_the_windows_last_frame_passes_c7(tmp_path):
    """C7: none of the pass's flight is in the clip; its last motion is h1's dribble, not the kick."""
    assert not fails(run(tmp_path, cut(struck_away_from_its_end_point(60), 0, 60)), "C7 ball path",
                     "ball never reaches")


def test_a_pass_struck_one_frame_before_the_windows_end_is_judged(tmp_path):
    """C7: one frame of flight is in the clip, so the pass is judged: here the ball has gone the
    wrong way, away from (10, 20)."""
    clip = struck_away_from_its_end_point(59)
    for f in clip["frames"][60:]:  # the struck ball runs on toward x=50, away from the end point
        f["ball"]["x"], f["ball"]["y"] = 45.9 + 0.6 * (f["frame"] - 59), 30.0
    assert fails(run(tmp_path, cut(clip, 0, 60)), "C7 ball path", "ball never reaches")


def test_a_pass_struck_on_the_last_frame_of_a_whole_clip_is_still_judged(tmp_path):
    """C7: without a window there is no cut, so the last-frame exemption does not apply."""
    clip = cut(struck_away_from_its_end_point(60), 0, 60)
    del clip["meta"]["window"]
    assert fails(run(tmp_path, clip), "C7 ball path", "ball never reaches")


# --- a broadcast cut through a dead ball (ninety/render/edit.py) --------------------------------


def restart_clip() -> dict:
    """h2 lets the ball run out at frame 40 and it lies dead; a1 walks 15 m to take the restart,
    and at frame 130 the set piece is his (the ball placed at his spot). The picture may cut from
    frame 60 to frame 120: a1 is somewhere else after the cut, and that is not running."""
    clip = clean_clip()
    for f in clip["frames"]:
        n = f["frame"]
        if n >= 40:
            f["possessor"] = "a1" if n >= 130 else None
        # a1 sets off at frame 41 and is at his spot by frame 129 (smoothstep: up to 6.4 m/s and
        # 7.3 m/s², inside P1 and P2); most of the walk is inside the cut.
        u = min(max((n - 41) / 88, 0.0), 1.0)
        f["players"][2].update(x=75.0 - 15.0 * u * u * (3 - 2 * u), y=40.0)
        if n >= 130:
            f["ball"].update(x=60.0, y=40.0)
    clip["events"] += [event("e2", 40, "out_of_play", "home", x=50.0),
                       event("e3", 130, "set_piece", "away", "a1", x=60.0, y=40.0)]
    return clip


def cut_away(clip: dict, first: int, last: int, record: bool = True) -> dict:
    """Leave out frames first..last as the broadcast does, and record it in meta.json."""
    clip["frames"] = [f for f in clip["frames"] if not first <= f["frame"] <= last]
    if record:
        clip["meta"]["cuts"] = [{"first_frame": first, "last_frame": last}]
    return clip


def test_a_dead_ball_clip_without_a_cut_passes(tmp_path):
    assert run(tmp_path, restart_clip()) == {}


def test_a_recorded_cut_through_a_dead_ball_passes(tmp_path):
    """The players are elsewhere after the cut; that is the edit, not a 15 m jump in a frame."""
    assert run(tmp_path, cut_away(restart_clip(), 60, 120)) == {}


def test_a_gap_in_the_frames_that_no_cut_records_fails(tmp_path):
    problems = run(tmp_path, cut_away(restart_clip(), 60, 120, record=False))
    assert fails(problems, "C2 frame order", "frame 121 at position 60, after frame 59")


def test_a_recorded_cut_that_is_not_a_gap_in_the_frames_fails(tmp_path):
    clip = restart_clip()
    clip["meta"]["cuts"] = [{"first_frame": 60, "last_frame": 120}]
    assert fails(run(tmp_path, clip), "C2 frame order", "is not a gap between two frames")


def test_a_recorded_cut_of_other_frames_than_the_gap_fails(tmp_path):
    clip = cut_away(restart_clip(), 60, 120)
    clip["meta"]["cuts"] = [{"first_frame": 60, "last_frame": 119}]
    problems = run(tmp_path, clip)
    assert fails(problems, "C2 frame order", "frame 121 at position 60")
    assert fails(problems, "C2 frame order", "is not a gap between two frames")


def test_a_cut_through_play_fails(tmp_path):
    """The pass from frame 5 is in flight until frame 30, before any stoppage: cutting there hides play."""
    problems = run(tmp_path, cut_away(restart_clip(), 10, 20))
    assert fails(problems, "C2 frame order", "no stoppage before it or no restart after it")


def test_a_cut_after_the_restart_fails(tmp_path):
    problems = run(tmp_path, cut_away(restart_clip(), 132, 140))
    assert fails(problems, "C2 frame order", "no stoppage before it or no restart after it")


def test_a_cut_over_an_event_fails(tmp_path):
    """Nothing that happened is cut: the event would be on no frame of the clip."""
    clip = restart_clip()
    clip["events"].append(event("e4", 90, "pressure", "away", "a1", x=67.5, y=40.0))
    assert fails(run(tmp_path, cut_away(clip, 60, 120)), "C2 frame order", "hides e4 pressure")


def test_a_cut_that_hides_the_restart_fails(tmp_path):
    """The set piece at 130 is inside the cut: no restart is shown after it."""
    problems = run(tmp_path, cut_away(restart_clip(), 60, 135))
    assert fails(problems, "C2 frame order", "no stoppage before it or no restart after it")


def test_a_cut_in_a_window_opened_on_a_dead_ball_fails(tmp_path):
    """Coordinator decision (Oct 20): a cut shows the ball dead at both ends, its stoppage and its
    restart both in the clip. A window opened after the stoppage shows only the restart: before, C2
    took a loose ball from the window's first frame for a dead one, and a window of open play with
    a gap and no event at all passed (the independent review's planted clips)."""
    problems = run(tmp_path, cut_away(cut(restart_clip(), 45, 149), 60, 120))
    assert fails(problems, "C2 frame order", "no stoppage before it or no restart after it")
    clip = cut(restart_clip(), 45, 149)
    clip["events"] = [e for e in clip["events"] if e["frame"] < 45]  # a window with no event in it
    problems = run(tmp_path, cut_away(clip, 60, 120))
    assert fails(problems, "C2 frame order", "no stoppage before it or no restart after it")


def test_play_between_the_stoppage_and_the_cut_fails(tmp_path):
    """The independent review's first planted clip: the stoppage at 40, then a pass at 50 puts the
    ball back in play before the cut. C2 used to look only at stoppages and restarts before the cut,
    so the pass was invisible to it and the cut passed."""
    clip = restart_clip()
    clip["events"].append(event("e4", 50, "pass", "away", "a1", "a2", x=75.0, y=40.0, end_x=70.0,
                                end_y=40.0, outcome="success", intended="a2"))
    problems = run(tmp_path, cut_away(clip, 60, 120))
    assert fails(problems, "C2 frame order", "the ball was in play (e4 pass)")


@pytest.mark.parametrize("stop", ["out_of_play", "foul", "offside"])
def test_a_cut_from_each_kind_of_stoppage_passes(tmp_path, stop):
    clip = restart_clip()
    for e in clip["events"]:
        if e["id"] == "e2":
            e["type"] = stop
    assert run(tmp_path, cut_away(clip, 60, 120)) == {}


@pytest.mark.parametrize("record", [
    {"first_frame": 60.0, "last_frame": 120},
    {"first_frame": True, "last_frame": 120},
    {"first_frame": "60", "last_frame": 120},
    {"first_frame": 60},
])
def test_a_cut_record_that_is_not_two_frame_numbers_fails_c1(tmp_path, record):
    """A cut given as 80.0 used to match the gap (80, ...) and pass (the independent review)."""
    clip = cut_away(restart_clip(), 60, 120)
    clip["meta"]["cuts"] = [record]
    assert fails(run(tmp_path, clip), "C1 files", "meta.json cuts must be a list of")


def test_a_ball_is_not_in_flight_across_a_cut():
    """C8's excuse for an interception or goal whose pass or shot came before a window needs the
    ball seen moving every frame: across a broadcast cut it is not seen."""
    from ninety.validate import in_flight_from_the_cut

    frames = [{"frame": n, "possessor": None, "ball": {"x": 30.0 + 0.5 * n, "y": 30.0, "z": 0.0}}
              for n in list(range(10, 20)) + list(range(60, 70))]
    assert in_flight_from_the_cut(frames, 19)
    assert not in_flight_from_the_cut(frames, 65)


def test_a_frame_that_breaks_its_schema_fails_c1(tmp_path):
    """Lesson 8: C1's frame schema had no planted defect (the independent review of #180)."""
    clip = clean_clip()
    clip["frames"][3]["ball"]["z"] = "high"
    assert fails(run(tmp_path, clip), "C1 frame schema", "frame 3:")


def test_every_check_the_validator_reports_has_a_planted_defect():
    """Lesson 8: a check that no planted defect has made fail is not known to fail at all. Every
    problem the validator can report is named in this file (the independent review of #180)."""
    import re
    from pathlib import Path

    root = Path(__file__).resolve().parent.parent
    keys = set(re.findall(r'problems\["([A-Z]\d+ [^"]+)"\]', (root / "ninety/validate.py").read_text()))
    tests = Path(__file__).read_text()
    assert keys and not {k for k in keys if f'"{k}"' not in tests}


def _down(player, fall=85.0):
    return {**player, "action": "down", "fall": fall, "fall_dir": 1.0304}


def fall_clip(late_at: int | None = None) -> dict:
    """h9 is fouled at 0.2 s. The free kick is taken at 2.8 s. Down through frame 40 (1.6 s) is
    1.2 s clear: legal at the 1 s floor, not at 1.5 s. `late_at` is one more frame left down."""
    players = [
        {"id": "h9", "team": "home", "x": 60.6, "y": 35.0, "action": "stand"},
        {"id": "a4", "team": "away", "x": 60.0, "y": 34.0, "action": "stand"},
        {"id": "h1", "team": "home", "x": 20.0, "y": 20.0, "action": "stand"},
    ]
    frames = []
    for n in range(75):
        row = [dict(p) for p in players]
        if 5 <= n <= 40 or n == late_at:
            row[0] = _down(row[0])
        frames.append({
            "frame": n, "t": n / FPS, "ball": {"x": 40.0, "y": 30.0, "z": 0.0},
            "possessor": None, "players": row,
        })
    events = [
        event("e1", 5, "foul", "away", "a4", "h9", x=60.6, y=35.0),
        event("e2", 70, "set_piece", "home", "h1", x=60.6, y=35.0),
    ]
    return {"events": events, "frames": frames, "meta": {"fps": FPS, "score": {"home": 0, "away": 0}}}


def test_a_foul_that_lets_him_up_in_time_passes(tmp_path):
    assert run(tmp_path, fall_clip()) == {}


def test_a_player_still_down_within_a_second_of_the_restart_fails(tmp_path):
    """Frame 50 is at 2.0 s, 0.8 s before the kick: inside the 1 s floor, outside a 0.5 s floor."""
    assert fails(run(tmp_path, fall_clip(50)), "P18 foul fall", "still down")


def test_a_player_down_four_tenths_before_the_restart_fails(tmp_path):
    """Frame 60 is at 2.4 s. A deeper miss than the floor, so dropping it is not how the 0.5 s
    mutant goes red: that one is the 0.8 s plant above."""
    assert fails(run(tmp_path, fall_clip(60)), "P18 foul fall", "still down")


def test_a_fall_of_zero_is_not_a_fall(tmp_path):
    """The schema allows 0. P18 does not: a fall that is present is above 0."""
    clip = fall_clip()
    clip["frames"][10]["players"][0]["fall"] = 0
    assert fails(run(tmp_path, clip), "P18 foul fall", "not degrees")


def test_a_fall_with_no_direction_fails(tmp_path):
    clip = fall_clip()
    del clip["frames"][10]["players"][0]["fall_dir"]
    assert fails(run(tmp_path, clip), "P18 foul fall", "no fall_dir")


def test_a_fall_past_flat_fails():
    """95° is already illegal in the schema, and validate() returns before P18, so the cap is
    planted on the check itself."""
    from collections import defaultdict

    from ninety.validate import check_foul_fall

    problems = defaultdict(list)
    who = _down({"id": "h9", "team": "home", "x": 60.6, "y": 35.0, "action": "stand"}, 95)
    check_foul_fall([], [{"frame": 10, "t": 0.4, "players": [who]}], problems)
    assert fails(problems, "P18 foul fall", "not degrees")


def test_a_fall_outside_zero_to_ninety_fails_the_schema():
    import json
    from pathlib import Path

    from jsonschema import Draft202012Validator

    schema = json.loads(
        (Path(__file__).resolve().parent.parent / "schemas/frame.schema.json").read_text())
    check = Draft202012Validator(schema)

    def frame(fall: float) -> dict:
        return {
            "frame": 0, "t": 0.0, "ball": {"x": 40.0, "y": 30.0, "z": 0.0},
            "players": [{"id": "h9", "team": "home", "x": 60.6, "y": 35.0, "fall": fall}],
        }

    assert list(check.iter_errors(frame(0))) == []  # the schema's minimum is 0; P18 rejects it
    assert list(check.iter_errors(frame(85))) == []
    assert list(check.iter_errors(frame(95)))  # maximum 90, not a wider cap
    assert list(check.iter_errors(frame(-1)))


def test_a_fall_without_the_down_action_fails(tmp_path):
    clip = fall_clip()
    clip["frames"][10]["players"][0]["action"] = "run"
    assert fails(run(tmp_path, clip), "P18 foul fall", "action run")
