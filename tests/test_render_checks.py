"""The render checks themselves, on hand-built frames with known answers."""

from ninety.render.camera import Camera
from ninety.render.checks import label_completeness, occlusion, projection_errors


def frame(ball_centroid_shift=0.0, ball_visibility=1.0):
    cam = Camera((52.5, -35.0, 20.0), (52.5, 34.0, 0.0), 20.0, 1280, 720)
    u, v = cam.project((52.5, 34.0, 0.11))
    players = []
    for i in range(22):
        x = 40.0 + i
        fu, fv = cam.project((x, 34.0, 0.0))
        players.append(
            {
                "id": f"p{i}",
                "team": "home",
                "x": x,
                "y": 34.0,
                "bbox": [fu - 8, fv - 60, fu + 8, fv],
                "visibility": 1.0,
                "pixels": 500,
                "foot_px": [fu, fv],
            }
        )
    return {
        "frame": 0,
        "t": 0.0,
        "image": "images/00000.jpg",
        "camera": cam.to_dict(),
        "keypoints": [],
        "ball": {
            "x": 52.5,
            "y": 34.0,
            "z": 0.0,
            "bbox": [u - 4, v - 4, u + 4, v + 4],
            "pixels": 40,
            "visibility": ball_visibility,
            "centroid_px": [u + ball_centroid_shift, v],
        },
        "players": players,
    }


def test_projection_check_catches_a_shifted_ball():
    assert projection_errors([frame()])["ball_px"]["max"] < 1e-3
    assert projection_errors([frame(2.0)])["ball_px"]["max"] > 1.9


def test_projection_check_catches_a_box_away_from_the_feet():
    f = frame()
    f["players"][0]["bbox"] = [b + 80 for b in f["players"][0]["bbox"]]
    assert projection_errors([f])["player_foot_outside_box"] == 1


def test_completeness_flags_missing_boxes_and_rows():
    f = frame()
    assert label_completeness({"frames": 1}, [f])["ok"]
    f["players"][3]["bbox"] = None
    assert not label_completeness({"frames": 1}, [f])["ok"]
    assert not label_completeness({"frames": 2}, [frame()])["ok"]


def test_occlusion_share():
    o = occlusion([frame(ball_visibility=0.2), frame(), frame(), frame()])
    assert o["ball_visibility_lt_0_5_share"] == 0.25


def test_player_height_counts_only_whole_players_and_splits_by_angle():
    f = frame()
    whole = occlusion([f])["player_height_px"]
    assert whole["n"] == 22 and whole["p05"] == whole["p95"] == 60
    cut = frame()
    for p in cut["players"][:11]:  # cut by the bottom edge: 5 px of a player is not his height
        p["bbox"] = [p["bbox"][0], 715, p["bbox"][2], 720]
    cut["camera"]["angle"] = "tight"
    h = occlusion([f, cut])["player_height_px"]
    assert h["n"] == 33 and h["p05"] == 60
    assert h["by_angle"]["main"]["n"] == 22 and h["by_angle"]["tight"]["n"] == 11


def _lying(box_from_feet, fall=85.0):
    """Player 0 drawn lying: his box placed by `box_from_feet` (dx0, dy0, dx1, dy1) about his
    projected ground point, and his frame row carrying `fall` degrees (None: no field)."""
    f = frame()
    p = f["players"][0]
    fu, fv = p["foot_px"]
    p["bbox"] = [fu + box_from_feet[0], fv + box_from_feet[1], fu + box_from_feet[2], fv + box_from_feet[3]]
    if fall is not None:
        p["fall"] = fall
    return f


# Boxes of a body lying about 1.7 m along the grass, seen from this camera (lesson 173).
TOWARD_CAMERA = (-10, -1, 10, 25)  # feet at the top of the box, the body down the image toward us
AWAY = (-10, -12, 10, 1)  # feet at the bottom, the body up the image away from us
SIDEWAYS = (-2, -6, 60, 2)  # feet at the left end, the body along the touchline


def test_an_upright_player_is_checked_as_before():
    """No `fall` field (every clip before 0.5.10, every standing player): the ground point must be
    at the bottom of the box, so a box whose top is at the feet fails exactly as it always did."""
    assert projection_errors([_lying(TOWARD_CAMERA, fall=None)])["player_foot_outside_box"] == 1
    assert projection_errors([_lying(TOWARD_CAMERA, fall=0.0)])["player_foot_outside_box"] == 1
    assert projection_errors([frame()])["player_foot_outside_box"] == 0


def test_a_fallen_player_toward_the_camera_has_his_feet_in_his_box():
    assert projection_errors([_lying(TOWARD_CAMERA)])["player_foot_outside_box"] == 0


def test_a_fallen_player_away_from_the_camera_has_his_feet_in_his_box():
    assert projection_errors([_lying(AWAY)])["player_foot_outside_box"] == 0


def test_a_fallen_player_sideways_has_his_feet_in_his_box():
    assert projection_errors([_lying(SIDEWAYS)])["player_foot_outside_box"] == 0


def test_a_fallen_players_box_away_from_his_feet_still_fails():
    """Lying down excuses where in the box the feet are, never a box that misses them."""
    shifted = tuple(d + 80 for d in TOWARD_CAMERA)
    assert projection_errors([_lying(shifted)])["player_foot_outside_box"] == 1
    beside = (25, -6, 85, 2)  # a lying body's box 25 px clear of his feet
    assert projection_errors([_lying(beside)])["player_foot_outside_box"] == 1
    above = (-10, -40, 10, -15)  # a lying body's box 15 px above his feet (added after a mutant survived)
    assert projection_errors([_lying(above)])["player_foot_outside_box"] == 1


# V6 from a high lens (lesson 212): a foot drawn reaching to the ball it touches.
HIGH = Camera((52.5, -32.0, 28.0), (30.0, 34.0, 0.0), 34.6, 1920, 1080)


def _reach_clip(ball_off: float, touch: bool, n: int = 12, at: int = 6, foot_off: float | None = None,
                lift: float = 0.0, side: float = 0.0, cut_after: int | None = None, jump: int = 500,
                part: str = "foot") -> tuple[list[dict], list]:
    """One player at (30, 5), near the touchline, lunging: his box from his head over the tracked
    point (1.6 m up, the hips down in the reach) to his foot `foot_off` metres toward the camera
    (default: at the ball, `ball_off` out); on row `at` he touches the ball (action foot) when
    `touch`. `lift` raises the whole drawn body, `side` moves it along the touchline, and
    `cut_after` puts an edit cut after that row (the match frames jump `jump`); `part` is the touch's."""
    frames = []
    bx, by = 30.0, 5.0 - ball_off
    fo = ball_off if foot_off is None else foot_off
    for i in range(n):
        head = HIGH.project((30.0 + side, 5.0, 1.6 + lift))
        sole = HIGH.project((30.0 + side, 5.0 - fo, lift))
        foot = HIGH.project((30.0 + side, 5.0, lift))
        box = [min(head[0], sole[0], foot[0]) - 6, head[1], max(head[0], sole[0], foot[0]) + 6,
               max(sole[1], foot[1])]
        num = 100 + i + (jump if cut_after is not None and i > cut_after else 0)
        frames.append({
            "frame": num, "t": num / 25, "camera": HIGH.to_dict(), "keypoints": [],
            "ball": {"x": bx, "y": by, "z": 0.0, "bbox": None, "pixels": 0, "visibility": 0.0,
                     "centroid_px": None},
            "players": [{"id": "h7", "team": "home", "x": 30.0, "y": 5.0, "vx": 1.0, "vy": 0.0,
                         "heading": -1.5708, "action": part if touch and i == at else "walk",
                         "bbox": box, "visibility": 1.0, "pixels": 400}],
        })
    return frames, []


def _outside(frames, events=()):
    return projection_errors(frames, list(events), {"h7": 1.84})["player_foot_outside_box"]


def test_a_foot_drawn_to_the_ball_it_touches_is_inside_its_box_from_a_high_lens():
    """Seeds 70 and 79 of dataset tactical: on a touch the foot is drawn at the ball, 0.85 to 0.9 m
    out. From a high lens that is far down the picture, past the side-on slack of 0.45 m; the box is
    right, and the check now measures the reach on the ground through the saved matrix."""
    frames, events = _reach_clip(1.0, touch=True)
    assert projection_errors(frames)["player_foot_outside_box"] > 0  # the side-on slack alone fails it
    assert _outside(frames, events) == 0


def test_a_foot_that_far_out_with_no_touch_is_still_caught():
    frames, events = _reach_clip(1.0, touch=False)
    assert _outside(frames, events) == len(frames)


def test_a_foot_beyond_the_leg_is_caught_even_on_a_touch():
    """The reach is the leg's ((LEG_M + HIP_SIDE_M) at his scale, about 1.1 m at 1.84 m tall), not
    wherever the ball is: a box reaching 2.5 m to a ball fails on the touch frames too."""
    frames, events = _reach_clip(2.5, touch=True)
    assert _outside(frames, events) == len(frames)


def test_a_short_touch_does_not_excuse_a_long_reach():
    """The allowance is where the foot is drawn (at the ball), not the leg's whole reach: a ball 0.3 m
    out does not let the box reach 1.0 m."""
    frames, events = _reach_clip(0.3, touch=True, foot_off=1.0)
    assert _outside(frames, events) == len(frames)


def test_a_body_drawn_above_his_ground_point_is_caught_on_a_touch():
    """A reach toward the camera moves the box's bottom down the picture, never up: a body floating
    0.8 m above the grass on a short touch fails on the touch frames as on any other. (A float that a
    long reach toward the lens offsets exactly cannot be told from a box alone.)"""
    frames, events = _reach_clip(0.3, touch=True, lift=0.8)
    assert _outside(frames, events) == len(frames)


def test_a_box_beside_him_is_caught_on_a_touch():
    """Across the picture the tracked point stays inside the box, touch or not: the same box moved
    60 px sideways (its bottom where it was) fails, and so does a body drawn 1.5 m along the line."""
    frames, events = _reach_clip(1.0, touch=True)
    for fr in frames:
        b = fr["players"][0]["bbox"]
        fr["players"][0]["bbox"] = [b[0] + 60, b[1], b[2] + 60, b[3]]
    assert _outside(frames, events) == len(frames)
    frames, events = _reach_clip(1.0, touch=True, side=1.5)
    assert _outside(frames, events) == len(frames)


def test_the_reach_is_allowed_only_round_the_touch_and_never_across_a_cut():
    """Rows far after the touch get no allowance (the renderer's window is under a second), and a row
    after an edit cut is another shot, however near in rows."""
    frames, events = _reach_clip(1.0, touch=True, n=60)
    out = _outside(frames, events)
    assert 0 < out < len(frames) and out >= len(frames) - 6 - 25
    frames, events = _reach_clip(1.0, touch=True, cut_after=7)
    assert _outside(frames, events) == len(frames) - 8  # rows 0 to 7 round the touch pass; none after the cut
    # however few match frames the cut skips, the rows after it are another shot
    frames, events = _reach_clip(1.0, touch=True, cut_after=7, jump=2)
    assert _outside(frames, events) == len(frames) - 8


def test_a_chest_or_thigh_touch_puts_no_foot_at_the_ball():
    """Only a foot is drawn at the ball (touch_at): a chest touch with the box reaching 1.0 m along
    the grass gets no allowance."""
    for part in ("chest", "thigh"):
        frames, events = _reach_clip(1.0, touch=True, part=part)
        assert _outside(frames, events) == len(frames), part


def test_a_reach_away_from_the_camera_never_raises_the_bottom():
    """The standing foot is under him, so a ball away from the lens leaves the lowest sole at his
    ground point: a body lifted 0.5 m on such a touch fails (the second review's floating case)."""
    frames, events = _reach_clip(-1.0, touch=True, foot_off=0.0, lift=0.5)
    assert _outside(frames, events) == len(frames)


def test_the_bounds_are_tight_at_the_foot_and_at_the_lift():
    """The bottom may be V6's 0.45 m beyond the drawn foot and no further, and his sole lifted 0.45 m
    and no higher (both measured through the matrix, no other slack)."""
    ok, _ = _reach_clip(0.6, touch=True, foot_off=0.95)
    past, _ = _reach_clip(0.6, touch=True, foot_off=1.2)
    assert _outside(ok) == 0 and _outside(past) == len(past)
    low, _ = _reach_clip(0.3, touch=True, foot_off=0.0, lift=0.35)
    high, _ = _reach_clip(0.3, touch=True, foot_off=0.0, lift=0.6)
    assert _outside(low) == 0 and _outside(high) == len(high)


def test_the_allowance_covers_exactly_the_frames_the_touch_is_drawn_on():
    """scene._touch_window: from a kick's start before the contact to a touch's end after it, compared
    in seconds as touch_at compares them; every row inside passes and every row outside fails."""
    from ninety.render.scene import _touch_window

    frames, events = _reach_clip(1.0, touch=True, n=30, at=10)
    lo = min(_touch_window({"part": "strike", "out": 0.0})[0], _touch_window({"part": "chest"})[0])
    hi = max(_touch_window({"part": "strike", "out": 0.0})[1], _touch_window({"part": "chest"})[1])
    drawn = [i for i in range(30) if lo < (i - 10) / 25 < hi]
    assert 15 <= len(drawn) <= 21  # about 0.8 s
    assert _outside(frames, events) == 30 - len(drawn)


def test_a_tall_players_leg_reaches_further():
    """The reach is scaled by his own height, as touch_at scales the leg: a ball 1.15 m out with the
    box 1.55 m out passes for a 2.0 m player and fails at the asset's 1.684 m."""
    frames, events = _reach_clip(1.15, touch=True, foot_off=1.55)
    assert projection_errors(frames, events, {"h7": 2.0})["player_foot_outside_box"] == 0
    assert projection_errors(frames, events, {"h7": 1.684})["player_foot_outside_box"] == len(frames)


def test_rows_shared_by_two_touches_keep_either_touchs_reach():
    """touch_at draws one of two overlapping touches (the one further into its swing), so a row in
    both windows may show either: a foot drawn to the first ball still passes while the second
    touch, away from the camera, is in its window too; past the first's window it fails."""
    frames, events = _reach_clip(1.0, touch=True, n=26, at=6)
    for i, fr in enumerate(frames):
        if i >= 11:
            fr["ball"]["y"] = 6.5  # the second ball, 1.5 m behind him, there before he touches it
        if i == 12:
            fr["players"][0]["action"] = "foot"
    assert _outside(frames, events) == 26 - 19  # rows 0 to 18 by the first touch; 19 to 25 fail
