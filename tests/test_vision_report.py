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
