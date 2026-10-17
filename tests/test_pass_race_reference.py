"""The passer's estimate (decisions.pass_confidence) against a naive reference race: every point of
every flight, no bounds, no lookup tables, no cutoffs that only skip work, no remembered flights.
The production race takes shortcuts for speed; they must change nothing, so the two must agree.
Scenes come from the engine itself (engine.scene_for during a match) and from random pitches with
moving opponents and real passers."""

import math
import random

from ninety.sim import decisions as D
from ninety.sim import offball, perception
from ninety.sim.body import can_get_to, relative_speed
from ninety.sim.engine import Engine
from ninety.sim.firsttouch import CUSHION, KEEP_MPS, SURFACES
from ninety.sim.profiles import Profile


def ref_flight(ground: float, up: float):
    return D.fly((round(ground / D.LAUNCH_STEP_MPS), round(up / D.LAUNCH_STEP_MPS)))


def ref_reach(points, rests, t_end, sx, sy, ux, uy, px, py, vx, vy, react, limit, box_x, late):
    """Hard: the first point he can play (a ball at rest whenever he gets there). Late: the least,
    over every playable point before `limit`, of when the ball and he could both be there."""
    best, at, last = math.inf, -1, len(points) - 1
    for i, (t, a, z, _, _) in enumerate(points):
        if t > limit or t >= t_end:
            break
        resting = rests and i == last
        if t <= react and not resting:
            continue
        bx, by = sx + ux * a, sy + uy * a
        hands = box_x is not None and D.in_box(bx, by, box_x)
        reach_m, reach_z = offball.reach_for(hands, t - react, z, t - max(react, offball.UP_AFTER_CONTACT_S))
        if z > reach_z:
            continue
        ok, gap, along = can_get_to(D.AVERAGE_BODY, bx - px, by - py, reach_m, vx, vy, t - react)
        if ok:
            arrive = t
        elif late or resting:
            arrive = max(t, react + D.AVERAGE_BODY.time_to_cover(gap, along))
        else:
            continue
        if not late:
            return (arrive, i) if arrive <= limit else (math.inf, -1)
        if arrive < best:
            best, at = arrive, i
    return best, at


def reference(scene, tx, ty, mx, my, age, lofted, pace, receiver):
    sx, sy = scene.x, scene.y
    direction = math.atan2(ty - sy, tx - sx)
    # P16: everyone moves on while he turns
    _, wait = D.strike_turn(scene.heading, tx - sx, ty - sy, scene.throw)
    seen = {m[0]: m for m in scene.mates}
    meant = seen.get(receiver, (receiver, mx, my, age))
    mvx, mvy = meant[4:6] or (0.0, 0.0)
    mates = [(mx + mvx * wait, my + mvy * wait, mvx, mvy, perception.SIMPLE_REACTION_S,
              scene.absorb.get(receiver, D.CONTROL_EST_MPS))]
    for mid, qx, qy, _, *vel in scene.mates:
        if mid != receiver:
            qvx, qvy = vel or (0.0, 0.0)
            mates.append((qx + qvx * wait, qy + qvy * wait, qvx, qvy, perception.CHOICE_REACTION_S,
                          scene.absorb.get(mid, D.CONTROL_EST_MPS)))
    cx, cy = sx - scene.ball_offset[0], sy - scene.ball_offset[1]
    react = perception.CHOICE_REACTION_S
    total = 0.0
    for w, d_angle, ground, up in D.strike_nodes(scene, tx, ty, lofted, pace):
        points, rests = ref_flight(ground, up)
        ux, uy = math.cos(direction + d_angle), math.sin(direction + d_angle)
        t_end = next((t for t, a, *_ in points if D.out_of_play(sx + ux * a, sy + uy * a)), math.inf)
        take, at, taker = math.inf, -1, None
        for mate in mates:
            t, i = ref_reach(points, rests, t_end, sx, sy, ux, uy, *mate[:5], math.inf, None, False)
            if t < take:
                take, at, taker = t, i, mate
        if taker is None:
            continue
        _, _, z, g, vz = points[at]
        if at == len(points) - 1 and rests:
            g = vz = 0.0
        rel = relative_speed(g * ux, g * uy, vz, taker[2], taker[3])
        # The engine's touch: the part the ball meets at its height (SURFACES) kills its CUSHION share
        # of a foot's pace, and he keeps it if what is left is no more than KEEP_MPS. Written out here,
        # not a call to firsttouch.surface, on purpose: this is an independent reference.
        part = next(name for name, top in SURFACES if z <= top)
        absorb = taker[5] * CUSHION[part]
        p = D.sigmoid((absorb + KEEP_MPS - rel) / D.CONTROL_MARGIN_MPS)
        horizon = take + D.OPPONENT_LATE_S
        for ox0, oy0, ovx, ovy, keeper in scene.moving:
            ox, oy = ox0 + ovx * wait, oy0 + ovy * wait
            d = math.hypot(ox - cx, oy - cy)
            p *= 1 - D.body_hit(points, take, sx, sy, ux, uy, ox, oy, ovx, ovy, react,
                                perception.POSITION_ERROR_PER_M * d, perception.VELOCITY_ERROR_PER_M * d)
            t, _ = ref_reach(points, rests, t_end, sx, sy, ux, uy, ox, oy, ovx, ovy, react, horizon,
                             scene.goal_x if keeper else None, True)
            if t <= horizon:
                p *= D.sigmoid((t - take) / D.LANE_MARGIN_S)
        total += w * p
    return total * (0.8 if age > D.STALE_S else 1.0)


def estimates_asked(scene):
    """Every pass estimate the passer makes choosing from this scene (D.options), as asked."""
    asked = []
    production = D.pass_confidence

    def record(*args):
        asked.append(args)
        return production(*args)
    D.pass_confidence = record
    try:
        D.options(scene)
    finally:
        D.pass_confidence = production
    return asked


def engine_scenes(seed: int, minutes: float, every: int):
    e = Engine(seed)
    scenes = []
    for _ in range(int(minutes * 60 * 25)):
        e.step()
        if e.possessor and e.frame % every == 0 and not e.restart:
            scenes.append(e.scene_for(e.by_id[e.possessor]))
    return scenes


def random_scenes(n: int, rng: random.Random):
    scenes = []
    for _ in range(n):
        opps = [(rng.uniform(0, 105), rng.uniform(0, 68), rng.uniform(-6, 6), rng.uniform(-6, 6), i == 0)
                for i in range(11)]
        mates = [(f"m{i}", rng.uniform(0, 105), rng.uniform(0, 68), rng.choice((0.0, 3.0)),
                  rng.uniform(-6, 6), rng.uniform(-6, 6)) for i in range(10)]
        x, y = rng.uniform(5, 100), rng.uniform(5, 63)
        scenes.append(D.Scene(x, y, rng.choice((0.0, 105.0)), mates, [o[:2] for o in opps], opps[0][:2],
                              0.5, 0.5, 0.5, (), 0.0, opps, {m[0]: rng.uniform(12, 24) for m in mates},
                              Profile.generate(rng.choice(("CM", "LCB", "RW")), rng),
                              heading=rng.uniform(-3, 3),
                              fresh=rng.uniform(0.5, 1.0),
                              ball_offset=(rng.uniform(-0.6, 0.6), rng.uniform(-0.6, 0.6))))
    return scenes


def test_the_estimate_is_the_naive_race_without_its_shortcuts(monkeypatch):
    monkeypatch.setattr(D, "POSSESSION", None)
    scenes = engine_scenes(3, 4.0, 150) + random_scenes(25, random.Random(5))
    asked = [a for s in scenes for a in estimates_asked(s)]
    assert len(asked) >= 400
    worst, middling = 0.0, 0
    for args in asked:
        fast = D.pass_confidence(*args)
        worst = max(worst, abs(fast - reference(*args)))
        middling += 0.05 < fast < 0.95
    print(f"{len(asked)} estimates, {middling} between 0.05 and 0.95, largest difference {worst:.1e}")
    assert worst <= 1e-12
    assert middling >= 40  # a control: many of the cases are genuinely in doubt
