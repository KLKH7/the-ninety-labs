"""Engine-level behaviour the step 2 audit found untested: contact needs approach, passes go where
the passer believes, keepers only anticipate shots, pressers stand goal-side, and facing holds."""

import math
from statistics import mean, pstdev

import pytest

from ninety.sim import ball, perception
from ninety.sim.engine import BODY_RADIUS, BODY_RESTITUTION, DT, PRESS_GAP_M, Engine
from ninety.sim.profiles import MAX_STRIKE_MPS


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
        brain.block = "mid"  # engages at halfway
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
    want = offball.attacking_slot("RB", 0.0, 50.0, 34.0, e.brains["away"].line_x)
    assert e.shape_target(p)[:2] == want


def test_his_own_pass_that_goes_straight_in_is_his_shot_not_an_old_deflection():
    e = Engine(1)
    e.deflect(e.by_id["h10"], 60.0, 32.0, 0.3, 0.3)  # an earlier touch
    carrier = e.by_id["h10"]
    e.ball = (90.0, 30.0, 0.0, 0.0, 0.0, 0.0)
    e.kicked = e.emit("pass", "home", 90.0, 30.0, player="h10")
    e.kick(carrier, 20.0, 4.0, 0.0)
    e.last_touch = "h10"
    e.scored("home", e.kicked, 105.0, 34.0)
    kinds = {ev["type"] for ev in e.match.events if ev["player"] == "h10" and ev["type"] != "goal"}
    assert "deflection" in kinds  # the old touch stays what it was
    shot = next(ev for ev in e.match.events if ev["type"] == "shot")
    assert shot["outcome"] == "goal" and shot["x"] == 90.0


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
    for _ in range(10):
        e.tick_carrier()
        e.t += 1 / 25
    assert p.vx > 2.0  # still going his way, at a dribbling pace
    assert p.x > 50.0 + 1.5


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
            tx, ty, speed = s.shape_target(p)
            if s.chase.get(p.team, [None])[0] == p.id or (s.brains[p.team].in_possession and s.run_target(
                    p, s.by_id[s.possessor], s.brains[p.team]) if s.possessor else False):
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
    e.dribbler, e.runs, e.chase = "h7", {"h9": (90.0, 30.0)}, {"home": ["h7"]}
    e.kickoff("away")
    assert e.dribbler is None and not e.runs and not e.chase


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
    for _ in range(5):
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
    k = _shot_at_keeper(e, (90.0, 34.0, 2.0, 25.0, 6.0, 5.0))  # rising steeply
    e.t += e.reaction(k)
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
    before = e.reach(k, 104.0, 34.0)[0]
    e.dive = (k.id, e.t, k.y, 0.5, e.kicked_at + e.reaction(k))  # he decides to dive only now
    assert e.reach(k, 104.0, 34.0)[0] >= before



def test_before_he_reacts_the_keeper_has_only_his_standing_reach_then_it_grows():
    from ninety.sim import offball
    e = Engine(1)
    k = _shot_at_keeper(e, (90.0, 34.0, 0.5, 25.0, 0.0, 0.0))
    e.t += e.reaction(k) * 0.5
    assert e.reach(k, 104.0, 34.0)[0] == offball.KEEPER_STAND_REACH_M
    e.t += e.reaction(k) * 0.5 + 0.2
    assert e.reach(k, 104.0, 34.0)[0] > offball.KEEPER_STAND_REACH_M


def test_a_deflection_does_not_unstretch_a_dive_already_under_way():
    e = Engine(1)
    k = _shot_at_keeper(e, (90.0, 34.0, 0.5, 25.0, 6.0, 0.0))
    e.t += e.reaction(k)
    assert e.keeper_dive(k)
    e.t += 0.3
    stretched = e.reach(k, 104.0, 34.0)[0]
    e.kicked_at = e.t  # deflected mid-dive
    assert e.reach(k, 104.0, 34.0)[0] == stretched


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
    for _ in range(int(0.5 * 25) + 2):
        e.keeper_dive(k)
        e.t += 1 / 25
    assert e.dive is None and e.off_balance[k.id] > e.t  # landed, on the ground
    e.kicked_at = e.t  # a deflection while he is down
    assert e.reach(k, 104.0, 36.0)[0] > 1.5


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
    assert e.can_reach(k, 103.0, 35.7, 0.5, t, delay=t)[0]  # 1.7 m: his hands, without a step
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
    ramp = 2 * (offball.DIVE_TIME_S - offball.KEEPER_DIVE_TRAVEL_M / offball.DIVE_PEAK_MPS)
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
    # GROUNDING P2: the dive moves him sideways; the run he was making brakes as hard as legs allow.
    from ninety.sim.engine import BRAKE_MAX, DT
    _, ahead, landed = _dive_speeds(1.0, vx=-4.0)
    run = [-4.0] + ahead[:landed + 1]
    assert run[1] < -3.0  # he does not stop dead
    for a, b in zip(run, run[1:], strict=False):
        if a < -BRAKE_MAX * DT:  # still running: braking as hard as his legs allow, no harder
            assert b - a == pytest.approx(BRAKE_MAX * DT)


def test_a_keeper_already_running_sideways_dives_on_from_that_run_and_does_not_lose_it():
    # GROUNDING P15 and P2: toward the dive, the push starts from his run; away from it, he first
    # brakes as legs allow, then pushes; his sideways speed never jumps.
    from ninety.sim import offball
    from ninety.sim.engine import BRAKE_MAX, DT
    ramp = 2 * (offball.DIVE_TIME_S - offball.KEEPER_DIVE_TRAVEL_M / offball.DIVE_PEAK_MPS)
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
