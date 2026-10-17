"""The fetcher takes exactly what training reads, and never a test seed."""

import pytest

from ninety.vision.fetch_clips import plan, wanted


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
