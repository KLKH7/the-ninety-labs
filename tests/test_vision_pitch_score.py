"""Pitch-level scoring of detections (ninety/eval/vision_pitch_score.py) and its planted damage
(ninety/eval/fake_box_detections.py), on frames built here."""

import json
import math

import pytest

from ninety.eval import event_score, pitch_score, vision_score
from ninety.eval.fake_box_detections import (
    PITCH_DAMAGES,
    fake_pitch_detections,
    pitch_disagreements,
    pitch_shift_m,
)
from ninety.eval.vision_pitch_score import (
    BALL_CENTRE_Z,
    IN_AIR_Z,
    PLAYER_LENIENT_M,
    RADIUS_M,
    has_cameras,
    place,
    score_pitch,
    to_ground,
)

W, H = 1280, 720
# A saved camera from a rendered clip (the main gantry, looking up the pitch at about x 53, y 45).
CAMERA = [[3346.877682, 637.544378, -89.040782, -153738.181593],
          [0.122991, -109.239073, -3365.122304, 46771.259851],
          [-0.001115, 0.990274, -0.139126, 37.26842]]
VISIBILITIES = (1.0, 0.7, 0.3)  # one in each group: visible, partly hidden, mostly hidden


def project(P, x, y, z):
    h = [P[i][0] * x + P[i][1] * y + P[i][2] * z + P[i][3] for i in range(3)]
    return h[0] / h[2], h[1] / h[2]


def player_box(P, x, y):
    u, v = project(P, x, y, 0.0)
    return [u - 8, v - 40, u + 8, v]


def ball_box(P, x, y, z):
    u, v = project(P, x, y, z + BALL_CENTRE_Z)
    return [u - 5, v - 5, u + 5, v + 5]


def frames(n=12, P=CAMERA):
    """Players 5 m apart (further than any damage reaches plus the lenient radius), a crowd of two
    players 0.5 m apart that no damage may touch, and a ball on the ground or in the air."""
    rows = []
    for f in range(n):
        spots = [(43.0 + 5 * i, 40.0 + 5 * j) for i in range(5) for j in range(3)]
        players = [{"id": f"p{k}", "x": x, "y": y, "bbox": player_box(P, x, y),
                    "visibility": VISIBILITIES[(f + k) % 3]} for k, (x, y) in enumerate(spots)]
        players += [{"id": f"c{k}", "x": 66.0 + 0.5 * k, "y": 52.0,
                     "bbox": player_box(P, 66.0 + 0.5 * k, 52.0), "visibility": 1.0} for k in range(2)]
        z = 0.0 if f % 2 else 1.0
        bx, by = 45.0 + f, 47.5
        rows.append({"frame": f, "clip": "seed1", "camera": {"width": W, "height": H, "P": P},
                     "players": players,
                     "ball": {"x": bx, "y": by, "z": z, "bbox": ball_box(P, bx, by, z),
                              "visibility": VISIBILITIES[f % 3]}})
    return rows


def copies(rows):
    return [{"frame": r["frame"], "cls": cls, "bbox": list(o["bbox"]), "score": 1.0}
            for r in rows for cls, o in [*(("player", p) for p in r["players"]), ("ball", r["ball"])]]


def test_the_frames_are_in_the_image():
    for row in frames():
        for obj in [*row["players"], row["ball"]]:
            x0, y0, x1, y1 = obj["bbox"]
            assert 0 < x0 < x1 < W and 0 < y0 < y1 < H


# --- the rule ---------------------------------------------------------------------------------


def test_the_radii_are_the_ones_in_evaluation_md_and_the_event_scorer_s():
    assert RADIUS_M == {"strict": {"player": 1.0, "ball": 1.0}, "lenient": {"player": 1.5, "ball": 2.0}}
    assert RADIUS_M["strict"]["player"] is event_score.STRICT_M
    assert RADIUS_M["strict"]["ball"] is event_score.STRICT_M
    assert RADIUS_M["lenient"]["ball"] is event_score.LENIENT_M
    assert IN_AIR_Z == 0.5  # EVALUATION.md: in the air is a height above 0.5 m


def test_the_ball_s_height_on_the_ground_is_event_detection_s():
    observe = pytest.importorskip("ninety.vision.observe")
    assert BALL_CENTRE_Z == observe.BALL_CENTRE_Z


def test_the_position_scorer_uses_the_pixel_scorer_s_rule():
    assert pitch_score.PLAYER_IOU is vision_score.PLAYER_IOU
    assert pitch_score.BALL_PX is vision_score.BALL_DISTANCE_PX
    assert pitch_score.SCORE_MIN is vision_score.DEFAULT_THRESHOLD
    assert pitch_score.GROUND_Z is IN_AIR_Z


@pytest.mark.parametrize(("x", "y", "z"), [(53.0, 45.0, 0.0), (40.2, 61.7, 0.0), (60.0, 38.0, 1.3)])
def test_a_point_goes_back_to_where_the_camera_drew_it(x, y, z):
    u, v = project(CAMERA, x, y, z)
    gx, gy = to_ground(CAMERA, u, v, z)
    assert math.dist((gx, gy), (x, y)) < 1e-6


def test_a_pixel_above_the_horizon_has_no_place():
    # The camera looks along +y and down; a pixel far above the image centre sees the sky.
    assert to_ground(CAMERA, 640, -5000, 0.0) is None


def test_a_player_is_placed_at_his_feet_and_the_ball_at_its_centre():
    assert math.dist(place("player", player_box(CAMERA, 50.0, 45.0), CAMERA), (50.0, 45.0)) < 1e-6
    assert math.dist(place("ball", ball_box(CAMERA, 50.0, 45.0, 0.0), CAMERA), (50.0, 45.0)) < 1e-6


# --- boundaries, on a camera looking straight down at SCALE px per metre ------------------------

SCALE = 100.0
TOP_DOWN = [[SCALE, 0.0, 0.0, 640.0], [0.0, SCALE, 0.0, 360.0], [0.0, 0.0, 0.0, 1.0]]
ONE_PX_M = 1 / SCALE


def one(cls, label_box, found_box, z=0.0):
    row = {"frame": 0, "clip": "seed1", "camera": {"width": W, "height": H, "P": TOP_DOWN},
           "players": [{"bbox": label_box, "visibility": 1.0}] if cls == "player" else [],
           "ball": ({"bbox": label_box, "visibility": 1.0, "z": z} if cls == "ball"
                    else {"bbox": None, "visibility": 0.0, "z": 0.0})}
    return score_pitch([row], [{"frame": 0, "cls": cls, "bbox": found_box, "score": 1.0}])


def shifted(box, metres):
    return [box[0] + metres * SCALE, box[1], box[2] + metres * SCALE, box[3]]


@pytest.mark.parametrize("cls", ["player", "ball"])
@pytest.mark.parametrize("rule", ["strict", "lenient"])
def test_exactly_the_radius_matches_and_one_pixel_past_it_misses(cls, rule):
    box = [600.0, 300.0, 616.0, 340.0] if cls == "player" else [600.0, 300.0, 610.0, 310.0]
    radius = RADIUS_M[rule][cls]
    assert one(cls, box, shifted(box, radius))[rule]["by_class"][cls]["tp"] == 1
    past = one(cls, box, shifted(box, radius + ONE_PX_M))[rule]["by_class"][cls]
    assert (past["tp"], past["fp"], past["fn"]) == (0, 1, 1)


@pytest.mark.parametrize("cls", ["player", "ball"])
def test_just_past_the_strict_radius_is_a_strict_miss_but_a_lenient_match(cls):
    box = [600.0, 300.0, 616.0, 340.0] if cls == "player" else [600.0, 300.0, 610.0, 310.0]
    assert RADIUS_M["strict"][cls] + ONE_PX_M < RADIUS_M["lenient"][cls]
    report = one(cls, box, shifted(box, RADIUS_M["strict"][cls] + ONE_PX_M))
    assert report["strict"]["by_class"][cls]["recall"] == 0.0
    assert report["lenient"]["by_class"][cls]["recall"] == 1.0
    assert PLAYER_LENIENT_M == RADIUS_M["lenient"]["player"]


def test_a_player_is_matched_by_his_feet_not_his_box_centre():
    # Same foot point, a box twice as tall: the centre moves, the feet do not.
    box = [600.0, 300.0, 616.0, 340.0]
    tall = [600.0, 260.0, 616.0, 340.0]
    assert one("player", box, tall)["strict"]["by_class"]["player"]["tp"] == 1


def test_nearest_first_and_one_to_one():
    box = [600.0, 300.0, 616.0, 340.0]
    row = {"frame": 0, "clip": "seed1", "camera": {"width": W, "height": H, "P": TOP_DOWN},
           "players": [{"bbox": box, "visibility": 1.0}], "ball": {"bbox": None, "visibility": 0.0, "z": 0}}
    far, near = shifted(box, 0.6), shifted(box, 0.2)
    report = score_pitch([row], [{"frame": 0, "cls": "player", "bbox": b, "score": 1.0} for b in (far, near)])
    strict = report["strict"]["by_class"]["player"]
    assert (strict["tp"], strict["fp"], strict["fn"]) == (1, 1, 0)
    assert report["strict"]["distance_m"]["max"] == pytest.approx(0.2)


def test_a_detection_under_the_score_threshold_is_not_counted():
    box = [600.0, 300.0, 616.0, 340.0]
    row = {"frame": 0, "camera": {"width": W, "height": H, "P": TOP_DOWN},
           "players": [{"bbox": box, "visibility": 1.0}], "ball": {"bbox": None, "visibility": 0.0, "z": 0}}
    found = [{"frame": 0, "cls": "player", "bbox": box, "score": vision_score.DEFAULT_THRESHOLD - 0.01}]
    assert score_pitch([row], found)["strict"]["overall"]["fp"] == 0
    found[0]["score"] = vision_score.DEFAULT_THRESHOLD
    assert score_pitch([row], found)["strict"]["overall"]["tp"] == 1


@pytest.mark.parametrize(("z", "group"), [(IN_AIR_Z, "on the ground"), (IN_AIR_Z + 0.001, "in the air"),
                                          (0.0, "on the ground")])
def test_the_ball_is_in_the_air_above_the_cut_off(z, group):
    box = [600.0, 300.0, 610.0, 310.0]
    height = one("ball", box, box, z=z)["strict"]["height"]["ball"]
    assert height[group]["tp"] == 1
    assert sum(g["tp"] for g in height.values()) == 1


def test_a_box_with_no_place_is_a_miss_and_a_false_alarm():
    sky = [600.0, -6000.0, 616.0, -5960.0]
    row = {"frame": 0, "camera": {"width": W, "height": H, "P": CAMERA},
           "players": [{"bbox": sky, "visibility": 1.0}], "ball": {"bbox": None, "visibility": 0.0, "z": 0}}
    report = score_pitch([row], [{"frame": 0, "cls": "player", "bbox": sky, "score": 1.0}])
    assert report["unplaced"] == {"labels": 1, "detections": 1}
    row = report["lenient"]["overall"]
    assert (row["tp"], row["fp"], row["fn"]) == (0, 1, 1)


def test_only_run_frames_are_scored_and_a_frame_without_a_camera_is_refused():
    rows = frames(2)
    report = score_pitch(rows, [d for d in copies(rows) if d["frame"] == 0], run={0})
    assert report["strict"]["overall"]["fn"] == 0
    rows[1]["camera"].pop("P")
    with pytest.raises(ValueError, match="saved camera matrix"):
        score_pitch(rows, copies(rows))
    with pytest.raises(ValueError, match="some frames"):
        has_cameras(rows)
    assert score_pitch(rows, [d for d in copies(rows) if d["frame"] == 0], run={0})


# --- a perfect copy and planted damage ---------------------------------------------------------


def test_a_perfect_copy_scores_one():
    rows = frames()
    report = score_pitch(rows, copies(rows))
    for rule in ("strict", "lenient"):
        for cls in ("player", "ball"):
            row = report[rule]["by_class"][cls]
            assert row["recall"] == row["precision"] == 1.0
        for group in ("on the ground", "in the air"):
            assert report[rule]["height"]["ball"][group]["recall"] == 1.0
    detections, expected = fake_pitch_detections(rows, seed=0, per_damage=0)
    assert pitch_disagreements(expected, score_pitch(rows, detections)) == []


def test_the_shifts_sit_either_side_of_the_radii():
    for cls in ("player", "ball"):
        shift, strict, lenient = pitch_shift_m(cls), RADIUS_M["strict"][cls], RADIUS_M["lenient"][cls]
        assert shift["shift_in"] < strict < shift["shift_mid"] < lenient < shift["shift_out"]


@pytest.mark.parametrize("seed", range(6))
def test_the_pitch_scorer_reports_exactly_what_was_planted(seed):
    rows, per = frames(), 2
    detections, expected = fake_pitch_detections(rows, seed=seed, per_damage=per)
    labels = {"player": sum(len(r["players"]) for r in rows), "ball": len(rows)}
    # From the damage alone: drop misses under both rules, shift_mid under strict only, shift_out
    # under both; shift_mid, shift_out and add are false alarms where they miss.
    for cls in ("player", "ball"):
        strict, lenient = expected["strict"]["by_class"][cls], expected["lenient"]["by_class"][cls]
        assert (strict["tp"], strict["fp"], strict["fn"]) == (labels[cls] - 3 * per, 3 * per, 3 * per)
        assert (lenient["tp"], lenient["fp"], lenient["fn"]) == (labels[cls] - 2 * per, 2 * per, 2 * per)
    kinds = [(e["cls"], e["damage"]) for e in expected["damage"]]
    assert sorted(kinds) == sorted((c, d) for c in ("player", "ball") for d in PITCH_DAMAGES
                                   for _ in range(per))
    assert pitch_disagreements(expected, score_pitch(rows, detections)) == []


def test_damage_never_touches_the_crowd():
    rows = frames()
    crowd = {(r["frame"], tuple(p["bbox"])) for r in rows for p in r["players"] if p["id"].startswith("c")}
    detections, _ = fake_pitch_detections(rows, seed=3, per_damage=2)
    kept = {(d["frame"], tuple(d["bbox"])) for d in detections}
    assert crowd <= kept


def test_a_scorer_that_ignored_the_radius_would_be_caught():
    rows = frames()
    detections, expected = fake_pitch_detections(rows, seed=1, per_damage=2)
    report = score_pitch(rows, detections)
    report["strict"] = report["lenient"]  # as if strict used the lenient radius
    assert pitch_disagreements(expected, report)


def test_the_cli_reports_pitch_numbers_beside_the_pixel_numbers(tmp_path, capsys):
    rows = frames(2)
    (tmp_path / "frames.jsonl").write_text("".join(json.dumps(r) + "\n" for r in rows))
    model = {"name": "rf-detr", "size": "small", "version": "test", "checkpoint": "coco"}
    lines = [json.dumps({"clip": "seed1", "frame": r["frame"], "t": r["frame"] / 25, "model": model,
                         "detections": [{k: v for k, v in d.items() if k != "frame"}
                                        for d in copies(rows) if d["frame"] == r["frame"]]}) + "\n"
             for r in rows]
    (tmp_path / "det.jsonl").write_text("".join(lines))
    vision_score.main(["--frames", str(tmp_path / "frames.jsonl"), "--detected", str(tmp_path / "det.jsonl")])
    report = json.loads(capsys.readouterr().out)
    assert report["overall"]["recall"] == 1.0
    pitch = report["pitch"]
    assert pitch["strict"]["overall"]["recall"] == pitch["lenient"]["overall"]["recall"] == 1.0


def test_the_fake_detections_cli_checks_the_pitch_too(tmp_path, capsys):
    from ninety.eval.fake_box_detections import main

    clip = tmp_path / "seed1"
    clip.mkdir()
    (clip / "frames.jsonl").write_text("".join(json.dumps(r) + "\n" for r in frames()))
    with pytest.raises(SystemExit) as done:
        main([str(clip)])
    assert done.value.code == 0
    rows = [json.loads(line) for line in capsys.readouterr().out.splitlines()]
    assert [r.get("pitch", False) for r in rows] == [False, True]
    assert all(r["agrees"] for r in rows)


def test_one_detection_never_matches_two_labels():
    a, b = [600.0, 300.0, 616.0, 340.0], [640.0, 300.0, 656.0, 340.0]  # feet 0.4 m apart
    row = {"frame": 0, "camera": {"width": W, "height": H, "P": TOP_DOWN},
           "players": [{"bbox": a, "visibility": 1.0}, {"bbox": b, "visibility": 1.0}],
           "ball": {"bbox": None, "visibility": 0.0, "z": 0}}
    between = shifted(a, 0.2)
    strict = score_pitch([row], [{"frame": 0, "cls": "player", "bbox": between, "score": 1.0}])["strict"]
    assert (strict["overall"]["tp"], strict["overall"]["fp"], strict["overall"]["fn"]) == (1, 0, 1)


@pytest.mark.parametrize("z", [0.0, IN_AIR_Z, IN_AIR_Z + 0.001, 1.3])
def test_the_planted_height_groups_follow_the_same_cut_off(z):
    from ninety.eval.fake_box_detections import height_of
    from ninety.eval.vision_pitch_score import height_group

    assert height_of(z) == height_group(z) == ("in the air" if z > 0.5 else "on the ground")


@pytest.mark.parametrize("seed", range(6))
def test_a_false_box_lands_further_than_the_lenient_radius_from_every_label(seed):
    rows = frames()
    _, expected = fake_pitch_detections(rows, seed=seed, per_damage=2)
    adds = [e for e in expected["damage"] if e["damage"] == "add"]
    assert len(adds) == 4
    for entry in adds:
        row, cls = rows[entry["frame"]], entry["cls"]
        truth = [p["bbox"] for p in row["players"]] if cls == "player" else [row["ball"]["bbox"]]
        spot = place(cls, entry["bbox"], CAMERA)
        assert all(math.dist(spot, place(cls, t, CAMERA)) > RADIUS_M["lenient"][cls] for t in truth)
