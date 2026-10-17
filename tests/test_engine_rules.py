"""Engine-level behaviour the step 2 audit found untested: contact needs approach, passes go where
the passer believes, keepers only anticipate shots, pressers stand goal-side, and facing holds."""

import math
from collections import defaultdict
from statistics import mean, pstdev

from ninety.sim import ball, perception
from ninety.sim.body import BRAKE_MAX
from ninety.sim.engine import (
    BODY_RADIUS,
    BODY_RESTITUTION,
    DIVE_TIME_S,
    DT,
    FPS,
    MAX_STRIKE_MPS,
    MISCONTROL_KEEP,
    Engine,
    simulate,
    throw_hands,
    throw_stand,
)
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
    nx, ny = e.ball[0] - p.x, e.ball[1] - p.y
    n = math.hypot(nx, ny)
    assert n >= BODY_RADIUS + ball.RADIUS  # it leaves from outside the body, not from inside it
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


def test_the_presser_stands_goal_side_for_both_teams():
    for team, defends_x in (("home", 0.0), ("away", 105.0)):
        e = Engine(1)
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


def test_a_restart_is_ready_within_two_seconds():
    for seed, kind, spot in (
        (1, "throw_in", (40.0, 0.0)),
        (2, "goal_kick", (5.5, 34.0)),
        (3, "corner", (105.0, 0.0)),
    ):
        e = Engine(seed)
        e.stop(kind, "home", spot)
        wait = e.restart.ready_at - e.t
        assert 1.0 <= wait <= 2.0


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
    for touch in (1.0, 0.0):  # can kill 16 m/s, or 8 m/s
        e = Engine(1)
        still(e)
        p = e.by_id["a6"]
        p.x, p.y = 50.0, 30.0
        p.profile.attributes["first_touch"] = touch
        e.possessor, e.last_touch, e.kicker_clear, e.kicked_at = None, "h2", True, e.t - 2.0
        before = (49.4, 30.0, 0.0, 12.0, 0.0, 0.0)
        e.ball = (49.4 + 12.0 * DT, 30.0, 0.0, 12.0, 0.0, 0.0)
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
    e.ball = (49.6 + speed * DT, y, z, speed, 0.0, 0.0)
    e.contact((49.6, y, z, speed, 0.0, 0.0))
    return e


def test_a_high_ball_can_be_taken_on_the_body_and_a_poor_touch_is_worse():
    # 6 m/s at chest height: a good first touch kills it, a poor one is a heavy touch.
    killed = _high_ball(1.0, 6.0, 1.35, True)
    assert killed.possessor == "a6" and killed.ball[3] == 0.0 and killed.ball[5] == 0.0
    assert not any(ev["type"] == "deflection" for ev in killed.match.events)
    heavy = _high_ball(0.0, 6.0, 1.35, True)
    assert heavy.possessor is None
    assert math.isclose(heavy.ball[3], -MISCONTROL_KEEP * 6.0, rel_tol=0.05)
    # The same arrival with no time to set himself still just rebounds off the body.
    cold = _high_ball(1.0, 6.0, 1.35, False)
    assert cold.possessor is None
    assert math.isclose(cold.ball[3], -BODY_RESTITUTION * 6.0, rel_tol=0.05)
    # A thigh is the same idea, and harder than a foot reached out to the side.
    thigh = _high_ball(1.0, 12.0, 0.7, True)
    assert thigh.possessor is None and any(ev["type"] == "deflection" for ev in thigh.match.events)
    foot = _high_ball(1.0, 12.0, 0.7, True, y=30.55)
    assert foot.possessor == "a6"
    # A clip of the outside rebounds even when he is ready and his touch is perfect.
    clip = _high_ball(1.0, 6.0, 1.35, True, y=30.32)
    assert clip.possessor is None and any(ev["type"] == "deflection" for ev in clip.match.events)
    # Already leaving him, or over his head, or past his shoulder: he does not take it.
    e = Engine(1)
    still(e)
    p = e.by_id["a6"]
    p.x, p.y = 50.0, 30.0
    p.profile.attributes["first_touch"] = 1.0
    e.possessor, e.last_touch, e.kicker_clear, e.kicked_at = None, "h2", True, e.t - 2.0
    e.ball = (50.1 + 6.0 * DT, 30.0, 1.35, 6.0, 0.0, 0.0)
    e.contact((50.1, 30.0, 1.35, 6.0, 0.0, 0.0))
    assert e.possessor is None and e.ball[3] == 6.0
    over = _high_ball(1.0, 6.0, 2.1, True)
    assert over.possessor is None and over.ball[3] == 6.0
    wide = _high_ball(1.0, 6.0, 1.35, True, y=30.7)
    assert wide.possessor is None and wide.ball[3] == 6.0


def test_a_touch_names_the_part_and_a_carry_does_not():
    chest = _high_ball(1.0, 6.0, 1.35, True)
    assert chest.pose(chest.by_id["a6"])[0] == "chest"
    chest.t += 0.35
    assert chest.pose(chest.by_id["a6"])[0] != "chest"
    thigh = _high_ball(1.0, 12.0, 0.7, True)
    assert thigh.pose(thigh.by_id["a6"])[0] == "thigh"
    foot = _high_ball(1.0, 12.0, 0.2, True, y=30.55)
    assert foot.pose(foot.by_id["a6"])[0] == "foot"
    cold = _high_ball(1.0, 6.0, 1.35, False)
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


def test_a_dive_stays_drawn_until_the_stretch_ends():
    e = Engine(1)
    still(e)
    gk = e.keeper("home")
    gk.x, gk.y, gk.heading = 8.0, 34.0, 0.0
    gk.profile.attributes["reflexes"] = 1.0
    e.possessor = None
    e.free_since = 0.0
    react = e.reaction(gk)
    e.t = react + 0.2
    diving = 0.2 / DIVE_TIME_S
    reach = 1.0 + 0.8 * diving
    dist = (1.0 + reach + 0.5) / 2
    e.ball = (8.0, 34.0 + dist, 0.5, 0.0, 6.0, 0.0)
    assert e.pose(gk)[0] == "dive"
    e.t = react + DIVE_TIME_S - 0.04
    e.ball = (20.0, 50.0, 0.2, 0.0, 1.0, 0.0)
    assert e.pose(gk)[0] == "dive"
    e.t = react + DIVE_TIME_S + 0.04
    assert e.pose(gk)[0] != "dive"


def test_a_keeper_in_his_box_still_holds_a_high_ball_with_his_hands():
    e = Engine(1)
    still(e)
    p = e.keeper("home")
    p.x, p.y = 5.0, 34.0
    p.profile.attributes["first_touch"] = 0.0  # a chest could not kill this
    p.profile.attributes["handling"] = 1.0
    e.possessor, e.last_touch, e.kicker_clear, e.kicked_at = None, "a6", True, e.t - 2.0
    e.ball = (4.6 + 12.0 * DT, 34.0, 1.4, 12.0, 0.0, 0.0)
    e.contact((4.6, 34.0, 1.4, 12.0, 0.0, 0.0))
    assert e.possessor == p.id
    assert e.pose(p)[0] == "hands"


def test_a_long_ball_to_the_wing_is_struck_as_a_cross_and_a_shot_with_finishing(monkeypatch):
    e, p = kicker()
    used = []
    original = e.execute
    monkeypatch.setattr(e, "execute", lambda *a: used.append(a[-1]) or original(*a))
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


def test_a_throw_in_taker_runs_to_his_spot_and_stops_there():
    """Lesson 5: the taker was once moved the last metre to his spot in one frame (22 m/s) and
    stopped dead with the ball. The match must contain a throw-in, so the case is exercised; a
    short clip with no restart would pass whatever the engine did."""
    m = simulate(7, 6)
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


def step(e: Engine) -> None:
    """One frame of Engine.run without its kick-off."""
    e.moved = None
    e.perceive_and_think()
    e.duels()
    if e.possessor:
        e.tick_carrier()
    elif e.restart:
        e.tick_restart()
    else:
        e.tick_free()
    e.move_players()
    e.snapshot()
    e.t += DT
    e.frame += 1


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
    for _ in range(int(10 / DT)):
        step(e)
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
        step(e)
        speeds.append(math.hypot(taker.vx, taker.vy))
    assert e.throw_by == taker.id
    for before, after in zip(speeds, speeds[1:], strict=False):
        assert after <= before + 1e-9 and before - after <= BRAKE_MAX * DT + 1e-9, speeds
