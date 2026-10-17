"""The cushioned first touch (ninety/sim/firsttouch.py, A4): a player who has reacted and reaches the
ball takes out what his surface can kill and sends the rest where he chooses, with his own error.
What is left decides the rest: at his feet, or a heavy touch the race decides (D6)."""

import math

import pytest

from ninety.sim import ball, firsttouch
from ninety.sim import decisions as D
from ninety.sim.body import FOOT_REACH_Z
from ninety.sim.engine import DT, PITCH_Y, Engine
from ninety.sim.perception import Sighting
from ninety.sim.profiles import FOOT_ABSORB_MPS, SPEED_ERROR


def scene(keep: tuple[str, ...], seed: int = 1) -> Engine:
    """Everyone still, everyone not in `keep` far away (the home side by their own corner flag, the
    away side by the other), nobody deciding anything and nobody seen by anyone."""
    e = Engine(seed)
    for p in e.players:
        p.vx = p.vy = 0.0
        if p.id not in keep:
            p.x, p.y = (2.0, 2.0) if p.team == "home" else (103.0, 66.0)
    for view in e.beliefs.values():
        view.seen.clear()
        view.next_scan = 1e9  # nobody looks again: what each believes is set by the test
    e.decide = lambda *a, **k: None
    return e


def arrive(e: Engine, pid: str, speed: float, direction: float, z: float = 0.0, steps: int = 1) -> None:
    """A ball from h2 (far away, struck long ago, so he has reacted) arriving at `pid`'s feet at
    `speed`, along `direction`; then `steps` frames of the match."""
    p = e.by_id[pid]
    e.possessor, e.last_touch, e.kicker_clear, e.kicked_at = None, "h2", True, e.t - 2.0
    ux, uy = math.cos(direction), math.sin(direction)
    e.ball = (p.x - 0.9 * ux, p.y - 0.9 * uy, z, speed * ux, speed * uy, 0.0)
    for _ in range(steps):
        e.step()


def test_a_slow_pass_to_a_free_player_ends_at_his_feet():
    e = scene(("h8",))
    p = e.by_id["h8"]
    p.x, p.y, p.heading = 50.0, 34.0, math.pi
    arrive(e, "h8", 8.0, 0.0, steps=3)  # well within what any foot kills (12 m/s at the worst)
    assert e.possessor == "h8" and e.dribbler is None
    assert math.hypot(e.ball[0] - p.x, e.ball[1] - p.y) < 1.0


def test_a_fast_ball_is_a_heavy_touch_he_runs_onto_when_nobody_is_nearer():
    e = scene(("h8",))
    p = e.by_id["h8"]
    p.x, p.y, p.heading = 50.0, 34.0, math.pi
    p.profile.attributes["first_touch"] = 0.0  # kills 12 m/s
    arrive(e, "h8", 20.0, 0.0)
    assert e.possessor is None and e.dribbler == "h8"  # 8 m/s left over: more than he keeps at his feet
    # In the data a heavy touch is a deflection (DATA_CONTRACT); unlike a rebound it is still his
    # to run onto (dribbler).
    assert [ev["player"] for ev in e.match.events if ev["type"] == "deflection"] == ["h8"]
    # It came at his front and his aim (the goal he attacks) is behind him: he takes it across his
    # body, never through it (P11): it leaves him moving away from him.
    bx, by, _, vx, vy, _ = e.ball
    assert (vx - p.vx) * (bx - p.x) + (vy - p.vy) * (by - p.y) > 0
    for _ in range(int(6.0 / DT)):
        e.step()
        if e.possessor:
            break
    assert e.possessor == "h8"


def test_a_heavy_touch_is_won_by_an_opponent_nearer_where_it_runs():
    e = scene(("h8", "a4"))
    p, rival = e.by_id["h8"], e.by_id["a4"]
    p.x, p.y, p.heading = 50.0, 34.0, math.pi
    p.profile.attributes["first_touch"] = 0.0
    arrive(e, "h8", 20.0, 0.0)
    assert e.dribbler == "h8"
    # a4 stands 6 m on along where the touch runs, nearer it than h8 (he still has to react to it).
    bx, by, _, vx, vy, _ = e.ball
    n = math.hypot(vx, vy)
    rival.x, rival.y = bx + 6.0 * vx / n, by + 6.0 * vy / n
    for _ in range(int(3.0 / DT)):
        e.step()
        if e.possessor:
            break
    assert e.possessor == "a4"


def touchline_touch(e: Engine) -> None:
    """h8 on the touchline (y = 0.8), the ball coming hard across him toward the line (-y), 6 m/s
    more than his foot kills: a heavy touch, the ordinary kind, nobody near."""
    p = e.by_id["h8"]
    p.x, p.y, p.heading = 50.0, 0.8, math.pi / 2
    p.profile.attributes["first_touch"] = 0.0
    arrive(e, "h8", FOOT_ABSORB_MPS[0] + 6.0, -math.pi / 2, steps=int(3.0 / DT))


def test_a_player_on_the_touchline_does_not_send_an_ordinary_touch_out():
    e = scene(("h8",))
    touchline_touch(e)
    assert not any(ev["type"] == "out_of_play" for ev in e.match.events)
    assert 0.0 <= e.ball[1] <= PITCH_Y


def test_planted_defect_a_touch_that_ignores_his_chosen_direction_goes_out(monkeypatch):
    # The same touch, but the ball keeps the way it came (as if he chose nothing): the touchline test
    # has to be able to fail.
    e = scene(("h8",))

    def the_way_it_came(p, cx, cy, speed):
        bvx, bvy = e.ball[3], e.ball[4]
        n = math.hypot(bvx, bvy)
        return p.vx + speed * bvx / n, p.vy + speed * bvy / n
    monkeypatch.setattr(e, "cushion", the_way_it_came)
    touchline_touch(e)
    assert any(ev["type"] == "out_of_play" for ev in e.match.events)


def test_he_turns_the_touch_back_in_rather_than_play_it_over_a_line():
    # His chosen way (away from an opponent pressing him from infield) points over the touchline;
    # he sends it the least turn back in that keeps it on the pitch.
    e = scene(("h8", "a4"))
    p = e.by_id["h8"]
    p.x, p.y, p.heading = 50.0, 2.0, 0.0
    e.beliefs["h8"].seen.clear()
    aim = e.touch_aim(p, p.x, p.y)
    rival = e.by_id["a4"]
    rival.x, rival.y = 50.5, 4.0
    e.beliefs["h8"].seen["a4"] = Sighting(50.5, 4.0, 0.0, 0.0, e.t)
    pressed = e.touch_aim(p, p.x, p.y)
    assert math.sin(pressed) < math.sin(aim)  # pressed from infield, he would play it toward the line
    vx, vy = e.cushion(p, p.x, p.y, 6.0)
    path = ball.predict((p.x, p.y, 0.0, vx, vy, 0.0), DT, 6.0)
    assert not any(D.out_of_play(q[0], q[1]) for q in path)


def test_a_ball_he_has_not_reacted_to_or_far_too_fast_still_rebounds():
    e = scene(("h8",))
    p = e.by_id["h8"]
    p.x, p.y, p.heading = 50.0, 34.0, math.pi
    e.possessor, e.last_touch, e.kicker_clear, e.kicked_at = None, "h2", True, e.t  # no time to react
    e.ball = (49.1, 34.0, 1.2, 10.0, 0.0, 0.0)
    for _ in range(3):  # 0.12 s: it reaches him well inside any reaction time
        e.step()
    assert e.dribbler is None and any(ev["type"] == "deflection" for ev in e.match.events)
    absorb = p.profile.absorb_mps(False)
    assert firsttouch.beaten(firsttouch.BEATEN_FACTOR * absorb + 0.1, absorb)
    assert not firsttouch.beaten(firsttouch.BEATEN_FACTOR * absorb - 0.1, absorb)


@pytest.mark.parametrize("z,into", [(0.1, True), (1.0, True), (1.0, False)])
def test_the_passer_judges_the_touch_by_the_engines_rule(z, into):
    # One rule (firsttouch.py) for both: the estimate is even odds exactly where the engine's touch
    # stops keeping the ball at his feet, on the surface the ball's height and line give.
    absorb = firsttouch.surface_absorb(18.0, z, into)
    edge = absorb + firsttouch.KEEP_MPS
    assert firsttouch.at_feet(firsttouch.residual(edge - 0.01, absorb))
    assert not firsttouch.at_feet(firsttouch.residual(edge + 0.01, absorb))
    assert firsttouch.kept_estimate(edge, absorb, D.CONTROL_MARGIN_MPS) == pytest.approx(0.5)


def test_a_thigh_or_chest_only_for_a_ball_into_his_body_and_beside_him_a_foot():
    # A4 and P14: above BODY_TOUCH_Z a ball coming into his body meets a thigh, chest or head, which
    # kills AERIAL_ABSORB of what a foot does; beside him, within his foot's reach, it is the foot.
    knee = (firsttouch.BODY_TOUCH_Z + FOOT_REACH_Z) / 2
    assert firsttouch.surface_absorb(18.0, knee, True) == pytest.approx(18.0 * firsttouch.AERIAL_ABSORB)
    assert firsttouch.surface_absorb(18.0, knee, False) == 18.0
    assert firsttouch.surface_absorb(18.0, firsttouch.BODY_TOUCH_Z, True) == 18.0


def test_a_pass_a_team_mate_plays_ends_with_him_even_when_his_heavy_touch_is_lost():
    # The pass reached him: it is completed where he touched it. a4 winning the loose ball after is
    # a new event, never the pass's end (C7: a pass ends before anything else happens to the ball).
    e = scene(("h8", "a4"))
    p, rival = e.by_id["h8"], e.by_id["a4"]
    p.x, p.y, p.heading = 50.0, 34.0, math.pi
    p.profile.attributes["first_touch"] = 0.0
    sent = e.emit("pass", "home", 30.0, 34.0, player="h2")
    e.kicked, e.intended = sent, "h8"
    arrive(e, "h8", 20.0, 0.0)
    assert e.dribbler == "h8"
    assert sent["outcome"] == "success" and sent["receiver"] == "h8"
    assert math.hypot(sent["end_x"] - p.x, sent["end_y"] - p.y) < 1.5
    bx, by, _, vx, vy, _ = e.ball
    n = math.hypot(vx, vy)
    rival.x, rival.y = bx + 6.0 * vx / n, by + 6.0 * vy / n
    for _ in range(int(3.0 / DT)):
        e.step()
        if e.possessor:
            break
    assert e.possessor == "a4" and sent["receiver"] == "h8"


def touch_spread(first_touch: float, n: int = 400) -> tuple[float, float]:
    """(direction SD in degrees, speed SD in m/s) of 6 m/s cushioned touches from h8's front."""
    from statistics import pstdev
    e = scene(("h8",))
    p = e.by_id["h8"]
    p.x, p.y, p.heading = 50.0, 34.0, 0.0
    p.profile.attributes["first_touch"] = first_touch
    sent = [e.cushion(p, 50.6, 34.0, 6.0) for _ in range(n)]
    angles = [math.degrees(math.atan2(vy, vx)) for vx, vy in sent]
    return pstdev(angles), pstdev(math.hypot(vx, vy) for vx, vy in sent)


def test_the_touch_is_sent_with_his_own_error_in_direction_and_speed():
    good, poor = touch_spread(1.0), touch_spread(0.0)
    assert poor[0] > 1.5 * good[0] > 0  # direction: wider with a poorer first touch (A3's rule)
    # speed: A3's share of the speed it is sent at (unpressed, whatever his skill)
    assert good[1] == pytest.approx(SPEED_ERROR * 6.0, rel=0.2) and poor[1] == pytest.approx(good[1], rel=0.2)


def test_however_wide_his_error_a_touch_never_leaves_into_his_own_body():
    e = scene(("h8",))
    p = e.by_id["h8"]
    p.x, p.y, p.heading = 50.0, 34.0, 0.0
    p.profile.attributes["first_touch"] = 0.0
    for bx, by in ((50.6, 34.0), (49.4, 34.0), (50.0, 34.6), (50.4, 33.6)):  # in front, behind, beside
        for _ in range(200):
            vx, vy = e.cushion(p, bx, by, 8.0)
            assert vx * (bx - p.x) + vy * (by - p.y) >= -1e-9  # P11: away from him, or across him


def test_back_on_a_heavy_touch_won_from_the_other_side_is_a_possession_change_not_a_tackle():
    e = scene(("a4",))
    p = e.by_id["a4"]
    p.x, p.y, p.heading = 50.0, 34.0, 0.0
    p.profile.attributes["first_touch"] = 0.0
    e.poss_team = "home"  # h2's side had it
    arrive(e, "a4", 16.0, math.pi)  # a home pass coming at him from +x
    assert e.dribbler == "a4"
    for _ in range(int(6.0 / DT)):
        e.step()
        if e.possessor:
            break
    assert e.possessor == "a4"
    kinds = [(ev["type"], ev.get("player")) for ev in e.match.events]
    assert ("possession_change", "a4") in kinds
    assert not any(k == "tackle" for k, _ in kinds)  # nobody had it to be tackled


def test_a_heavy_touch_judges_offside_afresh():
    # Law 11: a team-mate offside when the pass was played, but not when h8 plays it on, is not
    # offside for what h8's touch sets free.
    e = scene(("h8", "h9", "a2"))
    p, mate = e.by_id["h8"], e.by_id["h9"]
    p.x, p.y, p.heading = 60.0, 34.0, math.pi
    e.by_id["a2"].x, e.by_id["a2"].y = 70.0, 30.0  # the second-last defender (with a1 in goal)
    mate.x, mate.y = 65.0, 40.0  # behind a2's line: onside now
    e.offside = {"h9"}  # as judged at the earlier pass
    p.profile.attributes["first_touch"] = 0.0
    arrive(e, "h8", 16.0, 0.0)
    assert e.dribbler == "h8" and "h9" not in e.offside


def test_winning_a_loose_heavy_touch_off_the_other_side_is_no_tackle():
    e = scene(("a4", "h8"))
    p, rival = e.by_id["a4"], e.by_id["h8"]
    p.x, p.y, p.heading = 50.0, 34.0, 0.0
    p.profile.attributes["first_touch"] = 0.0
    e.poss_team = "home"
    arrive(e, "a4", 16.0, math.pi)
    assert e.dribbler == "a4"
    bx, by, _, vx, vy, _ = e.ball
    n = math.hypot(vx, vy)
    rival.x, rival.y = bx + 6.0 * vx / n, by + 6.0 * vy / n  # h8 nearer where it runs
    for _ in range(int(3.0 / DT)):
        e.step()
        if e.possessor:
            break
    assert e.possessor == "h8"
    assert not any(ev["type"] == "tackle" for ev in e.match.events)  # a4 never had it
