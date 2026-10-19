"""Scenery hides what is behind it in the id pass, as it does in the picture.

Seed 900003 at `engine-v1` labelled a ball resting 0.5 m behind the far advertising boards as
fully visible (visibility 1.0, 55 pixels): the boards were decor, and the id pass hid all decor.
The detector found it by missing that ball, which the picture does not show.

Skipped when three.js or Chromium is not installed, unless NINETY_REQUIRE_RENDER=1.
"""

import os

import pytest

from ninety.render.camera import Camera
from ninety.render.clip import RenderUnavailable, browser_page
from ninety.render.params import sample_params
from ninety.render.scene import ball_parts, parts_box

W, H = 1280, 720
GANTRY = (53.09, -35.46, 15.05)  # seed 900003's main camera at frame 5806
FOV = 9.5


@pytest.fixture(scope="module")
def page():
    try:
        with browser_page() as (pg, _):
            p = sample_params(900003)
            cfg = {
                "seed": 900003,
                "params": {**p.to_dict(), "width": W, "height": H},
                "objects": [{"id": "ball", "colors": {"ball": "#f2f2f2"}}],
            }
            pg.evaluate("cfg => window.ninety.init(cfg)", cfg)
            yield pg
    except RenderUnavailable as e:
        if os.environ.get("NINETY_REQUIRE_RENDER") == "1":
            raise
        pytest.skip(str(e))


def ball_labels(pg, x: float, y: float) -> dict:
    cam = Camera(GANTRY, (x, y, 0.11), FOV, W, H)
    parts = ball_parts(x, y, 0.0)
    spec = {
        "index": 0,
        "camera": {"position": list(cam.position), "R": cam.R, "fov_v_deg": cam.fov_v_deg},
        "objects": [{"id": "ball", "parts": parts, "box": parts_box(cam, parts)}],
        "keypoints": [],
        "blur": [0.0, 0.0],
        "score": [0, 0],
        "clock": "00:00",
        "goal_age": None,
        "goal_side": None,
        "net": None,
        "want_image": False,
    }
    return pg.evaluate("s => window.ninety.frame(s)", spec)["objects"]["ball"]


def test_a_ball_behind_the_far_boards_is_not_visible(page):
    o = ball_labels(page, 73.1, 72.0)  # the far boards stand at y = 71.5, 1.8 m tall
    assert o["full"] > 0  # it is in shot: the solo pass draws it
    assert o["visible"] == 0, o


def test_a_ball_in_front_of_the_boards_is_visible(page):
    o = ball_labels(page, 73.1, 70.0)  # on the pitch, the boards behind it
    assert o["full"] > 0
    assert o["visible"] / o["full"] > 0.9, o
