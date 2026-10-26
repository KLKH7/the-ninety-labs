"""The skinned body stays inside the capsule box the labels use.

The page draws the mesh. The box is still the capsules from body_parts. Head, feet and,
on a throw, the hands have to project inside that box. A planted foot stays on its plant
while the hips move on.
"""

import math
import os

import pytest

from ninety.render.camera import Camera
from ninety.render.clip import RenderUnavailable, _appearance, browser_page
from ninety.render.meshpose import pose_markers, world_markers
from ninety.render.params import sample_params
from ninety.render.scene import PLANT_AHEAD_MAX, Gait, Look, body_parts, parts_box, reach_sign

LOOK = Look("h1", "home", "CM", 1.84, 1.0, "#c68642", "#1b1410")
CAM = Camera((52.5, -35.0, 20.0), (40.0, 30.0, 0.0), 20.0, 1280, 720)


def _box_for(action, phase, speed, dive=0.0, ball=None, heading=0.4):
    g = Gait(action=action, phase=phase, speed=speed, dive=dive, heading=heading)
    parts = body_parts(40.0, 30.0, LOOK, g, ball)
    box = parts_box(CAM, parts)
    reach = reach_sign(40.0, 30.0, g, ball)
    pts = world_markers(
        40.0, 30.0, heading, LOOK.height_m, action, phase, speed, reach, g.dive,
        g.plant_l, g.plant_r,
    )
    return box, pts


def _inside(box, point, pad=2.0):
    """Head and feet stay in the capsule box. The sole may sit 4 px under it.

    The boot capsule is held off the grass. The mesh sole is on the grass, and the
    ground point under a player is already allowed 4 px past the bottom of this box.
    """
    uv = CAM.project(point)
    assert uv is not None, point
    x0, y0, x1, y1 = box
    assert x0 - pad <= uv[0] <= x1 + pad and y0 - pad <= uv[1] <= y1 + 4.0, (uv, box)


def test_head_and_feet_project_inside_the_capsule_box():
    ball = (40.7, 30.25, 0.15)
    cases = [
        ("stand", 0.0, 0.0, 0.0, None),
        ("run", 0.4, 5.5, 0.0, None),
        ("run", 1.7, 6.0, 0.0, None),
        ("run", 3.4, 5.0, 0.0, None),
        ("run", 4.8, 4.5, 0.0, None),
        ("walk", 1.1, 1.3, 0.0, None),
        ("strike", 0.2, 0.4, 0.0, ball),
        ("foot", 0.2, 0.8, 0.0, ball),
        ("thigh", 0.3, 0.6, 0.0, (40.3, 30.4, 0.9)),
        ("chest", 0.0, 0.2, 0.0, None),
        ("head", 0.0, 0.2, 0.0, None),
        ("hands", 0.0, 0.2, 0.0, None),
        ("throw", 0.0, 0.0, 0.0, None),
        ("dive", 0.2, 1.0, 0.8, None),
        ("dive", 0.2, 1.0, -0.7, None),
        ("shield", 0.0, 0.3, 0.0, None),
    ]
    for action, phase, speed, dive, at in cases:
        box, pts = _box_for(action, phase, speed, dive, at)
        assert box is not None, action
        for name in ("head", "foot_l", "foot_r"):
            _inside(box, pts[name])
        if action == "throw":
            _inside(box, pts["hand_l"])
            _inside(box, pts["hand_r"])


def test_the_planted_foot_does_not_skate_with_the_hip():
    # A run lands its foot no further ahead than the mesh's leg reaches (scene.PLANT_AHEAD_MAX).
    plant = (10.0 + PLANT_AHEAD_MAX, 20.02)
    a = world_markers(10.0, 20.0, 0.0, 1.84, "run", 0.6, 5.0, 0.0, 0.0, plant, None)
    b = world_markers(10.22, 20.0, 0.0, 1.84, "run", 2.1, 5.0, 0.0, 0.0, plant, None)
    for foot in (a["foot_l"], b["foot_l"]):
        assert math.hypot(foot[0] - plant[0], foot[1] - plant[1]) < 0.22
        assert foot[2] < 0.12
    moved = math.hypot(a["foot_l"][0] - b["foot_l"][0], a["foot_l"][1] - b["foot_l"][1])
    assert moved < 0.12


@pytest.fixture(scope="module")
def page():
    try:
        with browser_page() as (pg, _):
            yield pg
    except RenderUnavailable as e:
        if os.environ.get("NINETY_REQUIRE_RENDER") == "1":
            raise
        pytest.skip(str(e))


def test_the_page_skins_the_same_body_the_box_uses(page):
    """Beauty and the id pass are the same mesh, and it agrees with the Python markers."""
    p = sample_params(5)
    params = {**p.to_dict(), "width": 1280, "height": 720}
    page.evaluate("cfg => window.ninety.init(cfg)",
                  {"seed": 5, "params": params, "objects": [_appearance(LOOK, p)]})
    ball = (40.7, 30.25, 0.12)
    g = Gait(action="run", phase=1.2, speed=5.2, heading=0.4)
    parts = body_parts(40.0, 30.0, LOOK, g, None)
    pose = {
        "action": "run", "phase": 1.2, "speed": 5.2, "reach": 0, "dive": 0,
        "plant_l": list(g.plant_l) if g.plant_l else None,
        "plant_r": list(g.plant_r) if g.plant_r else None,
        "x": 40.0, "y": 30.0,
    }
    spec = {
        "index": 0,
        "camera": {"position": list(CAM.position), "R": CAM.R, "fov_v_deg": CAM.fov_v_deg},
        "objects": [{"id": LOOK.id, "parts": parts, "box": parts_box(CAM, parts), "heading": 0.4,
                     "pose": pose}],
        "keypoints": [], "blur": [0.0, 0.0], "score": [0, 0], "clock": "00:00",
        "goal_age": None, "goal_side": None, "net": None, "want_image": False, "want_markers": True,
    }
    res = page.evaluate("s => window.ninety.frame(s)", spec)
    drawn = res["objects"][LOOK.id]["bbox"]
    assert drawn is not None and res["objects"][LOOK.id]["full"] > 200
    box = spec["objects"][0]["box"]
    # The id pass counts the same mesh the beauty pass drew. A couple of pixels of filter is the edge.
    assert box[0] - 4 <= drawn[0] and drawn[2] <= box[2] + 4
    assert box[1] - 4 <= drawn[1] and drawn[3] <= box[3] + 4
    py = world_markers(40, 30, 0.4, 1.84, "run", 1.2, 5.2, 0, 0, g.plant_l, g.plant_r)
    js = res["markers"][LOOK.id]
    for name in ("head", "foot_l", "foot_r"):
        assert math.dist(py[name], js[name]) < 0.015, (name, py[name], js[name])
    # A strike on the same body, so the kicking foot is the one the capsule reaches with.
    g2 = Gait(action="strike", heading=0.0)
    parts2 = body_parts(40.0, 30.0, LOOK, g2, ball)
    pose2 = {
        "action": "strike", "phase": 0, "speed": 0.3,
        "reach": reach_sign(40, 30, g2, ball), "dive": 0,
        "plant_l": None, "plant_r": None, "x": 40.0, "y": 30.0,
    }
    spec["objects"] = [{"id": LOOK.id, "parts": parts2, "box": parts_box(CAM, parts2), "heading": 0.0,
                        "pose": pose2}]
    spec["index"] = 1
    res2 = page.evaluate("s => window.ninety.frame(s)", spec)
    py2 = world_markers(40, 30, 0.0, 1.84, "strike", 0, 0.3, pose2["reach"], 0, None, None)
    js2 = res2["markers"][LOOK.id]
    assert math.dist(py2["foot_r"] if pose2["reach"] <= 0 else py2["foot_l"], 
                      js2["foot_r"] if pose2["reach"] <= 0 else js2["foot_l"]) < 0.015
    assert res2["objects"][LOOK.id]["full"] > 200
    # A bald slim player and a broad crown still land in the capsule box.
    for style, build in (("bald", 0.9), ("crown", 1.15)):
        look = Look(LOOK.id, "home", "CM", 1.84, build, LOOK.skin, LOOK.hair, hair_style=style)
        g3 = Gait(action="run", phase=1.2, speed=5.2, heading=0.4)
        parts3 = body_parts(40.0, 30.0, look, g3, None)
        pose3 = dict(pose, build=build, hair_style=style)
        spec["objects"] = [{"id": look.id, "parts": parts3, "box": parts_box(CAM, parts3), "heading": 0.4,
                            "pose": pose3}]
        spec["index"] += 1
        res3 = page.evaluate("s => window.ninety.frame(s)", spec)
        drawn3 = res3["objects"][look.id]["bbox"]
        box3 = spec["objects"][0]["box"]
        assert drawn3 is not None and res3["objects"][look.id]["full"] > 200
        assert box3[0] - 4 <= drawn3[0] and drawn3[2] <= box3[2] + 4, (style, drawn3, box3)
        assert box3[1] - 4 <= drawn3[1] and drawn3[3] <= box3[3] + 4, (style, drawn3, box3)


def test_the_page_turns_steps_and_touches_like_the_python_pose(page):
    """Hips ahead of the chest, feet planted and twisted or stepping, and each touch: the page's
    skinned markers are the Python ones (meshpose.pose_markers), so the tests of the motion
    (test_render_motion.py) hold for the pixels."""
    from ninety.render.meshpose import pose_markers

    p = sample_params(5)
    params = {**p.to_dict(), "width": 1280, "height": 720}
    page.evaluate("cfg => window.ninety.init(cfg)",
                  {"seed": 5, "params": params, "objects": [_appearance(LOOK, p)]})
    base = {"phase": 0.0, "speed": 0.0, "reach": 0, "dive": 0, "x": 40.0, "y": 30.0, "lift": 0.0}
    poses = [
        {**base, "action": "stand", "lead": 0.35,
         "plant_l": [40.05, 30.22, 0.9, 0.0], "plant_r": [39.9, 29.8, 0.2, 0.06]},
        {**base, "action": "run", "phase": 1.2, "speed": 5.2, "lead": -0.2,
         "plant_l": [40.2, 30.15, 0.3, 0.0], "plant_r": None},
        {**base, "action": "strike", "reach": -1.0, "speed": 0.3,
         "touch": {"part": "strike", "side": "r", "at": [40.35, 29.85, 0.05], "w": 0.7}},
        {**base, "action": "thigh", "reach": 1.0,
         "touch": {"part": "thigh", "side": "l", "at": [40.15, 30.1, 0.62], "w": 1.0}},
        {**base, "action": "chest",
         "touch": {"part": "chest", "side": "r", "at": [40.3, 30.0, 1.25], "w": 1.0}},
        {**base, "action": "head", "lift": 0.2,
         "touch": {"part": "head", "side": "r", "at": [40.2, 30.0, 1.95], "w": 1.0}},
        # The arms: a walk and a jog between the stored walk and run, a kick's balance half-way in
        # (a stooped body whose blended foot is put back on the grass), and a keeper's hands on a
        # ball at his feet and at his chest.
        {**base, "action": "walk", "phase": 2.1, "speed": 1.4},
        {**base, "action": "walk", "phase": 4.0, "speed": 3.1},
        {**base, "action": "strike", "speed": 1.0, "lift": -0.3,
         "plant_l": [40.1, 30.25, 0.4, 0.0], "plant_r": [39.95, 29.85, 0.4, 0.0],
         "touch": {"part": "strike", "side": "r", "at": [39.7, 29.8, 0.4], "w": 0.35}},
        {**base, "action": "hands", "lift": -0.3,
         "plant_l": [40.05, 30.22, 0.4, 0.0], "plant_r": [39.95, 29.83, 0.4, 0.0],
         "hold": {"at": [40.25, 30.1, 0.11], "w": 1.0, "bend": 1.4}},
        {**base, "action": "hands", "hold": {"at": [40.3, 30.12, 1.2], "w": 0.6, "bend": 0.0}},
        # A stride's plant half taken (its weight), and speeds where the stand pose and the walk's
        # short stride blend into the stride.
        {**base, "action": "walk", "phase": 5.3, "speed": 2.0, "plant_l": [40.12, 30.2, 0.4, 0.0, 0.4]},
        {**base, "action": "walk", "phase": 1.0, "speed": 0.6},
        {**base, "action": "stand", "phase": 2.0, "speed": 0.4},
        # The runner's bob (in lift), a trunk leaning into a sprint start or coming up braking, and
        # the sprint's wider arm swing (scene.pace, scene.PUMP).
        {**base, "action": "run", "phase": 0.9, "speed": 6.5, "lift": -0.025, "lean": 0.31, "pump": 1.2,
         "plant_r": [40.05, 29.9, 0.4, 0.0]},
        {**base, "action": "walk", "phase": 3.6, "speed": 3.4, "lift": 0.02, "lean": -0.12, "pump": 1.0},
        {**base, "action": "stand", "speed": 0.1, "lean": 0.4},
        # A keeper's dive part way (from standing), and getting up from one into a walk (dive_up).
        {**base, "action": "dive", "dive": -0.4},
        {**base, "action": "walk", "phase": 2.6, "speed": 1.2, "dive_up": 0.55},
        # A foul's reactions (fouls.py, lesson 234): the fouler's hand up, part way and full, and a
        # team-mate's head turned to the fouled player while he walks.
        {**base, "action": "stand", "signal": {"side": "r", "at": [40.08, 29.8, 2.06], "w": 1.0}},
        {**base, "action": "walk", "phase": 1.4, "speed": 1.1,
         "signal": {"side": "r", "at": [40.08, 29.8, 2.06], "w": 0.5}},
        {**base, "action": "walk", "phase": 4.1, "speed": 1.3, "look": {"yaw": 0.9, "w": 1.0}},
        {**base, "action": "stand", "look": {"yaw": -1.2, "w": 0.6}},
        # A fouled player's hands out to break his fall (fouls.fall_at, lesson 280), full and half.
        {**base, "action": "stand", "brace": {"w": 1.0, "l": [40.5, 30.45, 0.95], "r": [40.6, 29.95, 0.85]}},
        {**base, "action": "stand", "brace": {"w": 0.5, "l": [40.3, 30.6, 1.1], "r": [40.4, 29.7, 1.0]}},
    ]
    for i, pose in enumerate(poses):
        heading = 0.4
        g = Gait(action=pose["action"], heading=heading)
        parts = body_parts(40.0, 30.0, LOOK, g, None)
        spec = {
            "index": 10 + i,
            "camera": {"position": list(CAM.position), "R": CAM.R, "fov_v_deg": CAM.fov_v_deg},
            "objects": [{"id": LOOK.id, "parts": parts, "box": parts_box(CAM, parts), "heading": heading,
                         "pose": pose}],
            "keypoints": [], "blur": [0.0, 0.0], "score": [0, 0], "clock": "00:00",
            "goal_age": None, "goal_side": None, "net": None, "want_image": False, "want_markers": True,
        }
        js = page.evaluate("s => window.ninety.frame(s)", spec)["markers"][LOOK.id]
        py = pose_markers(pose, heading, LOOK.height_m)
        for name in ("head", "foot_l", "foot_r", "hand_l", "hand_r", "brow", "chest", "thigh_top_l"):
            assert math.dist(py[name], js[name]) < 0.015, (i, pose["action"], name, py[name], js[name])


def test_a_player_is_drawn_as_tall_as_he_is(page):
    """The mesh's skull top is ASSET_STATURE_M in its own metres; scaled as a 1.84 m body it drew
    every player at 91.5% of his height (lesson 157). A standing, bald player seen from the side at
    eye level is now drawn from the grass to his height, within 2%, at every drawn stature."""
    p = sample_params(5)
    params = {**p.to_dict(), "width": 1280, "height": 720}
    cam = Camera((40.0, 22.0, 0.95), (40.0, 30.0, 0.95), 20.0, 1280, 720)
    for i, stature in enumerate((1.65, 1.84, 1.98)):
        look = Look(f"h{i + 1}", "home", "CM", stature, 1.0, LOOK.skin, LOOK.hair, hair_style="bald")
        page.evaluate("cfg => window.ninety.init(cfg)",
                      {"seed": 5, "params": params, "objects": [_appearance(look, p)]})
        g = Gait(action="stand", heading=0.0)
        parts = body_parts(40.0, 30.0, look, g, None)
        pose = {"action": "stand", "phase": 0.0, "speed": 0.0, "reach": 0, "dive": 0, "x": 40.0, "y": 30.0,
                "plant_l": list(g.plant_l) if g.plant_l else None,
                "plant_r": list(g.plant_r) if g.plant_r else None, "hair_style": "bald"}
        camera = {"position": list(cam.position), "R": cam.R, "fov_v_deg": cam.fov_v_deg}
        spec = {"index": 40 + i, "camera": camera,
                "objects": [{"id": look.id, "parts": parts, "box": parts_box(cam, parts), "heading": 0.0,
                             "pose": pose}],
                "keypoints": [], "blur": [0.0, 0.0], "score": [0, 0], "clock": "00:00",
                "goal_age": None, "goal_side": None, "net": None, "want_image": False}
        box = page.evaluate("s => window.ninety.frame(s)", spec)["objects"][look.id]["bbox"]
        # From the side, the nearer of his planted feet (about 0.2 m either side of him) is the
        # lowest thing drawn: measure from the grass under it, not under his centre.
        feet = pose_markers(pose, 0.0, stature)
        sole = max(cam.project((feet[f][0], feet[f][1], 0.0))[1] for f in ("foot_l", "foot_r"))
        crown = cam.project((40.0, 30.0, stature))[1]
        drawn, real = box[3] - box[1], sole - crown
        assert abs(drawn / real - 1.0) < 0.02, (stature, drawn, real)


def test_the_body_has_a_mans_proportions_and_its_stature_is_the_scale():
    """The drawn body is the asset scaled to the player's height, so its joints must sit where a
    man's do, as fractions of stature (Drillis and Contini 1966, as tabulated in Winter,
    Biomechanics and Motor Control of Human Movement, fig. 4.1): knee 0.285, hip 0.530, shoulder
    0.818, chin 0.870. The asset is a standing A-pose, so elbow and wrist are not compared. Within
    0.03 of stature (about 5 cm): where a joint centre sits inside a skinned mesh is not known more
    closely than that. And ASSET_STATURE_M is the top of the body mesh's skull."""
    from ninety.render.meshpose import ASSET_STATURE_M, asset

    data = asset()
    body = data["parts"]["body"]["pos"]
    assert abs(max(body[1::3]) - ASSET_STATURE_M) < 1e-3
    head = {b["name"]: b["head"] for b in data["bones"]}
    for bone, ratio in (("calf_l", 0.285), ("thigh_l", 0.530), ("upperarm_l", 0.818), ("neck_01", 0.870)):
        assert abs(head[bone][1] / ASSET_STATURE_M - ratio) < 0.03, (bone, head[bone][1] / ASSET_STATURE_M)
