"""The fetcher takes exactly what training reads, and never a test seed."""

import json

import pytest

from ninety.vision.fetch_clips import plan, plan_list, read_list, wanted


def test_keeps_labels_and_every_fifth_frame():
    assert wanted("v2/train/seed3/clip.json", "v2", 5) == (3, "clip.json")
    assert wanted("v2/train/seed3/frames.jsonl", "v2", 5) == (3, "frames.jsonl")
    assert wanted("v2/train/seed3/images/00010.jpg", "v2", 5) == (3, "images/00010.jpg")
    assert wanted("v2/train/seed3/images/00011.jpg", "v2", 5) is None
    assert wanted("v2/train/seed3/events.jsonl", "v2", 5) is None
    assert wanted("v1/train/seed3/clip.json", "v2", 5) is None  # another run
    assert wanted("v2/failed/seed9.json", "v2", 5) is None


def test_frames_match_what_coco_export_keeps():
    names = [f"v2/train/seed3/images/{i:05d}.jpg" for i in range(250)]
    kept = [rel for _, _, rel in plan(names, "v2", 5)]
    assert kept == [f"images/{i:05d}.jpg" for i in range(0, 250, 5)]


def test_a_test_seed_is_refused():
    with pytest.raises(ValueError, match="not a training seed"):
        plan(["v2/train/seed900001/clip.json"], "v2", 5)


def test_a_seed_from_an_earlier_run_is_not_fetched_again():
    names = ["v2/train/seed2001/clip.json", "v2/train/seed3/clip.json"]
    assert [s for _, s, _ in plan(names, "v2", 5, frozenset({2001}))] == [3]


def clip_blobs(run, seed, frames=10):
    return [f"{run}/train/seed{seed}/clip.json"] + [
        f"{run}/train/seed{seed}/images/{i:05d}.jpg" for i in range(frames)
    ]


def test_a_list_takes_each_seed_from_the_run_it_names_and_nothing_else():
    # seed 4 is in both runs and the list takes it from v3boards; seed 5 is in v3 but not listed
    names = {"v3": clip_blobs("v3", 3) + clip_blobs("v3", 4) + clip_blobs("v3", 5),
             "v3boards": clip_blobs("v3boards", 4)}
    media, truth = plan_list(names, {3: "v3", 4: "v3boards"}, 5)
    assert {(n.split("/")[0], s) for n, s, _ in media} == {("v3", 3), ("v3boards", 4)}
    kept = sorted(rel for _, s, rel in media if s == 3)
    assert kept == ["clip.json", "images/00000.jpg", "images/00005.jpg"]
    assert truth == [("v3/train/seed3/frames.jsonl", 3, "frames.jsonl"),
                     ("v3boards/train/seed4/frames.jsonl", 4, "frames.jsonl")]


def test_labels_come_from_the_truth_container_not_renders():
    # a run from before the truth was sealed still has frames.jsonl in renders: a list fetch ignores it
    names = {"v3": clip_blobs("v3", 3) + ["v3/train/seed3/frames.jsonl"]}
    media, truth = plan_list(names, {3: "v3"}, 5)
    assert "frames.jsonl" not in {rel for _, _, rel in media}
    assert [rel for _, _, rel in truth] == ["frames.jsonl"]


def test_a_listed_seed_missing_from_its_run_is_an_error():
    with pytest.raises(ValueError, match=r"no clip.json in their run: \[4\]"):
        plan_list({"v3": clip_blobs("v3", 3) + clip_blobs("v3", 4)}, {3: "v3", 4: "v3boards"}, 5)


def write_list(tmp_path, clips):
    p = tmp_path / "dataset.json"
    p.write_text(json.dumps({"clips_list": clips}))
    return p


def test_a_list_refuses_a_test_seed_and_a_seed_twice(tmp_path):
    assert read_list(write_list(tmp_path, [{"seed": 3, "run": "v3"}])) == {3: "v3"}
    with pytest.raises(ValueError, match="not a training seed"):
        read_list(write_list(tmp_path, [{"seed": 900001, "run": "v3"}]))
    with pytest.raises(ValueError, match="twice"):
        read_list(write_list(tmp_path, [{"seed": 3, "run": "v3"}, {"seed": 3, "run": "v3boards"}]))
