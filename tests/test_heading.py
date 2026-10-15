"""Heading (docs/GROUNDING.md P11, P17): the head plays a ball above a foot's reach, higher with a
jump once there is time to rise; a header is struck from where the ball is met, no harder than the
head can send it, with a header's error; a player heads a ball only when it is contested and lets
an unchallenged one drop to his feet; the passer's race decides the same way. Each test names the
mutation it must catch."""

import math

import pytest

from ninety.sim import ball, decisions, offball
from ninety.sim.body import (
    BODY_RESTITUTION,
    CONTROL_M,
    FOOT_REACH_Z,
    HAND_REACH_Z,
    HEAD_JUMP_Z,
    HEAD_REACH_M,
    HEAD_SPEED_MPS,
    HEAD_STAND_Z,
    JUMP_RISE_S,
)
from ninety.sim.engine import DT, Engine
from ninety.sim.profiles import HEADER_ERROR

LATE = JUMP_RISE_S + 0.1  # long enough after his reaction to have jumped


@pytest.mark.parametrize("z, since, heads, hands, reach", [
    (0.5, LATE, True, False, CONTROL_M),  # a foot
    (FOOT_REACH_Z + 0.2, 0.0, True, False, HEAD_REACH_M),  # a stooping header, no jump needed
    (HEAD_STAND_Z, 0.0, True, False, HEAD_REACH_M),  # a standing header at its highest
    (HEAD_STAND_Z + 0.1, JUMP_RISE_S * 0.5, True, False, None),  # needs a jump he has not had time for
    (HEAD_STAND_Z + 0.1, LATE, True, False, HEAD_REACH_M),  # jumping
    (HEAD_JUMP_Z + 0.05, LATE, True, False, None),  # over his jump
    (FOOT_REACH_Z + 0.2, LATE, False, False, None),  # letting it drop: only his feet
    (0.5, LATE, False, False, CONTROL_M),
    (HAND_REACH_Z - 0.1, 0.0, True, True, offball.arm_reach_m(0.0)),  # a keeper's hands
    (HAND_REACH_Z + 0.1, LATE, True, True, None),
], ids=["foot", "stooping", "standing", "too soon to jump", "jumping", "over the jump", "feet only above",
        "feet only below", "keeper hands", "over the keeper"])
def test_what_a_player_reaches_at_each_height(z, since, heads, hands, reach):
    """Mutations caught: no jump time; the head reaching any height; the jump's or the standing
    header's limit widened; `heads` ignored; a keeper's hands above his reach."""
    assert offball.reach_at(hands, since, z, heads) == reach


def test_a_header_is_judged_a_header_only_above_a_foot_and_out_of_a_keepers_hands():
    assert offball.headed(False, FOOT_REACH_Z + 0.01) and not offball.headed(False, FOOT_REACH_Z)
    assert not offball.headed(True, 2.0)


@pytest.mark.parametrize("distance, speed, z0, aim", [(10.0, 14.0, 1.9, 0.5), (8.0, 14.0, 1.9, 2.0),
                                                      (12.0, 12.0, 1.8, 0.1), (5.0, 10.0, 1.9, 0.1)])
def test_a_header_launch_reaches_its_aim_in_flight(distance, speed, z0, aim):
    """ball.aim_from: flown by the engine's ball physics, the ball is at the aimed height when it has
    travelled the distance, and has not come down before. Mutation caught: accepting a bounce."""
    ground, up = ball.aim_from(distance, speed, z0, aim, DT)
    assert math.hypot(ground, up) == pytest.approx(speed)
    path = ball.predict((0.0, 0.0, z0, ground, 0.0, up), DT, 5.0)
    k = next(k for k, s in enumerate(path) if s[0] >= distance)
    a, b = path[k - 1], path[k]
    height = a[2] + (distance - a[0]) / (b[0] - a[0]) * (b[2] - a[2])
    assert height == pytest.approx(aim, abs=0.02)
    assert all(s[2] > 0.0 for s in path[1:k])  # still in the air


def test_a_header_cannot_reach_what_is_beyond_it():
    assert ball.aim_from(30.0, 12.0, 1.8, 0.1, DT) is None


def scene_at(x: float, y: float, z: float, incoming: tuple[float, float, float]) -> decisions.Scene:
    e = Engine(1)
    p = next(q for q in e.players if q.role == "ST" and q.team == "home")
    p.x, p.y = x, y
    e.ball = (x + 0.2, y, z, *incoming)
    s = e.scene_for(p)
    s.header, s.z, s.incoming = True, z, incoming
    return s


def test_the_hardest_header_is_the_heads_drive_and_what_the_ball_keeps_of_its_own_speed():
    """P17. Mutations caught: the ball's own speed ignored; added when it is moving away; the wrong
    restitution."""
    still = scene_at(95.0, 34.0, 1.6, (0.0, 0.0, 0.0))
    hardest = (1 + BODY_RESTITUTION) * HEAD_SPEED_MPS
    assert decisions.header_cap(still, 105.0, 34.0) == pytest.approx(hardest)
    along = scene_at(95.0, 34.0, 1.6, (15.0, 0.0, 0.0))  # already going the way he heads it
    against = scene_at(95.0, 34.0, 1.6, (-15.0, 0.0, 0.0))  # coming at him: headed back where it came from
    assert decisions.header_cap(against, 105.0, 34.0) == pytest.approx(hardest + BODY_RESTITUTION * 15.0)
    assert decisions.header_cap(along, 105.0, 34.0) == pytest.approx(hardest)


def test_a_header_is_less_precise_than_a_kick():
    """Mutation caught: the header error not applied (or applied to kicks)."""
    p = Engine(1).players[9].profile
    kick = p.strike_error("finishing", 15.0, 5.0, 1.0, 0.0)
    head = p.strike_error("finishing", 15.0, 5.0, 1.0, 0.0, header=True)
    assert head[0] == pytest.approx(kick[0] * HEADER_ERROR)
    assert head[2] == pytest.approx(kick[2] * HEADER_ERROR)
    assert head[3] == 1.0  # no weaker foot


CROSS = (96.0, 24.0, 1.5, 0.0, 14.0, 3.7)  # fast, at his head height as it reaches him 0.7 s later
DROPPING = (96.0, 29.0, 3.0, 0.0, 6.0, 1.0)  # coming down onto him: head height, then his feet


def cross_at_head(defender_gap: float | None, state: tuple = CROSS) -> tuple[Engine, list[dict]]:
    """A ball played toward an attacker (`state`: by default crossed at his head height from the
    wing), with a defender `defender_gap` metres from him (None: nobody near), everyone else far
    away; played on for 1.2 s."""
    e = Engine(3)
    att = next(q for q in e.players if q.role == "ST" and q.team == "home")
    dfd = next(q for q in e.players if q.role == "RCB" and q.team == "away")
    for k, q in enumerate(e.players):
        if q not in (att, dfd):
            q.x, q.y, q.vx, q.vy = 30.0 + k, 5.0 + 2.5 * (k % 20), 0.0, 0.0
    att.x, att.y, att.vx, att.vy = 96.0, 34.0, 0.0, 0.0
    if defender_gap is None:
        dfd.x, dfd.y = 60.0, 60.0
    else:
        dfd.x, dfd.y = 96.0 + defender_gap, 34.0
    dfd.vx = dfd.vy = 0.0
    e.possessor = e.restart = e.set_play = None
    e.ball = state
    e.kicked = e.emit("pass", "home", state[0], state[1], player="h7")
    e.last_touch = "h7"
    e.kicked_at = e.free_since = e.t - 2.0  # everyone has long reacted
    start = len(e.match.events)
    for _ in range(int(1.2 / DT)):
        e.step()
    return e, e.match.events[start:]


def test_a_contested_cross_is_headed_from_where_it_is_met_no_harder_than_a_head_can():
    """Mutations caught: no header (the ball passes over the box, as before heading); a header struck
    from the ground; a header harder than the cap."""
    e, events = cross_at_head(0.6)
    headers = [ev for ev in events if ev["type"] in ("pass", "shot")]
    assert headers, "nobody headed a contested cross at head height"
    h = headers[0]
    z = e.match.frames[h["frame"]]["ball"]["z"]
    assert FOOT_REACH_Z < z <= HEAD_JUMP_Z
    cap = (1 + BODY_RESTITUTION) * HEAD_SPEED_MPS + BODY_RESTITUTION * 14.0
    assert h["ball_speed_kmh"] / 3.6 <= cap * 1.25  # the cap, with his speed error (a few SD of 6%)


def headers_in(e: Engine, events: list[dict]) -> list[dict]:
    return [ev for ev in events if ev["type"] in ("pass", "shot")
            and e.match.frames[ev["frame"]]["ball"]["z"] > FOOT_REACH_Z]


def test_an_unchallenged_ball_dropping_onto_him_is_brought_down_and_a_contested_one_headed():
    """P17 (engine.goes_up): the same ball, alone and with a defender at his shoulder. Mutations
    caught: heading whatever reaches the head first; never heading."""
    e, events = cross_at_head(None, DROPPING)
    assert not headers_in(e, events)
    striker = next(q.id for q in e.players if q.role == "ST" and q.team == "home")
    assert any(f["possessor"] == striker for f in e.match.frames[-10:])  # he has it at his feet
    e, events = cross_at_head(0.6, DROPPING)
    assert headers_in(e, events)


def test_a_ball_flying_past_him_that_he_cannot_bring_down_is_headed():
    """Unchallenged, but past him before he could get it at his feet: heading it is the only way to
    play it. Mutation caught: an unchallenged ball never headed."""
    e, events = cross_at_head(None, CROSS)
    assert headers_in(e, events)
