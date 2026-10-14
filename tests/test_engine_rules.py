"""Engine-level behaviour the step 2 audit found untested: contact needs approach, passes go where
the passer believes, keepers only anticipate shots, pressers stand goal-side, and facing holds."""

import math
from statistics import mean, pstdev

from ninety.sim import ball, perception
from ninety.sim.engine import BODY_RADIUS, BODY_RESTITUTION, DT, MAX_STRIKE_MPS, PRESS_GAP_M, Engine


def still(e: Engine) -> None:
    for p in e.players:
        p.vx = p.vy = 0.0


def test_a_ball_moving_away_from_a_body_is_not_touched_by_it():
    e = Engine(1)
    still(e)
    p = e.by_id["a6"]
    p.x, p.y = 50.0, 30.0
    e.possessor, e.last_touch, e.kicker_clear = None, "h2", True
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
    assert scene.keeper == (100.0, 34.0) and scene.opponents == []  # the keeper is counted once


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
        assert math.isclose(abs(tx - 52.0), PRESS_GAP_M, abs_tol=0.01)
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
    taker.x, taker.y = 50.0, 0.0
    e.restart.ready_at = e.t
    e.tick_restart()
    assert e.throw_by == taker.id
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
    assert thrown_at is not None  # down the line once he has waited
    assert e.match.events[-1]["type"] == "pass" and e.ball[5] > 0  # thrown, through the air


def test_a_keeper_may_not_handle_a_team_mates_deliberate_pass():
    e = Engine(1)
    keeper, mate = e.keeper("home"), e.by_id["h3"]
    keeper.x, keeper.y = 6.0, 34.0
    e.kicked = {"type": "pass", "team": "home", "player": mate.id}
    e.last_touch = mate.id
    assert not e.hands(keeper, 6.0, 34.0)
    e.last_touch = "a9"  # an opponent got a touch on it
    assert e.hands(keeper, 6.0, 34.0)
