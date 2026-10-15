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
    e.kicked, e.pass_target = {"type": "pass"}, (70.0, 20.0)
    assert e.play_point() == (70.0, 20.0)
    p = e.by_id["a6"]
    e.brains["away"].in_possession = False
    before = e.shape_target(p)[:2]
    e.ball = (55.0, 27.0, 0.0, 14.0, 0.0, 0.0)  # the ball half way there: nobody's target moves
    assert e.shape_target(p)[:2] == before
    e.kicked = None  # a loose ball: play is where the ball is
    assert e.play_point() == (55.0, 27.0)
