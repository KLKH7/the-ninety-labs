"""Each contract check gets a clean clip that passes and a single planted defect that must fail it."""

import json

import pytest

from ninety.validate import validate

FPS = 25


def clean_clip() -> dict:
    """h1 passes 10 m to h2 over 1 s, then 5 s of play; a1 stands still. Everything consistent."""
    frames = []
    for n in range(150):
        u = min(n / 25, 1.0)
        frames.append({
            "frame": n, "t": n / FPS,
            "ball": {"x": 40 + 10 * u, "y": 30.0, "z": 0.0},
            "possessor": "h1" if n == 0 else ("h2" if u == 1 else None),
            "players": [
                {"id": "h1", "team": "home", "x": 40.0, "y": 30.0},
                {"id": "h2", "team": "home", "x": 50.0, "y": 30.0},
                {"id": "a1", "team": "away", "x": 60.0, "y": 40.0},
            ],
        })
    events = [{
        "id": "e1", "t": 0.0, "frame": 0, "type": "pass", "team": "home", "player": "h1",
        "receiver": "h2", "x": 40.0, "y": 30.0, "end_x": 50.0, "end_y": 30.0,
        "outcome": "success", "ball_speed_kmh": 36.0, "source": "truth", "confidence": None,
    }]
    return {"events": events, "frames": frames, "meta": {"fps": FPS}}


def write(tmp_path, clip):
    with open(tmp_path / "events.jsonl", "w") as f:
        f.writelines(json.dumps(e) + "\n" for e in clip["events"])
    with open(tmp_path / "frames.jsonl", "w") as f:
        f.writelines(json.dumps(fr) + "\n" for fr in clip["frames"])
    (tmp_path / "meta.json").write_text(json.dumps(clip["meta"]))
    return tmp_path


def test_clean_clip_passes(tmp_path):
    assert validate(write(tmp_path, clean_clip())) == {}


def teleport(c):
    c["frames"][30]["players"][2]["x"] = 70.0  # a1 jumps 10 m in one frame


def ball_jump(c):
    c["frames"][40]["ball"]["x"] = 90.0


def wrong_team(c):
    c["events"][0]["team"] = "away"


def unknown_player(c):
    c["events"][0]["receiver"] = "h9"


def event_far_from_ball(c):
    c["events"][0]["x"] = 20.0


def ball_never_arrives(c):
    c["events"][0]["end_x"] = 80.0


def event_time_mismatch(c):
    c["events"][0]["t"] = 1.0


def not_truth(c):
    c["events"][0]["source"] = "vision"


def roster_changes(c):
    c["frames"][10]["players"][2]["id"] = "a2"


def bad_schema(c):
    c["events"][0]["type"] = "dribble"


@pytest.mark.parametrize("defect, check", [
    (teleport, "player speed"),
    (ball_jump, "ball speed"),
    (wrong_team, "event players"),
    (unknown_player, "event players"),
    (event_far_from_ball, "event location"),
    (ball_never_arrives, "ball path"),
    (event_time_mismatch, "event frame"),
    (not_truth, "event schema"),
    (roster_changes, "roster"),
    (bad_schema, "event schema"),
])
def test_planted_defect_fails(tmp_path, defect, check):
    clip = clean_clip()
    defect(clip)
    assert check in validate(write(tmp_path, clip))


def test_kickoff_restart_may_reset_positions(tmp_path):
    clip = clean_clip()
    teleport(clip)
    clip["events"].append({
        "id": "e2", "t": 1.2, "frame": 30, "type": "kickoff", "team": "away", "player": "a1",
        "receiver": None, "x": 70.0, "y": 40.0, "end_x": None, "end_y": None, "outcome": None,
        "ball_speed_kmh": None, "source": "truth", "confidence": None,
    })
    assert "player speed" not in validate(write(tmp_path, clip))


def test_missing_file(tmp_path):
    assert "files" in validate(tmp_path)
