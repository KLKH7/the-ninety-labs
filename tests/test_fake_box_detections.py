import math

import pytest

from ninety.eval import vision_score
from ninety.eval.fake_box_detections import (
    BALL_SHIFT_PX,
    DAMAGES,
    PLAYER_SHIFT,
    blur_of,
    disagreements,
    fake_box_detections,
    height_of,
    main,
)
from ninety.eval.vision_score import BALL_DISTANCE_PX, BLUR_PX, IN_AIR_Z, PLAYER_IOU, iou, score

W, H = 1280, 720
VISIBILITIES = (1.0, 0.7, 0.3)  # one in each group: visible, partly hidden, mostly hidden
CROWD = ([600, 500, 620, 540], [610, 500, 630, 540])  # two overlapping players in every frame


def frames(n=12):
    """Spaced players and a ball in every visibility group, set directly (LESSONS 47), plus a crowd
    of two overlapping players that no damage may touch."""
    rows = []
    for f in range(n):
        players = [{"id": f"p{k}", "bbox": [100 + 150 * k, 100, 120 + 150 * k, 140],
                    "visibility": VISIBILITIES[(f + k) % 3]} for k in range(6)]
        players += [{"id": f"c{k}", "bbox": box, "visibility": 1.0} for k, box in enumerate(CROWD)]
        rows.append({"frame": f, "camera": {"width": W, "height": H}, "players": players,
                     "ball": {"bbox": [300 + 20 * f, 400, 310 + 20 * f, 410],
                              "visibility": VISIBILITIES[f % 3]}})
    return rows


def labels_of(cls):
    return sum(len(r["players"]) if cls == "player" else 1 for r in frames())


def test_the_shifts_sit_either_side_of_the_rule():
    # A sideways move of a share s of the width gives IoU (1 - s) / (1 + s).
    assert (1 - PLAYER_SHIFT["shift_in"]) / (1 + PLAYER_SHIFT["shift_in"]) > PLAYER_IOU
    assert (1 - PLAYER_SHIFT["shift_out"]) / (1 + PLAYER_SHIFT["shift_out"]) < PLAYER_IOU
    assert BALL_SHIFT_PX["shift_in"] < BALL_DISTANCE_PX < BALL_SHIFT_PX["shift_out"]


def test_a_perfect_copy_scores_one():
    detections, expected = fake_box_detections(frames(), seed=0, per_damage=0)
    report = score(frames(), detections)
    for cls in ("player", "ball"):
        assert report["by_class"][cls]["recall"] == report["by_class"][cls]["precision"] == 1.0
        assert expected["by_class"][cls]["recall"] == expected["by_class"][cls]["precision"] == 1.0
    assert disagreements(expected, report) == []


@pytest.mark.parametrize("seed", range(6))
def test_the_scorer_reports_exactly_what_was_planted(seed):
    per = 2
    detections, expected = fake_box_detections(frames(), seed=seed, per_damage=per)
    # The counts follow from the damage alone: drop and shift_out miss, shift_out and add are false.
    for cls in ("player", "ball"):
        row = expected["by_class"][cls]
        assert (row["tp"], row["fp"], row["fn"]) == (labels_of(cls) - 2 * per, 2 * per, 2 * per)
        assert row["recall"] == pytest.approx((labels_of(cls) - 2 * per) / labels_of(cls))
    assert len(expected["damage"]) == 2 * len(DAMAGES) * per
    report = score(frames(), detections)
    assert disagreements(expected, report) == []


def test_damage_never_touches_the_crowd():
    for seed in range(10):
        detections, _ = fake_box_detections(frames(), seed=seed, per_damage=3)
        for f in range(len(frames())):
            boxes = [d["bbox"] for d in detections if d["frame"] == f and d["cls"] == "player"]
            assert all(box in boxes for box in CROWD)


def test_a_box_shifted_past_the_rule_is_a_miss_and_a_false_alarm():
    detections, expected = fake_box_detections(frames(), seed=3, per_damage=1)
    out = next(e for e in expected["damage"] if e["damage"] == "shift_out" and e["cls"] == "player")
    truth = [p["bbox"] for p in frames()[out["frame"]]["players"]]
    # The moved copy still overlaps its own label (an added box overlaps none), but less than the rule.
    moved = [i for i, d in enumerate(detections) if d["frame"] == out["frame"] and d["cls"] == "player"
             and d["bbox"] not in truth and max(iou(d["bbox"], box) for box in truth) > 0]
    assert len(moved) == 1
    assert max(iou(detections[moved[0]]["bbox"], box) for box in truth) < PLAYER_IOU
    report = score(frames(), detections)
    assert moved[0] not in {p["detection"] for p in report["pairs"]}


@pytest.mark.parametrize("rule,value", [("PLAYER_IOU", 0.1), ("BALL_DISTANCE_PX", 100.0),
                                        ("PLAYER_IOU", 0.9), ("BALL_DISTANCE_PX", 1.0)])
def test_a_scorer_with_a_different_rule_disagrees(monkeypatch, rule, value):
    # The check can fail (LESSONS 8): a looser rule matches the shift_out copies, a stricter one
    # rejects the shift_in copies, and either way the report no longer matches what was planted.
    detections, expected = fake_box_detections(frames(), seed=1, per_damage=2)
    monkeypatch.setattr(vision_score, rule, value)
    assert disagreements(expected, score(frames(), detections))


def test_damage_is_refused_when_nothing_is_isolated():
    crowded = [{"frame": 0, "camera": {"width": W, "height": H},
                "players": [{"bbox": box, "visibility": 1.0} for box in CROWD], "ball": {"bbox": None}}]
    with pytest.raises(ValueError, match="isolated player"):
        fake_box_detections(crowded, seed=0, per_damage=1)


def test_a_false_box_is_refused_when_there_is_no_room():
    full = [{"frame": 0, "camera": {"width": 20, "height": 40},
             "players": [{"bbox": [0, 0, 20, 40], "visibility": 1.0}], "ball": {"bbox": None}}]
    fake_box_detections(full, seed=0, per_damage=0)
    with pytest.raises(ValueError, match="no room|isolated"):
        fake_box_detections(full, seed=0, per_damage=1)


def test_the_same_seed_gives_the_same_damage():
    assert fake_box_detections(frames(), seed=4) == fake_box_detections(frames(), seed=4)
    assert fake_box_detections(frames(), seed=4)[0] != fake_box_detections(frames(), seed=5)[0]


def test_cli_checks_a_clip(tmp_path, capsys):
    import json

    clip = tmp_path / "seed1"
    clip.mkdir()
    (clip / "frames.jsonl").write_text("".join(json.dumps(r) + "\n" for r in frames()))
    with pytest.raises(SystemExit) as done:
        main([str(clip)])
    assert done.value.code == 0
    assert json.loads(capsys.readouterr().out)["agrees"] is True


def test_a_moved_false_alarm_is_planted_only_where_its_own_label_is_nearest():
    # A wide visible player between two narrow, mostly hidden ones that it does not overlap even when
    # moved: moved out either way, its centre would be nearer a narrow one, so the scorer would put
    # the false alarm in the wrong group. Only the narrow players may take shift_out.
    rows = []
    for f in range(8):
        players = []
        for k in range(4):
            x = 100 + 200 * k
            players += [{"bbox": [x - 16, 100, x - 14, 140], "visibility": 0.3},
                        {"bbox": [x, 100, x + 20, 140], "visibility": 1.0},
                        {"bbox": [x + 34, 100, x + 36, 140], "visibility": 0.3}]
        rows.append({"frame": f, "camera": {"width": W, "height": H}, "players": players,
                     "ball": {"bbox": [300 + 20 * f, 400, 310 + 20 * f, 410], "visibility": 1.0}})
    for seed in range(10):
        detections, expected = fake_box_detections(rows, seed=seed, per_damage=1)
        out = [e for e in expected["damage"] if e["damage"] == "shift_out" and e["cls"] == "player"]
        assert [e["group"] for e in out] == ["mostly hidden"]
        assert disagreements(expected, score(rows, detections)) == []


def test_a_false_box_equally_near_two_labels_is_not_placed():
    from ninety.eval.fake_box_detections import _false_box

    class Draws:  # uniform() returns these in turn: first a box midway between the two players
        def __init__(self, values):
            self.values = iter(values)

        def uniform(self, a, b):
            return next(self.values)

    labels = [{"frame": 0, "cls": "player", "bbox": [0, 0, 20, 40], "visibility": 1.0},
              {"frame": 0, "cls": "player", "bbox": [100, 0, 120, 40], "visibility": 0.3}]
    camera = {"width": W, "height": H}
    assert _false_box(labels[0], labels, camera, Draws([50, 0, 60, 100])) == [60, 100, 80, 140]


def test_a_box_with_visibility_zero_is_neither_copied_nor_counted():
    # The scorer does not count a fully hidden box as a label (#119), so the fake must neither copy
    # it as a detection (a false alarm) nor expect it to be found (a planted miss).
    rows = frames()
    for row in rows:
        row["players"].append({"id": "hidden", "bbox": [1000, 100, 1020, 140], "visibility": 0.0})
    rows[0]["ball"]["visibility"] = 0.0
    detections, expected = fake_box_detections(rows, seed=2, per_damage=2)
    assert not any(d["bbox"] == [1000, 100, 1020, 140] for d in detections)
    assert expected["by_class"]["player"]["tp"] + expected["by_class"]["player"]["fn"] == labels_of("player")
    assert expected["by_class"]["ball"]["tp"] + expected["by_class"]["ball"]["fn"] == labels_of("ball") - 1
    assert disagreements(expected, score(rows, detections)) == []


# --- damage planted by ball height and camera blur ---------------------------------------------

# f % 4: on the ground twice (once exactly at the cut-off), then in the air twice
Z_CYCLE = (0.0, IN_AIR_Z, 1.0, 2.0)
# (f // 2) % 3: exactly the cut-off, then longer twice
BLUR_CYCLE = ([BLUR_PX, 0.0], [2.5, 2.5], [0.0, -6.0])


def axis_frames(n=24):
    """frames() with a ball height and a camera blur streak on every frame, set directly, the
    boundary values among them: 12 of 24 balls in the air, 16 of 24 frames blurred."""
    rows = frames(n)
    for row in rows:
        f = row["frame"]
        row["ball"]["z"] = Z_CYCLE[f % 4]
        row["blur_px"] = BLUR_CYCLE[(f // 2) % 3]
    return rows


def in_group(rows, cls, axis, group):
    """How many labels of a class are in a group, counted from the frames built above."""
    if axis == "height":
        ids = [r["frame"] for r in rows if (r["ball"]["z"] > 0.5) == (group == "in the air")]
    else:
        ids = [r["frame"] for r in rows if (math.hypot(*r["blur_px"]) > 3) == (group == "blurred")]
    per_frame = len(rows[0]["players"]) if cls == "player" else 1
    return per_frame * len(ids)


def test_the_axis_frames_have_both_groups_and_the_boundaries():
    rows = axis_frames()
    assert in_group(rows, "ball", "height", "in the air") == 12
    assert in_group(rows, "ball", "blur", "blurred") == 16
    assert any(r["ball"]["z"] == IN_AIR_Z for r in rows)
    assert any(r["blur_px"] == [BLUR_PX, 0.0] for r in rows)


@pytest.mark.parametrize("seed", range(4))
@pytest.mark.parametrize(("axis", "group", "other", "classes"), [
    ("height", "in the air", "on the ground", ("ball",)),
    ("height", "on the ground", "in the air", ("ball",)),
    ("blur", "blurred", "not blurred", ("player", "ball")),
    ("blur", "not blurred", "blurred", ("player", "ball")),
])
def test_damage_planted_in_one_group_is_scored_in_that_group(seed, axis, group, other, classes):
    rows, per = axis_frames(), 2
    detections, expected = fake_box_detections(rows, seed=seed, per_damage=per, only={axis: group})
    report = score(rows, detections)
    for cls in classes:
        assert {e[axis] for e in expected["damage"] if e["cls"] == cls} == {group}
        n = in_group(rows, cls, axis, group)
        # From the damage alone: drop and shift_out miss, shift_out and add are false alarms.
        want = {"tp": n - 2 * per, "fp": 2 * per, "fn": 2 * per,
                "recall": (n - 2 * per) / n, "precision": (n - 2 * per) / n}
        got = report[axis][cls][group]
        assert {k: got[k] for k in want} == pytest.approx(want)
        rest = in_group(rows, cls, axis, other)
        assert {k: report[axis][cls][other][k] for k in want} == {
            "tp": rest, "fp": 0, "fn": 0, "recall": 1.0, "precision": 1.0}
    assert disagreements(expected, report) == []


@pytest.mark.parametrize("seed", range(6))
def test_damage_anywhere_is_scored_in_the_right_height_and_blur_groups(seed):
    rows = axis_frames()
    detections, expected = fake_box_detections(rows, seed=seed, per_damage=3)
    assert expected["height"] is not None and expected["blur"] is not None
    assert disagreements(expected, score(rows, detections)) == []


def test_a_height_restriction_leaves_the_players_damage_where_it_falls():
    detections, expected = fake_box_detections(axis_frames(), seed=0, per_damage=2,
                                               only={"height": "in the air"})
    players = [e for e in expected["damage"] if e["cls"] == "player"]
    assert len(players) == 2 * len(DAMAGES) and {e["height"] for e in players} == {None}


def test_an_unknown_axis_or_an_empty_group_is_refused():
    with pytest.raises(ValueError, match="no such axis"):
        fake_box_detections(axis_frames(), seed=0, per_damage=1, only={"weather": "rain"})
    with pytest.raises(ValueError, match="isolated|no ball label"):
        fake_box_detections(frames(), seed=0, per_damage=1, only={"height": "in the air"})


@pytest.mark.parametrize(("name", "value"), [("IN_AIR_Z", 1.5), ("IN_AIR_Z", 0.0),
                                             ("BLUR_PX", 5.0), ("BLUR_PX", 0.0)])
def test_a_scorer_with_a_different_cut_off_disagrees(monkeypatch, name, value):
    # The check can fail (LESSONS 8): the planted groups come from the clip, not from the scorer,
    # so a scorer that moved either cut-off puts some labels in the other group.
    rows = axis_frames()
    detections, expected = fake_box_detections(rows, seed=1, per_damage=2)
    monkeypatch.setattr(vision_score, name, value)
    assert disagreements(expected, score(rows, detections))


@pytest.mark.parametrize(("name", "rule"), [
    ("height_group", lambda z: "in the air" if z >= IN_AIR_Z else "on the ground"),
    ("blur_group", lambda b: "blurred" if math.hypot(*b) >= BLUR_PX else "not blurred"),
    ("blur_group", lambda b: "blurred" if max(abs(v) for v in b) > BLUR_PX else "not blurred"),
])
def test_a_scorer_that_moved_a_boundary_disagrees(monkeypatch, name, rule):
    # At the boundary values the frames contain: exactly 0.5 m, exactly 3 px, and a streak whose
    # parts are each under 3 px but whose length is over.
    rows = axis_frames()
    detections, expected = fake_box_detections(rows, seed=1, per_damage=2)
    monkeypatch.setattr(vision_score, name, rule)
    assert disagreements(expected, score(rows, detections))


@pytest.mark.parametrize("value", [IN_AIR_Z, math.nextafter(IN_AIR_Z, math.inf), 0.0, 1.3])
def test_the_planted_height_follows_the_scorer_s_cut_off(value):
    assert height_of(value) == vision_score.height_group(value) == (
        "in the air" if value > 0.5 else "on the ground")


@pytest.mark.parametrize("blur", [[BLUR_PX, 0.0], [0.0, -BLUR_PX], [math.nextafter(BLUR_PX, math.inf), 0.0],
                                  [-2.5, 2.5], [0.0, 0.0]])
def test_the_planted_blur_follows_the_scorer_s_cut_off(blur):
    assert blur_of(blur) == vision_score.blur_group(blur) == (
        "blurred" if math.hypot(*blur) > 3 else "not blurred")


def test_frames_without_height_or_blur_expect_no_such_group():
    _, expected = fake_box_detections(frames(), seed=0, per_damage=1)
    assert expected["height"] is None and expected["blur"] is None
