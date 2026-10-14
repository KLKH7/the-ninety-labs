"""Engine-level behaviour the step 2 audit found untested: contact needs approach, passes go where
the passer believes, keepers only anticipate shots, pressers stand goal-side, and facing holds."""

import math

from ninety.sim import ball, perception
from ninety.sim.engine import BODY_RADIUS, BODY_RESTITUTION, DT, PRESS_GAP_M, Engine


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


def test_a_pass_goes_where_the_passer_believes_the_team_mate_is():
    e = Engine(1)
    still(e)
    carrier, mate = e.by_id["h6"], e.by_id["h9"]
    carrier.x, carrier.y = 40.0, 34.0
    e.ball = (40.3, 34.0, 0.0, 0.0, 0.0, 0.0)
    mate.x, mate.y = 55.0, 34.0
    e.beliefs[carrier.id].seen[mate.id] = perception.Sighting(55.0, 50.0, 0.0, 0.0, e.t)  # wrong
    e.pass_to(carrier, mate)
    assert e.ball[4] > 0.5 * abs(e.ball[3])  # aimed toward y=50, where he thinks the mate is


def test_only_a_shot_at_his_own_goal_lets_a_keeper_react_early():
    e = Engine(1)
    keeper, outfield = e.keeper("away"), e.by_id["a6"]
    e.kicked = {"type": "pass", "team": "home"}
    assert e.reaction(keeper) == e.reaction(outfield)
    e.kicked = {"type": "shot", "team": "home"}
    assert e.reaction(keeper) < e.reaction(outfield)
    e.kicked = {"type": "shot", "team": "away"}  # his own team's shot at the other end
    assert e.reaction(keeper) == e.reaction(outfield)


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
    e.beliefs[carrier.id].seen[mate.id] = perception.Sighting(25.0, 34.0, 0.0, 0.0, e.t)
    e.pass_to(carrier, mate)
    assert e.possessor == carrier.id and e.windup  # not struck through his own body
    for _ in range(10):
        e.tick_carrier()
        if e.possessor is None:
            break
    assert e.possessor is None and e.ball[3] < 0  # struck, from behind him, toward the team-mate
    assert e.ball[0] < carrier.x
