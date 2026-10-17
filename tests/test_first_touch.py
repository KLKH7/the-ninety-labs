"""The cushioned first touch (ninety/sim/firsttouch.py, A4): a player who has reacted and reaches the
ball takes out what his surface can kill and sends the rest where he chooses, with his own error.
What is left decides the rest: at his feet, or a heavy touch the race decides (D6)."""

import math

import pytest

from ninety.sim import ball, firsttouch
from ninety.sim import decisions as D
from ninety.sim.engine import DT, PITCH_Y, Engine
from ninety.sim.perception import Sighting
from ninety.sim.profiles import FOOT_ABSORB_MPS


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


@pytest.mark.parametrize("z", [0.1, 1.0])
def test_the_passer_judges_the_touch_by_the_engines_rule(z):
    # One rule (firsttouch.py) for both: the estimate is even odds exactly where the engine's touch
    # stops keeping the ball at his feet, on the surface the ball's height gives.
    absorb = firsttouch.surface_absorb(18.0, z)
    edge = absorb + firsttouch.KEEP_MPS
    assert firsttouch.at_feet(firsttouch.residual(edge - 0.01, absorb))
    assert not firsttouch.at_feet(firsttouch.residual(edge + 0.01, absorb))
    assert firsttouch.kept_estimate(edge, absorb, D.CONTROL_MARGIN_MPS) == pytest.approx(0.5)
