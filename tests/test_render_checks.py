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


def _reach_clip(ball_off: float, touch: bool, n: int = 12, at: int = 6) -> tuple[list[dict], list[dict]]:
    """One player at (30, 5), near the touchline, lunging: his box from his head over the tracked
    point (1.6 m up, the hips down in the reach) to his foot at a ball `ball_off` metres toward the
    camera; on frame `at` he touches it (action foot) when `touch`."""
    frames = []
    bx, by = 30.0, 5.0 - ball_off
    for i in range(n):
        head = HIGH.project((30.0, 5.0, 1.6))
        sole = HIGH.project((bx, by, 0.0))
        foot = HIGH.project((30.0, 5.0, 0.0))
        box = [min(head[0], sole[0], foot[0]) - 6, head[1], max(head[0], sole[0], foot[0]) + 6, sole[1]]
        frames.append({
            "frame": 100 + i, "t": (100 + i) / 25, "camera": HIGH.to_dict(), "keypoints": [],
            "ball": {"x": bx, "y": by, "z": 0.0, "bbox": None, "pixels": 0, "visibility": 0.0,
                     "centroid_px": None},
            "players": [{"id": "h7", "team": "home", "x": 30.0, "y": 5.0, "vx": 1.0, "vy": 0.0,
                         "heading": -1.5708, "action": "foot" if touch and i == at else "walk",
                         "bbox": box, "visibility": 1.0, "pixels": 400}],
        })
    return frames, []


def test_a_foot_drawn_to_the_ball_it_touches_is_inside_its_box_from_a_high_lens():
    """Seeds 70 and 79 of dataset tactical: on a touch the foot is drawn at the ball, 0.85 to 0.9 m
    out. From a high lens that is far down the picture, past the side-on slack of 0.45 m; the box is
    right, and the check now measures the reach on the ground through the saved matrix."""
    frames, events = _reach_clip(1.0, touch=True)
    assert projection_errors(frames)["player_foot_outside_box"] > 0  # the side-on slack alone fails it
    assert projection_errors(frames, events, {"h7": 1.84})["player_foot_outside_box"] == 0


def test_a_foot_that_far_out_with_no_touch_is_still_caught():
    frames, events = _reach_clip(1.0, touch=False)
    assert projection_errors(frames, events, {"h7": 1.84})["player_foot_outside_box"] == len(frames)


def test_a_foot_beyond_the_leg_is_caught_even_on_a_touch():
    """The reach is the leg's ((LEG_M + HIP_SIDE_M) at his scale, about 1.1 m at 1.84 m tall), not
    wherever the ball is: a box reaching 2.5 m to a ball fails on the touch frames too."""
    frames, events = _reach_clip(2.5, touch=True)
    assert projection_errors(frames, events, {"h7": 1.84})["player_foot_outside_box"] == len(frames)
