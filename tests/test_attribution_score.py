"""The attribution scorer (ninety/eval/attribution_score.py): matching that ignores the team it
grades, names checked through the boxes, and a name nobody can check never counted right."""

from __future__ import annotations

import json

from ninety.eval import attribution_score as at
from tests.test_vision_events import BLUE, RED, pass_scene


def ev(id_, t, kind="pass", team="home", **kw):
    return {"id": id_, "t": t, "type": kind, "team": team, **kw}


def test_matching_pairs_by_type_and_time_whatever_the_team_says():
    truth = [ev("e1", 10.0, team="home"), ev("e2", 20.0)]
    detected = [ev("v1", 10.4, team="away"), ev("v2", 21.2), ev("v3", 10.1, kind="shot")]
    assert [(t["id"], d["id"]) for t, d in at.match(truth, detected)] == [("e1", "v1")]


def test_matching_is_one_to_one_nearest_in_time_first():
    truth = [ev("e1", 10.0), ev("e2", 10.6)]
    detected = [ev("v1", 10.5)]
    assert [(t["id"], d["id"]) for t, d in at.match(truth, detected)] == [("e2", "v1")]


def pair(truth_player, named, is_):
    return {"type": "shot", "team": {"truth": "home", "detected": "home"},
            "player": {"truth": truth_player, "detected": named, "is": is_}}


def test_a_name_nobody_can_check_is_not_right_and_a_null_name_is_left_null():
    clips = [{"pairs": [pair("h7", "h-t1", "h7"), pair("h7", "h-t2", None), pair("h7", None, None),
                        pair("h7", "h-t3", "h8"), pair(None, "h-t4", None)]}]
    row = at.grade(clips)["shot"]
    # The last: a name where the truth has none, unchecked: not right, though None equals None.
    assert row["player"] == {"truth_names": 4, "named": 4, "right": 1, "unchecked": 2,
                             "accuracy": 1 / 4, "left_null": 1}
    assert row["team_accuracy"] == 1.0


def test_the_passer_is_judged_at_the_strike_and_the_one_who_got_it_at_his_first_frame():
    e = {"id": "v1", "frame": 20}
    assert at.role_frame(e, "player", {"v1": 31}) == 20
    assert at.role_frame(e, "receiver", {"v1": 31}) == at.role_frame(e, "interceptor", {"v1": 31}) == 31


def write_clip(tmp_path, rows, truth_events, ids):
    """A test clip on disk: the scene's observations, and truth frames whose players carry the same
    boxes as the detections (so IoU is 1) under the ids given, in box order."""
    seed = 1
    root = tmp_path / "test" / f"seed{seed}"
    root.mkdir(parents=True)
    obs = tmp_path / "obs"
    obs.mkdir()
    (obs / f"observations-seed{seed}.jsonl").write_text("".join(json.dumps(r) + "\n" for r in rows))
    frames = [{"frame": r["frame"], "players": [{"id": ids[i], "bbox": d["bbox"], "visibility": 1.0}
                                                for i, d in enumerate(r["players"])]} for r in rows]
    (root / "frames.jsonl").write_text("".join(json.dumps(f) + "\n" for f in frames))
    lines = [json.dumps({**e, "source": "truth"}) + "\n" for e in truth_events]
    (root / "events.jsonl").write_text("".join(lines))
    return seed, tmp_path / "test", obs


CROWD = [f"c{k}" for k in range(8)]  # the scene's crowd, then the passer and the other player


def test_a_clip_end_to_end_names_the_passer_and_receiver_right(tmp_path):
    truth = [ev("e1", 20 / 25, team="home", player="h7", receiver="h8")]
    seed, test_dir, obs = write_clip(tmp_path, pass_scene(BLUE), truth, CROWD + ["h7", "h8"])
    clip = at.clip(seed, test_dir, obs)
    (p,) = clip["pairs"]
    assert p["player"] == {"truth": "h7", "detected": "h-t9", "is": "h7"}
    assert p["receiver"] == {"truth": "h8", "detected": "h-t10", "is": "h8"}
    assert at.grade([clip])["pass"]["player"]["right"] == 1


def test_a_clip_whose_truth_names_another_player_is_graded_wrong(tmp_path):
    truth = [ev("e1", 20 / 25, team="home", player="h8", interceptor="a4")]
    seed, test_dir, obs = write_clip(tmp_path, pass_scene(RED), truth, CROWD + ["h7", "a4"])
    clip = at.clip(seed, test_dir, obs)
    row = at.grade([clip])["pass"]
    assert row["player"]["named"] == 1 and row["player"]["right"] == 0
    assert row["interceptor"]["right"] == 1
