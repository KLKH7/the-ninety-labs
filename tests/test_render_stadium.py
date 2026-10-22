"""The advertising boards read the right way round from every camera that sees their print.

Old (since Oct 15): the two boards behind the goals had their texture flipped, so from the gantry
and from any player cam on the pitch their brands read mirrored; and the far boards were printed
on both faces, so the reverse angle, from behind them, read them mirrored too.

Skipped when three.js or Chromium is not installed, unless NINETY_REQUIRE_RENDER=1.
"""

import os

import pytest

from ninety.render.camera import Camera
from ninety.render.clip import RenderUnavailable, _appearance, browser_page
from ninety.render.params import sample_params
from ninety.render.scene import Gait, Look, ball_parts, body_parts, mesh_pose, parts_box, project_keypoints

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


@pytest.mark.parametrize("stadium, n", [("plain", 4), ("broadcast", 12)])
def test_every_board_reads_left_to_right_from_every_camera_that_sees_its_print(page, stadium, n):
    """A broadcast stadium closes the ring of boards at the corners (eight more pieces); they read
    the same way round as the plain boards."""
    p = sample_params(7, stadium=stadium)
    page.evaluate("cfg => window.ninety.init(cfg)",
                  {"seed": 7, "params": {**p.to_dict(), "width": 1280, "height": 720}, "objects": []})
    boards = page.evaluate("() => window.ninety.boards()")
    assert len(boards) == n
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


LOOK = Look("h1", "home", "CM", 1.84, 1.0, "#c68642", "#1b1410")
LOOK2 = Look("a4", "away", "CB", 1.80, 1.0, "#8d5a3b", "#1b1410")


def _labels(page, stadium):
    """One frame's labels (each object's solo and visible pixels, box, centroid; the pitch
    keypoints' visibility) from three cameras: the gantry on two players and a ball in the air with
    the far stand full behind them, the reverse angle, and the gantry on a ball kicked into the far
    stand, where fans in the rows in front of it stand between it and the lens."""
    p = sample_params(8001, stadium=stadium)
    looks = [LOOK, LOOK2]
    page.evaluate("cfg => window.ninety.init(cfg)",
                  {"seed": 8001, "params": {**p.to_dict(), "width": 1280, "height": 720},
                   "objects": [*(_appearance(lk, p) for lk in looks),
                               {"id": "ball", "colors": {"ball": "#f2f2f2"}}]})
    out = []
    # The far lower tier's floor rises from z 2.0 at y 74.3 to 9.2 at y 91 (web/render/render.js).
    in_stand = (60.0, 80.0, 2.0 + (80.0 - 74.3) / 16.7 * 7.2 + 0.2)
    views = [(Camera((52.5, -35.0, 20.0), (60.0, 66.0, 2.0), 30.0, 1280, 720), (60.0, 67.0, 3.0)),
             (Camera((52.5, 86.0, 12.0), (52.5, 20.0, 0.0), 40.0, 1280, 720), (60.0, 67.0, 3.0)),
             (Camera((52.5, -35.0, 20.0), in_stand, 8.0, 1280, 720), in_stand)]
    for v, (cam, at) in enumerate(views):
        objects = []
        for lk, (x, y) in zip(looks, ((58.0, 64.0), (62.0, 66.5)), strict=True):
            g = Gait(action="run", phase=1.2, speed=5.0, heading=0.4)
            parts = body_parts(x, y, lk, g, None)
            objects.append({"id": lk.id, "parts": parts, "box": parts_box(cam, parts), "heading": 0.4,
                            "pose": mesh_pose(g, x, y, 0.0)})
        ball = ball_parts(*at)
        objects.append({"id": "ball", "parts": ball, "box": parts_box(cam, ball)})
        kps = project_keypoints(cam)
        spec = {
            "index": 40 + v,
            "camera": {"position": list(cam.position), "R": cam.R, "fov_v_deg": cam.fov_v_deg},
            "objects": objects, "keypoints": [[k["px"], k["py"]] for k in kps],
            "blur": [0.0, 0.0], "score": [1, 0], "clock": "02:37",
            # The home fans are jumping for a goal: moving figures change no label either.
            "goal_age": 0.6, "goal_side": 0, "net": None, "want_image": False, "want_markers": False,
        }
        res = page.evaluate("s => window.ninety.frame(s)", spec)
        out.append((res["objects"], res["keypoints"]))
    return out


def test_the_crowd_is_never_labelled_and_hides_only_what_is_behind_it(page):
    """stadium=broadcast puts tens of thousands of spectators in the stands. None of them is a
    labelled object, and in front of play they change no label: from the gantry and the reverse
    angle every player's, the ball's and the keypoints' labels are the plain stadium's, pixel for
    pixel. A ball kicked into the stands is hidden by the fans in front of it, as the picture hides
    it (lesson 84): fewer visible pixels, the same solo silhouette and box."""
    plain = _labels(page, "plain")
    broadcast = _labels(page, "broadcast")
    assert page.evaluate("() => window.ninety.crowd()") > 20000
    assert broadcast[:2] == plain[:2]
    # The frames do see the players and the ball, so the comparison is not of empty labels.
    for objects, _ in plain[:2]:
        assert all(objects[k]["visible"] > 0 for k in ("h1", "a4", "ball")), objects
    (p_obj, p_kps), (b_obj, b_kps) = plain[2], broadcast[2]
    assert b_kps == p_kps
    assert p_obj["ball"]["visible"] > 20, p_obj["ball"]
    assert b_obj["ball"]["visible"] < 0.8 * p_obj["ball"]["visible"], (b_obj["ball"], p_obj["ball"])
    for k in ("h1", "a4", "ball"):
        assert {f: b_obj[k][f] for f in ("full", "bbox", "centroid")} == \
            {f: p_obj[k][f] for f in ("full", "bbox", "centroid")}, k
        if k != "ball":
            assert b_obj[k] == p_obj[k], k
