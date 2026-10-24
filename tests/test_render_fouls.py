"""A foul made legible on screen (lesson 173): the body lies at the engine's fall and fall_dir, and
the fouler's leg goes out at the contact. The renderer does not time the fall. The bounds below
were written before the animation was built.
"""

import copy
import math

from ninety.render import fouls
from ninety.render.meshpose import pose_markers
from ninety.render.scene import Gait, Look, body_parts, contacts

FPS = 25
F, R = 100, 100 + 30 * FPS  # the foul's frame, and the free kick taken 30 s later


def _events():
    return [{"frame": F, "type": "foul", "team": "home", "player": "h5", "receiver": "a7",
             "x": 40.0, "y": 30.0},
            {"frame": R, "type": "set_piece", "team": "away", "player": "a4", "x": 40.0, "y": 30.0},
            {"frame": R + 40, "type": "pass", "team": "away", "player": "a4", "x": 40.0, "y": 30.0}]


def _frames(n=R + 60):
    """Two players: the fouler h5 runs into the fouled a7 from his west and stops."""
    out = []
    for i in range(n):
        hx = min(38.6 + 0.2 * i / FPS, 39.4)
        out.append({"frame": i, "players": [
            {"id": "h5", "team": "home", "x": hx, "y": 30.0, "vx": 0.0, "vy": 0.0, "heading": 0.0,
             "action": "run"},
            {"id": "a7", "team": "away", "x": 40.0, "y": 30.0, "vx": 0.0, "vy": 0.0, "heading": math.pi,
             "action": "stand"},
        ], "ball": {"x": 45.0, "y": 30.0, "z": 0.0, "vx": 0.0, "vy": 0.0}})
    return out


def test_the_picture_uses_the_engines_fall_and_invents_none():
    """Down by the degrees and the direction on the frame. A frame with no fall, or a fall of 0,
    is standing, and reading it does not change the player."""
    player = {"id": "a7", "x": 40.0, "y": 30.0, "action": "stand"}
    before = copy.deepcopy(player)
    assert fouls.drawn_fall(player) == (0.0, 0.0)
    assert player == before
    angle, direction = fouls.drawn_fall({**player, "fall": 85.0, "fall_dir": 0.4})
    assert angle == math.radians(85.0)
    assert direction == 0.4
    assert fouls.drawn_fall({**player, "fall": 0.0, "fall_dir": 0.4}) == (0.0, 0.0)
    g = Gait()
    fouls.apply_fall(g, {**player, "fall": 85.0, "fall_dir": 0.4})
    assert g.fall == math.radians(85.0) and g.fall_dir == 0.4
    fouls.apply_fall(g, player)
    assert g.fall == 0.0 and g.fall_dir == 0.0


def _lying_gait(angle, direction):
    g = Gait(heading=math.pi)
    g.action, g.speed = "stand", 0.0
    g.fall, g.fall_dir = angle, direction
    return g


def test_a_fallen_players_body_lies_on_the_grass():
    """At the full fall the label capsules lie down: every capsule point below 0.7 m, and the body
    stretched at least 1.2 m along the fall's direction from his feet."""
    look = Look(id="a7", team="away", role="CM", height_m=1.84, build=1.0, skin="#a0785a", hair="#2b1d14")
    angle, direction = fouls.drawn_fall({"id": "a7", "fall": 85.0, "fall_dir": 0.0})
    g = _lying_gait(angle, direction)  # pushed east, the engine's 85 degrees
    parts = body_parts(40.0, 30.0, look, g)
    pts = [p for part in parts for p in ([part["a"], part["b"]] if "b" in part else [part["a"]])]
    assert max(p[2] for p in pts) < 0.7, max(p[2] for p in pts)
    assert max(p[0] for p in pts) - 40.0 >= 1.2


def test_the_page_twin_lies_down_with_the_labels():
    """The mesh twin (meshpose) puts the head on the grass with the labels: head marker below 0.6 m."""
    angle, direction = fouls.drawn_fall({"fall": 85.0, "fall_dir": 0.0})
    pose = {"action": "stand", "phase": 0.0, "speed": 0.0, "reach": 0.0, "dive": 0.0, "x": 40.0, "y": 30.0,
            "fall": angle, "fall_dir": direction}
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


def test_the_frame_row_says_how_far_a_player_is_down():
    """The label row carries `fall` in degrees while he is down (render-check judges a lying body by
    it), and nothing at all while he stands, so upright rows are exactly as before; the truth fields
    are copied unchanged."""
    import json
    from pathlib import Path

    from jsonschema import ValidationError, validate

    schema = json.loads((Path(__file__).resolve().parent.parent / "schemas/frame.schema.json").read_text())
    pl = _frames(1)[0]["players"][1]
    assert fouls.row(pl, 0.0) == pl and "fall" not in fouls.row(pl, 0.0)
    down = fouls.row(pl, math.radians(85))
    assert abs(down["fall"] - 85.0) < 0.05 and {k: down[k] for k in pl} == pl
    frame = {"frame": 0, "t": 0.0, "ball": {"x": 1.0, "y": 1.0, "z": 0.0}, "players": [down]}
    validate(frame, schema)
    frame["players"][0] = {**pl, "fall": -5.0}
    try:
        validate(frame, schema)
        raise AssertionError("a negative fall passed the schema")
    except ValidationError:
        pass


# The players' reactions to a foul (lesson 234): drawn from the engine's foul event and positions.



def _foul_frames(n=80, foul_at=20):
    """h4 fouls a9 at frame foul_at; a9's team-mates at 3, 6, 9, 12 and 30 m from him."""
    frames = []
    for i in range(n):
        players = [{"id": "h4", "team": "home", "x": 50.5, "y": 34.0, "heading": 3.1},
                   {"id": "a9", "team": "away", "x": 50.0, "y": 34.0, "heading": 0.0}]
        for k, d in enumerate((3.0, 6.0, 9.0, 12.0, 30.0)):
            players.append({"id": f"a{k + 2}", "team": "away", "x": 50.0, "y": 34.0 + d, "heading": 0.0})
        frames.append({"frame": 1000 + i, "players": players})
    return frames, [{"type": "foul", "frame": 1000 + foul_at, "player": "h4", "receiver": "a9"}]


def test_the_fouler_signals_and_the_fouled_sides_nearest_turn_to_him():
    frames, events = _foul_frames()
    r = fouls.reactions(frames, events)
    assert r["h4"] == [{"kind": "signal", "frame": 20}]
    lookers = sorted(pid for pid, mine in r.items() if any(x["kind"] == "look" for x in mine))
    assert lookers == ["a2", "a3", "a4"]  # the three nearest team-mates, not the fouled man himself
    assert all(x["to"] == "a9" for pid in lookers for x in r[pid])


def test_a_reaction_starts_at_the_foul_and_is_gone_after_react_s():
    frames, events = _foul_frames()
    r = fouls.reactions(frames, events)
    g = Gait(heading=0.0)
    ws = []
    for fi in range(80):
        fouls.signal_at(g, r["h4"], fi, 25, 50.5, 34.0, 1.84)
        ws.append(g.signal["w"] if g.signal else 0.0)
    assert all(w == 0.0 for w in ws[:20])  # nothing before the whistle
    assert max(ws) == 1.0 and ws[20 + round(fouls.REACT_S * 25) + 1] == 0.0
    assert g.signal is None
    fouls.signal_at(g, r["h4"], 40, 25, 50.5, 34.0, 1.84)
    assert g.signal["at"][2] == round(fouls.HAND_UP * 1.84, 4) > 1.84  # above his head


def test_a_turned_head_faces_the_fouled_player_within_the_necks_reach():
    frames, events = _foul_frames()
    r = fouls.reactions(frames, events)
    g = Gait(heading=0.0)  # a2 faces +x; a9 is 3 m to his right (-y)
    fouls.look_at(g, r["a2"], 40, 25, 50.0, 37.0, frames[40])
    assert g.look["yaw"] == round(-fouls.LOOK_MAX, 4)  # a quarter turn away: as far as the neck goes
    g.heading = -1.2  # nearly facing him
    fouls.look_at(g, r["a2"], 40, 25, 50.0, 37.0, frames[40])
    assert abs(g.look["yaw"] - (-math.pi / 2 + 1.2)) < 1e-3
    # and the drawn brow turns that way: toward a9 (-y) from a body facing +x
    pose = {"action": "stand", "phase": 0, "speed": 0, "x": 50.0, "y": 37.0}
    plain = pose_markers(pose, 0.0, 1.84)["brow"]
    turned = pose_markers({**pose, "look": {"yaw": -1.0, "w": 1.0}}, 0.0, 1.84)["brow"]
    assert turned[1] < plain[1] - 0.04


def test_no_foul_no_reaction():
    frames, _ = _foul_frames()
    assert fouls.reactions(frames, []) == {}


def test_a_reaction_eases_in_rather_than_jumping():
    """Halfway up the ease the reaction is part-way: strictly between none and full."""
    fps = 100  # REACT_EASE_S / 2 = 0.15 s is a whole number of frames here
    w = fouls._weight(1000 + round(fouls.REACT_EASE_S / 2 * fps), 1000, fps)
    assert 0.0 < w < 1.0, w
