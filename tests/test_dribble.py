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


def test_his_own_body_does_not_knock_on_a_touch_he_is_not_back_on_yet():
    e, att, _ = carry_in_space()
    assert not [ev for ev in e.match.events if ev["type"] == "deflection" and ev.get("player") == att.id]


def test_the_push_allows_for_his_own_kick_error():
    def push(exact: bool) -> float:
        e = Engine(3)
        att = e.by_id["h9"]
        for p in e.players:
            p.vx = p.vy = 0.0
            if p is not att:
                p.x, p.y = (2.0, 2.0) if p.team == "home" else (103.0, 66.0)
        att.x, att.y, att.vx, att.heading = 50.0, 34.0, 4.0, 0.0
        if exact:
            att.profile.strike_error = lambda *a: (0.0, 0.0, 0.0, 1.0)
        e.ball = (50.37, 34.0, 0.0, 0.0, 0.0, 0.0)
        e.beliefs[att.id].seen.clear()
        return e.touch_speed(att, 1.0, 0.0, 4.0, 12.0)

    assert push(exact=False) < push(exact=True)


def test_he_runs_through_his_touch_along_its_path_not_to_a_point_beside_it():
    e = Engine(3)
    att = e.by_id["h9"]
    att.x, att.y, att.vx, att.vy = 50.0, 34.0, 4.0, 0.0
    e.possessor, e.dribbler = None, att.id
    e.ball = (51.0, 34.0, 0.0, 6.0, 0.0, 0.0)
    tx, ty, speed = e.shape_target(att)
    assert tx > 51.0 + 6.0 and abs(ty - 34.0) < 0.1  # where it would stop, far beyond it
    assert speed > 6.0


def test_a_ball_deflected_off_someone_else_is_no_longer_his_touch():
    e = Engine(3)
    att, dfd = e.by_id["h9"], e.by_id["a4"]
    att.x, att.y, dfd.x, dfd.y = 50.0, 34.0, 52.0, 34.0
    e.possessor, e.dribbler = None, att.id
    e.ball = (51.6, 34.0, 0.0, 5.0, 0.0, 0.0)
    e.deflect(dfd, 51.7, 34.0, 0.0, 0.3)
    assert e.dribbler is None
