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
