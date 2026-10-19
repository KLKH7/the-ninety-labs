"""Failure clusters: each label lands in the situation its geometry says, training seeds only, and
the Data agent is handed only clusters the renderer can make more of."""

import json

import pytest

from ninety.agents.data_agent import plan
from ninety.vision.failure_clusters import audit, handoff, situation

# A gantry camera on the near touchline, looking across the pitch (+y is away from the lens).
CAMERA = {"width": 1280, "height": 720, "position": [52.5, -35.0, 20.0]}


def player(pid, x, y, bbox, role="CM", action="run", visibility=1.0):
    return {"id": pid, "team": "home", "role": role, "x": x, "y": y, "action": action,
            "bbox": bbox, "visibility": visibility}


def ball_label(x, y, bbox, players, visibility=0.3):
    ball = {"x": x, "y": y, "z": 0.0, "bbox": bbox, "visibility": visibility}
    row = {"frame": 0, "camera": CAMERA, "players": players, "ball": ball}
    return {"cls": "ball", "bbox": bbox, "visibility": visibility, "obj": ball, "row": row}


BALL_BOX = [600, 400, 610, 410]
OVER_BALL = [590, 340, 630, 420]  # a player box that covers the ball's box
ELSEWHERE = [100, 100, 140, 180]


def test_a_player_nearer_the_lens_over_the_ball_hides_it():
    nearer = player("h1", 52.5, 30.0, OVER_BALL)
    assert situation(ball_label(52.5, 34.0, BALL_BOX, [nearer])) == "behind a player"


def test_a_player_beyond_the_ball_hides_nothing_even_when_the_boxes_overlap():
    beyond = player("h1", 52.5, 38.0, OVER_BALL)
    assert situation(ball_label(52.5, 34.0, BALL_BOX, [beyond])) == "no occluder found"


def test_a_crowd_is_three_or_more_players_within_four_metres():
    nearer = player("h1", 52.5, 31.0, OVER_BALL)
    two_more = [player("a1", 54.0, 35.0, ELSEWHERE), player("a2", 51.0, 36.0, ELSEWHERE)]
    assert situation(ball_label(52.5, 34.0, BALL_BOX, [nearer, *two_more])) == "behind a player in a crowd"
    one_more = two_more[:1]
    assert situation(ball_label(52.5, 34.0, BALL_BOX, [nearer, *one_more])) == "behind a player"
    far = [player("a1", 60.0, 35.0, ELSEWHERE), player("a2", 45.0, 36.0, ELSEWHERE)]
    assert situation(ball_label(52.5, 34.0, BALL_BOX, [nearer, *far])) == "behind a player"


def test_a_keeper_handling_the_ball_or_standing_in_front_is_the_keeper():
    handling = player("h1", 1.5, 34.0, ELSEWHERE, role="GK", action="hands")
    assert situation(ball_label(1.0, 34.5, BALL_BOX, [handling])) == "behind the keeper"
    standing = player("h1", 1.5, 34.0, ELSEWHERE, role="GK", action="stand")
    assert situation(ball_label(1.0, 34.5, BALL_BOX, [standing])) == "behind the goal frame"
    in_front = player("h1", 52.5, 30.0, OVER_BALL, role="GK", action="stand")
    assert situation(ball_label(52.5, 34.0, BALL_BOX, [in_front])) == "behind the keeper"


def test_the_goal_frame_the_boards_and_the_edge():
    assert situation(ball_label(104.5, 35.0, BALL_BOX, [])) == "behind the goal frame"
    assert situation(ball_label(60.0, 69.0, BALL_BOX, [])) == "off the pitch, by the boards"
    assert situation(ball_label(60.0, 30.0, [0, 400, 8, 410], [])) == "at the frame's edge"
    assert situation(ball_label(60.0, 30.0, BALL_BOX, [])) == "no occluder found"


def test_a_player_hidden_by_another_player_nearer_the_lens():
    front = player("h1", 52.5, 30.0, [580, 330, 640, 470])
    back = player("a1", 52.7, 33.0, [590, 340, 630, 420], visibility=0.2)
    row = {"frame": 0, "camera": CAMERA, "players": [front, back], "ball": {}}
    label = {"cls": "player", "bbox": back["bbox"], "visibility": 0.2, "obj": back, "row": row}
    assert situation(label) == "behind a player"
    # The one in front is not hidden by the one behind.
    label_front = {"cls": "player", "bbox": front["bbox"], "visibility": 0.9, "obj": front, "row": row}
    assert situation(label_front) == "no occluder found"


def write_clip(root, seed, ball_found):
    clip = root / f"seed{seed}"
    clip.mkdir()
    (clip / "clip.json").write_text(json.dumps({"seed": seed, "params": {"kit_contrast": "low"}}))
    nearer = player("h1", 52.5, 30.0, OVER_BALL)
    row = {"frame": 0, "camera": CAMERA, "players": [nearer],
           "ball": {"x": 52.5, "y": 34.0, "z": 0.0, "bbox": BALL_BOX, "visibility": 0.3}}
    (clip / "frames.jsonl").write_text(json.dumps(row) + "\n")
    dets = [{"cls": "player", "bbox": OVER_BALL, "score": 0.9}]
    if ball_found:
        dets.append({"cls": "ball", "bbox": BALL_BOX, "score": 0.9})
    (clip / "det.jsonl").write_text(json.dumps({"frame": 0, "detections": dets}) + "\n")
    return clip


def test_the_audit_counts_misses_per_situation_and_hands_off_only_renderable_clusters(tmp_path):
    clips = [write_clip(tmp_path, 7001, ball_found=False), write_clip(tmp_path, 7002, ball_found=True)]
    report = audit(clips, "det.jsonl")
    ball = [r for r in report["rows"] if r["cls"] == "ball"]
    assert ball == [{"cls": "ball", "visibility": "mostly hidden", "situation": "behind a player",
                     "kit_contrast": "low", "labels": 2, "missed": 1}]
    h = handoff(report, "round1")
    assert h["clusters"] == [{"name": "ball mostly hidden, behind a player", "misses": 1,
                              "render": {"occlusion": "crowded"}}]
    assert h["unmapped"] == []
    # The Data agent takes the handoff as it is.
    p = plan(h, budget=3, first_seed=7001, commit="abc")
    assert p["clusters"][0]["set"] == "occlusion=crowded" and p["clusters"][0]["clips"] == 3


def test_a_cluster_with_no_render_setting_is_not_handed_to_the_data_agent():
    report = {"rows": [{"cls": "ball", "visibility": "mostly hidden", "situation": "behind the keeper",
                        "kit_contrast": "normal", "labels": 4, "missed": 3}]}
    h = handoff(report, "round1")
    assert h["clusters"] == []
    assert h["unmapped"] == [{"name": "ball mostly hidden, behind the keeper", "misses": 3}]


@pytest.mark.parametrize("seed", [900001, 900042])
def test_test_and_reserved_seeds_are_refused(tmp_path, seed):
    clip = write_clip(tmp_path, seed, ball_found=False)
    with pytest.raises(ValueError, match="training seeds only"):
        audit([clip], "det.jsonl")
