"""Engine-level behaviour the step 2 audit found untested: contact needs approach, passes go where
the passer believes, keepers only anticipate shots, pressers stand goal-side, and facing holds."""

import math
import random
from collections import defaultdict
from statistics import mean, pstdev

import pytest

from ninety.sim import ball, offball, perception, shape
from ninety.sim.body import BRAKE_MAX, STRIKE_FACING, TURN_RATE
from ninety.sim.body import move as move_body
from ninety.sim.engine import (
    BODY_RESTITUTION,
    COVER_BEHIND_M,
    DT,
    FPS,
    MISCONTROL_KEEP,
    RESTART_DELAY_S,
    Engine,
    simulate,
    throw_hands,
    throw_stand,
)
from ninety.sim.firsttouch import CUSHION, KEEP_MPS
from ninety.sim.profiles import FOOT_ABSORB_MPS, MAX_STRIKE_MPS
from ninety.sim.style import Style
from ninety.validate import check_physics


def still(e: Engine) -> None:
    for p in e.players:
        p.vx = p.vy = 0.0


def test_a_ball_moving_away_from_a_body_is_not_touched_by_it():
    e = Engine(1)
    still(e)
    p = e.by_id["a6"]
    p.x, p.y = 50.0, 30.0
    e.possessor, e.last_touch, e.kicker_clear, e.kicked_at = None, "h2", True, e.t  # body only
    before = (50.1, 30.0, 0.0, 12.0, 0.0, 0.0)  # starts at his body, rolling away from it
    e.ball = (50.1 + 12.0 * DT, 30.0, 0.0, 12.0, 0.0, 0.0)
    e.contact(before)
    assert e.ball[3] == 12.0 and not any(ev["type"] == "deflection" for ev in e.match.events)


def test_a_ball_into_a_body_rebounds_with_only_its_normal_part_reduced():
    e = Engine(1)
    still(e)
    p = e.by_id["a6"]
    p.x, p.y = 50.0, 30.0
    e.possessor, e.last_touch, e.kicker_clear, e.kicked_at = None, "h2", True, e.t  # nobody has reacted
    before = (49.5, 30.05, 0.0, 10.0, 2.0, 0.0)
    e.ball = (49.5 + 10.0 * DT, 30.05 + 2.0 * DT, 0.0, 10.0, 2.0, 0.0)
    e.contact(before)
    vx, vy = e.ball[3], e.ball[4]
    assert any(ev["type"] == "deflection" for ev in e.match.events)
    assert shape.clearance(e.ball[0], e.ball[1], p.x, p.y, p.heading) >= ball.RADIUS  # outside the body
    sx, sy = shape.nearest_on_spine(e.ball[0], e.ball[1], p.x, p.y, p.heading)
    nx, ny = e.ball[0] - sx, e.ball[1] - sy  # the body's surface normal where it was met
    n = math.hypot(nx, ny)
    nx, ny = nx / n, ny / n
    out, into_before = vx * nx + vy * ny, -(10.0 * nx + 2.0 * ny)
    assert math.isclose(out, BODY_RESTITUTION * into_before, rel_tol=0.05)
    tangent_before = 10.0 * -ny + 2.0 * nx
    assert math.isclose(vx * -ny + vy * nx, tangent_before, rel_tol=0.05)


def test_the_carrier_decides_on_where_he_believes_team_mates_are():
    e = Engine(1)
    still(e)
    carrier, mate = e.by_id["h6"], e.by_id["h9"]
    carrier.x, carrier.y = 40.0, 34.0
    e.ball = (40.3, 34.0, 0.0, 0.0, 0.0, 0.0)
    mate.x, mate.y = 55.0, 34.0
    e.beliefs[carrier.id].seen = {mate.id: perception.Sighting(55.0, 50.0, 0.0, 0.0, e.t)}  # wrong
    scene = e.scene_for(carrier)
    assert [(m[1], m[2]) for m in scene.mates] == [(55.0, 50.0)]  # never the truth
    assert scene.opponents == [] and scene.keeper is None  # nobody else seen
    keeper = e.keeper("away")
    e.beliefs[carrier.id].seen[keeper.id] = perception.Sighting(100.0, 34.0, 0.0, 0.0, e.t)
    scene = e.scene_for(carrier)
    assert scene.keeper == (100.0, 34.0) and scene.opponents == [(100.0, 34.0)]  # in lanes too


def test_a_keeper_reacts_to_the_ball_like_anyone_and_reads_only_shots_at_his_goal():
    e = Engine(1)
    keeper, outfield = e.keeper("away"), e.by_id["a6"]
    keeper.profile.attributes["reflexes"] = outfield.profile.attributes["reflexes"]
    assert e.reaction(keeper) == e.reaction(outfield)
    carrier = e.by_id["h9"]
    carrier.x, carrier.y, carrier.heading = 85.0, 34.0, 0.0
    e.give(carrier.id)
    e.ball = (85.37, 34.0, 0.0, 0.0, 0.0, 0.0)
    e.shoot(carrier)
    assert e.read and e.read[0] == keeper.id
    tx, ty, _ = e.shape_target(keeper)
    assert math.isclose(ty, min(34 + 3.66, max(34 - 3.66, e.read[1])))  # toward his read, within the posts
    e.give(carrier.id)
    assert e.read is None


def test_the_cover_stands_goal_side_of_the_ball_at_the_cover_distance():
    """T3: the second player covers 8 m behind the presser, goal-side of the ball (the constant
    was once shadowed by the 10 m commit-with-cover radius of D8)."""
    for team in ("home", "away"):
        e = Engine(1, styles={team: Style()})  # a mid style: engages at 60 m from its goal (T3)
        still(e)
        carrier = next(p for p in e.players if p.team != team and p.role == "CM")
        presser = next(p for p in e.players if p.team == team and p.role == "CM")
        cover = next(p for p in e.players if p.team == team and p.role == "RCM")
        carrier.x, carrier.y = 52.0, 34.0
        presser.x, presser.y = 55.0 if team == "away" else 49.0, 34.0
        e.ball = (52.0, 34.0, 0.0, 0.0, 0.0, 0.0)
        e.possessor = carrier.id
        brain = e.brains[team]
        brain.in_possession, brain.pressers, brain.markers = False, [presser.id, cover.id], {}
        tx, ty, _ = e.shape_target(cover)
        assert math.isclose(math.hypot(tx - 52.0, ty - 34.0), COVER_BEHIND_M, abs_tol=0.01)


def test_the_presser_stands_goal_side_for_both_teams():
    for team, defends_x in (("home", 0.0), ("away", 105.0)):
        e = Engine(1, styles={team: Style()})  # a mid style: engages at 60 m from its goal (T3)
        still(e)
        carrier = next(p for p in e.players if p.team != team and p.role == "CM")
        presser = next(p for p in e.players if p.team == team and p.role == "CM")
        carrier.x, carrier.y = 52.0, 34.0
        presser.x, presser.y = 55.0 if team == "away" else 49.0, 34.0
        e.ball = (52.0, 34.0, 0.0, 0.0, 0.0, 0.0)
        e.possessor = carrier.id
        brain = e.brains[team]
        brain.in_possession, brain.pressers = False, [presser.id]
        tx, _, _ = e.shape_target(presser)
        assert math.isclose(abs(tx - 52.0), brain.press_gap_m, abs_tol=0.01)
        assert abs(tx - defends_x) < abs(52.0 - defends_x)  # between the ball and his own goal


def test_nobody_presses_inside_the_law_distance_at_a_corner():
    e = Engine(1)
    still(e)
    e.possessor = None
    e.stop("corner", "home", (105.0, 0.0))
    e.ball = (105.0, 0.0, 0.0, 0.0, 0.0, 0.0)
    presser = e.by_id["a2"]
    presser.x, presser.y = 100.0, 5.0
    brain = e.brains["away"]
    brain.in_possession, brain.pressers = False, [presser.id]
    tx, ty, _ = e.shape_target(presser)
    assert math.hypot(tx - 105.0, ty - 0.0) >= 9.15 - 0.6  # the target is kept on the pitch


def test_facing_wraps_at_half_a_turn_and_holds_when_the_ball_is_at_his_feet():
    assert perception.visible(math.pi, 0.0, 0.0, -20.0, -0.5)  # just past -180 degrees
    assert perception.visible(-math.pi, 0.0, 0.0, -20.0, 0.5)
    assert perception.facing(2.0, 0.0, 0.0, 10.0, 10.0, 10.1, 10.0) == 2.0
    assert math.isclose(perception.facing(2.0, 0.0, 0.0, 10.0, 10.0, 20.0, 10.0), 0.0)


def test_a_keeper_may_not_handle_a_ball_he_released_until_someone_else_touches_it():
    e = Engine(1)
    keeper = e.keeper("home")
    keeper.x, keeper.y = 6.0, 34.0
    assert e.hands(keeper, 6.0, 34.0)
    e.ball = (6.3, 34.0, 0.0, 0.0, 0.0, 0.0)
    e.kick(keeper, 15.0, 0.0, 0.0)
    assert not e.hands(keeper, 6.5, 34.0)
    e.touched(e.by_id["a9"], 8.0, 34.0, controls=False)
    assert e.hands(keeper, 6.5, 34.0)


def test_a_carrier_turns_the_ball_onto_his_kicking_side_before_passing_behind_him():
    e = Engine(1)
    still(e)
    e.possessor = None
    carrier, mate = e.by_id["h6"], e.by_id["h5"]
    carrier.x, carrier.y, carrier.heading = 40.0, 34.0, 0.0
    mate.x, mate.y = 25.0, 34.0
    e.give(carrier.id)
    e.ball = (40.37, 34.0, 0.0, 0.0, 0.0, 0.0)  # at his feet, in front; the team-mate is behind
    e.pass_to(carrier, 25.0, 34.0, lofted=False)
    assert e.possessor == carrier.id and e.windup  # not struck through his own body
    for _ in range(10):
        e.tick_carrier()
        if e.possessor is None:
            break
    assert e.possessor is None and e.ball[3] < 0  # struck, from behind him, toward the team-mate
    assert e.ball[0] < carrier.x


def kicker(foot: str = "right") -> tuple[Engine, object]:
    e = Engine(3)
    still(e)
    p = e.by_id["h9"]
    p.x, p.y, p.heading = 50.0, 34.0, 0.0
    p.profile.foot = foot
    p.profile.attributes.update(finishing=0.5, composure=0.5, weak_foot=0.0)
    for q in e.players:
        if q.team == "away":
            q.x, q.y = 5.0, 5.0  # nobody near: no pressure
    return e, p


def test_execution_scatters_direction_by_the_profiles_error_and_never_kicks_down():
    e, p = kicker()
    angles, speeds = [], []
    for _ in range(3000):
        vx, vy, vz = e.execute(p, 21.0, 0.0, 0.0, "finishing")
        angles.append(math.degrees(math.atan2(vy, vx)))
        speeds.append(math.sqrt(vx * vx + vy * vy + vz * vz))
        assert vz == 0.0  # a ground pass is not lofted by error
    expected = p.profile.kick_error("finishing", 21.0, 0.0, 1.0, False)[0]
    assert abs(pstdev(angles) - expected) < 0.1 * expected
    assert max(e.execute(p, 35.9, 0.0, 0.0, "finishing")[0] for _ in range(500)) <= MAX_STRIKE_MPS


def mean_speed(e: Engine, p, deg: float) -> float:
    a = math.radians(deg)
    return mean(math.hypot(*e.execute(p, 20 * math.cos(a), 20 * math.sin(a), 0.0, "passing")[:2])
                for _ in range(2000))


def test_the_weaker_foot_is_used_on_its_side_and_strikes_slower():
    for foot, weak_side in (("right", 60.0), ("left", -60.0)):
        e, p = kicker(foot)
        assert mean_speed(e, p, weak_side) < 0.92 * mean_speed(e, p, -weak_side)


def test_the_engine_uses_each_profile_for_body_and_sight(monkeypatch):
    e = Engine(4)
    p = e.players[3]
    assert p.physique.f0 == p.profile.physique().f0 and p.physique.v0 == p.profile.physique().v0
    seen = {}
    def spy(belief, me, others, now, rng, half_angle, scan_interval):
        seen[me] = (half_angle, scan_interval)
    monkeypatch.setattr(perception, "observe", spy)
    for _ in range(6):
        e.perceive_and_think()
        e.frame += 1
    assert seen[(p.x, p.y, p.heading)] == (p.profile.view_half_angle(), p.profile.scan_interval())


def test_a_pass_is_struck_with_execution_error():
    angles = set()
    for seed in range(8):
        e, p = kicker()
        e.rng.seed(seed)
        mate = e.by_id["h10"]
        mate.x, mate.y = 70.0, 34.0
        e.give(p.id)
        e.ball = (50.37, 34.0, 0.0, 0.0, 0.0, 0.0)
        e.pass_to(p, 70.0, 34.0, lofted=False)
        angles.add(round(math.atan2(e.ball[4], e.ball[3]), 6))
    assert len(angles) > 1  # the same intended pass is not struck identically every time


def test_a_throw_in_is_always_thrown_even_with_nobody_free():
    e = Engine(1)
    still(e)
    e.possessor = None
    e.stop("throw_in", "home", (50.0, 0.0))
    taker = e.by_id[e.restart.taker]
    taker.x, taker.y = throw_stand(50.0, 0.0)  # he has run to his spot behind the line
    e.restart.ready_at = e.t
    e.tick_restart()
    assert e.throw_by == taker.id
    assert taker.y < -0.3  # standing behind the near touchline
    assert e.ball[1] < 0 and e.ball[2] > 1.5  # in the hands, off the pitch, not on a boot
    assert e.pose(taker) == ("throw", 0.0)
    for b in e.beliefs.values():
        b.seen.clear()  # he can see nobody to throw to
    b = e.beliefs[taker.id]
    b.next_scan = 1e9
    thrown_at = None
    for _ in range(int(10 / DT)):
        e.beliefs[taker.id].seen.clear()
        e.tick_carrier()
        assert e.dribble_to is None and not any(ev["type"] == "shot" for ev in e.match.events)
        if e.possessor is None:
            thrown_at = e.t
            break
        e.t += DT
        e.frame += 1
    assert thrown_at is not None and thrown_at <= 3.0  # down the line within a couple of seconds
    assert e.match.events[-1]["type"] == "pass" and e.ball[5] > 0  # thrown, through the air
    assert e.ball[2] > 1.5  # it left his hands, not his foot
    for _ in range(8):
        e.tick_free()
        e.t += DT
    assert e.restart is None and e.ball[1] > 0  # it enters; the release is not a new throw-in


def test_a_keeper_may_not_handle_a_team_mates_deliberate_pass():
    e = Engine(1)
    keeper, mate = e.keeper("home"), e.by_id["h3"]
    keeper.x, keeper.y = 6.0, 34.0
    e.kicked = {"type": "pass", "team": "home", "player": mate.id}
    e.last_touch = mate.id
    assert not e.hands(keeper, 6.0, 34.0)
    e.last_touch = "a9"  # an opponent got a touch on it
    assert e.hands(keeper, 6.0, 34.0)


def scatter(e: Engine, p, n: int = 1500) -> tuple[float, float]:
    """Spread of struck direction (degrees) and of struck speed (m/s) for one intended kick."""
    shots = [e.execute(p, 21.0, 0.0, 0.0, "finishing") for _ in range(n)]
    return (pstdev(math.degrees(math.atan2(vy, vx)) for vx, vy, _ in shots),
            pstdev(math.hypot(vx, vy) for vx, vy, _ in shots))


def test_pressure_widens_what_is_struck_unless_he_is_composed():
    e, p = kicker()
    calm = scatter(e, p)
    e.by_id["a6"].x, e.by_id["a6"].y = 50.8, 34.0  # an opponent at his shoulder
    pressed = scatter(e, p)
    assert pressed[0] > 1.15 * calm[0] and pressed[1] > 1.3 * calm[1] > 0
    p.profile.attributes["composure"] = 1.0
    assert math.isclose(scatter(e, p)[0], calm[0], rel_tol=0.1)


def test_a_tired_player_strikes_less_accurately():
    e, p = kicker()
    fresh = scatter(e, p)[0]
    p.physique.spent = 20 * 225.0  # a match of hard running: the slow store is low
    assert scatter(e, p)[0] > 1.1 * fresh


def test_a_keepers_read_is_centred_on_the_aim_and_needs_to_see_the_kicker():
    e = Engine(5)
    keeper, shooter = e.keeper("away"), e.by_id["h9"]
    keeper.x, keeper.y, keeper.heading = 104.0, 34.0, math.pi  # facing the play
    shooter.x, shooter.y = 88.0, 34.0
    reads = [e.keeper_read(keeper, shooter, 36.0) for _ in range(3000)]
    assert abs(mean(reads) - 36.0) < 0.1
    assert abs(pstdev(reads) - keeper.profile.read_error_m()) < 0.1
    keeper.heading = 0.0  # facing his own net
    assert e.keeper_read(keeper, shooter, 36.0) is None


def test_reflexes_set_reaction_in_the_engine():
    e = Engine(1)
    p = e.by_id["a6"]
    p.profile.attributes["reflexes"] = 1.0
    quick = e.reaction(p)
    p.profile.attributes["reflexes"] = 0.0
    assert e.reaction(p) > quick


def test_first_touch_decides_whether_a_ball_is_killed():
    outcomes = {}
    for touch in (1.0, 0.0):  # can kill 24 m/s, or 12 m/s
        e = Engine(1)
        still(e)
        p = e.by_id["a6"]
        p.x, p.y = 50.0, 30.0
        p.profile.attributes["first_touch"] = touch
        e.possessor, e.last_touch, e.kicker_clear, e.kicked_at = None, "h2", True, e.t - 2.0
        before = (49.4, 30.0, 0.0, 18.0, 0.0, 0.0)
        e.ball = (49.4 + 18.0 * DT, 30.0, 0.0, 18.0, 0.0, 0.0)
        e.contact(before)
        outcomes[touch] = e.possessor == p.id
    assert outcomes == {1.0: True, 0.0: False}


def _high_ball(touch: float, speed: float, z: float, reacted: bool, y: float = 30.0) -> Engine:
    """A ball arriving on a standing outfielder. z is the bottom of the ball."""
    e = Engine(1)
    still(e)
    p = e.by_id["a6"]
    p.x, p.y = 50.0, 30.0
    p.profile.attributes["first_touch"] = touch
    e.possessor, e.last_touch, e.kicker_clear = None, "h2", True
    e.kicked_at = e.t - (2.0 if reacted else 0.0)
    e.ball = (49.7 + speed * DT, y, z, speed, 0.0, 0.0)
    e.contact((49.7, y, z, speed, 0.0, 0.0))
    return e


# Speeds between what a body part kills at the worst and the best first touch (profiles.absorb_mps).
FOOT_WORST, FOOT_BEST = FOOT_ABSORB_MPS[0], FOOT_ABSORB_MPS[0] + FOOT_ABSORB_MPS[1]
CHEST = (FOOT_WORST + FOOT_BEST) / 2 * CUSHION["chest"]  # a good chest kills it, a poor one does not
PAST_THIGH = (FOOT_BEST * CUSHION["thigh"] + FOOT_BEST) / 2  # past the best thigh, inside the best foot


def test_a_high_ball_can_be_taken_on_the_body_and_a_poor_touch_is_worse():
    # At chest height: a good first touch kills it, a poor one is a heavy touch: what the chest could
    # not kill runs on, toward where he sends it (firsttouch.py), and he is not on it yet (D6).
    killed = _high_ball(1.0, CHEST, 1.35, True)
    assert killed.possessor == "a6" and killed.ball[3] == 0.0 and killed.ball[5] == 0.0
    assert not any(ev["type"] == "deflection" for ev in killed.match.events)
    heavy = _high_ball(0.0, CHEST, 1.35, True)
    assert heavy.possessor is None and heavy.dribbler == "a6"  # still his to run onto, unlike a rebound
    left = CHEST - FOOT_WORST * CUSHION["chest"]  # what a poor chest could not kill
    assert left > KEEP_MPS and math.isclose(math.hypot(heavy.ball[3], heavy.ball[4]), left, rel_tol=0.3)
    # Far too fast for the surface, it beats him and rebounds.
    fast = 1.1 * FOOT_WORST * (1 + CUSHION["chest"])  # past what his chest kills plus what he can steer
    beat = _high_ball(0.0, fast, 1.35, True)
    assert beat.possessor is None and beat.dribbler is None
    assert math.isclose(beat.ball[3], -MISCONTROL_KEEP * fast, rel_tol=0.05)
    # The same arrival with no time to set himself still just rebounds off the body.
    cold = _high_ball(1.0, CHEST, 1.35, False)
    assert cold.possessor is None
    assert math.isclose(cold.ball[3], -BODY_RESTITUTION * CHEST, rel_tol=0.05)
    # A thigh is the same idea, and harder than a foot reached out to the side.
    thigh = _high_ball(1.0, PAST_THIGH, 0.7, True)
    assert thigh.possessor is None and thigh.dribbler == "a6"  # a heavy touch, where a foot keeps it
    foot = _high_ball(1.0, PAST_THIGH, 0.2, True, y=30.55)
    assert foot.possessor == "a6"
    # A clip of the outside rebounds even when he is ready and his touch is perfect.
    clip = _high_ball(1.0, CHEST, 1.35, True, y=30.32)
    assert clip.possessor is None and any(ev["type"] == "deflection" for ev in clip.match.events)
    # Already leaving him, or over his head, or past his shoulder: he does not take it.
    e = Engine(1)
    still(e)
    p = e.by_id["a6"]
    p.x, p.y = 50.0, 30.0
    p.profile.attributes["first_touch"] = 1.0
    e.possessor, e.last_touch, e.kicker_clear, e.kicked_at = None, "h2", True, e.t - 2.0
    e.ball = (50.1 + CHEST * DT, 30.0, 1.35, CHEST, 0.0, 0.0)
    e.contact((50.1, 30.0, 1.35, CHEST, 0.0, 0.0))
    assert e.possessor is None and e.ball[3] == CHEST
    over = _high_ball(1.0, CHEST, 2.1, True)
    assert over.possessor is None and over.ball[3] == CHEST
    wide = _high_ball(1.0, CHEST, 1.35, True, y=30.7)
    assert wide.possessor is None and wide.ball[3] == CHEST


def test_a_touch_names_the_part_and_a_carry_does_not():
    chest = _high_ball(1.0, CHEST, 1.35, True)
    assert chest.pose(chest.by_id["a6"])[0] == "chest"
    chest.t += 0.35
    assert chest.pose(chest.by_id["a6"])[0] != "chest"
    thigh = _high_ball(1.0, PAST_THIGH, 0.7, True)
    assert thigh.pose(thigh.by_id["a6"])[0] == "thigh"
    foot = _high_ball(1.0, PAST_THIGH, 0.2, True, y=30.55)
    assert foot.pose(foot.by_id["a6"])[0] == "foot"
    cold = _high_ball(1.0, CHEST, 1.35, False)
    assert cold.pose(cold.by_id["a6"])[0] not in ("chest", "thigh", "head", "foot", "hands")
    e = Engine(1)
    still(e)
    p = e.by_id["a6"]
    p.x, p.y = 50.0, 30.0
    e.dribbler = p.id
    e.possessor, e.last_touch, e.kicker_clear, e.kicked_at = None, "h2", True, e.t - 2.0
    e.ball = (50.2 + 2.0 * DT, 30.0, 0.0, 2.0, 0.0, 0.0)
    e.contact((50.2, 30.0, 0.0, 2.0, 0.0, 0.0))
    assert e.pose(p)[0] != "foot"


def test_a_dive_is_drawn_as_far_as_he_has_gone_and_until_he_is_up():
    e = Engine(1)
    k = _shot_at_keeper(e, (90.0, 34.0, 0.5, 25.0, 6.0, 0.0))  # heading for his left
    assert e.pose(k)[0] != "dive"  # he has not reacted yet
    e.t += e.reaction(k)
    gone = []
    while e.keeper_dive(k):
        gone.append(abs(e.pose(k)[1]) if e.dive else 1.0)
        e.t += DT
    assert gone == sorted(gone) and gone[0] < 0.5 and gone[-1] == 1.0  # drawn as far as the engine has him
    assert e.pose(k)[0] == "dive" and abs(e.pose(k)[1]) == 1.0  # down on the ground
    e.t = e.off_balance[k.id] + DT
    assert e.pose(k)[0] != "dive"  # up again


def test_a_keeper_in_his_box_still_holds_a_high_ball_with_his_hands():
    e = Engine(1)
    still(e)
    p = e.keeper("home")
    p.x, p.y = 5.0, 34.0
    p.profile.attributes["first_touch"] = 0.0  # a chest could not kill this
    p.profile.attributes["handling"] = 1.0
    e.possessor, e.last_touch, e.kicker_clear, e.kicked_at = None, "a6", True, e.t - 2.0
    hold = p.profile.absorb_mps(True)
    fast = (hold * CUSHION["chest"] + hold) / 2  # inside his hold, past what a chest of his would kill
    e.ball = (4.6 + fast * DT, 34.0, 1.4, fast, 0.0, 0.0)
    e.contact((4.6, 34.0, 1.4, fast, 0.0, 0.0))
    assert e.possessor == p.id
    assert e.pose(p)[0] == "hands"


def test_a_long_ball_to_the_wing_is_struck_as_a_cross_and_a_shot_with_finishing(monkeypatch):
    e, p = kicker()
    used = []
    original = e.execute
    monkeypatch.setattr(e, "execute", lambda *a, **kw: used.append(a[-1]) or original(*a, **kw))
    e.give(p.id)
    e.ball = (50.37, 34.0, 0.0, 0.0, 0.0, 0.0)
    e.pass_to(p, 85.0, 60.0, lofted=True)
    p.x, p.y, p.heading = 88.0, 34.0, 0.0
    e.give(p.id)
    e.ball = (88.37, 34.0, 0.0, 0.0, 0.0, 0.0)
    e.shoot(p)
    assert used == ["crossing", "finishing"]


def test_a_stronger_team_is_made_of_better_players():
    e = Engine(2, strengths={"home": 1.5, "away": -1.5})
    quality = lambda team: mean(p.profile.quality for p in e.players if p.team == team)  # noqa: E731
    assert quality("home") - quality("away") > 2.0  # 3.0 expected; about 0 if strength were ignored


def test_a_fast_ball_aimed_at_a_standing_body_always_hits_it():
    for speed in (6.0, 20.0, 30.0):
        for offset in (0.0, 0.1, 0.2, 0.3):
            e = Engine(1)
            still(e)
            p = e.by_id["a6"]
            p.x, p.y = 50.0, 30.0
            e.possessor, e.last_touch, e.kicker_clear, e.kicked_at = None, "h2", True, e.t  # no reaction yet
            before = (49.7, 30.0 + offset, 0.5, speed, 0.0, 0.0)  # it reaches him this step
            e.ball = (49.7 + speed * DT, 30.0 + offset, 0.5, speed, 0.0, 0.0)
            e.contact(before)
            assert any(ev["type"] == "deflection" for ev in e.match.events), (speed, offset)


def shot_in_flight(on_target: bool) -> tuple[Engine, dict]:
    e = Engine(1)
    shooter = e.by_id["h9"]
    e.kicked = e.emit("shot", "home", 90.0, 34.0, player=shooter.id)
    e.shot_touched_by = e.shot_was_on_target = None
    e.heading_on_target = lambda team: on_target
    return e, e.kicked


def goal_event(e: Engine) -> dict:
    return next(ev for ev in reversed(e.match.events) if ev["type"] == "goal")


def test_a_shot_deflected_in_counts_for_the_shooter_only_if_it_was_on_target():
    e, shot = shot_in_flight(True)
    e.touched(e.by_id["a4"], 95.0, 34.0, controls=False)
    e.last_touch = "a4"
    e.scored("home", e.kicked, 105.0, 34.0)
    assert shot["outcome"] == "goal" and goal_event(e)["player"] == "h9"
    e, shot = shot_in_flight(False)
    e.touched(e.by_id["a4"], 95.0, 34.0, controls=False)
    e.last_touch = "a4"
    e.scored("home", e.kicked, 105.0, 34.0)
    assert shot["outcome"] == "blocked" and goal_event(e)["player"] is None  # an own goal


def test_a_parry_is_a_save_and_a_block_is_a_block():
    e, shot = shot_in_flight(True)
    e.touched(e.keeper("away"), 103.0, 34.0, controls=False)
    assert e.kicked is shot  # still live: the parry may yet go in
    e.close_shot(shot, 103.0, 34.0)
    assert shot["outcome"] == "on_target"
    e, shot = shot_in_flight(True)
    e.touched(e.by_id["a4"], 95.0, 34.0, controls=False)
    e.touched(e.by_id["a5"], 96.0, 34.0, controls=True)
    assert shot["outcome"] == "blocked" and e.kicked is None


def test_a_blocked_pass_fails_and_a_pass_back_to_the_passer_is_not_completed():
    e = Engine(1)
    e.kicked = e.emit("pass", "home", 50.0, 34.0, player="h6")
    e.touched(e.by_id["a8"], 52.0, 34.0, controls=False)
    assert e.match.events[-1]["outcome"] == "fail" and e.kicked is None
    assert not any(ev["type"] == "interception" for ev in e.match.events)
    e.kicked = e.emit("pass", "home", 50.0, 34.0, player="h6")
    e.touched(e.by_id["h6"], 50.5, 34.0, controls=True)
    assert e.match.events[-1]["outcome"] == "fail" and e.match.events[-1]["receiver"] is None


def test_a_pass_is_struck_at_the_pace_chosen():
    speeds = {}
    for pace in (6.0, 14.0):
        e, p = kicker()
        e.give(p.id)
        e.ball = (50.37, 34.0, 0.0, 0.0, 0.0, 0.0)
        e.pass_to(p, 70.0, 34.0, lofted=False, pace=pace)
        speeds[pace] = math.hypot(e.ball[3], e.ball[4])
    assert speeds[14.0] > speeds[6.0] * 1.3


def test_a_ball_that_goes_in_off_an_attacker_is_his_shot_and_goal():
    e = Engine(1)
    e.kicked = e.emit("pass", "home", 80.0, 30.0, player="h2")
    e.frame += 10
    e.deflect(e.by_id["h10"], 100.0, 32.0, 0.3, 0.3)  # then it goes in off the striker
    e.last_touch = "h10"
    e.scored("home", e.kicked, 105.0, 34.0)
    touch = next(ev for ev in e.match.events
                 if ev["player"] == "h10" and ev["type"] in ("shot", "deflection"))
    assert touch["type"] == "shot" and touch["outcome"] == "goal"
    assert goal_event(e)["player"] == "h10"
    p = next(ev for ev in e.match.events if ev["type"] == "pass")
    assert p["receiver"] == "h10" and p["outcome"] == "success" and p["end_x"] == touch["x"]


def test_an_old_deflection_is_never_relabelled_as_a_later_goal():
    e = Engine(1)
    e.deflect(e.by_id["h10"], 60.0, 32.0, 0.3, 0.3)  # long ago
    e.give("h10")  # he then had the ball, so that touch is history
    e.last_touch = "h10"
    e.scored("home", None, 105.0, 34.0)
    old = next(ev for ev in e.match.events if ev["player"] == "h10" and ev["type"] in ("shot", "deflection"))
    assert old["type"] == "deflection"


def test_his_own_pass_turned_in_off_himself_is_not_received_by_him():
    e = Engine(1)
    e.kicked = e.emit("pass", "home", 80.0, 30.0, player="h10")
    e.frame += 10
    e.deflect(e.by_id["h10"], 100.0, 32.0, 0.3, 0.3)
    e.last_touch = "h10"
    e.scored("home", e.kicked, 105.0, 34.0)
    p = next(ev for ev in e.match.events if ev["type"] == "pass")
    assert p["receiver"] is None and p["outcome"] == "fail"


def test_team_mates_velocity_reaches_the_passers_picture():
    e = Engine(1)
    carrier, mate = e.by_id["h6"], e.by_id["h9"]
    e.beliefs[carrier.id].seen[mate.id] = perception.Sighting(70.0, 34.0, 6.0, 1.0, e.t)
    m = next(m for m in e.scene_for(carrier).mates if m[0] == mate.id)
    assert m[4:6] == (6.0, 1.0)


def test_the_passer_judges_opponents_where_they_will_be():
    from ninety.sim.engine import ANTICIPATE_S
    e = Engine(1)
    carrier, opp = e.by_id["h6"], e.by_id["a6"]
    e.beliefs[carrier.id].seen = {opp.id: perception.Sighting(60.0, 34.0, -5.0, 0.0, e.t)}
    assert e.scene_for(carrier).opponents == [(60.0 - 5.0 * ANTICIPATE_S, 34.0)]


def test_the_engine_uses_the_attacking_shape_with_the_ball():
    from ninety.sim import offball
    e = Engine(1)
    p = e.by_id["h2"]  # RB
    e.brains["home"].in_possession = True
    e.possessor = None  # a pass in flight: the shape still holds
    e.ball = (50.0, 34.0, 0.0, 0.0, 0.0, 0.0)
    from ninety.sim import roles
    role = roles.role_of(p.profile.archetype)
    seen = [w for w in (e.beliefs[p.id].where(q.id, e.t) for q in e.players if q.team != p.team) if w]
    want = offball.attacking_slot("RB", 0.0, 50.0, 34.0, e.onside_limit("home", seen, 50.0),
                                  role.forward_m, role.inside_m)
    assert e.shape_target(p)[:2] == want


def test_his_own_pass_that_goes_straight_in_is_his_shot_not_an_old_deflection():
    e = Engine(1)
    e.deflect(e.by_id["h10"], 60.0, 32.0, 0.3, 0.3)  # an earlier touch
    carrier = e.by_id["h10"]
    e.ball = (90.0, 30.0, 0.0, 0.0, 0.0, 0.0)
    e.kicked = e.emit("pass", "home", 90.0, 30.0, player="h10", intended="h9", interceptor=None,
                      deflected_by=None)
    e.kick(carrier, 20.0, 4.0, 0.0)
    e.last_touch = "h10"
    e.scored("home", e.kicked, 105.0, 34.0)
    kinds = {ev["type"] for ev in e.match.events if ev["player"] == "h10" and ev["type"] != "goal"}
    assert "deflection" in kinds  # the old touch stays what it was
    shot = next(ev for ev in e.match.events if ev["type"] == "shot")
    assert shot["outcome"] == "goal" and shot["x"] == 90.0
    assert not {"intended", "interceptor", "deflected_by"} & set(shot)  # pass-only fields


def test_an_opponent_cutting_a_pass_out_intercepts_but_collecting_it_where_it_was_going_recovers():
    for at_x, label in ((60.0, True), (79.0, False)):
        e = Engine(1)
        e.pass_target = (80.0, 34.0)
        e.kicked = e.emit("pass", "home", 50.0, 34.0, player="h6")
        e.touched(e.by_id["a6"], at_x, 34.0, controls=True)
        assert any(ev["type"] == "interception" for ev in e.match.events) is label


def test_only_a_carry_in_progress_is_a_choice_he_carries_on_with():
    e = Engine(1)
    e.give("h6")
    assert e.scene_for(e.by_id["h6"]).current is None  # just received: nothing to carry on with
    e.dribble_to = (70.0, 34.0)
    assert e.scene_for(e.by_id["h6"]).current == "dribble"


def test_off_the_ball_he_runs_only_as_fast_as_the_ball_could_get_there():
    e = Engine(1)
    p = e.by_id["h6"]
    e.give("h10")
    e.hold_until = e.t  # the carrier can play at once
    e.ball = (p.x + 40.0, p.y, 0.0, 0.0, 0.0, 0.0)
    far = e.in_time(p, p.x + 5.0, p.y)  # the ball is 35 m from where he is going: no hurry
    e.ball = (p.x + 10.0, p.y, 0.0, 0.0, 0.0, 0.0)
    near = e.in_time(p, p.x + 5.0, p.y)  # 5 m: the pass could be there in a third of a second
    assert far < 3.0 < 6.0 < near
    e.hold_until = e.t + 1.0  # the carrier is not ready yet: more time
    assert e.in_time(p, p.x + 5.0, p.y) < near


def test_a_receiver_takes_the_ball_in_his_stride_instead_of_stopping_dead():
    e = Engine(1)
    p = e.by_id["h8"]
    for q in e.players:
        if q.team == "away":
            q.x, q.y = 100.0, 60.0  # nobody near him
    p.x, p.y, p.vx, p.vy = 50.0, 34.0, 5.0, 0.0
    e.give(p.id)
    e.ball = (p.x + 0.37, p.y, 0.0, 5.0, 0.0, 0.0)
    e.hold_until = e.t + 0.5  # settling the ball
    frames, v = 10, 5.0
    for _ in range(frames):
        e.tick_carrier()
        e.t += 1 / 25
    assert p.vx > 2.0  # still going his way, at a dribbling pace
    # further than a man who stops dead, braking as hard as he can (P2), goes in the same time
    t = frames / 25
    stopping = min(v * v / (2 * BRAKE_MAX), v * t - BRAKE_MAX * t * t / 2)
    assert p.x - 50.0 > stopping


def test_every_off_ball_target_is_reached_just_in_time_through_the_real_path():
    from ninety.sim.engine import Restart
    states = []
    e = Engine(5)
    e.run(1)  # a minute of real play: real shapes, a real carrier or ball in flight
    states.append(e)
    e2 = Engine(6)
    e2.run(1)
    e2.possessor, e2.restart = None, Restart("goal_kick", "home", 5.5, 30.0, "h1", e2.t + 7.5)
    states.append(e2)
    checked = 0
    for s in states:
        for p in s.players:
            if p.role == "GK" or p.id in s.lunges or p.id == s.possessor or p.id == s.dribbler:
                continue
            if s.restart and p.id == s.restart.taker:
                continue
            if s.brains[p.team].pressers[:1] == [p.id]:  # the presser keeps his work rate (T3)
                continue
            if s.presses_high(p, s.brains[p.team], *s.play_point(p)):  # so does a pressing role (O9)
                continue
            tx, ty, speed = s.shape_target(p)
            # O10: a forward run is a sprint, while a team-mate has the ball
            running = s.possessor is not None and s.moves.get(p.id, ("hold",))[0] in offball.FORWARD_RUNS
            if s.chase.get(p.team, [None])[0] == p.id or (s.brains[p.team].in_possession and running):
                continue
            assert speed >= s.in_time(p, tx, ty) - 1e-9, (p.id, speed)
            checked += 1
    assert checked > 10


def test_nobody_sprints_for_a_restart_that_is_seconds_away():
    from ninety.sim.engine import Restart
    e = Engine(1)
    p = e.by_id["a9"]
    p.x, p.y = 60.0, 34.0
    e.possessor = None
    e.restart = Restart("goal_kick", "home", 5.5, 34.0, "h1", e.t + 7.5)
    assert e.in_time(p, 30.0, 34.0) < 4.0  # 30 m to go, about 10 s to do it
    e.restart = Restart("goal_kick", "home", 5.5, 34.0, "h1", e.t)
    assert e.in_time(p, 30.0, 34.0) > 4.0  # being taken now: hurry


def test_a_pass_in_flight_is_timed_from_where_it_is_going():
    e = Engine(1)
    p = e.by_id["a6"]
    p.x, p.y = 30.0, 34.0
    e.possessor = None
    e.ball = (31.0, 34.0, 0.0, 20.0, 0.0, 0.0)  # next to him, but on its way to x = 90
    e.kicked, e.pass_target = {"type": "pass"}, (90.0, 34.0)
    away = e.in_time(p, 33.0, 34.0)
    e.kicked = None  # a loose ball at his feet instead
    assert away < e.in_time(p, 33.0, 34.0)


def test_a_kickoff_is_set_up_and_seen_before_it_is_taken():
    e = Engine(2)
    e.kickoff("away")
    kicked_at = None
    for _ in range(int(6 / DT)):
        before = e.restart is not None
        e.step()
        if before and e.restart is None and kicked_at is None:
            kicked_at = e.t
        if e.restart:
            for p in e.players:
                own_half = p.x >= 52.5 - 0.5 if p.team == "away" else p.x <= 52.5 + 0.5
                assert own_half or p.id == e.restart.taker, p.id  # Law 8
                if p.team == "home":
                    assert math.hypot(p.x - 52.5, p.y - 34.0) >= 9.15 - 0.5  # outside the circle
    assert kicked_at is not None and kicked_at >= 1.0  # a visible pause, then the kick


def test_once_a_pass_is_struck_shape_is_set_for_where_it_is_going():
    e = Engine(1)
    e.possessor = None
    e.ball = (40.0, 34.0, 0.0, 14.0, 0.0, 0.0)
    e.kicked, e.pass_target = {"type": "pass", "x": 30.0, "y": 34.0}, (70.0, 20.0)
    e.kicked_at, e.seen_going = e.t, (68.0, 34.0)
    p = e.by_id["a6"]
    e.brains["away"].in_possession = False
    before = e.shape_target(p)[:2]
    e.ball = (55.0, 27.0, 0.0, 14.0, 0.0, 0.0)  # the ball half way there: nobody's target moves
    assert e.shape_target(p)[:2] == before
    e.kicked = None  # a loose ball: play is where the ball is
    assert e.play_point() == (55.0, 27.0)


def test_only_the_passer_and_his_receiver_know_where_a_pass_is_meant_defenders_react_to_what_they_see():
    e = Engine(1)
    e.possessor = None
    e.ball = (40.0, 34.0, 0.0, 14.0, 0.0, 0.0)
    e.kicked, e.pass_target = {"type": "pass", "x": 35.0, "y": 34.0}, (70.0, 20.0)
    e.kicked_at, e.seen_going = e.t, (68.0, 34.0)
    e.intended, e.released_by = "h9", "h6"
    assert e.play_point(e.by_id["h9"]) == (70.0, 20.0)  # he expects it
    d = e.by_id["a6"]
    assert e.play_point(d) == (35.0, 34.0)  # not yet reacted: play is where it was struck
    e.t += e.reaction(d)
    assert e.play_point(d) == (68.0, 34.0)  # then where he sees it going, not where it was meant


def test_a_marker_on_his_spot_moves_only_as_his_man_moves():
    e = Engine(1)
    d, man = e.by_id["a4"], e.by_id["h9"]
    brain = e.brains["away"]
    brain.in_possession = False
    man.x, man.y = 90.0, 34.0
    d.x, d.y = 91.0, 34.0
    brain.markers = {d.id: (91.0, 34.0)}
    e.beliefs[d.id].seen = {man.id: perception.Sighting(90.0, 34.0, 0.0, 0.0, e.t)}
    assert e.shape_target(d)[2] < 0.1  # on his spot, his man still: no need to run
    e.beliefs[d.id].seen = {man.id: perception.Sighting(90.0, 34.0, 0.0, 6.0, e.t)}
    assert abs(e.shape_target(d)[2] - 6.0) < 0.1  # his man runs: he goes with him


def test_play_is_where_the_ball_is_once_a_pass_is_deflected_or_has_run_past_its_target():
    e = Engine(1)
    e.possessor = None
    e.kicked, e.pass_target = {"type": "pass", "team": "home", "x": 40.0, "y": 34.0}, (70.0, 34.0)
    e.kicked_at, e.seen_going = e.t - 1.0, (70.0, 34.0)  # reacted to; seen going to the target
    e.ball = (55.0, 34.0, 0.0, 14.0, 0.0, 0.0)
    assert e.play_point() == (70.0, 34.0)
    e.ball = (74.0, 34.0, 0.0, 6.0, 0.0, 0.0)  # it ran past where it was aimed
    assert e.play_point() == (74.0, 34.0)
    e.ball = (55.0, 34.0, 0.0, 14.0, 0.0, 0.0)
    e.last_deflection = {"type": "deflection"}  # a team-mate got a touch on it on the way
    assert e.play_point() == (55.0, 34.0)


def test_a_kickoff_starts_a_new_phase_of_play():
    e = Engine(1)
    e.dribbler, e.moves, e.chase = "h7", {"h9": ("in_behind", 90.0, 30.0, 0.0)}, {"home": ["h7"]}
    e.kickoff("away")
    assert e.dribbler is None and not e.moves and not e.chase


def test_a_marker_chases_harder_when_his_man_runs_away_from_him_than_toward_him():
    e = Engine(1)
    d, man = e.by_id["a4"], e.by_id["h9"]
    e.brains["away"].in_possession = False
    d.x, d.y = 80.0, 34.0
    e.brains["away"].markers = {d.id: (86.0, 34.0)}  # 6 m to his spot, ahead of him
    speeds = []
    for vx in (5.0, -5.0):  # his man runs away from him, then toward him
        e.beliefs[d.id].seen = {man.id: perception.Sighting(87.0, 34.0, vx, 0.0, e.t)}
        speeds.append(e.shape_target(d)[2])
    assert speeds[0] > speeds[1]


def test_the_keeper_dives_toward_the_shot_after_reacting_then_is_down():
    from ninety.sim.offball import DIVE_PEAK_MPS, DIVE_TIME_S, KEEPER_DIVE_TRAVEL_M
    e = Engine(1)
    k = e.keeper("away")
    k.x, k.y, k.vx, k.vy = 104.0, 34.0, 0.0, 0.0
    e.possessor = None
    e.kicked = {"type": "shot", "team": "home"}
    e.ball = (90.0, 34.0, 0.5, 25.0, 6.0, 0.0)  # heading for about 3.4 m to his left
    e.kicked_at = e.free_since = e.t
    assert not e.keeper_dive(k)  # he has not reacted yet
    e.t += e.reaction(k)
    y0 = k.y
    assert e.keeper_dive(k)
    for _ in range(int(DIVE_TIME_S * 25) + 2):
        if not e.keeper_dive(k):
            break
        landed_at = k.y
        e.t += 1 / 25
    # launched toward it, no further than a dive goes (and what is left of the frame he lands in)
    assert 1.0 < landed_at - y0 <= KEEPER_DIVE_TRAVEL_M + DIVE_PEAK_MPS / 25 + 1e-9
    assert e.dive is None and e.off_balance[k.id] > e.t - 1 / 25  # and down on the ground after it


def _shot_at_keeper(e, ball):
    k = e.keeper("away")
    k.x, k.y, k.vx, k.vy = 104.0, 34.0, 0.0, 0.0
    e.possessor = None
    e.kicked = {"type": "shot", "team": "home", "x": ball[0], "y": ball[1]}
    e.ball = ball
    e.kicked_at = e.free_since = e.t
    return k


def test_the_dive_runs_in_the_match_loop_and_waits_for_the_keepers_reaction():
    e = Engine(1)
    k = _shot_at_keeper(e, (90.0, 34.0, 0.5, 25.0, 6.0, 0.0))
    y0 = k.y
    e.move_players()
    assert k.y == y0 or abs(k.y - y0) < 0.05  # nothing yet: he has not reacted
    e.t += e.reaction(k)
    for _ in range(8):
        e.move_players()
        e.t += 1 / 25
    assert k.y - y0 > 0.2  # launched by the match loop itself


def test_a_deflection_restarts_the_keepers_reaction_before_he_dives():
    e = Engine(1)
    k = _shot_at_keeper(e, (90.0, 34.0, 0.5, 25.0, 6.0, 0.0))
    e.t += e.reaction(k)
    e.kicked_at = e.t  # just deflected on its way
    assert not e.keeper_dive(k)


def test_no_dive_at_a_ball_going_over_the_bar():
    e = Engine(1)
    k = _shot_at_keeper(e, (90.0, 34.0, 2.0, 25.0, 6.0, 5.5))  # rising steeply
    e.t += e.reaction(k)
    assert e.ball_at_x(k.x)[2] > offball.reach_for(True, 9.0, 0.0, 9.0)[1]  # over his highest reach
    assert not e.keeper_dive(k)


def test_the_keeper_moves_sideways_at_his_depth_when_he_reads_a_shot():
    e = Engine(1)
    k = _shot_at_keeper(e, (90.0, 34.0, 0.5, 25.0, 0.0, 0.0))
    k.x = 99.0  # he had come out
    e.read = (k.id, 36.0)
    tx, _, _ = e.shape_target(k)
    assert tx == 99.0


def test_the_keeper_sets_himself_from_the_ball_not_where_a_pass_is_going():
    from ninety.sim import offball
    e = Engine(1)
    k = e.keeper("away")
    e.brains["away"].in_possession = False
    e.possessor = None
    e.kicked, e.pass_target = {"type": "pass", "team": "home", "x": 60.0, "y": 34.0}, (95.0, 10.0)
    e.ball = (70.0, 34.0, 0.0, 14.0, -12.0, 0.0)
    tx, ty, _ = e.shape_target(k)
    assert (tx, ty) == offball.keeper_spot(70.0, 34.0, 105.0)


def test_a_short_dive_is_the_same_push_over_sooner_and_travel_counts_the_arms_reach_by_then():
    from ninety.sim import offball
    e = Engine(1)
    k = _shot_at_keeper(e, (95.0, 34.0, 0.3, 25.0, 6.0, 0.0))  # crosses about 2 m wide
    e.t += e.reaction(k)
    y0 = k.y
    assert e.keeper_dive(k)
    travel = e.dive[3]
    when, cross, _ = e.ball_at_x(k.x)
    assert abs(travel - (abs(cross - y0) - offball.arm_reach_m(when))) < 1e-6  # his arms by then
    frames = 0
    while e.keeper_dive(k):
        frames += 1
        e.t += 1 / 25
    # done early, where the full dive's push takes him that far (and he carries on for the rest
    # of that frame at the speed the push gave him)
    reached = offball.dive_time_to(travel)
    assert frames == math.ceil(reached * 25 - 1e-9) < offball.DIVE_TIME_S * 25
    left = frames / 25 - reached
    assert abs(k.y - y0 - travel - offball.dive_motion(reached)[1] * left) < 1e-6


def test_the_keeper_dives_at_a_dipping_shot_that_comes_in_under_the_bar():
    e = Engine(1)
    k = _shot_at_keeper(e, (80.0, 34.0, 0.3, 19.0, 3.0, 4.5))  # rises, then drops under the bar
    when, _, z = e.ball_at_x(k.x)
    assert z < 2.44  # it does come in under the bar, though a straight line says over
    e.t += e.reaction(k)
    assert e.keeper_dive(k)


def test_ball_at_x_interpolates_the_crossing_between_frames():
    e = Engine(1)
    e.ball = (80.0, 34.0, 0.0, 10.0, 4.0, 0.0)  # along the ground, slowing a little with drag
    when, y, _ = e.ball_at_x(90.0)
    path = ball.predict(e.ball, 1 / 25, 3.0)
    k = next(i for i, s in enumerate(path) if s[0] >= 90.0)
    assert (k - 1) / 25 < when < k / 25  # between the frames, neither the frame before nor after
    assert abs((y - 34.0) / (90.0 - 80.0) - 0.4) < 0.01  # on the ball's own line


def test_a_late_dive_never_shrinks_the_keepers_reach():
    e = Engine(1)
    k = _shot_at_keeper(e, (80.0, 34.0, 0.3, 20.0, 1.0, 0.0))
    e.t += e.reaction(k) + 0.4
    before = e.reach(k, 104.0, 34.0, offball.KEEPER_COM_Z)[0]
    e.dive = (k.id, e.t, k.y, 0.5, e.kicked_at + e.reaction(k))  # he decides to dive only now
    assert e.reach(k, 104.0, 34.0, offball.KEEPER_COM_Z)[0] >= before



def test_before_he_reacts_the_keeper_has_only_his_standing_reach_then_it_grows():
    from ninety.sim import offball
    e = Engine(1)
    k = _shot_at_keeper(e, (90.0, 34.0, 0.5, 25.0, 0.0, 0.0))
    e.t += e.reaction(k) * 0.5
    assert e.reach(k, 104.0, 34.0, offball.KEEPER_COM_Z)[0] == offball.KEEPER_STAND_REACH_M
    e.t += e.reaction(k) * 0.5 + 0.2
    assert e.reach(k, 104.0, 34.0, offball.KEEPER_COM_Z)[0] > offball.KEEPER_STAND_REACH_M


def test_a_deflection_does_not_unstretch_a_dive_already_under_way():
    e = Engine(1)
    k = _shot_at_keeper(e, (90.0, 34.0, 0.5, 25.0, 6.0, 0.0))
    e.t += e.reaction(k)
    assert e.keeper_dive(k)
    e.t += 0.3
    stretched = e.reach(k, 104.0, 34.0, offball.KEEPER_COM_Z)[0]
    e.kicked_at = e.t  # deflected mid-dive
    assert e.reach(k, 104.0, 34.0, offball.KEEPER_COM_Z)[0] == stretched


def test_a_late_dive_counts_the_stretch_his_arms_already_have():
    from ninety.sim import offball
    e = Engine(1)
    k = _shot_at_keeper(e, (100.0, 34.0, 0.3, 20.0, 9.0, 0.0))  # close: his arms are still stretching
    e.t += e.reaction(k) + 0.1  # he waits, then dives
    when, cross, _ = e.ball_at_x(k.x)
    assert when < 0.4
    y0 = k.y
    assert e.keeper_dive(k)
    assert e.dive[4] == e.kicked_at + e.reaction(k)  # his arms began when he reacted, not when he dived
    want = min(abs(cross - y0) - offball.arm_reach_m(0.1 + when), offball.KEEPER_DIVE_TRAVEL_M)
    assert abs(abs(e.dive[3]) - want) < 1e-6


def test_the_keeper_follows_a_slow_shot_however_long_it_takes_to_arrive():
    e = Engine(1)
    e.ball = (65.0, 34.0, 0.0, 70 / 3.6, 0.0, 0.0)  # a slow ground shot from 40 m
    arrival = e.ball_at_x(104.0)
    assert arrival is not None and arrival[0] > 3.0


def test_a_keeper_down_after_a_dive_keeps_his_stretch_until_he_is_up():
    e = Engine(1)
    k = _shot_at_keeper(e, (90.0, 34.0, 0.5, 25.0, 6.0, 0.0))
    e.t += e.reaction(k)
    assert e.keeper_dive(k)
    for _ in range(int(offball.DIVE_TIME_S * 25) + 2):
        e.keeper_dive(k)
        e.t += 1 / 25
    assert e.dive is None and e.off_balance[k.id] > e.t  # landed, on the ground
    e.kicked_at = e.t  # a deflection while he is down
    assert e.reach(k, 104.0, 36.0, offball.KEEPER_COM_Z)[0] == pytest.approx(offball.KEEPER_ARM_M)


def _alone_with(e, mate_xy, others=(5.0, 5.0)):
    for q in e.players:
        q.vx = q.vy = 0.0
        q.x, q.y = others
    mate = e.by_id["h9"]
    mate.x, mate.y = mate_xy
    e.released_by = "h6"
    e.by_id["h6"].x, e.by_id["h6"].y = 40.0, 34.0
    return mate


def test_a_struck_ball_is_seen_going_where_somebody_can_first_get_to_it():
    e = Engine(1)
    _alone_with(e, (55.0, 34.0))
    e.ball = (40.0, 34.0, 0.0, 10.0, 0.0, 0.0)  # a slow ground pass straight at him, 15 m away
    x, y = e.ball_destination()
    assert 50.0 < x <= 56.0 and y == 34.0  # near him: not the kick spot, not where it would stop
    e.ball = (100.0, 60.0, 0.0, 10.0, 20.0, 0.0)  # heading out of play, nobody near
    assert e.ball_destination()[1] == 68.0


def test_a_lofted_ball_is_not_reachable_while_it_is_over_his_head():
    e = Engine(1)
    _alone_with(e, (50.0, 34.0))
    e.ball = (40.0, 34.0, 0.0, 12.0, 0.0, 9.0)  # lofted over him
    x, _ = e.ball_destination()
    assert x > 52.0  # where it comes down, beyond him


def test_a_pass_that_waits_for_the_passer_to_turn_still_knows_its_receiver():
    e = Engine(1)
    p = e.by_id["h6"]
    e.give(p.id)
    e.ball = (p.x - 0.4, p.y, 0.0, 0.0, 0.0, 0.0)  # the ball on the far side of his body
    e.pass_to(p, p.x + 15.0, p.y, lofted=False, receiver="h9")
    assert e.windup is not None and e.intended is None  # he turns first; nothing struck yet
    e.ball = (p.x + 0.4, p.y, 0.0, 0.0, 0.0, 0.0)  # taken round to his kicking side
    strike, e.windup = e.windup[2], None
    strike()
    assert e.intended == "h9"

def test_each_side_s_brain_reads_play_from_its_own_view_of_a_pass():
    e = Engine(1)
    e.possessor = None
    e.ball = (40.0, 34.0, 0.0, 14.0, 0.0, 0.0)
    e.kicked, e.pass_target = {"type": "pass", "team": "home", "x": 35.0, "y": 34.0}, (80.0, 34.0)
    e.kicked_at, e.seen_going = e.t, (45.0, 34.0)
    e.intended, e.released_by = "h9", "h6"
    seen = {}
    for team, brain in e.brains.items():
        brain.update = lambda now, has, ball_x, reach, team=team: seen.__setitem__(team, ball_x)
    for frame in range(12):  # each brain reads the game once in this many frames
        e.frame = frame
        e.perceive_and_think()
    assert seen == {"home": 80.0, "away": 35.0}  # his side knows the target; theirs saw the strike

def test_the_passing_side_knows_where_its_pass_was_meant_and_the_other_side_reacts():
    e = Engine(1)
    e.possessor = None
    e.ball = (40.0, 34.0, 0.0, 14.0, 0.0, 0.0)
    e.kicked, e.pass_target = {"type": "pass", "team": "home", "x": 35.0, "y": 34.0}, (70.0, 20.0)
    e.kicked_at, e.seen_going = e.t, (68.0, 34.0)
    e.intended, e.released_by = "h9", "h6"
    assert e.play_point(e.by_id["h6"]) == (70.0, 20.0)  # the passer
    assert e.play_point(team="home") == (70.0, 20.0)  # his side's brain
    assert e.play_point(team="away") == (35.0, 34.0)  # theirs, before it reacts
    e.t += 1.0
    assert e.play_point(team="away") == (68.0, 34.0)


def test_a_throw_in_is_meant_for_the_team_mate_it_is_thrown_to():
    e = Engine(1)
    p = e.by_id["h2"]
    e.give(p.id)
    e.ball = (p.x, p.y, 0.0, 0.0, 0.0, 0.0)
    p.heading = 0.0
    e.pass_to(p, p.x + 10.0, p.y, lofted=True, throw=True, receiver="h7")
    assert e.intended == "h7" and e.seen_going is not None


def test_a_new_strike_clears_a_keeper_landed_from_an_earlier_dive():
    e = Engine(1)
    p = e.by_id["h6"]
    e.give(p.id)
    e.landed = ("a1", e.t - 1.0)
    e.kick(p, 15.0, 0.0, 0.0)
    assert e.landed is None


def test_where_play_goes_waits_for_the_reaction_and_counts_running_but_not_the_kicker():
    e = Engine(1)
    _alone_with(e, (44.0, 36.0))  # 2 m off the line, close to the kicker
    e.ball = (40.0, 34.0, 0.0, 14.0, 0.0, 0.0)
    x_near, _ = e.ball_destination()
    assert x_near > 46.0  # he has to react first: the ball is past his spot before he can move
    e2 = Engine(1)
    _alone_with(e2, (60.0, 37.0))  # 3 m off the line further on: only running gets him there
    e2.ball = (40.0, 34.0, 0.0, 10.0, 0.0, 0.0)
    x_run, _ = e2.ball_destination()
    assert 55.0 < x_run < 62.0
    e3 = Engine(1)
    _alone_with(e3, (5.0, 5.0))  # nobody else anywhere near
    e3.ball = (40.0, 34.0, 0.0, 3.0, 0.0, 0.0)  # a slow ball rolling away from the kicker
    x_away, _ = e3.ball_destination()
    assert x_away > 41.0  # not the kicker's own feet


def test_a_pass_records_where_play_is_seen_going_through_the_real_path():
    e = Engine(1)
    mate = _alone_with(e, (56.0, 34.0))
    p = e.by_id["h6"]
    e.give(p.id)
    e.ball = (p.x + 0.4, p.y, 0.0, 0.0, 0.0, 0.0)
    e.pass_to(p, 56.0, 34.0, lofted=False, pace=6.0, receiver=mate.id)
    assert 48.0 < e.seen_going[0] <= 57.0  # where he meets it, stepping toward it: not the kick spot


def test_can_reach_counts_a_keepers_stretching_hands_in_his_box_not_his_feet():
    e = Engine(1)
    k = e.keeper("away")
    k.x, k.y, k.vx, k.vy = 103.0, 34.0, 0.0, 0.0
    e.kicked_at = e.t - 0.1
    t = e.reaction(k) + 0.6  # by then his arms are fully stretched
    assert e.can_reach(k, 103.0, 35.4, 0.5, t, delay=t)[0]  # 1.4 m: his hands, without a step
    outfield = e.by_id["a4"]
    outfield.x, outfield.y, outfield.vx, outfield.vy = 60.0, 34.0, 0.0, 0.0
    assert not e.can_reach(outfield, 60.0, 35.7, 0.5, t, delay=t)[0]  # a foot reaches 1 m


def test_can_reach_counts_his_speed_toward_the_ball_and_braking_away_from_it():
    e = Engine(1)
    p = e.by_id["a4"]
    p.x, p.y = 60.0, 34.0
    p.vx, p.vy = 6.0, 0.0  # already running toward the point
    toward = e.can_reach(p, 64.0, 34.0, 0.0, 0.5)[0]
    p.vx = -6.0  # running away from it: he must brake first
    away = e.can_reach(p, 64.0, 34.0, 0.0, 0.5)[0]
    p.vx = 0.0
    standing = e.can_reach(p, 64.0, 34.0, 0.0, 0.5)[0]
    assert toward and not standing and not away
    near = 61.5, 34.0  # 1.5 m away: a standing man gets there in half a second
    assert e.can_reach(p, *near, 0.0, 0.5)[0]
    p.vx = -6.0  # one running away at 6 m/s must first stop, which takes longer than that
    assert not e.can_reach(p, *near, 0.0, 0.5)[0]


def test_nobody_counts_as_reaching_a_struck_ball_before_reacting():
    e = Engine(1)
    _alone_with(e, (40.5, 34.0))  # right at the kicker's feet, as the ball leaves him
    e.ball = (40.0, 34.0, 0.0, 20.0, 0.0, 0.0)  # struck hard away from both
    assert e.ball_destination()[0] > 45.0


def test_nobody_counts_as_reaching_it_anywhere_inside_the_reaction_window():
    e = Engine(1)
    _alone_with(e, (42.4, 34.0))  # the ball passes him 0.12 s after the strike: before he can react
    e.ball = (40.0, 34.0, 0.0, 20.0, 0.0, 0.0)
    assert e.ball_destination()[0] > 46.0


def test_a_kick_clears_a_downed_keeper_before_judging_where_play_goes():
    e = Engine(1)
    p = e.by_id["h6"]
    e.give(p.id)
    e.landed = ("a1", e.t - 5.0)
    seen = []
    judge = e.ball_destination
    e.ball_destination = lambda: (seen.append(e.landed), judge())[1]
    e.kick(p, 15.0, 0.0, 0.0)
    assert seen == [None]


def test_the_keepers_envelope_comes_from_his_body_and_his_jump():
    # GROUNDING P11: hands within KEEPER_ARM_M of the centre of mass (standing reach less its
    # height), the centre of mass at most a jump above where it stands, so his highest reach is his
    # standing reach plus that jump.
    from ninety.sim import body
    stand = body.KEEPER_STATURE_M * body.STANDING_REACH_SHARE
    assert offball.KEEPER_COM_Z + offball.KEEPER_ARM_M == pytest.approx(stand)
    assert offball.reach_for(True, 9.0, 0.0, 9.0)[1] == pytest.approx(stand + body.KEEPER_JUMP_M)
    assert offball.reach_for(True, 9.0, 0.0, 0.0)[1] == pytest.approx(stand)  # no jump yet: no higher
    assert offball.jump_rise_m(0.1) < offball.jump_rise_m(0.2) < body.KEEPER_JUMP_M  # rising under gravity
    apex = (2 * body.GRAVITY * body.KEEPER_JUMP_M) ** 0.5 / body.GRAVITY
    assert offball.jump_rise_m(apex) == pytest.approx(body.KEEPER_JUMP_M) == offball.jump_rise_m(2 * apex)


def test_high_balls_are_reached_less_far_across_and_low_ones_once_he_falls():
    # GROUNDING P11: the higher the ball above where his centre of mass can be, the less far across he
    # reaches it; a low ball needs him to have fallen toward it (gravity, from when his save began).
    full = 9.0
    mid = offball.reach_for(True, full, offball.KEEPER_COM_Z, full)[0]
    high = offball.reach_for(True, full, 2.4, full)[0]
    assert mid == pytest.approx(offball.KEEPER_ARM_M) and high < mid
    standing = offball.KEEPER_COM_Z  # his centre of mass, before he has fallen at all
    on_the_ground = (offball.KEEPER_ARM_M ** 2 - standing ** 2) ** 0.5
    stretched = offball.DIVE_TIME_S  # his arms fully stretched by the dive's end
    fallen = offball.reach_for(True, stretched, 0.0, 0.0)[0]  # fallen to the ground by then
    assert fallen == pytest.approx(offball.KEEPER_ARM_M)
    assert fallen > on_the_ground


def test_the_upward_part_of_a_save_starts_no_sooner_than_245_ms_after_the_kick():
    # GROUNDING P15 (Higueras-Herbada et al. 2020): a keeper who dived at the strike reaches a ball
    # under the bar later than one at his waist, because he cannot start rising until then.
    e = Engine(1)
    k = e.keeper("away")
    k.x, k.y, k.vx, k.vy = 104.0, 34.0, 0.0, 0.0
    e.kicked = {"type": "shot", "team": "home"}
    e.kicked_at = e.t
    e.dive = (k.id, e.t, k.y, 1.0, e.t)  # his save began at the strike
    top = lambda at: e.reach(k, 104.0, 34.0, 0.0, at=e.kicked_at + at)[1]  # noqa: E731
    assert top(offball.UP_AFTER_CONTACT_S) == pytest.approx(offball.KEEPER_COM_Z + offball.KEEPER_ARM_M)
    assert top(offball.UP_AFTER_CONTACT_S + 0.1) > top(offball.UP_AFTER_CONTACT_S)


def test_the_engine_the_dive_and_the_shooter_share_one_envelope():
    # One definition (offball.reach_for): engine.reach, the shooter's judgement (keeper_reach_m) and
    # the passer's race (decisions._reach) give the same reach for the same moment and height.
    from ninety.sim import decisions
    e = Engine(1)
    k = e.keeper("away")
    k.x, k.y, k.vx, k.vy = 104.0, 34.0, 0.0, 0.0
    react = 0.36
    e.kicked = {"type": "shot", "team": "home"}
    e.kicked_at = e.t
    e.reaction = lambda p: react
    for at, z in ((0.5, 0.2), (0.6, 1.0), (0.7, 2.3), (1.2, 2.6)):
        engine = e.reach(k, 104.0, 34.0, z, at=e.t + at)
        passer = decisions._reach(104.0, 34.0, z, at, react, 105.0)
        assert engine == pytest.approx(passer)
        shooter = offball.keeper_reach_m(at, react, z)
        across = engine[0] if z <= engine[1] else 0.0
        launched = offball.KEEPER_DIVE_TRAVEL_M * offball.dive_progress(at - react)
        assert shooter == pytest.approx(across + launched)


def test_the_keeper_touches_a_ball_at_his_waist_that_he_cannot_yet_touch_under_the_bar():
    # GROUNDING P11, P15: engine.contact judges the hands by the ball's height. 0.9 m across, half a
    # second after the kick: at his waist it is in his hands; at 2.6 m his jump has not lifted him
    # high enough yet.
    def passes(z):
        e = Engine(1)
        k = e.keeper("away")
        for q in e.players:
            if q is not k:
                q.x, q.y = (2.0, 2.0) if q.team == "home" else (60.0, 60.0)
        k.x, k.y, k.vx, k.vy = 104.0, 34.0, 0.0, 0.0
        e.reaction = lambda p: 0.36
        e.possessor = None
        e.kicked = {"type": "shot", "team": "home", "player": "h9"}
        e.kicked_at, e.last_touch, e.kicker_clear = e.t - 0.5, "h9", True
        before = (104.6, 34.9, z, -25.0, 0.0, 0.0)
        e.ball = (103.6, 34.9, z, -25.0, 0.0, 0.0)
        e.contact(before)
        return e.ball[3] != -25.0 or e.possessor == k.id
    assert passes(1.0)
    assert not passes(2.6)


def _dive_speeds(travel: float, vx: float = 0.0, vy: float = 0.0
                 ) -> tuple[list[float], list[float], int]:
    """The keeper's sideways and forward speeds, frame by frame, over a dive of `travel` metres
    and a second after it (he was running at (vx, vy) when it began); and the frame he lands in."""
    from ninety.sim.engine import DT
    e = Engine(1)
    k = e.by_id["a1"]
    k.x, k.y, k.heading, k.vx, k.vy = 100.0, 34.0, math.pi, vx, vy
    e.dive = (k.id, e.t, k.y, travel, e.t, math.copysign(1.0, travel) * vy)
    side, ahead, landed = [], [], None
    for i in range(40):
        x0, y0 = k.x, k.y
        if not e.keeper_dive(k):
            e.move_players()
        elif e.dive is None:
            landed = i
        side.append((k.y - y0) / DT)
        ahead.append((k.x - x0) / DT)
        e.t += DT
    return side, ahead, landed


def test_every_dive_is_the_full_dives_push_so_a_short_one_is_no_harder_and_lands_slower():
    # GROUNDING P15: one push for every dive; a shorter dive stops it sooner.
    from ninety.sim import offball
    from ninety.sim.engine import DT
    ramp = offball.DIVE_PUSH_OFF_S
    push = offball.DIVE_PEAK_MPS / ramp * DT  # the full dive's gain in speed per frame
    landings = []
    for travel in (0.2, 0.5, 0.9, offball.KEEPER_DIVE_TRAVEL_M):
        side, _, landed = _dive_speeds(travel)
        assert landed is not None
        gains = [b - a for a, b in zip(side, side[1:landed + 1], strict=False)]
        assert max(gains) <= push + 1e-9 and max(side) <= offball.DIVE_PEAK_MPS + 1e-9
        landings.append(side[landed])
    assert landings == sorted(landings) and landings[0] < landings[-1]


def test_a_keeper_who_lands_slows_on_the_ground_and_does_not_stop_dead():
    # GROUNDING P2: on the ground he slows no faster than a body brakes, from the speed he landed at.
    from ninety.sim import offball
    from ninety.sim.engine import BRAKE_MAX, DT
    for travel in (0.2, 0.5, offball.KEEPER_DIVE_TRAVEL_M):
        side, _, landed = _dive_speeds(travel)
        after = side[landed:]
        assert after[0] > 1.0  # still moving when he lands
        drops = [a - b for a, b in zip(after, after[1:], strict=False)]
        assert max(drops) <= BRAKE_MAX * DT + 1e-9
        assert min(abs(v) for v in after) < 0.05  # and comes to rest (then gets up and goes back)


def test_a_keeper_who_dives_while_running_brakes_his_run_and_does_not_stop_dead():
    # GROUNDING P2: the dive moves him sideways; the run he was making brakes with the grip left.
    from ninety.sim.engine import BRAKE_MAX, DT
    _, ahead, landed = _dive_speeds(1.0, vx=-4.0)
    run = [-4.0] + ahead[:landed + 1]
    side, _, _ = _dive_speeds(1.0, vx=-4.0)
    side = [0.0] + side[:landed + 1]
    assert run[1] < -3.0  # he does not stop dead
    for i in range(1, len(run)):
        if run[i - 1] < -BRAKE_MAX * DT:  # still running: braking as hard as the grip his push leaves
            pushing = abs(side[i] - side[i - 1]) / DT
            grip = max(BRAKE_MAX ** 2 - pushing ** 2, 0.0) ** 0.5
            assert run[i] - run[i - 1] == pytest.approx(grip * DT, abs=1e-9)
            change = ((run[i] - run[i - 1]) ** 2 + (side[i] - side[i - 1]) ** 2) ** 0.5
            assert change <= max(BRAKE_MAX * DT, pushing * DT) + 1e-9  # never more than one grip
    assert any(b - a > 0.5 * BRAKE_MAX * DT for a, b in zip(run, run[1:], strict=False))  # it does brake


def test_a_keeper_already_running_sideways_dives_on_from_that_run_and_does_not_lose_it():
    # GROUNDING P15 and P2: toward the dive, the push starts from his run; away from it, he first
    # brakes as legs allow, then pushes; his sideways speed never jumps.
    from ninety.sim.engine import BRAKE_MAX, DT
    ramp = offball.DIVE_PUSH_OFF_S
    push = offball.DIVE_PEAK_MPS / ramp * DT
    for vy in (2.0, -2.0, 4.5):  # 4.5: faster than the dive's own peak, which it keeps
        side, _, landed = _dive_speeds(1.0, vy=vy)
        speeds = [vy] + side[:landed + 1]
        gains = [b - a for a, b in zip(speeds, speeds[1:], strict=False)]
        assert min(gains) >= -1e-9  # toward the dive throughout: never thrown back
        braking = [b - a for a, b in zip(speeds, speeds[1:], strict=False) if b < 0]  # still running away
        assert bool(braking) == (vy < 0)
        assert all(g <= BRAKE_MAX * DT + 1e-9 for g in braking)
        assert max(gains) <= max(push, BRAKE_MAX * DT) + 1e-9
    toward, _, landed_toward = _dive_speeds(1.0, vy=2.0)
    still, _, landed_still = _dive_speeds(1.0)
    assert toward[0] > still[0] and landed_toward <= landed_still  # a run toward it helps him


def test_a_keeper_dives_once_at_a_touch_and_again_only_after_a_new_one():
    # GROUNDING P15: one dive per touch of the ball. Down after diving at a slow shot, he gets up
    # and does not dive at the same ball again; a deflection is a new touch he may dive at.
    e = Engine(1)
    k = _shot_at_keeper(e, (80.0, 34.0, 0.3, 20.0, 4.5, 0.0))  # slow, wide of him: time to dive, land, rise
    e.t += e.reaction(k)
    assert e.keeper_dive(k)
    while e.dive is not None:
        e.keeper_dive(k)
        e.t += 1 / 25
    e.t = e.off_balance[k.id] + 0.01  # up again, the same ball still coming
    k.y = 34.0
    assert not e.keeper_dive(k)
    e.kicked_at = e.t - 1.0  # it came off someone: a new touch, which he has reacted to
    assert e.keeper_dive(k)


def test_a_deflection_does_not_pull_a_diving_keeper_out_of_his_jump():
    # GROUNDING P15: his rise counts from the touch he dived at, not from a deflection mid-dive.
    e = Engine(1)
    k = _shot_at_keeper(e, (90.0, 34.0, 0.5, 25.0, 6.0, 0.0))
    e.t += e.reaction(k)
    assert e.keeper_dive(k)
    e.t += 0.3
    before = e.reach(k, 104.0, 34.0, 2.8)
    e.kicked_at = e.t  # deflected mid-dive
    assert e.reach(k, 104.0, 34.0, 2.8) == before


def test_a_ball_crossing_high_needs_a_longer_dive_than_one_at_his_waist():
    # GROUNDING P11, P15: he dives only as far as his hands will not reach the ball at the height it
    # crosses his line; higher up they reach less far across, so his body must go further.
    def travel(vz):
        e = Engine(1)
        k = _shot_at_keeper(e, (92.0, 34.0, 0.3, 25.0, 4.0, vz))
        e.t += e.reaction(k)
        assert e.keeper_dive(k)
        return abs(e.dive[3]), e.ball_at_x(k.x)[2]
    (low, z_low), (high, z_high) = travel(5.0), travel(7.0)
    assert z_low < 1.5 < 2.0 < z_high
    assert high > low


def test_can_reach_judges_a_keepers_hands_by_the_balls_height():
    e = Engine(1)
    k = e.keeper("away")
    k.x, k.y, k.vx, k.vy = 103.0, 34.0, 0.0, 0.0
    e.kicked_at = e.t - 0.1
    t = e.reaction(k) + 0.6
    assert e.can_reach(k, 103.0, 35.4, 1.0, t, delay=t)[0]  # at his waist
    assert not e.can_reach(k, 103.0, 35.4, 2.9, t, delay=t)[0]  # near the top of his jump: not so far across


def test_the_dives_push_stays_within_what_legs_give():
    # GROUNDING P2, P15: pushed off over the cited push-off time, the body speeds up no faster than
    # a player can (the validator's own P2 limit), whatever the dive's length.
    from ninety.sim.engine import DT
    from ninety.validate import MAX_PLAYER_ACCEL
    for travel in (0.5, 1.0, offball.KEEPER_DIVE_TRAVEL_M):
        side, _, landed = _dive_speeds(travel)
        speeds = [0.0] + side[:landed + 1]
        assert max(b - a for a, b in zip(speeds, speeds[1:], strict=False)) <= MAX_PLAYER_ACCEL * DT + 1e-9


def test_a_thrower_turns_to_face_the_field_no_faster_than_a_body_turns_then_throws(monkeypatch):
    e = Engine(1)
    still(e)
    e.possessor = None
    e.stop("throw_in", "home", (40.0, 0.0))
    taker = e.by_id[e.restart.taker]
    taker.x, taker.y = throw_stand(40.0, 0.0)
    taker.heading = -math.pi / 2  # facing away from the field
    e.restart.ready_at = e.t
    e.tick_restart()
    assert taker.heading == -math.pi / 2  # placed at the line, not spun round (P16)
    e.hold_until, e.throw_ready = e.t, e.t - 10.0  # set, and done looking: only facing holds it back
    hands = []
    original = e.execute
    monkeypatch.setattr(e, "execute", lambda *a, **kw: hands.append(kw.get("hands")) or original(*a, **kw))
    last, thrown = taker.heading, None
    for _ in range(int(10 / DT)):
        e.tick_carrier()
        assert abs((taker.heading - last + math.pi) % (2 * math.pi) - math.pi) <= TURN_RATE * DT + 1e-9
        last = taker.heading
        if e.possessor is None:
            thrown = taker.heading
            break
        e.t += DT
        e.frame += 1
    assert thrown is not None  # Law 15: thrown facing the field, within the P16 strike angle of it
    assert math.cos(thrown - math.pi / 2) >= math.cos(STRIKE_FACING) - 1e-9
    assert hands == [True]  # with both hands


def test_a_throw_that_never_enters_the_field_is_taken_again_by_the_same_side():
    e = Engine(1)
    still(e)
    taker = e.by_id["h4"]
    e.possessor, e.last_touch, e.into_play, e.throw_from = None, taker.id, True, (40.0, 0.0)
    e.kicked = {"type": "pass", "team": "home"}
    e.ball = (40.0, -0.43, 1.88, 0.0, -4.0, 0.6)  # going back over his head, away from the field
    assert e.went_out((40.0, -0.27, 1.85, 0.0, -4.0, 1.0))
    r = e.restart
    assert (r.kind, r.team, r.taker, r.x, r.y) == ("throw_in", "home", taker.id, 40.0, 0.0)  # Law 15
    assert e.kicked is None
    # One that came onto the field and went back out is the other side's throw (Law 15).
    e = Engine(1)
    still(e)
    e.possessor, e.last_touch, e.into_play, e.throw_from = None, taker.id, True, (40.0, 0.0)
    e.ball = (40.0, 0.4, 1.5, 0.0, 4.0, 0.0)
    assert not e.went_out((40.0, -0.27, 1.85, 0.0, 4.0, 0.0)) and not e.into_play
    e.ball = (41.0, -0.3, 0.2, 0.0, -4.0, 0.0)
    assert e.went_out((41.0, 0.0, 0.3, 0.0, -4.0, 0.0))
    assert (e.restart.kind, e.restart.team) == ("throw_in", "away")


def test_a_throw_has_no_kicking_side_so_where_he_faces_does_not_change_it():
    e = Engine(1)
    p = e.by_id["h4"]
    thrown, kicked = [], []
    for heading in (math.pi / 2, -math.pi / 2):  # facing the way it goes, and facing away
        p.heading = heading
        e.rng = random.Random(5)
        thrown.append(e.execute(p, 0.0, 10.0, 4.0, "passing", hands=True))
        p.heading = heading
        e.rng = random.Random(5)
        kicked.append(e.execute(p, 0.0, 10.0, 4.0, "passing"))
    assert thrown[0] == thrown[1]
    assert kicked[0] != kicked[1]  # a kick does depend on it (P13)


def test_a_throw_taken_from_a_restart_and_never_entering_is_retaken_where_it_was_awarded():
    e = Engine(1)
    still(e)
    e.possessor = None
    e.stop("throw_in", "home", (40.0, 0.0))
    taker = e.by_id[e.restart.taker]
    taker.x, taker.y = throw_stand(40.0, 0.0)
    e.restart.ready_at = e.t
    e.tick_restart()  # placed: the throw is awarded at x = 40
    # Released backwards and drifting along the line, away from where it was awarded.
    e.possessor, e.last_touch, e.into_play = None, taker.id, True
    e.ball = (41.3, -0.45, 1.9, 1.0, -4.0, 0.5)
    assert e.went_out((41.26, -0.29, 1.88, 1.0, -4.0, 0.6))
    r = e.restart
    assert (r.kind, r.team, r.taker, r.x, r.y) == ("throw_in", "home", taker.id, 40.0, 0.0)
    assert not e.into_play


def test_a_throw_in_taker_runs_to_his_spot_and_stops_there():
    """Lesson 5: the taker was once moved the last metre to his spot in one frame (22 m/s) and
    stopped dead with the ball. The match must contain a throw-in, so the case is exercised; a
    short clip with no restart would pass whatever the engine did. Twelve minutes: seed 7's first
    throw-in came inside six until the cushioned touch changed the match's course, then at 8.2."""
    m = simulate(7, 12)
    assert any(p["action"] == "throw" for fr in m.frames for p in fr["players"])
    problems = defaultdict(list)
    check_physics(m.events, m.frames, FPS, m.roster, problems)
    assert not problems.get("P1 player speed") and not problems.get("P2 player acceleration"), dict(problems)


def throw_in_scene() -> tuple[Engine, object, object]:
    """Home's h9 holds the ball for a throw-in on the near touchline; away's a5 is within lunge
    reach with a team-mate covering goal-side, so in open play he could commit (D8)."""
    e = Engine(1)
    still(e)
    thrower, defender, cover = e.by_id["h9"], e.by_id["a5"], e.by_id["a3"]
    thrower.x, thrower.y = 56.1, -0.45
    defender.x, defender.y = 56.6, 0.4
    cover.x, cover.y = 60.0, 4.0
    e.restart, e.possessor, e.dribbler, e.throw_by = None, thrower.id, None, thrower.id
    e.ball = (*throw_hands(thrower.x, thrower.y), 0.0, 0.0, 0.0)
    e.hold_until = e.t + 99.0
    return e, thrower, defender


def test_nobody_challenges_a_ball_held_for_a_throw_in():
    """Law 15: the ball is not in play until it is thrown."""
    e, _, defender = throw_in_scene()
    defender.profile.attributes["aggression"] = 1.0
    for frame in range(60):
        e.frame = frame
        e.duels()
    assert defender.id not in e.lunges


def test_a_lunge_that_arrives_during_a_throw_in_finds_nothing():
    e, thrower, defender = throw_in_scene()
    held = e.ball
    # Defence in depth: a lunge lasts under 0.5 s and a restart takes at least 1 s, so play should
    # never produce this; if it did, the held ball must still be safe.
    e.lunges[defender.id] = e.t
    e.duels()
    assert e.possessor == thrower.id and e.ball == held
    assert not any(ev["type"] == "tackle" for ev in e.match.events)


def test_a_dribbler_whose_touch_went_out_still_takes_the_throw_in():
    """His touch ran over the line, so the ball is dead and his dribble is over; he runs to his
    spot behind the line like any thrower. (He once kept chasing his touch, which a target held
    on the pitch never let him leave, so the restart never came.)"""
    e = Engine(1)
    still(e)
    taker = e.by_id["h9"]
    taker.x, taker.y = 50.0, 2.0
    e.possessor, e.dribbler = None, taker.id
    e.ball = (50.0, -1.0, 0.0, 0.0, 0.0, 0.0)
    e.stop("throw_in", "home", (50.0, 0.0), taker=taker.id)
    for _ in range(int((RESTART_DELAY_S["throw_in"][1] + 10) / DT)):  # the sourced delay, then his run
        e.step()
        if e.restart is None:
            break
    assert e.restart is None and e.throw_by == taker.id


def test_taking_the_ball_for_a_throw_in_never_brakes_or_speeds_him_up_beyond_his_body():
    """He arrives still moving a little (just under one frame of braking). Over the frame he takes
    the ball and the frames he holds it, his speed only falls, by no more than his braking grip."""
    e = Engine(1)
    still(e)
    e.possessor = None
    e.stop("throw_in", "home", (50.0, 0.0))
    taker = e.by_id[e.restart.taker]
    taker.x, taker.y = throw_stand(50.0, 0.0)
    taker.vx, taker.vy = 0.25, 0.0
    e.restart.ready_at = e.t
    speeds = [0.25]
    for _ in range(5):
        e.step()
        speeds.append(math.hypot(taker.vx, taker.vy))
    assert e.throw_by == taker.id
    for before, after in zip(speeds, speeds[1:], strict=False):
        assert after <= before + 1e-9 and before - after <= BRAKE_MAX * DT + 1e-9, speeds


def thrower_ready_at(x: float, y: float, vx: float = 0.0, vy: float = 0.0) -> tuple[Engine, object]:
    """Home's h9 is the taker of a throw-in where the ball crossed the near touchline at x = 50,
    standing at (x, y) and moving at (vx, vy); the restart is ready now."""
    e = Engine(1)
    still(e)
    taker = e.by_id["h9"]
    taker.x, taker.y, taker.vx, taker.vy = x, y, vx, vy
    e.possessor = None
    e.ball = (50.0, -1.0, 0.0, 0.0, 0.0, 0.0)
    e.stop("throw_in", "home", (50.0, 0.0), taker=taker.id)
    e.restart.ready_at = e.t
    return e, taker


def test_a_throw_in_is_thrown_from_behind_the_touchline_with_the_ball_over_or_behind_it():
    """Law 15 (D5): at the moment of the throw the thrower stands on or behind the touchline and
    the ball, in his hands, is over or behind it. He starts standing 0.9 m inside the pitch, so
    a spot tolerance wide enough to reach him there would let him throw from the field."""
    e, taker = thrower_ready_at(50.0, 0.35)
    thrown = False
    for _ in range(int(10 / DT)):
        x, y = taker.x, taker.y  # the throw uses where he stands as the frame starts
        e.step()
        thrown = any(ev["type"] == "pass" and ev["player"] == taker.id for ev in e.match.events)
        if thrown:
            break
    assert thrown  # positive control: he did throw
    assert y < 0.0, y  # his body is behind the line, not on the pitch
    # The ball leaves from his hands, a reach in front of him (events clamp to the pitch, so read
    # the ball itself: it was struck this frame and has not moved yet).
    assert e.ball[:3] == throw_hands(x, y)
    assert e.ball[1] <= 0.0, e.ball  # over or behind the line


def test_taking_the_ball_for_a_throw_in_never_places_the_taker():
    """Lesson 5: he is never moved to his spot. He is inside the spot tolerance and slow enough
    to take the ball, but not on the spot; over the frame he takes it, tick_restart leaves his
    position and velocity exactly where his own movement model puts them."""
    sx, sy = throw_stand(50.0, 0.0)
    e, taker = thrower_ready_at(sx + 0.15, sy + 0.1, vx=0.2, vy=-0.05)
    expect = move_body(taker.x, taker.y, taker.vx, taker.vy, taker.x, taker.y, 0.0, taker.physique, DT)
    e.tick_restart()
    assert e.restart is None and e.throw_by == taker.id  # positive control: he took the ball
    assert (taker.x, taker.y, taker.vx, taker.vy) == expect


def test_a_thrower_arriving_faster_than_one_frame_of_braking_does_not_take_the_ball():
    """D5, P2: he takes the ball only when one frame of his braking limit stops him. Just above
    that, on his spot, he waits; just below, he takes it."""
    sx, sy = throw_stand(50.0, 0.0)
    limit = BRAKE_MAX * DT
    e, taker = thrower_ready_at(sx, sy, vx=limit * 1.05)
    e.tick_restart()
    assert e.restart is not None and e.throw_by is None
    e, taker = thrower_ready_at(sx, sy, vx=limit * 0.95)
    e.tick_restart()
    assert e.restart is None and e.throw_by == taker.id


def test_a_presser_off_the_lane_cuts_into_it_then_closes_down_along_it():
    p = Engine(1).by_id["a4"]
    # The carrier is going to (30, 34); the lane runs toward the goal at x = 0; his spot is 2 m goal-side.
    p.x, p.y = 22.0, 39.0  # 8 m goal-side, 5 m off the lane
    assert Engine.press_path(p, 30.0, 34.0, -1.0, 0.0, 2.0) == (23.0, 34.0)  # cuts in: 5 m beyond the spot
    p.x, p.y = 22.0, 34.0  # on the line: straight up it to the spot
    assert Engine.press_path(p, 30.0, 34.0, -1.0, 0.0, 2.0) == (28.0, 34.0)
    p.x, p.y = 22.0, 54.0  # far off it: into the lane at his own depth first
    assert Engine.press_path(p, 30.0, 34.0, -1.0, 0.0, 2.0) == (22.0, 34.0)
    p.x, p.y = 33.0, 39.0  # behind the ball: he runs for the spot itself
    assert Engine.press_path(p, 30.0, 34.0, -1.0, 0.0, 2.0) == (28.0, 34.0)
    # No switch, so no stop-start: a step closer to the line moves his target by no more than the step.
    for off in (0.5, 0.99, 1.0, 1.01, 2.0):
        p.x, p.y = 22.0, 34.0 + off
        near = Engine.press_path(p, 30.0, 34.0, -1.0, 0.0, 2.0)
        p.y -= 0.02
        nearer = Engine.press_path(p, 30.0, 34.0, -1.0, 0.0, 2.0)
        assert math.hypot(near[0] - nearer[0], near[1] - nearer[1]) <= 0.02 + 1e-9


def test_the_first_presser_takes_that_path_in_the_match():
    e = Engine(1)
    carrier, p = e.by_id["a10"], e.by_id["h4"]  # away attack toward x = 0; h4 defends that goal
    carrier.x, carrier.y, carrier.vx, carrier.vy = 30.0, 34.0, 0.0, 0.0
    e.ball = (30.0, 34.0, 0.0, 0.0, 0.0, 0.0)
    e.give(carrier.id)
    brain = e.brains["home"]
    brain.in_possession, brain.changed_at, brain.pressers, brain.markers = False, e.t, [p.id], {}
    p.x, p.y = 22.0, 39.0
    tx, ty, _ = e.shape_target(p)
    assert (round(tx, 6), round(ty, 6)) == (23.0, 34.0)
    carrier.vx = -4.0  # running at goal: the lane is the one from where he is going (2 m on)
    tx, ty, _ = e.shape_target(p)
    assert (round(tx, 6), round(ty, 6)) == (22.0, 34.0)
