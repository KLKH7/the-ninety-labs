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


# --- deriving the constants on non-test clips (ninety/eval/attribution_derive.py) ----------------


def dribble_rows():
    """test_vision_events' dribbler: one blue player with the ball, his track broken at frame 30."""
    from tests.test_vision_events import FPS, crowd, row
    rows = []
    for f in range(60):
        x, y = 40.0 + 5.0 * f / FPS, 34.0 + (1.5 if f >= 30 else 0.0)
        rows.append(row(f, crowd(f) + [(x, y, BLUE)], (x + 0.3, y)))
    return rows


def test_derive_finds_the_self_pass_with_the_rule_off_and_none_with_it_on():
    from ninety.eval import attribution_derive as de
    rows = dribble_rows()
    ids = CROWD + ["h7"]
    frames = {r["frame"]: {"frame": r["frame"], "players": [
        {"id": ids[i], "bbox": d["bbox"], "visibility": 1.0} for i, d in enumerate(r["players"])]}
        for r in rows}
    off = de.self_passes(rows, frames, join_breaks=False)["passes"]
    assert [p["self"] for p in off] == [True] and off[0]["players"] == ["h7", "h7"]
    assert de.self_passes(rows, frames, join_breaks=True)["passes"] == []


def test_derive_refuses_a_test_seed(tmp_path):
    import pytest

    from ninety.eval import attribution_derive as de
    seed = sorted(de.test_seeds())[0]
    with pytest.raises(SystemExit, match="test seeds"):
        de.main(["--clips", str(tmp_path), "--observations", str(tmp_path), "--seeds", str(seed),
                 "--out", str(tmp_path / "x")])


def test_the_report_is_strict_json_a_nan_is_an_error_never_written():
    import math

    import pytest
    with pytest.raises(ValueError):
        at.dump({"x": math.nan})
    assert at.dump({"x": 1.0}) == '{\n  "x": 1.0\n}\n'


def test_check_fails_on_a_stale_report_and_passes_on_a_current_one(tmp_path):
    import pytest
    out = tmp_path / "r"
    body = {"commit": "a", "date": "d", "x": 1}
    md = lambda b: f"x={b['x']}\n"  # noqa: E731
    at.write_or_check(out, body, md, check=False)
    at.write_or_check(out, {**body, "commit": "b", "date": "e"}, md, check=True)  # only results count
    with pytest.raises(SystemExit, match="stale"):
        at.write_or_check(out, {**body, "x": 2}, md, check=True)


def test_a_box_that_barely_overlaps_a_true_player_is_nobody():
    from ninety.vision import track as tr
    t = tr.Track(1, frames=[0], xy=[(1.0, 2.0)], team="home")
    obs = {0: {"players": [{"bbox": [0, 0, 10, 30], "score": 0.9, "x": 1.0, "y": 2.0}]}}

    def truth(box):
        return {0: {"players": [{"id": "h7", "bbox": box, "visibility": 1.0}]}}
    assert at.truth_player(t, 0, obs, truth([0, 0, 10, 30])) == "h7"
    assert at.truth_player(t, 0, obs, truth([0, 0, 10, 14])) is None  # IoU 0.47: under 0.5
    assert at.truth_player(t, 0, obs, truth([5, 0, 15, 30])) is None  # IoU 0.33


def test_false_events_count_their_names_and_who_those_really_are():
    clips = [{"unmatched_detected": [
        {"id": "v1", "type": "pass", "player": "h-t1", "receiver": "h-t2",
         "is": {"player": "h3", "receiver": "h3"}},
        {"id": "v2", "type": "out_of_play", "is": {}},
        {"id": "v3", "type": "pass", "player": "h-t4", "is": {"player": None}}]}]
    assert at.false_names(clips) == {"false_events": 3, "false_events_named": 2, "names": 3,
                                     "names_checkable": 2}


def test_rival_m_is_the_committed_validation_measurement():
    from pathlib import Path

    from ninety.vision import events as events_
    body = json.loads((Path(__file__).resolve().parents[1] / "docs/eval/attribution-derive.json").read_text())
    assert events_.RIVAL_M == round(body["players_position_error"]["p90_m"], 2)
    assert not set(body["seeds"]) & set(json.loads(
        (Path(__file__).resolve().parents[1] / "docs/eval/test-set-frozen.json").read_text())["seeds"])


def test_old_truth_without_an_interceptor_field_names_him_as_the_failed_passs_receiver():
    old = {"type": "pass", "outcome": "fail", "player": "a11", "receiver": "h9"}
    assert (at.truth_role(old, "receiver"), at.truth_role(old, "interceptor")) == (None, "h9")
    new = {**old, "receiver": None, "interceptor": "h9"}
    assert (at.truth_role(new, "receiver"), at.truth_role(new, "interceptor")) == (None, "h9")
    done = {"type": "pass", "outcome": "success", "player": "a11", "receiver": "a9"}
    assert (at.truth_role(done, "receiver"), at.truth_role(done, "interceptor")) == ("a9", None)
