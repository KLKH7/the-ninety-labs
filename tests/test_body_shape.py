"""The body is as wide as a footballer's shoulders and as deep as his chest, turned the way he faces
(ninety/sim/shape.py, GROUNDING P11), and the ball, other players and the renderer all meet that
same shape."""

import math
import random

from ninety.render.scene import Gait, Look, advance_gaits, body_parts, face
from ninety.sim import ball, body, engine, firsttouch, profiles, shape
from ninety.sim.engine import BODY_RESTITUTION, DT, Engine


def still(e: Engine) -> None:
    for p in e.players:
        p.vx = p.vy = 0.0


def test_the_body_is_shoulders_wide_and_chest_deep_whichever_way_he_faces():
    for heading in (0.0, 0.7, math.pi / 2, -2.5):
        assert math.isclose(shape.surface(heading, heading), shape.CHEST_DEPTH_M / 2)  # chest
        assert math.isclose(shape.surface(heading + math.pi, heading), shape.CHEST_DEPTH_M / 2)  # back
        assert math.isclose(shape.surface(heading + math.pi / 2, heading), shape.SHOULDER_BREADTH_M / 2)
        assert math.isclose(shape.surface(heading - math.pi / 2, heading), shape.SHOULDER_BREADTH_M / 2)


def test_the_surface_is_where_the_clearance_is_zero_in_every_direction():
    rng = random.Random(3)
    for _ in range(500):
        heading, angle = rng.uniform(-math.pi, math.pi), rng.uniform(-math.pi, math.pi)
        r = shape.surface(angle, heading)
        x, y = 10.0, 20.0
        assert abs(shape.clearance(x + r * math.cos(angle), y + r * math.sin(angle), x, y, heading)) < 1e-9


def test_the_first_touch_is_where_a_ball_first_comes_within_reach_of_the_outline():
    rng = random.Random(5)
    paths = [tuple(rng.uniform(-1.0, 1.0) for _ in range(4)) for _ in range(300)]
    paths += [(-1.0, y, 1.0, y) for y in (0.0, 0.2, 0.3, 0.33)]  # along the shoulders (parallel)
    paths += [(y, -1.0, y, 1.0) for y in (0.0, 0.2, 0.3)]
    for x0, y0, x1, y1 in paths:
        heading = rng.uniform(-math.pi, math.pi) if abs(x0) < 1 or abs(y0) < 1 else 0.0
        found = shape.first_contact(x0, y0, x1, y1, 0.0, 0.0, heading, ball.RADIUS)
        fine = next((k / 4000 for k in range(4001)
                     if shape.clearance(x0 + k / 4000 * (x1 - x0), y0 + k / 4000 * (y1 - y0), 0.0, 0.0,
                                        heading) <= ball.RADIUS), None)
        assert (found is None) == (fine is None)
        if found is not None:
            assert abs(found - fine) < 1e-3


def test_resting_against_the_outline_is_a_balls_radius_clear_in_every_direction():
    rng = random.Random(9)
    for _ in range(500):
        heading, angle = rng.uniform(-math.pi, math.pi), rng.uniform(-math.pi, math.pi)
        r = shape.surface(angle, heading, pad=ball.RADIUS)
        assert math.isclose(shape.clearance(r * math.cos(angle), r * math.sin(angle), 0.0, 0.0, heading),
                            ball.RADIUS, abs_tol=1e-9)


def roll_past(heading: float) -> Engine:
    """A ball rolls along the line y = 30.3, 0.3 m from a still player's centre at (50, 30)."""
    e = Engine(1)
    still(e)
    p = e.by_id["a6"]
    p.x, p.y, p.heading = 50.0, 30.0, heading
    e.possessor, e.last_touch, e.kicker_clear, e.kicked_at = None, "h2", True, e.t  # body only
    for q in e.players:  # nobody else anywhere near
        if q is not p:
            q.x, q.y = 10.0, 60.0
    before = (49.8, 30.3, 0.0, 10.0, 0.0, 0.0)
    e.ball = (49.8 + 10.0 * DT, 30.3, 0.0, 10.0, 0.0, 0.0)
    e.contact(before)
    return e


def test_a_ball_passing_his_shoulder_hits_him_but_the_same_ball_past_his_chest_misses():
    side_on = roll_past(0.0)  # facing along the ball's path: 0.3 m out is his shoulder
    hit = next(ev for ev in side_on.match.events if ev["type"] == "deflection")
    p = side_on.by_id["a6"]
    # met where it first touched his shoulder, and bounced off the surface there, not carried
    # on through: the part of its velocity into his body is reversed, the rest kept
    assert math.isclose(shape.clearance(hit["x"], hit["y"], p.x, p.y, p.heading), ball.RADIUS, abs_tol=0.02)
    sx, sy = shape.nearest_on_spine(hit["x"], hit["y"], p.x, p.y, p.heading)
    n = math.hypot(hit["x"] - sx, hit["y"] - sy)
    nx, ny = (hit["x"] - sx) / n, (hit["y"] - sy) / n
    into = 10.0 * nx
    assert into < -1.0  # it was a real hit, not a graze
    assert math.isclose(side_on.ball[3] * nx + side_on.ball[4] * ny, -BODY_RESTITUTION * into, rel_tol=0.1)
    # and it leaves from that point on his surface, flying on for what is left of the step
    left = DT - (hit["x"] - 49.8) / 10.0
    flown = math.hypot(side_on.ball[0] - hit["x"], side_on.ball[1] - hit["y"])
    assert math.isclose(flown, math.hypot(side_on.ball[3], side_on.ball[4]) * left, abs_tol=0.005)
    assert shape.clearance(side_on.ball[0], side_on.ball[1], p.x, p.y, p.heading) >= ball.RADIUS
    face_on = roll_past(math.pi / 2)  # facing the ball's line: 0.3 m is past his chest, in the air
    assert not any(ev["type"] == "deflection" for ev in face_on.match.events)
    assert face_on.ball[3] == 10.0


def pair(dx: float, dy: float) -> tuple:
    """Two still-facing players, both facing +x, b closing on a at 2 m/s."""
    e = Engine(1)
    still(e)
    a, b = e.by_id["h6"], e.by_id["a6"]
    a.x, a.y, a.heading = 50.0, 30.0, 0.0
    b.x, b.y, b.heading = 50.0 + dx, 30.0 + dy, 0.0
    for q in e.players:
        if q not in (a, b):
            q.x, q.y = 10.0 + 2 * len(q.id), 60.0
    d = math.hypot(dx, dy)
    b.vx, b.vy = -2.0 * dx / d, -2.0 * dy / d
    a.physique.grip_used = b.physique.grip_used = 0.0
    e.separate()
    return a, b


def test_bodies_brace_where_their_shapes_touch_not_at_a_fixed_distance():
    a, b = pair(0.0, 0.45)  # side by side, 0.45 m apart: shoulders overlap
    assert math.hypot(b.vx, b.vy) < 2.0
    a, b = pair(0.45, 0.0)  # one behind the other, 0.45 m apart: chest to back is 0.25 m of air
    assert math.isclose(math.hypot(b.vx, b.vy), 2.0) and a.vx == a.vy == 0.0


def test_a_ball_at_his_feet_rests_against_his_body_on_the_side_he_faces():
    e = Engine(1)
    still(e)
    c = e.by_id["h6"]
    c.x, c.y, c.heading = 40.0, 34.0, 0.3
    for q in e.players:
        if q is not c:
            q.x, q.y = 90.0 if q.team == "away" else 10.0, 5.0 + 2 * int(q.id[1:])
    e.possessor = e.last_touch = c.id
    e.hold_until = e.t + 60.0  # he keeps it: no decisions in this test
    e.ball = (40.0 + 0.21 * math.cos(0.3), 34.0 + 0.21 * math.sin(0.3), 0.0, 0.0, 0.0, 0.0)
    for _ in range(25):
        e.tick_carrier()
        e.move_players()
    bx, by = e.ball[0], e.ball[1]
    angle = math.atan2(by - c.y, bx - c.x)
    assert abs((angle - c.heading + math.pi) % (2 * math.pi) - math.pi) < 0.2  # in front of him
    assert math.isclose(shape.clearance(bx, by, c.x, c.y, c.heading), ball.RADIUS, abs_tol=0.03)


LOOK = Look("h1", "home", "CM", 1.84, 1.0, "#d19a74", "#1b1410")


def plan_extent(parts: list[dict], heading: float, z_lo: float, z_hi: float) -> tuple[float, float]:
    """How far the drawn parts between two heights reach ahead of and beside the player's centre."""
    fwd = side = 0.0
    hx, hy = math.cos(heading), math.sin(heading)
    for p in parts:
        for key in ("a", "b"):
            if key in p and z_lo <= p[key][2] <= z_hi:
                x, y = p[key][0], p[key][1]
                fwd = max(fwd, abs(x * hx + y * hy) + p["r"])
                side = max(side, abs(-x * hy + y * hx) + p["r"])
    return fwd, side


def test_the_drawn_trunk_is_the_body_the_ball_meets():
    for heading in (0.0, 1.1):
        g = Gait(heading=heading)  # standing: no lean, no swing
        fwd, side = plan_extent(body_parts(0.0, 0.0, LOOK, g), heading, 0.95, 1.45)
        assert math.isclose(fwd, shape.CHEST_DEPTH_M / 2, abs_tol=0.01)
        assert math.isclose(side, shape.SHOULDER_BREADTH_M / 2, abs_tol=0.01)


def test_the_engine_reports_which_way_each_player_faces():
    e = Engine(1)
    e.kickoff("home")
    for _ in range(50):
        e.step()
    for row, p in zip(e.match.frames[-1]["players"], e.players, strict=True):
        assert row["id"] == p.id and math.isclose(row["heading"], p.heading, abs_tol=1e-3)


def test_his_own_kick_is_clear_of_him_once_it_is_outside_his_chest_not_a_wider_circle():
    e = Engine(1)
    still(e)
    k = e.by_id["h6"]
    k.x, k.y, k.heading = 50.0, 30.0, 0.0
    e.possessor, e.last_touch, e.kicker_clear, e.kicked_at = None, k.id, False, e.t
    before = (50.2, 30.0, 0.0, 1.0, 0.0, 0.0)  # struck straight ahead, a ball's width off his chest
    e.ball = (50.2 + 1.0 * DT, 30.0, 0.0, 1.0, 0.0, 0.0)
    e.contact(before)
    assert e.kicker_clear  # 0.24 m ahead of his centre is clear of a 0.20 m-deep chest


def test_whoever_the_ball_meets_first_takes_it_not_whoever_it_passes_closest():
    e = Engine(1)
    still(e)
    front, graze = e.by_id["a7"], e.by_id["a6"]
    front.x, front.y, front.heading = 50.5, 30.0, math.pi  # chest on to the ball: met at x = 50.29
    graze.x, graze.y, graze.heading = 50.45, 30.3, 0.0  # shoulder end beside its line: met at x = 50.30
    for q in e.players:
        if q not in (front, graze):
            q.x, q.y = 10.0, 60.0
    e.possessor, e.last_touch, e.kicker_clear, e.kicked_at = None, "h2", True, e.t
    before = (49.8, 30.0, 0.0, 30.0, 0.0, 0.0)
    e.ball = (49.8 + 30.0 * DT, 30.0, 0.0, 30.0, 0.0, 0.0)
    e.contact(before)
    assert [ev["player"] for ev in e.match.events if ev["type"] == "deflection"] == ["a7"]


def test_a_ball_off_one_shoulder_never_lands_inside_the_player_beside_him():
    e = Engine(1)
    still(e)
    a, b = e.by_id["a6"], e.by_id["a7"]
    a.x, a.y, a.heading = 50.0, 30.0, 0.0
    b.x, b.y, b.heading = 50.0, 30.5, 0.0  # shoulder to shoulder
    for q in e.players:
        if q not in (a, b):
            q.x, q.y = 10.0, 60.0
    e.possessor, e.last_touch, e.kicker_clear, e.kicked_at = None, "h2", True, e.t
    for y in (30.1, 30.2, 30.25, 30.3, 30.35):
        e.ball = (49.0, y, 0.0, 0.0, 0.0, 0.0)
        before = (49.0, y, 0.0, 20.0, 0.0, 0.0)
        e.ball = (49.0 + 20.0 * DT * 2, y, 0.0, 20.0, 0.0, 0.0)
        e.kicked_at, e.kicker_clear = e.t, True
        e.contact(before)
        for q in (a, b):
            assert shape.clearance(e.ball[0], e.ball[1], q.x, q.y, q.heading) >= ball.RADIUS - 1e-6


def test_braced_bodies_push_apart_along_the_line_between_their_nearest_surfaces():
    e = Engine(1)
    still(e)
    a, b = e.by_id["h6"], e.by_id["a6"]
    a.x, a.y, a.heading = 50.0, 30.0, 0.0
    b.x, b.y, b.heading = 50.1, 30.42, 0.0  # shoulder ends 0.16 m apart, off the line of centres
    for q in e.players:
        if q not in (a, b):
            q.x, q.y = 10.0 + 2 * len(q.id), 60.0
    b.vx, b.vy = 0.0, -2.0
    a.physique.grip_used = b.physique.grip_used = 0.0
    e.separate()
    nx, ny = 0.1, 0.12  # from a's shoulder end (50, 30.15) to b's (50.1, 30.27)
    dvx, dvy = b.vx, b.vy + 2.0
    assert math.hypot(dvx, dvy) > 0.01
    assert abs(math.atan2(dvy, dvx) - math.atan2(ny, nx)) < 1e-6


def test_a_shielded_ball_rests_a_balls_radius_off_his_body_at_any_angle():
    e = Engine(1)
    still(e)
    c, opp = e.by_id["h6"], e.by_id["a6"]
    c.x, c.y, c.heading = 40.0, 34.0, 0.3
    for q in e.players:
        if q not in (c, opp):
            q.x, q.y = 90.0 if q.team == "away" else 10.0, 5.0 + 2 * int(q.id[1:])
    toward = c.heading + math.radians(131) + math.pi  # he shields 131° off the way he faces
    e.possessor = e.last_touch = c.id
    e.hold_until = e.t + 60.0
    e.ball = (40.0, 34.0, 0.0, 0.0, 0.0, 0.0)
    for _ in range(40):
        opp.x, opp.y, opp.vx, opp.vy = 40.0 + 2.0 * math.cos(toward), 34.0 + 2.0 * math.sin(toward), 0.0, 0.0
        e.tick_carrier()
        e.move_players()
    assert math.isclose(shape.clearance(e.ball[0], e.ball[1], c.x, c.y, c.heading), ball.RADIUS, abs_tol=0.01)


def test_a_body_turns_no_faster_than_the_sourced_rate_and_gets_there():
    h = 0.0
    seen = []
    for _ in range(25):
        h2 = engine.turn_toward(h, math.pi - 0.01)
        seen.append(abs(h2 - h))
        h = h2
    assert max(seen) <= engine.TURN_RATE * DT + 1e-12
    assert math.isclose(h, math.pi - 0.01)
    assert math.isclose(engine.turn_toward(3.1, -3.1), -3.1)  # the short way, across the wrap


def test_no_player_turns_faster_than_the_sourced_rate_in_a_match():
    e = Engine(4)
    e.kickoff("home")
    last = {p.id: p.heading for p in e.players}
    for _ in range(300):
        e.step()
        for p in e.players:
            turn = abs((p.heading - last[p.id] + math.pi) % (2 * math.pi) - math.pi)
            assert turn <= engine.TURN_RATE * DT + 1e-9
            last[p.id] = p.heading


def test_the_drawn_body_faces_where_the_engine_says():
    g = Gait(heading=0.0)
    face(g, {"id": "h1", "x": 0.0, "y": 0.0, "heading": 2.0})
    assert g.heading == 2.0
    face(g, {"id": "h1", "x": 0.0, "y": 0.0})  # an older frame without it: left as it was
    assert g.heading == 2.0


def discs_at(parts: list[dict], z: float) -> list[tuple[float, float, float]]:
    """Horizontal cross-sections (x, y, radius) of the drawn capsules and spheres at height z."""
    out = []
    for p in parts:
        a, r = p["a"], p["r"]
        b = p.get("b", a)
        lo, hi = min(a[2], b[2]), max(a[2], b[2])
        if lo <= z <= hi and hi > lo:
            f = (z - a[2]) / (b[2] - a[2])
            out.append((a[0] + f * (b[0] - a[0]), a[1] + f * (b[1] - a[1]), r))
        for c in (a, b):
            if abs(z - c[2]) < r:
                out.append((c[0], c[1], math.sqrt(r * r - (z - c[2]) ** 2)))
    return out


def covered(discs: list[tuple[float, float, float]], x: float, y: float) -> bool:
    return any(math.hypot(x - dx, y - dy) <= r + 1e-6 for dx, dy, r in discs)


def test_at_chest_height_the_drawn_body_stays_inside_the_outline_and_fills_most_of_it():
    # GROUNDING P11, regression pins of a measurement (not from a source): standing, within 6 mm
    # of the outline; from hip to shoulder it fills 60 to 86% of it (72 to 81% from the chest up),
    # with no gap wider than 6 cm.
    for stature, build, heading in ((1.65, 0.9, 0.0), (1.84, 1.0, 1.1), (1.98, 1.15, -2.0), (1.65, 1.15, 0.4),
                                    (1.98, 0.9, 2.2)):
        look = Look("h1", "home", "CM", stature, build, "#d19a74", "#1b1410")
        parts = body_parts(0.0, 0.0, look, Gait(heading=heading))  # standing: no lean, no swing
        k = stature / 1.84
        for f in (0.92, 1.0, 1.1, 1.2, 1.3):  # his own hips up to his shoulders (fractions of 1.84 m)
            z = f * k
            discs = discs_at(parts, z)
            hx, hy, lx, ly = math.cos(heading), math.sin(heading), -math.sin(heading), math.cos(heading)
            for i in range(-24, 25) if f >= 1.0 else ():  # chest up: no gap straight across or through
                u = i / 24 * (shape.SHOULDER_BREADTH_M / 2 - 0.01)
                v = i / 24 * (shape.CHEST_DEPTH_M / 2 - 0.01)
                assert covered(discs, lx * u, ly * u) and covered(discs, hx * v, hy * v), (stature, z, i)
            for dx, dy, r in discs:  # nothing drawn outside it
                assert shape.clearance(dx, dy, 0.0, 0.0, heading) + r <= 0.006, (stature, z)
            inside = filled = 0
            widest = 0.0
            for a in range(-60, 61):
                for b in range(-60, 61):
                    x, y = a / 240, b / 240
                    if shape.clearance(x, y, 0.0, 0.0, heading) <= 0:
                        inside += 1
                        gap = min(math.hypot(x - dx, y - dy) - r for dx, dy, r in discs)
                        filled += gap <= 1e-6
                        widest = max(widest, gap)
            share = filled / inside
            assert (0.72 <= share <= 0.81) if f >= 1.0 else (0.60 <= share <= 0.86), (stature, f, share)
            assert widest <= 0.06, (stature, f, widest)



def test_a_ball_skimming_outward_across_his_chest_is_not_stopped_by_it():
    e = Engine(1)
    still(e)
    p = e.by_id["a6"]
    p.x, p.y, p.heading = 50.0, 30.0, 0.0
    for q in e.players:
        if q is not p:
            q.x, q.y = 10.0, 60.0
    e.possessor, e.last_touch, e.kicker_clear, e.kicked_at = None, "h2", True, e.t  # body only
    # Against his chest and running across it, drifting away from it: it is heading toward his
    # centre, but not into his body, so the body does not meet it.
    before = (50.2, 30.14, 0.0, 0.5, -10.0, 0.0)
    e.ball = (50.2 + 0.5 * DT, 30.14 - 10.0 * DT, 0.0, 0.5, -10.0, 0.0)
    e.contact(before)
    assert not any(ev["type"] == "deflection" for ev in e.match.events)
    assert e.ball[4] == -10.0


def test_a_deliberate_touch_is_taken_where_the_ball_first_comes_within_reach():
    e = Engine(1)
    still(e)
    p = e.by_id["a6"]
    p.x, p.y, p.heading = 50.0, 30.0, math.pi
    for q in e.players:
        if q is not p:
            q.x, q.y = 10.0, 60.0
    e.possessor, e.last_touch, e.kicker_clear = None, "h2", True
    e.kicked_at = e.t - 5.0  # he has long since reacted
    before = (48.5, 30.0, 0.0, 30.0, 0.0, 0.0)  # closest to him at the end of the step, 49.7
    e.ball = (48.5 + 30.0 * DT, 30.0, 0.0, 30.0, 0.0, 0.0)
    e.contact(before)
    played = next(ev for ev in e.match.events if ev["type"] in ("deflection", "possession_change"))
    assert played["player"] == p.id
    assert math.isclose(played["x"], 50.0 - engine.CONTROL_M, abs_tol=0.01)  # where his foot first gets it


def test_a_half_turn_takes_about_the_published_plant_time():
    h, frames = 0.0, 0
    while abs(h) < math.pi - 1e-9:
        h, frames = engine.turn_toward(h, math.pi), frames + 1
        if frames > 100:
            break
    assert 0.47 <= frames * DT <= 0.57  # GROUNDING P16: 180° on a final foot contact of about 0.52 s


def test_he_strikes_only_once_he_faces_within_the_published_approach_angle():
    e = Engine(1)
    still(e)
    c = e.by_id["h6"]
    c.x, c.y = 40.0, 34.0
    for off, ok in ((math.radians(50), True), (math.radians(70), False)):
        c.heading = off  # the target is straight down +x
        r = shape.surface(c.heading, c.heading, pad=ball.RADIUS)  # at his feet, in front of him
        e.ball = (c.x + r * math.cos(c.heading), c.y + r * math.sin(c.heading), 0.0, 0.0, 0.0, 0.0)
        assert e.can_strike(c, 60.0, 34.0) is ok
    c.heading = 0.0  # facing the target, but the ball is behind him (shielded): not yet
    r = shape.surface(math.pi, 0.0, pad=ball.RADIUS)
    e.ball = (c.x - r, c.y, 0.0, 0.0, 0.0, 0.0)
    assert not e.can_strike(c, 60.0, 34.0)


def test_his_own_kick_is_not_clear_of_him_while_it_still_touches_him():
    e = Engine(1)
    still(e)
    k = e.by_id["h6"]
    k.x, k.y, k.heading = 50.0, 30.0, 0.0
    e.possessor, e.last_touch, e.kicker_clear, e.kicked_at = None, k.id, False, e.t
    at = 50.0 + shape.RADIUS_M + ball.RADIUS * 0.9  # still overlapping his chest
    e.ball = (at, 30.0, 0.0, 0.0, 0.0, 0.0)
    e.contact((at, 30.0, 0.0, 0.0, 0.0, 0.0))
    assert not e.kicker_clear


def lone(e: Engine, pid: str, x: float, y: float, heading: float):
    still(e)
    p = e.by_id[pid]
    p.x, p.y, p.heading = x, y, heading
    for q in e.players:
        if q is not p:
            q.x, q.y = 10.0, 60.0
    return p


def test_a_ball_rising_through_his_reach_is_played_while_it_is_still_low():
    e = Engine(1)
    p = lone(e, "a6", 50.0, 30.0, math.pi)
    e.possessor, e.last_touch, e.kicker_clear, e.kicked_at = None, "h2", True, e.t - 5.0
    # In reach from x = 49 at 0.4 m up; by its closest point it is above a foot's reach.
    before = (48.8, 30.0, 0.3, 20.0, 0.0, 15.0)
    e.ball = (48.8 + 20.0 * DT * 1.5, 30.0, 0.3 + 0.75 * 1.5, 20.0, 0.0, 15.0)
    e.contact(before)
    hit = [ev for ev in e.match.events if ev["type"] in ("deflection", "possession_change")]
    assert hit and hit[0]["player"] == p.id
    assert abs(hit[0]["x"] - (50.0 - engine.CONTROL_M)) < 0.05  # taken where it came into reach, low


def test_a_dropping_ball_is_played_once_it_comes_down_into_reach():
    e = Engine(1)
    p = lone(e, "a6", 50.0, 30.0, math.pi)
    e.possessor, e.last_touch, e.kicker_clear, e.kicked_at = None, "h2", True, e.t - 5.0
    before = (49.0, 30.0, 1.5, 5.0, 0.0, -10.0)  # in reach across the ground, too high, falling
    e.ball = (49.4, 30.0, 0.7, 5.0, 0.0, -10.0)
    e.contact(before)
    hit = [ev for ev in e.match.events if ev["type"] in ("deflection", "possession_change")]
    assert hit and hit[0]["player"] == p.id
    assert math.isclose(hit[0]["x"], 49.0 + 0.4 * (1.5 - body.FOOT_REACH_Z) / 0.8, abs_tol=0.03)


def test_a_ball_he_controls_against_his_body_is_on_its_surface_not_inside_it():
    e = Engine(1)
    p = lone(e, "a6", 50.0, 30.0, math.pi)
    e.possessor, e.last_touch, e.kicker_clear, e.kicked_at = None, "h2", True, e.t - 5.0
    for vz in (-2.0, -20.0):  # killed by his touch, or knocked off it: either way, on his surface
        before = (49.95, 30.0, 1.5, 0.0, 0.0, vz)  # dropping straight down just inside his chest
        e.ball = (49.95, 30.0, 0.7, 0.0, 0.0, vz)
        e.possessor, e.last_touch, e.kicked_at = None, "h2", e.t - 5.0
        e.contact(before)
        assert shape.clearance(e.ball[0], e.ball[1], p.x, p.y, p.heading) >= ball.RADIUS - 1e-6


def test_a_runner_meets_a_ball_he_runs_into_within_one_step():
    e = Engine(1)
    p = lone(e, "a6", 50.0, 30.0, math.pi)
    p.vx = -9.0  # sprinting at it: 0.36 m a step
    e.possessor, e.last_touch, e.kicker_clear, e.kicked_at = None, "h2", True, e.t  # body only
    before = (49.4, 30.0, 0.0, 5.0, 0.0, 0.0)  # it stops 0.19 m short of where his chest started
    e.ball = (49.4 + 5.0 * DT, 30.0, 0.0, 5.0, 0.0, 0.0)
    e.contact(before)
    assert any(ev["type"] == "deflection" for ev in e.match.events)
    end_x = p.x + p.vx * DT  # where he is when the step ends
    assert shape.clearance(e.ball[0], e.ball[1], end_x, p.y, p.heading) >= ball.RADIUS - 1e-6


def test_the_clips_gaits_take_the_engines_heading_every_frame():
    gaits, prev = {"h1": Gait(heading=0.0)}, {}
    frame = {"ball": {"x": 0.0, "y": 0.0, "z": 0.0},
             "players": [{"id": "h1", "x": 5.0, "y": 5.0, "heading": 2.5}]}
    advance_gaits(gaits, prev, frame, 0.04)
    assert gaits["h1"].heading == 2.5 and prev["h1"] == (5.0, 5.0)


def test_a_ball_he_controls_while_running_ends_the_step_against_him_not_inside_him():
    e = Engine(1)
    p = lone(e, "a6", 50.0, 30.0, math.pi)
    p.vx = -6.0  # running at it
    e.possessor, e.last_touch, e.kicker_clear, e.kicked_at = None, "h2", True, e.t - 5.0
    before = (49.75, 30.0, 0.0, -1.0, 0.0, 0.0)  # rolling the way he runs, slowly: he takes it
    e.ball = (49.75 - 1.0 * DT, 30.0, 0.0, -1.0, 0.0, 0.0)
    e.contact(before)
    assert e.possessor == p.id
    end_x = p.x + p.vx * DT
    assert shape.clearance(e.ball[0], e.ball[1], end_x, p.y, p.heading) >= ball.RADIUS - 0.01
    # exactly where it met him, relative to him: carried on with him, no further
    met = next(ev for ev in e.match.events if ev["type"] == "possession_change")
    s = (49.75 - met["x"]) / (1.0 * DT)  # how far through the step the ball had come
    assert math.isclose(e.ball[0] - end_x, met["x"] - (p.x + p.vx * DT * s), abs_tol=0.02)


def test_a_dribbler_touches_the_ball_on_only_once_he_faces_where_it_goes():
    e = Engine(1)
    still(e)
    c = e.by_id["h6"]
    c.x, c.y, c.heading = 40.0, 34.0, 0.0
    for q in e.players:
        if q is not c:
            q.x, q.y = 90.0 if q.team == "away" else 10.0, 5.0 + 2 * int(q.id[1:])
    r = shape.surface(0.0, 0.0, pad=ball.RADIUS)
    e.possessor = e.last_touch = c.id
    e.hold_until = e.t
    e.dribble_to = (20.0, 34.0)  # behind him
    e.ball = (c.x + r, c.y, 0.0, 0.0, 0.0, 0.0)
    e.tick_carrier()
    assert e.possessor == c.id  # no touch through his own body: he turns with it first


def test_his_body_meets_a_ball_before_his_foot_can_if_it_gets_there_first():
    e = Engine(1)
    p = lone(e, "a6", 50.0, 30.0, math.pi)
    # Set directly, not left to the seed's draw of him: a touch too poor for his chest to keep it.
    p.profile.attributes["first_touch"] = 0.0
    e.possessor, e.last_touch, e.kicker_clear, e.kicked_at = None, "h2", True, e.t - 5.0
    before = (49.75, 30.0, 1.3, 8.0, 0.0, -8.0)  # chest high, coming down onto him
    e.ball = (49.75 + 8.0 * DT, 30.0, 1.3 - 8.0 * DT, 8.0, 0.0, -8.0)
    e.contact(before)
    # It meets his chest first (the part drawn is the part the engine used, firsttouch.surface),
    # before his foot could reach down to it; the chest cushions it (A4).
    hit = [ev for ev in e.match.events if ev["type"] == "deflection"]
    assert hit and hit[0]["player"] == p.id and e.possessor is None  # too fast for him to keep it
    assert e.pose(p)[0] == "chest"


def test_a_ball_over_his_head_does_not_meet_his_body():
    for z, met in ((1.7, True), (1.9, False)):
        e = Engine(1)
        lone(e, "a6", 50.0, 30.0, math.pi)
        e.possessor, e.last_touch, e.kicker_clear, e.kicked_at = None, "h2", True, e.t  # body only
        before = (49.6, 30.0, z, 10.0, 0.0, 0.0)
        e.ball = (49.6 + 10.0 * DT, 30.0, z, 10.0, 0.0, 0.0)
        e.contact(before)
        assert any(ev["type"] == "deflection" for ev in e.match.events) is met


def test_shielding_takes_the_ball_round_his_body_not_through_it():
    e = Engine(1)
    still(e)
    c, opp = e.by_id["h6"], e.by_id["a6"]
    c.x, c.y, c.heading = 40.0, 34.0, 0.0
    for q in e.players:
        if q not in (c, opp):
            q.x, q.y = 90.0 if q.team == "away" else 10.0, 5.0 + 2 * int(q.id[1:])
    e.possessor = e.last_touch = c.id
    e.hold_until = e.t + 60.0
    r = shape.surface(0.0, 0.0, pad=ball.RADIUS)
    e.ball = (c.x + r, c.y, 0.0, 0.0, 0.0, 0.0)  # at his feet in front; then a man arrives in front
    # Round his outline no faster than it settles (BALL_TO_FEET), so never across him in a jump.
    most = engine.BALL_TO_FEET * DT / (shape.RADIUS_M + ball.RADIUS) + 1e-6
    for _ in range(25):
        opp.x, opp.y, opp.vx, opp.vy = 42.0, 34.05, 0.0, 0.0
        was = math.atan2(e.ball[1] - c.y, e.ball[0] - c.x)
        e.tick_carrier()
        assert shape.clearance(e.ball[0], e.ball[1], c.x, c.y, c.heading) >= ball.RADIUS - 1e-6
        now = math.atan2(e.ball[1] - c.y, e.ball[0] - c.x)
        assert abs((now - was + math.pi) % (2 * math.pi) - math.pi) <= most
    assert e.ball[0] < c.x  # it ended up behind him, away from the man


def settle_frames(ball_at: tuple[float, float], opponent: tuple[float, float] | None, frames: int = 20,
                  z: float = 0.0):
    """A still carrier at (40, 34) facing +x, just in control of a ball at `ball_at`; where the
    ball is after each of his frames."""
    e = Engine(1)
    still(e)
    c, opp = e.by_id["h6"], e.by_id["a6"]
    c.x, c.y, c.heading = 40.0, 34.0, 0.0
    for q in e.players:
        if q not in (c, opp):
            q.x, q.y = 90.0 if q.team == "away" else 10.0, 5.0 + 2 * int(q.id[1:])
    e.possessor = e.last_touch = c.id
    e.hold_until = e.t + 60.0
    e.ball = (ball_at[0], ball_at[1], z, 0.0, 0.0, 0.0)
    seen = [(e.ball[0] - c.x, e.ball[1] - c.y, e.ball[2])]
    for _ in range(frames):
        if opponent:
            opp.x, opp.y, opp.vx, opp.vy = opponent[0], opponent[1], 0.0, 0.0
        else:
            opp.x, opp.y = 90.0, 60.0
        e.tick_carrier()
        seen.append((e.ball[0] - c.x, e.ball[1] - c.y, e.ball[2]))
        assert shape.clearance(e.ball[0], e.ball[1], c.x, c.y, c.heading) >= ball.RADIUS - 2e-3
    return seen


def test_a_ball_settling_to_his_feet_never_moves_faster_than_it_settles():
    most = 0.48 + 1e-6  # GROUNDING P6: it settles at up to 12 m/s, 0.48 m a frame
    for ball_at, opponent, z in (((41.0, 34.0), (42.0, 34.0), 0.0),  # ahead; he shields it behind him
                                 ((40.0, 35.0), None, 0.0),  # beside him, nobody near: round to his front
                                 ((39.4, 34.0), None, 0.0),  # behind him
                                 ((39.7, 34.3), None, 1.0)):  # from a keeper's hands, behind his shoulder
        seen = settle_frames(ball_at, opponent, z=z)
        for (x0, y0, z0), (x1, y1, z1) in zip(seen, seen[1:], strict=False):
            assert math.dist((x0, y0, z0), (x1, y1, z1)) <= most, (ball_at, x0, y0, z0, x1, y1, z1)
    assert settle_frames((41.0, 34.0), (42.0, 34.0))[-1][0] < 0  # and it does get behind him


def test_a_ball_met_partway_through_the_step_is_carried_on_with_him_for_the_rest_of_it_only():
    e = Engine(1)
    p = lone(e, "a6", 50.0, 30.0, math.pi)
    p.vx = -6.0
    e.possessor, e.last_touch, e.kicker_clear, e.kicked_at = None, "h2", True, e.t - 5.0
    before = (48.92, 30.0, 0.0, -1.0, 0.0, 0.0)  # 1.08 m from him, closing at 5 m/s: in reach 40% in
    e.ball = (48.92 - 1.0 * DT, 30.0, 0.0, -1.0, 0.0, 0.0)
    e.contact(before)
    assert e.possessor == p.id
    s = 0.08 / (5.0 * DT)
    met_x = 48.92 - 1.0 * DT * s  # where he took it, on the pitch
    assert math.isclose(e.ball[0], met_x + p.vx * DT * (1 - s), abs_tol=0.005)


def test_a_ball_he_bumps_into_is_no_new_surprise_to_him_so_he_plays_it():
    e = Engine(1)
    p = lone(e, "a6", 50.0, 30.0, math.pi)
    p.vx = -2.0  # running after a slower ball, about to have reacted to it
    e.possessor, e.last_touch, e.kicker_clear = None, "h2", True
    e.kicked_at = e.t - (e.reaction(p) - 0.02)
    e.ball = (49.78, 30.0, 0.0, -1.0, 0.0, 0.0)
    bumps = 0
    for _ in range(25):
        p.vx, p.vy = p.vx - 3.75 * DT, 0.0  # speeding up after it
        before = e.ball
        e.ball = (before[0] + before[3] * DT, before[1], 0.0, before[3], 0.0, 0.0)
        e.contact(before)
        bumps = sum(ev["type"] == "deflection" for ev in e.match.events)
        if e.possessor:
            break
        p.x += p.vx * DT
        e.t += DT
    assert e.possessor == p.id and bumps <= 1  # one bump at most, then he has it


def test_a_ball_he_fails_to_control_keeps_flying_and_falling_for_the_rest_of_the_step():
    e = Engine(1)
    p = lone(e, "a6", 50.0, 30.0, math.pi)
    p.profile.attributes["first_touch"] = 0.0  # it will not stick
    e.possessor, e.last_touch, e.kicker_clear, e.kicked_at = None, "h2", True, e.t - 5.0
    # dropping hard at his feet and driven at him, within his reach, too fast for him to steer
    # (firsttouch.beaten: more than his thigh kills plus his foot's, with no first touch)
    foot = profiles.FOOT_ABSORB_MPS[0]
    fast = foot * firsttouch.CUSHION["thigh"] + foot + 4.0  # its pace into him is past that
    before = (49.5, 30.0, 0.6, fast, 0.0, -12.0)
    e.ball = ball.step(before, DT)
    e.contact(before)
    assert any(ev["type"] == "deflection" for ev in e.match.events) and e.possessor is None
    assert e.ball[2] < 0.6 - 0.3  # it fell on through the step: a failed touch does not hold it up


def test_a_ball_off_one_player_meets_a_runner_where_he_has_got_to_by_then():
    e = Engine(1)
    for q in e.players:
        q.vx = q.vy = 0.0
        q.x, q.y = 10.0, 60.0
    a, b = e.by_id["a6"], e.by_id["a7"]
    a.x, a.y, a.heading = 50.0, 30.0, math.pi  # chest on to the ball
    b.x, b.y, b.heading, b.vy = 49.55, 30.6, 0.0, -8.0  # running across, into the rebound's way
    e.possessor, e.last_touch, e.kicker_clear, e.kicked_at = None, "h2", True, e.t  # bodies only
    before = (49.3, 30.0, 0.0, 30.0, 0.0, 0.0)
    e.ball = (49.3 + 30.0 * DT, 30.0, 0.0, 30.0, 0.0, 0.0)
    e.contact(before)
    assert [ev["player"] for ev in e.match.events if ev["type"] == "deflection"] == ["a6", "a7"]


def test_after_a_bump_a_new_strike_by_someone_else_is_new_to_everyone():
    e = Engine(1)
    p = lone(e, "a6", 50.0, 30.0, math.pi)
    e.possessor, e.last_touch, e.kicker_clear = None, "h2", True
    e.kicked_at = e.t - 5.0
    e.bumped = (p.id, e.t - 5.0)  # it came off him a while ago: he had long reacted
    k = e.by_id["h6"]
    k.x, k.y, k.heading = 40.0, 30.0, 0.0
    e.kick(k, 10.0, 0.0, 0.0)  # a new strike
    assert e.t - e.reacting_since(p) < e.reaction(p)  # he must react to it like anyone
    for strike in ("woodwork", "poke", "touch"):
        e.bumped = (p.id, e.t - 5.0)
        if strike == "woodwork":  # off the post: a new strike
            y = 34.0 + engine.GOAL_HALF_WIDTH
            e.ball = (105.4, y, 0.3, 20.0, 0.0, 0.0)
            e.woodwork((104.6, y, 0.3, 20.0, 0.0, 0.0))
        elif strike == "poke":
            h = e.by_id["h7"]
            h.x, h.y = 60.0, 40.0
            e.possessor, e.ball = h.id, (60.3, 40.0, 0.0, 0.0, 0.0, 0.0)
            e.poke(e.by_id["a7"], h)
        else:
            c = e.by_id["h8"]
            c.x, c.y, c.heading = 70.0, 20.0, 0.0
            c.vx, c.vy = 6.0 * math.cos(math.radians(40)), 6.0 * math.sin(math.radians(40))  # cutting across
            for q in e.players:  # nobody near: a push is his, so he does touch it on
                if q.team != c.team:
                    q.x, q.y, q.vx, q.vy = 10.0, 60.0, 0.0, 0.0
            e.beliefs[c.id].seen = {}
            e.possessor, e.dribble_to = c.id, (80.0, 20.0)
            e.ball = (70.21, 20.0, 0.0, 0.0, 0.0, 0.0)
            assert e.touch_ahead(c) and e.kicked_at == e.t  # a new strike (D6: not one along his run)
        assert e.bumped is None, strike


def test_a_ball_placed_at_his_centre_comes_out_to_his_feet_in_front_not_out_of_his_back():
    e = Engine(1)
    still(e)
    c = e.by_id["a6"]
    c.x, c.y, c.heading = 40.0, 34.0, math.pi  # facing -x
    for q in e.players:
        if q is not c:
            q.x, q.y = 90.0 if q.team == "home" else 10.0, 5.0 + 2 * int(q.id[1:])
    e.possessor = e.last_touch = c.id
    e.hold_until = e.t + 60.0
    e.ball = (40.0, 34.0, 0.0, 0.0, 0.0, 0.0)  # on his centre, as a restart places it
    e.tick_carrier()
    assert math.hypot(e.ball[0] - c.x, e.ball[1] - c.y) <= 0.48 + 1e-6
    assert e.ball[0] < c.x  # out of his front, toward his feet, never out of his back


def test_a_ball_he_knocks_on_into_the_post_comes_back_off_it_in_the_same_frame():
    e = Engine(1)
    for q in e.players:
        q.vx = q.vy = 0.0
        q.x, q.y = 50.0, 10.0
    d = e.by_id["a4"]
    y = 34.0 + engine.GOAL_HALF_WIDTH  # on the line of the post
    d.x, d.y, d.heading, d.vx = 104.4, y, 0.0, 8.0  # running back onto a slow ball
    e.possessor, e.last_touch, e.kicker_clear, e.kicked_at = None, "h9", True, e.t
    e.ball = (104.65, y, 0.0, 1.0, 0.0, 0.0)
    e.tick_free()
    assert [ev["type"] for ev in e.match.events] == ["deflection"]  # off him, then the post: no goal
    assert e.ball[3] < 0.0 and e.ball[0] < engine.PITCH_X


def test_a_ball_overlapping_him_after_a_turn_goes_round_him_not_through_him():
    e = Engine(1)
    still(e)
    c, opp = e.by_id["h6"], e.by_id["a6"]
    c.x, c.y, c.heading = 40.0, 34.0, 0.0
    for q in e.players:
        if q not in (c, opp):
            q.x, q.y = 90.0 if q.team == "away" else 10.0, 5.0 + 2 * int(q.id[1:])
    e.possessor = e.last_touch = c.id
    e.hold_until = e.t + 60.0
    r = shape.surface(0.0, 0.0, pad=ball.RADIUS) - 0.002  # 2 mm into his chest
    e.ball = (c.x + r, c.y, 0.0, 0.0, 0.0, 0.0)
    most = 0.48 / (shape.RADIUS_M + ball.RADIUS) + 1e-6  # round him, no faster than it settles
    for _ in range(10):
        opp.x, opp.y, opp.vx, opp.vy = 41.2, 34.02, 0.0, 0.0  # in front: he shields it behind him
        was = math.atan2(e.ball[1] - c.y, e.ball[0] - c.x)
        e.tick_carrier()
        now = math.atan2(e.ball[1] - c.y, e.ball[0] - c.x)
        assert abs((now - was + math.pi) % (2 * math.pi) - math.pi) <= most
        assert shape.clearance(e.ball[0], e.ball[1], c.x, c.y, c.heading) >= ball.RADIUS - 2e-3
    assert e.ball[0] < c.x


def rebound_past(runner_y: float, runner_vy: float) -> list[str]:
    """A 30 m/s ball off a6's chest, back toward a7 running across its way; who it meets this frame."""
    e = Engine(1)
    for q in e.players:
        q.vx = q.vy = 0.0
        q.x, q.y = 10.0, 60.0
    a, b = e.by_id["a6"], e.by_id["a7"]
    a.x, a.y, a.heading = 50.0, 30.0, math.pi
    b.x, b.y, b.heading, b.vy = 49.55, runner_y, 0.0, runner_vy
    e.possessor, e.last_touch, e.kicker_clear, e.kicked_at = None, "h2", True, e.t
    before = (49.3, 30.0, 0.0, 30.0, 0.0, 0.0)
    e.ball = (49.3 + 30.0 * DT, 30.0, 0.0, 30.0, 0.0, 0.0)
    e.contact(before)
    return [ev["player"] for ev in e.match.events if ev["type"] == "deflection"]


def test_the_rest_of_the_frame_is_timed_from_each_contact_and_holds_three_contacts():
    # Fast across: off a6, off a7 as he arrives, and back off a6, all in the same 40 ms.
    assert rebound_past(30.5, -12.0) == ["a6", "a7", "a6"]
    # Slower: he is not there yet when the rebound passes, so it does not meet him.
    assert rebound_past(30.6, -6.0) == ["a6"]


def test_his_own_kick_is_clear_of_him_only_once_it_is_clear_of_where_he_has_run_to():
    e = Engine(1)
    still(e)
    k = e.by_id["h6"]
    k.x, k.y, k.heading, k.vx = 50.0, 30.0, 0.0, 8.0  # running after his own soft touch
    e.possessor, e.last_touch, e.kicker_clear, e.kicked_at = None, k.id, False, e.t
    before = (50.22, 30.0, 0.0, 5.0, 0.0, 0.0)
    e.ball = (50.22 + 5.0 * DT, 30.0, 0.0, 5.0, 0.0, 0.0)  # clear of where he was, not of where he is
    e.contact(before)
    assert not e.kicker_clear


def test_a_ball_he_knocks_over_the_touchline_is_out_in_the_same_frame():
    e = Engine(1)
    for q in e.players:
        q.vx = q.vy = 0.0
        q.x, q.y = 50.0, 10.0
    d = e.by_id["a4"]
    d.x, d.y, d.heading, d.vy = 50.0, 67.6, math.pi / 2, 8.0  # running onto a slow ball by the line
    e.possessor, e.last_touch, e.kicker_clear, e.kicked_at = None, "h9", True, e.t
    e.ball = (50.0, 67.85, 0.0, 0.0, 1.0, 0.0)
    e.tick_free()
    assert [ev["type"] for ev in e.match.events] == ["deflection", "out_of_play"]
    assert e.restart is not None and e.restart.kind == "throw_in" and e.restart.team == "home"


def test_a_ball_held_high_on_his_centre_comes_out_no_faster_than_it_settles():
    e = Engine(1)
    still(e)
    c = e.by_id["a6"]
    c.x, c.y, c.heading = 40.0, 34.0, math.pi
    for q in e.players:
        if q is not c:
            q.x, q.y = 90.0 if q.team == "home" else 10.0, 5.0 + 2 * int(q.id[1:])
    e.possessor = e.last_touch = c.id
    e.hold_until = e.t + 60.0
    e.ball = (40.0, 34.0, 1.0, 0.0, 0.0, 0.0)  # in a keeper's hands, on his centre, a metre up
    was = e.ball
    e.tick_carrier()
    assert math.dist(was[:3], e.ball[:3]) <= 0.48 + 1e-6  # GROUNDING P6: out and down within 0.48 m a frame


def test_a_dribbler_whose_touch_is_declined_still_decides():
    e = Engine(1)
    still(e)
    c = e.by_id["h6"]
    c.x, c.y, c.heading = 40.0, 34.0, 0.0
    # No push is his. Set directly: whether he could run onto one depends on the seed's draw of him.
    e.touch_speed = lambda *args: None
    for q in e.players:
        if q is not c:
            q.x, q.y = 90.0 if q.team == "away" else 10.0, 5.0 + 2 * int(q.id[1:])
    r = shape.surface(0.0, 0.0, pad=ball.RADIUS)
    e.ball = (c.x + r, c.y, 0.0, 0.0, 0.0, 0.0)
    e.possessor = e.last_touch = c.id
    e.dribble_to, e.hold_until = (60.0, 34.0), e.t - 1.0
    calls = []
    e.decide = lambda p, **kw: calls.append(p.id)
    for _ in range(engine.DECIDE_EVERY):
        if e.possessor != c.id:
            break
        e.tick_carrier()
        e.frame += 1
    assert calls == [c.id]  # the touch was not his, so he keeps the ball and chooses again


def test_a_keeper_who_dives_while_running_brakes_his_run_and_does_not_stop_dead():
    e = Engine(1)
    k = e.by_id["a1"]
    k.x, k.y, k.heading, k.vx, k.vy = 100.0, 34.0, math.pi, -4.0, 0.0  # coming off his line
    e.dive = (k.id, e.t, k.y, 1.0, e.t)  # diving to his left
    seen = [k.vx]
    while e.dive is not None:
        x0 = k.x
        e.keeper_dive(k)
        assert math.isclose(k.x - x0, k.vx * DT)  # moved by the speed he has, not teleported
        seen.append(k.vx)
        e.t += DT
    # GROUNDING P2: never faster than his legs brake; while the dive's push takes all his grip he
    # carries the run, then brakes it
    assert all(-1e-9 <= b - a <= engine.BRAKE_MAX * DT + 1e-9 for a, b in zip(seen, seen[1:], strict=False))
    assert seen[1] < -3.0 and seen[-1] > seen[0]  # not stopped dead, but braked by the end


def test_a_keeper_who_dives_while_barely_moving_stops_and_does_not_run_back():
    e = Engine(1)
    k = e.by_id["a1"]
    k.x, k.y, k.heading, k.vx, k.vy = 100.0, 34.0, math.pi, -0.1, 0.0  # under one frame's braking
    e.dive = (k.id, e.t, k.y, 1.0, e.t)
    for _ in range(3):
        e.keeper_dive(k)
        assert k.vx == 0.0
        e.t += DT
