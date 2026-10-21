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
