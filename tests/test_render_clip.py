"""End-to-end render checks (guide section 6) on a short clip, in headless Chromium.

Skipped when three.js or Chromium is not installed, unless NINETY_REQUIRE_RENDER=1 (the CI render
job sets it, so the checks can never silently stop running there).
"""

import json
import os
from pathlib import Path

import pytest
from jsonschema import validate

from ninety.render.checks import check_clip, digest, load_clip
from ninety.render.clip import RenderUnavailable, browser_page, render_clip
from ninety.validate import validate as validate_clip

ROOT = Path(__file__).resolve().parent.parent
FRAME_SCHEMA = json.loads((ROOT / "schemas/frame.schema.json").read_text())
EVENT_SCHEMA = json.loads((ROOT / "schemas/match_event.schema.json").read_text())
SECONDS = 1.6
OVERRIDES = {"occlusion": "crowded", "kit_contrast": "low"}


@pytest.fixture(scope="module")
def page():
    try:
        with browser_page() as (pg, _):
            yield pg
    except RenderUnavailable as e:
        if os.environ.get("NINETY_REQUIRE_RENDER") == "1":
            raise
        pytest.skip(str(e))


@pytest.fixture(scope="module")
def clips(page, tmp_path_factory):
    root = tmp_path_factory.mktemp("render")
    a, b = root / "a", root / "b"
    render_clip(11, a, seconds=SECONDS, overrides=OVERRIDES, page=page)
    render_clip(11, b, seconds=SECONDS, overrides=OVERRIDES, page=page)
    return a, b


def test_ground_truth_validates_against_the_schemas(clips):
    clip, frames, events = load_clip(clips[0])
    assert len(frames) == round(SECONDS * 25)
    for fr in frames:
        validate(fr, FRAME_SCHEMA)
    for ev in events:
        validate(ev, EVENT_SCHEMA)
    assert clip["seed"] == 11 and clip["split"] == "train"
    assert clip["params"]["kit_contrast"] == "low" and clip["overrides"] == OVERRIDES


def test_a_rendered_clip_meets_the_data_contract(clips):
    # AGENTS.md: every clip passes `ninety-validate`. The renderer once wrote no meta.json, so
    # every rendered clip failed C1 and no training clip was checked against the contract.
    assert validate_clip(clips[0]) == {}
    meta = json.loads((clips[0] / "meta.json").read_text())
    assert {r["role"] for r in meta["roster"]} >= {"GK"} and len(meta["roster"]) == 22
    assert check_clip(clips[0])["passed"]["data_contract"]


def test_projection_error_under_one_pixel(clips):
    r = check_clip(clips[0])
    assert r["projection"]["ball_px"]["n"] > 0
    assert r["projection"]["ball_px"]["max"] < 1.0
    assert r["projection"]["keypoint_px"]["max"] < 1.0
    assert r["projection"]["player_foot_outside_box"] == 0


def test_boxes_match_visible_players_and_no_frame_misses_labels(clips):
    r = check_clip(clips[0])
    assert r["labels"]["ok"], r["labels"]["problems"]
    _, frames, _ = load_clip(clips[0])
    for fr in frames:
        w, h = fr["camera"]["width"], fr["camera"]["height"]
        drawn = [p for p in fr["players"] if p["bbox"]]
        assert drawn, "the camera must always have players in shot"
        for p in drawn:
            x0, y0, x1, y1 = p["bbox"]
            assert 0 <= x0 < x1 <= w and 0 <= y0 < y1 <= h
            assert p["pixels"] > 0
        for k in fr["keypoints"]:
            assert 0 <= k["px"] < w and 0 <= k["py"] < h


def test_same_seed_same_pixels_and_labels(clips):
    a, b = digest(clips[0]), digest(clips[1])
    assert a["image_count"] == round(SECONDS * 25)
    assert a == b


def test_images_are_720p_jpeg(clips):
    first = sorted((clips[0] / "images").glob("*.jpg"))[0].read_bytes()
    assert first[:2] == b"\xff\xd8"
    # SOF0 marker holds height then width
    i = first.index(b"\xff\xc0")
    h, w = int.from_bytes(first[i + 5 : i + 7], "big"), int.from_bytes(first[i + 7 : i + 9], "big")
    assert (w, h) == (1280, 720)
