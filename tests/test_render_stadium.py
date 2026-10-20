"""The advertising boards read the right way round from every camera that sees their print.

Old (since Oct 15): the two boards behind the goals had their texture flipped, so from the gantry
and from any player cam on the pitch their brands read mirrored; and the far boards were printed
on both faces, so the reverse angle, from behind them, read them mirrored too.

Skipped when three.js or Chromium is not installed, unless NINETY_REQUIRE_RENDER=1.
"""

import os

import pytest

from ninety.render.clip import RenderUnavailable, browser_page
from ninety.render.params import sample_params

# The broadcast gantry and the reverse angle (ninety/render/camera.py), and player cams on the pitch.
VIEWERS = {
    "gantry": (52.5, -35.0, 20.0),
    "reverse": (52.5, 86.0, 12.0),
    "player cam, left half": (20.0, 34.0, 1.7),
    "player cam, right half": (85.0, 34.0, 1.7),
    "player cam, near side": (52.5, 8.0, 1.7),
    "player cam, far side": (52.5, 60.0, 1.7),
    "player cam, a corner": (4.0, 4.0, 1.7),
}


@pytest.fixture(scope="module")
def page():
    try:
        with browser_page() as (pg, _):
            yield pg
    except RenderUnavailable as e:
        if os.environ.get("NINETY_REQUIRE_RENDER") == "1":
            raise
        pytest.skip(str(e))


def _sub(a, b):
    return [a[i] - b[i] for i in range(3)]


def _dot(a, b):
    return sum(a[i] * b[i] for i in range(3))


def _cross(a, b):
    return [a[1] * b[2] - a[2] * b[1], a[2] * b[0] - a[0] * b[2], a[0] * b[1] - a[1] * b[0]]


def _texture_axes(board):
    """World directions in which the print's u (along the text) and v (up the letters) grow, the
    face's normal (three.js draws the side the corners go round anticlockwise), and its centre."""
    pos, uv = board["position"], board["uv"]
    p = [pos[3 * j : 3 * j + 3] for j in range(3)]
    t = [uv[2 * j : 2 * j + 2] for j in range(3)]
    e1, e2 = _sub(p[1], p[0]), _sub(p[2], p[0])
    du1, dv1 = t[1][0] - t[0][0], t[1][1] - t[0][1]
    du2, dv2 = t[2][0] - t[0][0], t[2][1] - t[0][1]
    det = du1 * dv2 - du2 * dv1
    along = [(e1[i] * dv2 - e2[i] * dv1) / det for i in range(3)]
    up = [(e2[i] * du1 - e1[i] * du2) / det for i in range(3)]
    centre = [sum(pos[3 * j + i] for j in range(6)) / 6 for i in range(3)]
    return along, up, _cross(e1, e2), centre


def test_every_board_reads_left_to_right_from_every_camera_that_sees_its_print(page):
    p = sample_params(7)
    page.evaluate("cfg => window.ninety.init(cfg)",
                  {"seed": 7, "params": {**p.to_dict(), "width": 1280, "height": 720}, "objects": []})
    boards = page.evaluate("() => window.ninety.boards()")
    assert len(boards) == 4
    seen = 0
    for i, board in enumerate(boards):
        along, up, normal, centre = _texture_axes(board)
        assert up[2] > 0, (i, up)  # the letters stand upright
        for name, eye in VIEWERS.items():
            look = _sub(centre, eye)
            front = _dot(normal, _sub(eye, centre)) > 0
            if not front:
                # From behind, the print is not drawn: the board shows its plain back, or nothing.
                assert not board["doubleSided"], (i, name)
                continue
            seen += 1
            right = [look[1], -look[0], 0.0]  # the viewer's right, looking at the board
            assert _dot(along, right) > 0, (i, name)
    assert seen >= 4 * 3  # every board is read from the pitch by several of these cameras
