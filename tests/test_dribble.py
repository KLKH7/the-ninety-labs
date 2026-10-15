"""Dribbling (D6): a run of touches the carrier runs onto, each pushed no further than he wins."""

import math

from ninety.sim import perception
from ninety.sim.engine import DT, TOUCH_GAP_S, Engine


def carry_in_space(seconds: float = 3.0):
    """h9 running at 4 m/s along y = 34 with the ball, carrying it to (100, 34); everyone else far
    away and nobody deciding anything. Returns the engine and, per frame, (possessor, dribbler)."""
    e = Engine(3)
    att = e.by_id["h9"]
    for p in e.players:
        p.vx = p.vy = 0.0
        if p is not att:
            p.x, p.y = (2.0, 2.0) if p.team == "home" else (103.0, 66.0)
    att.x, att.y, att.vx, att.heading = 50.0, 34.0, 4.0, 0.0
    e.give(att.id)
    e.ball = (att.x + 0.37, 34.0, 0.0, 4.0, 0.0, 0.0)
    e.decide = lambda *a, **k: None  # he only carries
    e.dribble_to = (100.0, 34.0)
    seen = []
    for _ in range(int(seconds / DT)):
        e.step()
        seen.append((e.possessor, e.dribbler))
    return e, att, seen


def test_a_dribbler_is_not_back_on_his_touch_before_the_gap_it_was_pushed_for():
    e, att, seen = carry_in_space()
    free = [d == att.id for _, d in seen]
    spells, run = [], 0
    for f in free:
        if f:
            run += 1
        elif run:
            spells.append(run)
            run = 0
    assert len(spells) >= 2  # he touched it ahead more than once
    assert min(spells) * DT >= TOUCH_GAP_S - DT  # never back on it the next frame


def test_in_space_a_dribbler_keeps_the_ball_and_runs_onto_his_touches():
    e, att, seen = carry_in_space()
    assert all(p in (att.id, None) for p, _ in seen)
    assert e.possessor == att.id or e.dribbler == att.id
    assert att.x > 50.0 + 3.0 * 3.0  # covered ground faster than a jog
    assert math.hypot(e.ball[0] - att.x, e.ball[1] - att.y) < 2.0


def test_no_push_when_a_seen_opponent_gets_to_it_first():
    def push(opponent_x: float | None):
        e = Engine(3)
        att = e.by_id["h9"]
        for p in e.players:
            p.vx = p.vy = 0.0
            if p is not att:
                p.x, p.y = (2.0, 2.0) if p.team == "home" else (103.0, 66.0)
        att.x, att.y, att.vx = 50.0, 34.0, 4.0
        e.ball = (50.37, 34.0, 0.0, 0.0, 0.0, 0.0)
        view = e.beliefs[att.id]
        view.seen.clear()
        if opponent_x is not None:  # he believes a4 is standing on his line ahead
            view.seen["a4"] = perception.Sighting(opponent_x, 34.0, 0.0, 0.0, e.t)
        return e.touch_speed(att, 1.0, 0.0, 4.0, 9.0)

    assert push(None) is not None
    assert push(53.0) is None  # he could not be back on it before a4
    far = push(70.0)
    assert far is not None and far <= push(None)
