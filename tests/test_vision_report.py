"""The vision report scores only the frozen clips, sums clips correctly and places hidden-ball detections."""

import json

import pytest

from ninety.eval import vision_report
from ninety.render.checks import digest

MODEL = {"name": "rf-detr", "size": "small", "version": "1.11.2", "checkpoint": "ours-v2"}


def write_clip(root, seed, ball_vis=1.0):
    d = root / f"seed{seed}"
    (d / "images").mkdir(parents=True)
    (d / "images" / "00000.jpg").write_bytes(b"jpg")
    frame = {
        "frame": 0, "camera": {"width": 1280, "height": 720},
        "players": [{"id": "h1", "bbox": [100, 100, 120, 160], "visibility": 1.0}],
        "ball": {"bbox": [300, 300, 309, 309], "visibility": ball_vis},
    }
    (d / "frames.jsonl").write_text(json.dumps(frame) + "\n")
    (d / "events.jsonl").write_text("")
    return d


def write_dets(det_dir, seed, dets, checkpoint="ours-v2"):
    det_dir.mkdir(exist_ok=True)
    row = {"clip": f"seed{seed}", "frame": 0, "t": 0.0, "model": {**MODEL, "checkpoint": checkpoint},
           "detections": dets}
    (det_dir / f"seed{seed}.jsonl").write_text(json.dumps(row) + "\n")


def freeze_of(test, seeds):
    clips = [
        {"seed": s, "digest": digest(test / f"seed{s}"), "params": {"occlusion": k, "kit_contrast": "normal"}}
        for s, k in zip(seeds, ["crowded", "natural", "crowded"], strict=False)
    ]
    return {"tag": "t", "commit": "c", "clips": clips}


PLAYER = {"cls": "player", "bbox": [100, 100, 120, 160], "score": 0.9}
BALL_ON = {"cls": "ball", "bbox": [300, 300, 309, 309], "score": 0.9}
BALL_AT_FEET = {"cls": "ball", "bbox": [105, 155, 114, 164], "score": 0.9}


def test_clips_are_scored_separately_and_summed(tmp_path):
    # both clips use frame 0: scored together, one clip's detection could match the other's label
    test, dets = tmp_path / "test", tmp_path / "dets"
    write_clip(test, 1)
    write_clip(test, 2)
    write_dets(dets, 1, [PLAYER, BALL_ON])
    write_dets(dets, 2, [PLAYER])
    r = vision_report.build(test, dets, freeze_of(test, [1, 2]))
    assert r["frames_scored"] == 2
    assert {k: r["by_class"]["ball"][k] for k in ("tp", "fp", "fn")} == {"tp": 1, "fp": 0, "fn": 1}
    assert r["by_class"]["ball"]["recall"] == 0.5
    assert r["overall"]["tp"] == 3
    assert r["visibility"]["ball"]["visible"]["fn"] == 1
    assert r["ball_at_least_half_visible"]["recall"] == 0.5


def test_a_clip_that_is_not_the_frozen_one_is_refused(tmp_path):
    test, dets = tmp_path / "test", tmp_path / "dets"
    write_clip(test, 1)
    write_dets(dets, 1, [PLAYER])
    freeze = freeze_of(test, [1])
    labels = test / "seed1" / "frames.jsonl"
    labels.write_text(labels.read_text().replace("300", "301"))
    with pytest.raises(ValueError, match="frames_jsonl"):
        vision_report.build(test, dets, freeze)


def test_detections_from_two_checkpoints_are_refused(tmp_path):
    test, dets = tmp_path / "test", tmp_path / "dets"
    write_clip(test, 1)
    write_clip(test, 2)
    write_dets(dets, 1, [PLAYER])
    write_dets(dets, 2, [PLAYER], checkpoint="coco")
    with pytest.raises(ValueError, match="not one checkpoint"):
        vision_report.build(test, dets, freeze_of(test, [1, 2]))


@pytest.mark.parametrize("ball, on_it", [(BALL_ON, 1), (BALL_AT_FEET, 0)])
def test_hidden_ball_frames_say_where_the_detection_lands(tmp_path, ball, on_it):
    test, dets = tmp_path / "test", tmp_path / "dets"
    write_clip(test, 1, ball_vis=0.0)
    write_dets(dets, 1, [PLAYER, ball])
    r = vision_report.build(test, dets, freeze_of(test, [1]))
    hidden = r["hidden_ball_frames"]
    counts = (hidden["hidden_balls"], hidden["with_a_ball_detection"], hidden["on_the_hidden_ball"])
    assert counts == (1, 1, on_it)
    assert (hidden["median_distance_px"] == 0.0) == bool(on_it)
    # either way it is a false positive: a fully hidden ball is not a label
    assert (r["by_class"]["ball"]["fp"], r["by_class"]["ball"]["fn"]) == (1, 0)


def test_a_hidden_ball_with_no_confident_detection_is_counted_but_not_hit(tmp_path):
    test, dets = tmp_path / "test", tmp_path / "dets"
    write_clip(test, 1, ball_vis=0.0)
    write_dets(dets, 1, [PLAYER, {**BALL_ON, "score": 0.4}])
    hidden = vision_report.build(test, dets, freeze_of(test, [1]))["hidden_ball_frames"]
    counts = (hidden["hidden_balls"], hidden["with_a_ball_detection"], hidden["median_distance_px"])
    assert counts == (1, 0, None)


def test_only_a_fully_hidden_ball_counts_as_hidden(tmp_path):
    # visibility 0.3 is mostly hidden but still a label: not a hidden-ball frame
    test, dets = tmp_path / "test", tmp_path / "dets"
    write_clip(test, 1, ball_vis=0.3)
    write_dets(dets, 1, [PLAYER, BALL_ON])
    r = vision_report.build(test, dets, freeze_of(test, [1]))
    assert r["hidden_ball_frames"]["hidden_balls"] == 0
    assert r["visibility"]["ball"]["mostly hidden"]["tp"] == 1


def test_at_least_half_visible_includes_the_partly_hidden_group(tmp_path):
    test, dets = tmp_path / "test", tmp_path / "dets"
    write_clip(test, 1, ball_vis=0.7)
    write_dets(dets, 1, [PLAYER, BALL_ON])
    r = vision_report.build(test, dets, freeze_of(test, [1]))
    assert r["ball_at_least_half_visible"]["tp"] == 1


def test_counts_are_grouped_by_the_clip_knobs(tmp_path):
    test, dets = tmp_path / "test", tmp_path / "dets"
    for s in (1, 2, 3):
        write_clip(test, s)
    write_dets(dets, 1, [PLAYER, BALL_ON])
    write_dets(dets, 2, [PLAYER])
    write_dets(dets, 3, [PLAYER])
    r = vision_report.build(test, dets, freeze_of(test, [1, 2, 3]))
    assert r["by_knob"]["occlusion"]["crowded"]["ball"]["recall"] == 0.5  # seeds 1 and 3
    assert r["by_knob"]["occlusion"]["natural"]["ball"]["recall"] == 0.0
    assert r["by_knob"]["kit_contrast"]["normal"]["ball"]["tp"] == 1
    assert [c["occlusion"] for c in r["by_clip"]] == ["crowded", "natural", "crowded"]


def test_a_detections_file_that_skips_frames_is_refused(tmp_path):
    test, dets = tmp_path / "test", tmp_path / "dets"
    d = write_clip(test, 1)
    labels = d / "frames.jsonl"
    first = json.loads(labels.read_text())
    labels.write_text(labels.read_text() + json.dumps({**first, "frame": 1}) + "\n")
    write_dets(dets, 1, [PLAYER])  # frame 0 only
    with pytest.raises(ValueError, match="did not run on 1 of 2 frames"):
        vision_report.build(test, dets, freeze_of(test, [1]))


def test_a_validation_stride_scores_only_its_frames_and_still_refuses_a_gap(tmp_path):
    test, dets = tmp_path / "test", tmp_path / "dets"
    d = write_clip(test, 1)
    labels = d / "frames.jsonl"
    first = json.loads(labels.read_text())
    labels.write_text(labels.read_text() + json.dumps({**first, "frame": 1}) + "\n")
    write_dets(dets, 1, [PLAYER])  # frame 0: the only frame of stride 2
    report = vision_report.build(test, dets, freeze_of(test, [1]), stride=2)
    assert report["stride"] == 2 and report["frames_scored"] == 1
    labels.write_text(json.dumps({**first, "frame": 7}) + "\n" + json.dumps(first) + "\n")
    with pytest.raises(ValueError, match="did not run on 1 of 1 frames"):
        vision_report.build(test, dets, freeze_of(test, [1]), stride=2)


# --- pitch-level totals: a camera looking straight down at SCALE px per metre, so a shift in
# pixels is a known shift on the pitch ------------------------------------------------------------

SCALE = 100.0
TOP_DOWN = [[SCALE, 0.0, 0.0, 640.0], [0.0, SCALE, 0.0, 360.0], [0.0, 0.0, 0.0, 1.0]]
PLAYER_BOX = [632, 320, 648, 360]  # feet at pitch (0, 0)
BALL_BOX = [835, 155, 845, 165]  # centre at pitch (2, -2)


def write_pitch_clip(root, seed, ball_vis, ball_z, camera=True, blur=None):
    d = root / f"seed{seed}"
    (d / "images").mkdir(parents=True)
    (d / "images" / "00000.jpg").write_bytes(b"jpg")
    cam = {"width": 1280, "height": 720, **({"P": TOP_DOWN} if camera else {})}
    frame = {"frame": 0, "camera": cam, **({"blur_px": blur} if blur is not None else {}),
             "players": [{"id": "h1", "bbox": PLAYER_BOX, "visibility": 1.0}],
             "ball": {"bbox": BALL_BOX, "visibility": ball_vis, "z": ball_z}}
    (d / "frames.jsonl").write_text(json.dumps(frame) + "\n")
    (d / "events.jsonl").write_text("")


def moved(box, metres):
    return [box[0] + metres * SCALE, box[1], box[2] + metres * SCALE, box[3]]


def planted(root, camera=True, blur=(None, None)):
    """Two clips, both on frame 0. Seed 1: the player copied exactly, the ball moved 1.5 m (a strict
    miss and false alarm, a lenient match), a false player 5 m away. Seed 2 (the ball partly hidden
    and in the air): the player moved 1.2 m (strict miss and false alarm, lenient match), no ball.
    `blur` is each clip's camera blur streak, or None for none recorded."""
    test, dets = root / "test", root / "dets"
    write_pitch_clip(test, 1, ball_vis=1.0, ball_z=0.0, camera=camera, blur=blur[0])
    write_pitch_clip(test, 2, ball_vis=0.7, ball_z=1.0, camera=camera, blur=blur[1])
    write_dets(dets, 1, [{"cls": "player", "bbox": PLAYER_BOX, "score": 0.9},
                         {"cls": "ball", "bbox": moved(BALL_BOX, 1.5), "score": 0.9},
                         {"cls": "player", "bbox": moved(PLAYER_BOX, -5.0), "score": 0.9}])
    write_dets(dets, 2, [{"cls": "player", "bbox": moved(PLAYER_BOX, 1.2), "score": 0.9}])
    return vision_report.build(test, dets, freeze_of(test, [1, 2]))


def counts(row):
    return row["tp"], row["fp"], row["fn"]


def test_pitch_counts_are_summed_across_clips(tmp_path):
    pitch = planted(tmp_path)["pitch"]
    strict, lenient = pitch["strict"], pitch["lenient"]
    # From the plant above, clip by clip: (tp, fp, fn)
    assert counts(strict["by_class"]["player"]) == (1, 2, 1)
    assert counts(lenient["by_class"]["player"]) == (2, 1, 0)
    assert counts(strict["by_class"]["ball"]) == (0, 1, 2)
    assert counts(lenient["by_class"]["ball"]) == (1, 0, 1)
    assert counts(strict["overall"]) == (1, 3, 3)
    assert counts(lenient["overall"]) == (3, 1, 1)
    assert lenient["by_class"]["player"]["recall"] == 1.0
    assert lenient["by_class"]["player"]["precision"] == 2 / 3
    assert counts(strict["height"]["ball"]["on the ground"]) == (0, 1, 1)
    assert counts(strict["height"]["ball"]["in the air"]) == (0, 0, 1)
    assert counts(lenient["height"]["ball"]["on the ground"]) == (1, 0, 0)
    assert counts(lenient["visibility"]["ball"]["partly hidden"]) == (0, 0, 1)
    assert counts(strict["ball_at_least_half_visible"]) == (0, 1, 2)
    assert counts(lenient["ball_at_least_half_visible"]) == (1, 0, 1)
    assert pitch["unplaced"] == {"labels": 0, "detections": 0}


def test_the_pitch_block_leaves_the_pixel_totals_unchanged(tmp_path):
    with_cameras = planted(tmp_path / "a")
    without = planted(tmp_path / "b", camera=False)
    assert without["pitch"] is None
    for key in ("overall", "by_class", "visibility", "image_boundary", "ball_at_least_half_visible",
                "by_knob", "by_clip", "hidden_ball_frames", "frames_scored"):
        assert with_cameras[key] == without[key]


def test_clips_with_and_without_saved_cameras_are_refused(tmp_path):
    test, dets = tmp_path / "test", tmp_path / "dets"
    write_pitch_clip(test, 1, 1.0, 0.0)
    write_pitch_clip(test, 2, 1.0, 0.0, camera=False)
    write_dets(dets, 1, [])
    write_dets(dets, 2, [])
    with pytest.raises(ValueError, match="saved camera"):
        vision_report.build(test, dets, freeze_of(test, [1, 2]))


def test_pitch_counts_only_the_frames_a_validation_stride_ran(tmp_path):
    # Two labelled frames, detector run on frame 0 only (stride 2): frame 1's player and ball are
    # not misses (lesson 48), so the exact copies on frame 0 give recall 1.0 under both rules.
    test, dets = tmp_path / "test", tmp_path / "dets"
    write_pitch_clip(test, 1, 1.0, 0.0)
    d = test / "seed1"
    row = json.loads((d / "frames.jsonl").read_text())
    (d / "frames.jsonl").write_text(json.dumps(row) + "\n" + json.dumps({**row, "frame": 1}) + "\n")
    (d / "images" / "00001.jpg").write_bytes(b"jpg")
    write_dets(dets, 1, [{"cls": "player", "bbox": PLAYER_BOX, "score": 0.9},
                         {"cls": "ball", "bbox": BALL_BOX, "score": 0.9}])
    pitch = vision_report.build(test, dets, freeze_of(test, [1]), stride=2)["pitch"]
    for rule in ("strict", "lenient"):
        assert counts(pitch[rule]["overall"]) == (2, 0, 0)


# --- the ball's height and the camera's blur, totalled across clips ------------------------------

BLURRED, SHARP = [4.0, 0.0], [3.0, 0.0]  # longer than 3 px; exactly 3 px, which is not blurred


def test_height_and_blur_counts_are_summed_across_clips(tmp_path):
    r = planted(tmp_path, blur=(BLURRED, SHARP))
    # In pixels every moved box misses its label (100 px a metre), so from the plant, clip by clip:
    # seed 1 (blurred, ball on the ground): player found plus a false player; ball missed plus a false ball.
    # seed 2 (not blurred, ball in the air): player missed plus a false player; ball missed.
    assert counts(r["height"]["ball"]["on the ground"]) == (0, 1, 1)
    assert counts(r["height"]["ball"]["in the air"]) == (0, 0, 1)
    assert counts(r["blur"]["player"]["blurred"]) == (1, 1, 0)
    assert counts(r["blur"]["player"]["not blurred"]) == (0, 1, 1)
    assert counts(r["blur"]["ball"]["blurred"]) == (0, 1, 1)
    assert counts(r["blur"]["ball"]["not blurred"]) == (0, 0, 1)
    assert r["blur"]["player"]["blurred"]["precision"] == 0.5
    assert r["blur"]["player"]["blurred"]["recall"] == 1.0
    strict, lenient = r["pitch"]["strict"]["blur"], r["pitch"]["lenient"]["blur"]
    assert counts(strict["player"]["blurred"]) == (1, 1, 0)
    assert counts(strict["player"]["not blurred"]) == (0, 1, 1)
    assert counts(lenient["player"]["not blurred"]) == (1, 0, 0)
    assert counts(strict["ball"]["blurred"]) == (0, 1, 1)
    assert counts(lenient["ball"]["blurred"]) == (1, 0, 0)
    assert counts(lenient["ball"]["not blurred"]) == (0, 0, 1)


def test_the_new_groups_leave_the_existing_totals_unchanged(tmp_path):
    with_blur = planted(tmp_path / "a", blur=(BLURRED, SHARP))
    without = planted(tmp_path / "b")
    assert without["blur"] is None
    assert without["pitch"]["strict"]["blur"] is None and without["pitch"]["lenient"]["blur"] is None
    assert without["height"] == with_blur["height"]  # both clips record the ball's height
    for key in ("overall", "by_class", "visibility", "image_boundary", "ball_at_least_half_visible",
                "by_knob", "by_clip", "hidden_ball_frames", "frames_scored"):
        assert with_blur[key] == without[key]
    for rule in ("strict", "lenient"):
        assert ({k: v for k, v in with_blur["pitch"][rule].items() if k != "blur"}
                == {k: v for k, v in without["pitch"][rule].items() if k != "blur"})


def test_clips_without_a_ball_height_report_no_height_group(tmp_path):
    test, dets = tmp_path / "test", tmp_path / "dets"
    write_clip(test, 1)
    write_dets(dets, 1, [PLAYER, BALL_ON])
    r = vision_report.build(test, dets, freeze_of(test, [1]))
    assert r["height"] is None and r["blur"] is None


def test_clips_with_and_without_blur_are_refused(tmp_path):
    test, dets = tmp_path / "test", tmp_path / "dets"
    write_pitch_clip(test, 1, 1.0, 0.0, blur=BLURRED)
    write_pitch_clip(test, 2, 1.0, 0.0)
    write_dets(dets, 1, [])
    write_dets(dets, 2, [])
    with pytest.raises(ValueError, match="record the blur groups"):
        vision_report.build(test, dets, freeze_of(test, [1, 2]))
