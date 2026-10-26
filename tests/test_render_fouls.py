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


# How a fall is drawn inside the engine's spell down (lesson 280): a stumble, a topple that gathers
# pace, the arms out, the engine's get-up. The engine's frames below are its own foul_fall_deg.


def _spell_frames(pid="a7", vx=5.0, vy=0.0, i0=20, n=120, span=3.0, way=1.2, start=5000):
    from ninety.sim.engine import foul_fall_deg

    out = []
    for i in range(n):
        deg = round(foul_fall_deg((i - i0) / FPS + 1 / FPS, span), 1) if i >= i0 else 0.0
        pl = {"id": pid, "team": "away", "x": 40.0, "y": 30.0, "vx": vx if i < i0 else 0.0,
              "vy": vy if i < i0 else 0.0, "heading": 0.0, "action": "down" if deg > 0 else "stand"}
        if deg > 0:
            pl["fall"], pl["fall_dir"] = deg, way
        out.append({"frame": start + i, "players": [pl]})
    return out


def _drawn(frames, pid="a7"):
    spells = fouls.falls(frames, FPS).get(pid, [])
    rows = []
    for i, fr in enumerate(frames):
        pl = next(p for p in fr["players"] if p["id"] == pid)
        g = Gait(heading=pl["heading"])
        g.action = "stand"
        fouls.fall_at(g, spells, pl, i, FPS, 1.84)
        rows.append((pl, g))
    return rows


def test_a_drawn_fall_is_inside_the_engines_spell_and_moves_nobody():
    """Down only on the frames the engine has him down, never deeper than its angle at the deepest,
    up when it has him up; x and y untouched."""
    frames = _spell_frames()
    before = copy.deepcopy(frames)
    for pl, g in _drawn(frames):
        if not pl.get("fall"):
            assert g.fall == 0.0 and g.brace is None
        else:
            assert 0.0 < math.degrees(g.fall) <= 85.0 + 1e-9
    assert frames == before


def test_he_stumbles_then_topples_faster_and_lands_before_the_get_up():
    """A stumble first (less over than the engine's steady topple at the same instant), then the
    topple gathers pace to the grass, which he reaches before the engine's get-up starts."""
    rows = _drawn(_spell_frames())
    down = [(pl["fall"], math.degrees(g.fall)) for pl, g in rows if pl.get("fall")]
    assert down[2][1] < down[2][0] and down[2][1] < 25.0  # the stumble, early on
    angles = [d for _, d in down]
    peak_i = angles.index(max(angles))
    rise = next(k for k, (e, _) in enumerate(down) if k > 0 and e < down[k - 1][0])  # the engine's get-up
    assert peak_i < rise and max(angles) >= 0.9 * 85.0
    steps = [b - a for a, b in zip(angles[:peak_i], angles[1:peak_i + 1], strict=True)]
    assert max(steps[len(steps) // 2:]) > max(steps[:len(steps) // 2])  # gathering pace


def test_the_same_foul_falls_the_same_way_and_another_differently():
    """Seeded by the player and the engine frame: the same spell is the same drawing in any clip
    that holds it (a clip starting earlier included), and other fouls vary."""
    a = [(g.fall, g.fall_dir) for _, g in _drawn(_spell_frames())]
    shifted = _drawn(_spell_frames(i0=30, n=130, start=4990))[10:]
    assert a == [(g.fall, g.fall_dir) for _, g in shifted]
    pids = ("a2", "a3", "a4", "a5")
    ways = {round([g.fall_dir for _, g in _drawn(_spell_frames(pid=p), p) if g.fall][-1], 3) for p in pids}
    lands = {max(round(g.fall, 3) for _, g in _drawn(_spell_frames(pid=p), p)) for p in pids}
    assert len(ways) == 4 and len(lands) >= 3


def test_his_run_into_the_contact_carries_him_its_way():
    """Running east into a foul that sends him north, he goes down north-east, more so the faster
    he ran; standing, within FALL_JITTER of the engine's way."""
    def final(vx):
        return [g.fall_dir for pl, g in _drawn(_spell_frames(vx=vx, way=math.pi / 2)) if pl.get("fall")][-1]

    still, fast = final(0.0), final(8.0)
    assert abs(still - math.pi / 2) <= fouls.FALL_JITTER + 1e-9
    assert fast < still  # toward the east, the way he ran
    first = next(g.fall_dir for pl, g in _drawn(_spell_frames(vx=8.0, way=math.pi / 2)) if pl.get("fall"))
    assert abs(first) < 1e-9  # the stumble goes with his run


def test_his_hands_go_out_and_meet_the_grass_and_the_labels_follow_them():
    """Arms out as he goes down: lying, both hands on the grass (within 0.15 m, never under it) and
    the label capsules' hands where the mesh twin draws them."""
    from ninety.render.scene import mesh_pose

    look = Look(id="a7", team="away", role="CM", height_m=1.84, build=1.0, skin="#a0785a", hair="#2b1d14")
    rows = _drawn(_spell_frames())
    lying = [g for pl, g in rows if pl.get("fall") == 85.0 and g.crouch is None][-1]  # before the get-up
    assert lying.brace is not None and lying.brace["w"] == 1.0
    mk = pose_markers(mesh_pose(lying, 40.0, 30.0, 0.0), 0.0, 1.84)
    for side in ("l", "r"):
        assert -0.01 <= mk[f"hand_{side}"][2] <= 0.15, mk[f"hand_{side}"]
    parts = {p["n"]: p for p in body_parts(40.0, 30.0, look, lying)}
    hands = [p for n, p in parts.items() if "hand" in n or "forearm" in n or "lowerarm" in n]
    assert hands
    pts = [q for p in hands for q in ([p["a"], p["b"]] if "b" in p else [p["a"]])]
    for side in ("l", "r"):
        assert min(math.dist(q, mk[f"hand_{side}"]) for q in pts) < 0.12
    standing = [g for pl, g in rows if not pl.get("fall")][0]
    assert standing.brace is None


def test_a_spell_under_way_when_the_clip_starts_is_drawn_as_the_engine_has_it():
    rows = _drawn(_spell_frames()[30:])
    for pl, g in rows:
        if pl.get("fall"):
            assert g.fall == math.radians(pl["fall"]) and g.fall_dir == pl["fall_dir"] and g.brace is None


def test_the_frame_row_carries_the_drawn_way_down():
    pl = {**_frames(1)[0]["players"][1], "fall": 40.0, "fall_dir": 1.2}
    down = fouls.row(pl, math.radians(30.0), 0.9)
    assert abs(down["fall"] - 30.0) < 0.05 and down["fall_dir"] == 0.9


def test_he_gets_up_on_one_knee_and_is_up_with_the_engine():
    """Getting up takes GET_UP_S (pushed up on the hands, a beat on one knee, then standing), its
    last frame is the engine's last frame down, and he never pivots back up straight-legged: on the
    knee he is lowered (lift < 0) while still well over."""
    rows = [(pl, g) for pl, g in _drawn(_spell_frames()) if pl.get("fall")]
    spells = fouls.falls(_spell_frames(), FPS)["a7"][0]
    up = [(pl, g) for k, (pl, g) in enumerate(rows) if k + spells["i0"] >= spells["i_up"]]
    assert len(up) >= round(1.2 * FPS)
    angles = [g.fall for _, g in up]
    assert all(b <= a + 1e-9 for a, b in zip(angles, angles[1:], strict=False))
    knelt = [g for _, g in up if g.crouch and g.crouch["w"] > 0.9]
    assert knelt and all(g.lift < -0.2 and math.radians(10) < g.fall < math.radians(50) for g in knelt)
    assert up[0][1].brace is not None and up[0][1].brace["w"] == 1.0  # pushing on his hands
    assert 0.0 < angles[-1] < math.radians(10)


def test_a_head_on_foul_turns_him_smoothly():
    """Running into a foul that sends him back the way he came, the drawn way down turns no more
    than 30 degrees a frame (audit: averaging opposite directions flipped it)."""
    rows = [g for pl, g in _drawn(_spell_frames(vx=-2.0, way=0.0)) if pl.get("fall")]
    ways = [g.fall_dir for g in rows]
    turn = (ways[-1] - ways[0] + math.pi) % (2 * math.pi) - math.pi
    assert abs(turn) > math.radians(120)  # he does turn from his run to the way he was sent
    for a, b in zip(ways, ways[1:], strict=False):
        assert abs((b - a + math.pi) % (2 * math.pi) - math.pi) <= math.radians(30)


def _dive(n, side=1.0, heading=0.0):
    """A keeper n frames into a full dive, drawn as the clip draws it (fall_at, then dive_pose)."""
    from ninety.render.scene import dive_pose

    g = Gait(heading=heading)
    for _ in range(n):
        g.action, g.dive, g.dive_drawn = "dive", side, 1.0
        fouls.fall_at(g, [], {"id": "a1", "x": 40.0, "y": 30.0}, 0, FPS, 1.9)
        dive_pose(g, 40.0, 30.0, 1.9)
    return g


def test_a_keeper_dives_straight_with_his_arms_on_past_his_head():
    """A dive is the straight body tipped toward his side, over no faster than DIVE_TIP_RATE to
    DIVE_TIP, the arms reaching on past his head; no bent spine (lesson 280)."""
    from ninety.render.meshpose import pose_angles
    from ninety.render.scene import DIVE_TIP, DIVE_TIP_RATE, mesh_pose

    assert abs(_dive(1).fall - DIVE_TIP_RATE) < 1e-9
    g = _dive(40)
    assert g.fall == DIVE_TIP and abs(g.fall_dir - math.pi / 2) < 1e-9  # his left
    pose = mesh_pose(g, 40.0, 30.0, 0.0)
    angles = pose_angles(pose, 0.0, 1.9)
    assert all(abs(v) < 1e-9 for k, v in angles.items() if k.startswith("spine") and isinstance(v, float))
    mk = pose_markers(pose, 0.0, 1.9)
    for side in ("l", "r"):
        assert mk[f"hand_{side}"][1] - 30.0 > mk["head"][1] - 30.0 > 1.2  # out past his head, left
    assert abs(_dive(40, side=-1.0).fall_dir + math.pi / 2) < 1e-9


def test_a_keeper_gets_up_from_a_dive_through_a_crouch():
    """Standing still after a full dive he gets up lowered on bent knees (the get-up of a fall), and
    is up by the end of DIVE_UP_FRAMES."""
    from ninety.render.scene import DIVE_UP_FRAMES, dive_pose

    g = _dive(40)
    seen = []
    for k in range(DIVE_UP_FRAMES - 1):
        g.action, g.speed, g.up_n, g.dive_up = "stand", 0.0, k, 1.0 - (k + 1) / DIVE_UP_FRAMES
        fouls.fall_at(g, [], {"id": "a1", "x": 40.0, "y": 30.0}, 0, FPS, 1.9)
        dive_pose(g, 40.0, 30.0, 1.9)
        seen.append((g.fall, g.lift))
    assert min(lift for _, lift in seen) < -0.2
    assert seen[0][0] > math.radians(60) and seen[-1][0] < math.radians(10)
