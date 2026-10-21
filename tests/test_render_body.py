"""The drawn body is one connected silhouette, the capsules `body_parts` labels (scene.py).

A player cut by the bottom of the frame is drawn down to the frame edge, wherever the edge cuts
him between the soles and the chin. Seed 900002 at 443c4d5 drew a head with nothing under it: the
limbs were lathes that closed at their joints, so nothing filled the gap between the top of the
trunk and the base of the neck, and his box ended at the chin.

Skipped when three.js or Chromium is not installed, unless NINETY_REQUIRE_RENDER=1.
"""

import math
import os

import pytest

from ninety.render.camera import Camera
from ninety.render.clip import RenderUnavailable, _appearance, browser_page
from ninety.render.meshpose import ASSET_STATURE_M
from ninety.render.params import sample_params
from ninety.render.scene import HEAD_Z, Gait, Look, body_parts, parts_box

W, H = 1280, 720
GANTRY = (52.5, -32.4, 13.7)  # where seed 900002's main camera stood
FOV = 11.4  # its lens at those frames
SPOT = (40.0, 19.0)


@pytest.fixture(scope="module")
def page():
    try:
        with browser_page() as (pg, _):
            yield pg
    except RenderUnavailable as e:
        if os.environ.get("NINETY_REQUIRE_RENDER") == "1":
            raise
        pytest.skip(str(e))


def camera_cutting_at(z: float) -> Camera:
    """The gantry camera tilted so the bottom image edge crosses the player's axis at height z."""
    lo, hi = -20.0, 20.0  # target height; a higher target tilts up and moves him down the frame
    for _ in range(60):
        mid = (lo + hi) / 2
        cam = Camera(GANTRY, (SPOT[0], SPOT[1], mid), FOV, W, H)
        v = cam.project((SPOT[0], SPOT[1], z))[1]
        lo, hi = (mid, hi) if v < H else (lo, mid)
    return Camera(GANTRY, (SPOT[0], SPOT[1], lo), FOV, W, H)


def drawn_box(pg, look: Look, heading: float, cam: Camera) -> list[int] | None:
    parts = body_parts(SPOT[0], SPOT[1], look, Gait(heading=heading))
    spec = {
        "index": 0,
        "camera": {"position": list(cam.position), "R": cam.R, "fov_v_deg": cam.fov_v_deg},
        "objects": [{"id": look.id, "parts": parts, "box": parts_box(cam, parts), "heading": heading}],
        "keypoints": [],
        "blur": [0.0, 0.0],
        "score": [0, 0],
        "clock": "00:00",
        "goal_age": None,
        "goal_side": None,
        "net": None,
        "want_image": False,
    }
    return pg.evaluate("s => window.ninety.frame(s)", spec)["objects"][look.id]["bbox"]


@pytest.mark.parametrize("stature", [1.65, 1.98])  # the shortest and tallest drawn (sample_looks)
def test_a_player_cut_by_the_bottom_edge_is_drawn_down_to_it(page, stature):
    look = Look("a11", "away", "LW", stature, 1.0, "#d19a74", "#1b1410")
    p = sample_params(900002)
    params = {**p.to_dict(), "width": W, "height": H}
    cfg = {"seed": 900002, "params": params, "objects": [_appearance(look, p)]}
    page.evaluate("cfg => window.ninety.init(cfg)", cfg)
    k = stature / ASSET_STATURE_M
    chin = HEAD_Z * k - 0.105 * k  # the bottom of the head sphere (body_parts)
    gaps = []
    for heading in (0.0, math.pi / 2):  # side-on to the camera, and facing away from it
        for cm in range(20, int(chin * 100) - 2, 2):
            box = drawn_box(page, look, heading, camera_cutting_at(cm / 100))
            if box is None or box[3] != H:
                gaps.append((round(heading, 2), cm, box))
    assert not gaps, gaps
