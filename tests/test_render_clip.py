"""End-to-end render checks (guide section 6) on a short clip, in headless Chromium.

Skipped when three.js or Chromium is not installed, unless NINETY_REQUIRE_RENDER=1 (the CI render
job sets it, so the checks can never silently stop running there).
"""

import base64
import json
import os
import shutil
from pathlib import Path
from types import SimpleNamespace

import pytest
from jsonschema import validate

from ninety.render import edit
from ninety.render.camera import CUT_HOLD_S
from ninety.render.checks import check_clip, digest, load_clip
from ninety.render.cli import meta_main
from ninety.render.clip import SIM_MARGIN_S, RenderUnavailable, browser_page, render_clip
from ninety.sim.engine import simulate
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


def test_meta_is_rebuilt_from_the_clips_own_files(clips, tmp_path):
    """`ninety-render-meta` backfills clips rendered before the renderer wrote meta.json."""
    old = tmp_path / "old"
    shutil.copytree(clips[0], old, ignore=shutil.ignore_patterns("images", "meta.json"))
    assert validate_clip(old) == {"C1 files": ["missing meta.json"]}
    meta_main([str(old)])
    assert (old / "meta.json").read_text() == (clips[0] / "meta.json").read_text()
    assert validate_clip(old) == {}


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


class StandInPage:
    """render_clip's page without a browser: every truth row is Python's own, the picture is not
    drawn (no boxes, no pixels). Enough to check what a cut does to the truth."""

    context = SimpleNamespace(browser=SimpleNamespace(version="stand-in"))

    def evaluate(self, js, arg):
        if "init" in js:
            return {"bugRect": [0, 0, 1, 1]}
        return {"objects": {o["id"]: {"full": 0, "visible": 0, "bbox": None, "centroid": None}
                            for o in arg["objects"]},
                "keypoints": [False] * len(arg["keypoints"]),
                "image": "data:image/jpeg;base64," + base64.b64encode(b"x").decode()}


@pytest.fixture(scope="module")
def cut_clip(tmp_path_factory):
    """A broadcast clip from a second before the stoppage of seed 11's first long dead ball to a
    second past its restart. The cut is found from the match, as render_clip finds it, so a change
    to the engine moves the clip with it (lesson 78)."""
    first = None
    match = simulate(11, (240.0 + 30.0 + SIM_MARGIN_S) / 60)
    first = next(c for c in edit.cuts(match.events, 25) if c.stop >= 25)
    start = first.stop - 25
    seconds = (first.first_frame - start + first.restart + 25 - first.last_frame) / 25
    out = tmp_path_factory.mktemp("cut") / "c"
    render_clip(11, out, seconds=seconds, start_s=start / 25, overrides={"dead_ball_cut": True},
                page=StandInPage())
    return out, first, start


def test_a_clip_cuts_from_the_stoppage_to_the_restart_and_still_meets_the_contract(cut_clip):
    """The clip shows the stoppage, then cuts, then comes back for the restart. Every shown row is
    the engine's own frame of that number (render_clip draws from them), every event is on a shown
    frame, and the clip meets the data contract (C2 accepts the recorded cut)."""
    out, first, start = cut_clip
    clip, frames, events = load_clip(out)
    numbers = [f["frame"] for f in frames]
    k = first.first_frame - start
    assert numbers[:k] == list(range(start, first.first_frame))
    assert numbers[k] == first.last_frame + 1 and numbers[k:] == list(range(numbers[k], numbers[-1] + 1))
    assert first.stop in numbers and first.restart in numbers
    assert clip["cuts"] == [first.as_dict()]
    assert clip["segments"] == [{"index": 0, "frame": numbers[0], "frames": k},
                                {"index": k, "frame": numbers[k], "frames": len(frames) - k}]
    assert json.loads((out / "meta.json").read_text())["cuts"] == [first.as_dict()]
    assert [f["image"] for f in frames] == [f"images/{i:05d}.jpg" for i in range(len(frames))]
    assert all(e["frame"] in numbers for e in events)
    # The picture after the cut is a new shot, not a pan from the last one: unstreaked, and the
    # gantry closed up on the restart; it eases back out to the wide shot before the kick.
    fov = [f["camera"]["fov_v_deg"] for f in frames]
    restart_at = numbers.index(first.restart)
    assert frames[k]["blur_px"] == [0.0, 0.0]
    assert frames[k]["camera"]["position"] == frames[k - 1]["camera"]["position"]
    hold = round(CUT_HOLD_S * 25)
    assert fov[k] < 0.6 * fov[k - 1]  # a cut to a closer shot, not the same framing
    assert max(fov[k:k + hold]) < 1.2 * fov[k]  # held closed up for the shortest shot
    assert fov[restart_at] > 2 * fov[k]  # and eased back out by the kick ...
    assert max(abs(b - a) for a, b in zip(fov[k:], fov[k + 1:], strict=False)) < 0.5  # ... never snapped
    assert validate_clip(out) == {}
    assert check_clip(out)["passed"]["data_contract"]
