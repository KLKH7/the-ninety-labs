"""A foul made legible on screen (lesson 173): the fouled player goes down and gets up before the
restart, and the fouler's leg goes out at the contact. Drawn from the engine's foul event only: no
position, action or event changes. The bounds below were written before the animation was built.
"""

import copy
import math

from ninety.render import fouls
from ninety.render.meshpose import pose_markers
from ninety.render.scene import Gait, Look, body_parts, contacts

FPS = 25
F, R = 100, 100 + 30 * FPS  # the foul's frame, and the free kick taken 30 s later


def _events():
    return [{"frame": F, "type": "foul", "team": "home", "player": "h5", "receiver": "a7", "x": 40.0, "y": 30.0},
            {"frame": R, "type": "set_piece", "team": "away", "player": "a4", "x": 40.0, "y": 30.0},
            {"frame": R + 40, "type": "pass", "team": "away", "player": "a4", "x": 40.0, "y": 30.0}]


def _frames(n=R + 60):
    """Two players: the fouler h5 runs into the fouled a7 from his west and stops."""
    out = []
    for i in range(n):
        hx = min(38.6 + 0.2 * i / FPS, 39.4)
        out.append({"frame": i, "players": [
            {"id": "h5", "team": "home", "x": hx, "y": 30.0, "vx": 0.0, "vy": 0.0, "heading": 0.0, "action": "run"},
            {"id": "a7", "team": "away", "x": 40.0, "y": 30.0, "vx": 0.0, "vy": 0.0, "heading": math.pi, "action": "stand"},
        ], "ball": {"x": 45.0, "y": 30.0, "z": 0.0, "vx": 0.0, "vy": 0.0}})
    return out


def test_the_fouled_player_goes_down_and_is_up_before_the_restart():
    """Down past 70 degrees within 0.6 s of the foul, falling without ever rising on the way down,
    and standing again at least 1 s before the free kick; no fall outside that."""
    events, frames = _events(), _frames()
    sched = fouls.schedule(events, frames, FPS)
    a7 = sched["a7"]
    angle = {f: v["angle"] for f, v in a7.items()}
    assert angle.get(F - 1, 0.0) == 0.0
    assert max(angle.get(f, 0.0) for f in range(F, F + int(0.6 * FPS) + 1)) >= math.radians(70)
    down = [angle.get(f, 0.0) for f in range(F, F + int(0.6 * FPS) + 1)]
    peak = down.index(max(down))
    assert all(b >= a - 1e-9 for a, b in zip(down[:peak], down[1:peak + 1], strict=False))
    assert all(angle.get(f, 0.0) == 0.0 for f in range(R - FPS, R + 60))
    assert "h5" not in sched  # the fouler does not fall


def test_the_fall_is_drawn_from_the_events_without_touching_them():
    """The schedule reads the engine's foul and restart; frames and events are left as they were."""
    events, frames = _events(), _frames()
    before = (copy.deepcopy(events), copy.deepcopy(frames))
    fouls.schedule(events, frames, FPS)
    assert (events, frames) == before


def _lying_gait(angle, direction):
    g = Gait(heading=math.pi)
    g.action, g.speed = "stand", 0.0
    g.fall, g.fall_dir = angle, direction
    return g


def test_a_fallen_players_body_lies_on_the_grass():
    """At the full fall the label capsules lie down: every capsule point below 0.7 m, and the body
    stretched at least 1.2 m along the fall's direction from his feet."""
    look = Look(id="a7", team="away", role="CM", height_m=1.84, build=1.0, skin="#a0785a", hair="#2b1d14")
    g = _lying_gait(math.radians(85), 0.0)  # pushed east
    parts = body_parts(40.0, 30.0, look, g)
    pts = [p for part in parts for p in ([part["a"], part["b"]] if "b" in part else [part["a"]])]
    assert max(p[2] for p in pts) < 0.7, max(p[2] for p in pts)
    assert max(p[0] for p in pts) - 40.0 >= 1.2


def test_the_page_twin_lies_down_with_the_labels():
    """The mesh twin (meshpose) puts the head on the grass with the labels: head marker below 0.6 m."""
    pose = {"action": "stand", "phase": 0.0, "speed": 0.0, "reach": 0.0, "dive": 0.0, "x": 40.0, "y": 30.0,
            "fall": math.radians(85), "fall_dir": 0.0}
    head = pose_markers(pose, math.pi, 1.84)["head"]
    assert head[2] < 0.6, head
    assert head[0] - 40.0 > 1.0, head  # fallen toward the east, the way he was pushed


def test_the_foulers_foot_goes_to_the_fouled_players_legs():
    """The fouler gets a foot contact on the foul's frame, aimed at the fouled player's legs (within
    0.5 m of him, below knee height), as a tackle's foot meets the ball."""
    events, frames = _events(), _frames()
    mine = contacts(frames, events).get("h5", [])
    at_foul = [c for c in mine if c["frame"] == F]
    assert at_foul, mine
    bx, by, bz = at_foul[0]["ball"]
    assert math.hypot(bx - 40.0, by - 30.0) <= 0.5 and bz <= 0.5, at_foul[0]["ball"]
