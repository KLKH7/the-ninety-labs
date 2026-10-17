"""Roles and mentalities (roles.py): what an archetype makes a player want to do off the ball."""

from ninety.sim import offball, perception, roles
from ninety.sim.engine import PITCH_Y, Engine


def attacking(archetype: str, pid: str, ball: tuple[float, float], build_up: str = "quick"):
    """Home has the ball at `ball`, settled and unpressed; everyone else stands still and away."""
    e = Engine(3)
    p = e.by_id[pid]
    p.profile.archetype = archetype
    p.profile.traits = []
    brain = e.brains["home"]
    brain.in_possession, brain.build_up = True, build_up
    carrier = e.by_id["h7"] if pid != "h7" else e.by_id["h8"]
    for q in e.players:
        q.vx = q.vy = 0.0
        if q.team == "away":
            q.x, q.y = 103.0, 66.0 if q.y > PITCH_Y / 2 else 2.0
    e.brains["away"].line_x = 100.0
    carrier.x, carrier.y = ball
    e.give(carrier.id)
    e.hold_until = e.t
    e.ball = (*ball, 0.0, 0.0, 0.0, 0.0)
    return e, p, carrier, brain


def sees_them(e: Engine) -> None:
    """Every home player has just seen every opponent where he stands (so knows he is onside)."""
    for q in e.players:
        if q.team == "home":
            e.beliefs[q.id].seen = {o.id: perception.Sighting(o.x, o.y, 0.0, 0.0, e.t)
                                    for o in e.players if o.team == "away"}


def test_an_overlapping_full_back_runs_beyond_the_ball_on_his_flank():
    e, p, carrier, brain = attacking("overlapping", "h2", (60.0, 12.0))  # RB, the ball on his flank
    p.x, p.y = 50.0, 12.0
    sees_them(e)
    run = e.run_target(p, carrier, brain)
    assert run and run[0] > carrier.x and run[1] < 10.0  # past the ball, along his touchline
    e, p, carrier, brain = attacking("defensive", "h2", (60.0, 12.0))
    p.x, p.y = 50.0, 12.0
    sees_them(e)
    assert e.run_target(p, carrier, brain) is None  # a defensive full back holds


def test_a_box_to_box_midfielder_arrives_late_once_the_ball_is_in_the_final_third():
    e, p, carrier, brain = attacking("box_to_box", "h6", (80.0, 30.0))
    p.x, p.y = 65.0, 30.0
    sees_them(e)
    run = e.run_target(p, carrier, brain)
    assert run and abs(run[0] - (105.0 - roles.LATE_RUN_DEPTH_M)) < 1e-9
    e, p, carrier, brain = attacking("box_to_box", "h6", (50.0, 30.0))  # not yet in the final third
    p.x, p.y = 40.0, 30.0
    sees_them(e)
    assert e.run_target(p, carrier, brain) is None


def test_an_inside_forward_runs_from_wide_into_the_half_space():
    e, p, carrier, brain = attacking("inside_forward", "h9", (60.0, 30.0))  # RW
    p.x, p.y = 70.0, 8.0
    e.brains["away"].line_x = 80.0
    sees_them(e)
    run = e.run_target(p, carrier, brain)
    assert run and abs(run[1] - (PITCH_Y / 2 - roles.DIAGONAL_HALF_SPACE_M)) < 1e-9 and run[0] > 80.0


def test_a_direct_side_sends_only_its_attacking_roles():
    e, p, carrier, brain = attacking("touchline_winger", "h9", (60.0, 30.0), "direct")
    p.x, p.y = 70.0, 8.0
    e.brains["away"].line_x = 80.0
    sees_them(e)
    assert e.run_target(p, carrier, brain) is None  # balanced duty: he holds on a counter side
    e, p, carrier, brain = attacking("touchline_winger", "h9", (60.0, 30.0), "quick")
    p.x, p.y = 70.0, 8.0
    e.brains["away"].line_x = 80.0
    sees_them(e)
    assert e.run_target(p, carrier, brain)


def test_a_deep_playmaker_drops_to_receive_in_build_up_and_not_in_their_half():
    e, p, carrier, brain = attacking("deep_playmaker", "h7", (25.0, 20.0))
    assert e.drop_target(p, carrier) == (25.0 + roles.DROP_AHEAD_M, (20.0 + PITCH_Y / 2) / 2)
    e, p, carrier, brain = attacking("deep_playmaker", "h7", (70.0, 20.0))
    assert e.drop_target(p, carrier) is None
    e, p, carrier, brain = attacking("box_to_box", "h7", (25.0, 20.0))
    assert e.drop_target(p, carrier) is None


def test_the_role_shifts_his_spot_with_the_ball_and_never_beyond_the_last_line():
    base = offball.attacking_slot("RB", 0.0, 50.0, 34.0, 80.0)
    higher = offball.attacking_slot("RB", 0.0, 50.0, 34.0, 80.0, 6.0, 0.0)
    inside = offball.attacking_slot("RB", 0.0, 50.0, 34.0, 80.0, 0.0, 5.0)
    assert higher[0] == base[0] + 6.0 and inside[1] == base[1] + 5.0  # RB is on the low-y side
    capped = offball.attacking_slot("RCM", 0.0, 70.0, 34.0, 75.0, 30.0, 0.0)
    assert capped[0] <= 75.0  # L10: not beyond where he would be onside


def test_each_side_draws_a_build_up_style_from_its_own_stream():
    styles = {Engine(s).brains["home"].build_up for s in range(40)}
    assert styles == set(roles.STYLES)
    assert Engine(5).brains["home"].block == Engine(5).brains["home"].block  # blocks unchanged by it
