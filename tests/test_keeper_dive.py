"""P15 (lesson 198): a keeper dives only when moving across on his feet cannot bring his hands to the
ball, and launches no sooner than he must. Once he dived as soon as he reacted to any shot whose
crossing point lay beyond his hands: at balls a few centimetres beyond them that he could have
stepped to, and at long shots still more than a second away, so he landed before they arrived."""

import math

from ninety.sim import ball, offball
from ninety.sim.engine import DT, Engine


def shot_at_keeper(e: Engine, b: tuple) -> object:
    """The away keeper on his line at the goal's centre, still, a home shot `b` on its way, struck
    now by h9 just behind it (nobody else near: Engine(1)'s kick-off positions)."""
    k = e.keeper("away")
    k.x, k.y, k.vx, k.vy = 104.0, 34.0, 0.0, 0.0
    shooter = e.by_id["h9"]
    shooter.x, shooter.y, shooter.vx, shooter.vy = b[0] - 1.0, b[1], 0.0, 0.0
    e.possessor = None
    e.kicked = {"type": "shot", "team": "home", "player": shooter.id, "x": b[0], "y": b[1]}
    e.last_touch = shooter.id
    e.ball = b
    e.kicked_at = e.free_since = e.t
    return k


def beyond_his_hands(e: Engine, k, b: tuple) -> float:
    """How far beyond his hands' reach (offball.reach_for, the engine's own envelope) the shot `b`
    crosses his line when it gets there, from where he stands at the strike."""
    e.ball = b
    when, cross, z = e.ball_at_x(k.x)
    at = e.kicked_at + when
    arms, _ = offball.reach_for(True, at - e.stretch_from(k), z, at - e.rise_from(k))
    return abs(cross - k.y) - arms


def test_a_ball_beyond_his_hands_that_his_legs_get_him_to_is_taken_on_his_feet():
    # A ground shot from 13 m that crosses 0.55 m beyond his hands 0.77 s after it is struck. Moving
    # across gets his hands there in time (body.can_get_to), so he does, and takes it standing. Main
    # dived at it, and so does a keeper who only waits for the last moment to dive without asking
    # whether his legs will do: at that moment he is still on his way across.
    e = Engine(1)
    b = (92.0, 34.0, 0.3, 20.0, 3.0, 0.0)
    k = shot_at_keeper(e, b)
    assert 0.5 < beyond_his_hands(e, k, b) < offball.KEEPER_DIVE_TRAVEL_M  # the premise
    e.ball = b
    dived = False
    for _ in range(int(2.0 / DT)):
        e.step()
        dived = dived or e.dive is not None
        if e.possessor or e.shot_touched_by:
            break
    assert not dived
    assert e.shot_touched_by == "keeper"


def test_a_ball_wide_of_him_with_time_to_run_there_is_taken_on_his_feet():
    # 5.4 m wide and nearly two seconds away: beyond any dive from where he stands, but not beyond
    # his legs. He runs across and takes it standing.
    e = Engine(1)
    b = (80.0, 34.0, 0.3, 20.0, 4.5, 0.0)
    k = shot_at_keeper(e, b)
    assert beyond_his_hands(e, k, b) > offball.KEEPER_DIVE_TRAVEL_M  # the premise
    e.ball = b
    dived = False
    for _ in range(int(3.0 / DT)):
        e.step()
        dived = dived or e.dive is not None
        if e.possessor or e.shot_touched_by:
            break
    assert not dived and e.shot_touched_by == "keeper"


def fly_until_he_dives(e: Engine, k, seconds: float = 2.0) -> float | None:
    """The shot flies by its own flight and the keeper carries on at the velocity he has, a frame at a
    time, until he launches (keeper_dive alone decides when). The time he launched, or None."""
    for _ in range(int(seconds / DT)):
        if e.keeper_dive(k):
            return e.t
        e.ball = ball.step(e.ball, DT)
        k.x, k.y = k.x + k.vx * DT, k.y + k.vy * DT
        e.t += DT
    return None


def in_the_air_until(e: Engine, k) -> float:
    """Flies the dive already launched, a frame at a time: the time of the last frame it still moved him."""
    last = e.t
    while e.dive is not None:
        e.t += DT
        if e.keeper_dive(k):
            last = e.t
    return last


def test_at_a_long_shot_he_launches_no_sooner_than_he_must_and_is_in_the_air_as_it_arrives():
    # A ground shot from 15 m that crosses 1.2 m beyond his hands, further than his legs take him in
    # the time left (body.can_get_to), so only a dive gets there, and with time to spare: as he
    # reacts there is more time left than that dive takes. He waits on his feet and launches when the
    # dive just gets there: it ends as the ball arrives, not before, and not after it (one frame
    # later would be late). Main launched on reacting and landed 0.1 s early.
    from ninety.sim.body import can_get_to
    e = Engine(1)
    b = (90.0, 34.0, 0.3, 18.0, 3.5, 0.0)
    k = shot_at_keeper(e, b)
    need = beyond_his_hands(e, k, b)
    react = e.kicked_at + e.reaction(k)
    when, cross, _ = e.ball_at_x(k.x)
    arrives = e.kicked_at + when
    assert 0.0 < need < offball.KEEPER_DIVE_TRAVEL_M  # the premise: a dive reaches it,
    assert not can_get_to(k.physique, 0.0, cross - k.y, abs(cross - k.y) - need, 0.0, 0.0,
                          arrives - react)[0]  # his legs do not, standing as he reacts,
    assert arrives - react > offball.dive_time_to(need) + 2 * DT  # and there is time to spare
    launched = fly_until_he_dives(e, k)
    assert launched is not None and launched > react + DT  # not on reacting
    lands = launched + offball.dive_time_to(abs(e.dive[3]), e.dive[5])  # the dive's own model
    assert arrives - DT < lands <= arrives + 1e-9  # he lands as the ball gets there, never after
    assert in_the_air_until(e, k) >= arrives - DT  # flown frame by frame, still moving then


def test_a_run_toward_it_lets_him_launch_later_and_still_land_as_it_arrives():
    # P15: the push starts from the sideways run he is making toward it (dive_motion's v0), so with a
    # run the same dive takes less time and he launches later; he still lands as the ball arrives.
    def dive(vy: float) -> tuple[float, float, float]:
        e = Engine(1)
        b = (90.0, 34.0, 0.3, 18.0, 3.5, 0.0)
        k = shot_at_keeper(e, b)
        k.vy = vy
        arrives = e.kicked_at + e.ball_at_x(k.x)[0]
        launched = fly_until_he_dives(e, k)
        assert launched is not None
        assert e.dive[5] == vy  # the run he launched from
        return launched, launched + offball.dive_time_to(abs(e.dive[3]), e.dive[5]), arrives
    still, running = dive(0.0), dive(0.5)
    assert running[0] > still[0]  # with a run toward it, later
    for _, lands, arrives in (still, running):
        assert arrives - DT < lands <= arrives + 1e-9


def test_a_dive_launched_late_goes_as_far_as_the_one_launched_at_once():
    # Waiting does not shrink the dive: his arms stretch from when he reacted (P15), so where the
    # ball will cross and how far his hands reach by then are the same whenever he launches.
    e = Engine(1)
    b = (90.0, 34.0, 0.3, 18.0, 3.5, 0.0)
    k = shot_at_keeper(e, b)
    need = beyond_his_hands(e, k, b)
    assert fly_until_he_dives(e, k) is not None
    assert abs(abs(e.dive[3]) - min(need, offball.KEEPER_DIVE_TRAVEL_M)) < 1e-9  # standing still: the same
    assert math.copysign(1.0, e.dive[3]) == 1.0  # toward the ball


def test_he_does_not_dive_at_a_shot_going_wide():
    # Law 10: a shot whose own flight crosses his goal line outside the posts is not going in, and he
    # lets it go however far it is beyond his hands. On seed 8001 he once dived 1.45 m at a shot that
    # went 12 m wide. The same shot 1.5 m/s less across, heading inside the post, he dives at.
    e = Engine(1)
    wide = (90.0, 34.0, 0.3, 18.0, 5.0, 0.0)
    k = shot_at_keeper(e, wide)
    assert not e.heading_on_target("home") and beyond_his_hands(e, k, wide) > 1.0  # the premise
    e.ball = wide
    assert fly_until_he_dives(e, k) is None
    e = Engine(1)
    inside = (90.0, 34.0, 0.3, 18.0, 3.5, 0.0)
    k = shot_at_keeper(e, inside)
    assert e.heading_on_target("home")
    assert fly_until_he_dives(e, k) is not None
