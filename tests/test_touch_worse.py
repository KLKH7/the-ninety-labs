"""What makes a touch worse (firsttouch.quality, A4): his first-touch skill, where the ball comes from
against the way he faces, pressure from the nearest opponent (D2's zone), his energy and the ball's
speed relative to him. Each lowers the cushion (the fastest ball he keeps at his feet) and widens his
direction error. One hand-built scene per factor, good against bad, each with a planted defect (the
factor taken out) that must make it fail."""

import math

import pytest

from ninety.sim import firsttouch, perception
from ninety.sim.body import D0, SLOW_SCALE
from ninety.sim.engine import DT, Engine
from ninety.sim.profiles import Profile

SIDE_ON, BACK_TO_IT, FACING_IT = math.pi / 2, 0.0, math.pi  # headings for a ball from -x along y = 30
# A presser between D2's two reaches: inside the zone in front of him, outside it behind.
REACH_BETWEEN = (perception.PRESSURE_FRONT_M + perception.PRESSURE_BEHIND_M) / 2
TIRED_M = 10 * SLOW_SCALE * D0  # running above critical speed that all but empties the slow store (P10)
_real_pressure, _real_quality = perception.pressure_from, firsttouch.quality


def scene(heading: float = SIDE_ON, first_touch: float = 0.5, presser: float | None = None,
          spent: float = 0.0, composure: float = 0.0) -> tuple[Engine, object]:
    """h8 (attacking +x) at (50, 30), still, nobody else near; optionally a4 `presser` metres in front
    of him (toward the goal he attacks; negative is behind him). With no composure, pressure counts
    in full. `spent` is his running this match above critical speed (it lowers his slow store, P10)."""
    e = Engine(1)
    p = e.by_id["h8"]
    for q in e.players:
        q.vx = q.vy = 0.0
        if q is not p:
            q.x, q.y = (2.0, 2.0) if q.team == "home" else (103.0, 66.0)
    if presser is not None:
        e.by_id["a4"].x, e.by_id["a4"].y = 50.0 + presser, 30.0
    p.x, p.y, p.heading = 50.0, 30.0, heading
    p.profile.attributes["first_touch"] = first_touch
    p.profile.attributes["composure"] = composure
    p.physique.spent = spent
    e.possessor, e.last_touch, e.kicker_clear, e.kicked_at = None, "h2", True, e.t - 2.0
    return e, p


def set_ball(e: Engine, speed: float, x: float = 49.1) -> None:
    e.ball = (x, 30.0, 0.0, speed, 0.0, 0.0)


def worse_at(e: Engine, p, speed: float) -> float:
    set_ball(e, speed)
    return e.touch_worse(p, speed, p.profile.absorb_mps(False))


def fastest_kept(make) -> float:
    """The fastest ball (from -x, at his feet) his touch keeps at his feet, by the engine's rule."""
    e, p = make()
    foot = p.profile.absorb_mps(False)
    lo, hi = 0.0, 60.0
    for _ in range(40):
        v = (lo + hi) / 2
        left = firsttouch.residual(v, foot / worse_at(e, p, v))
        lo, hi = (v, hi) if firsttouch.at_feet(left) else (lo, v)
    return lo


def outcome(make, speed: float) -> str:
    e, p = make()
    set_ball(e, speed, 49.1 + speed * DT)
    e.contact((49.1, 30.0, 0.0, speed, 0.0, 0.0))
    return "kept" if e.possessor == p.id else ("heavy" if e.dribbler == p.id else "other")


def check(good, bad) -> None:
    """The bad case keeps less (lower cushion) and errs more (wider error), in the engine."""
    g, b = fastest_kept(good), fastest_kept(bad)
    assert b < g - 0.2  # a lower cushion: he keeps a slower ball at most
    between = (g + b) / 2
    assert outcome(good, between) == "kept" and outcome(bad, between) == "heavy"
    eg, pg = good()
    eb, pb = bad()
    assert worse_at(eb, pb, between) > worse_at(eg, pg, between)  # a wider direction error


FACTORS = {
    "skill": (lambda: scene(first_touch=1.0), lambda: scene(first_touch=0.0)),
    "body angle": (lambda: scene(heading=SIDE_ON), lambda: scene(heading=BACK_TO_IT)),
    "facing it, not his back to it": (lambda: scene(heading=FACING_IT), lambda: scene(heading=BACK_TO_IT)),
    "pressure": (lambda: scene(), lambda: scene(presser=1.2)),
    # D2's zone reaches further in front of him (toward the goal he attacks) than behind.
    "pressure in front, not behind": (lambda: scene(presser=-REACH_BETWEEN),
                                      lambda: scene(presser=REACH_BETWEEN)),
    "composure eases pressure": (lambda: scene(presser=1.2, composure=1.0), lambda: scene(presser=1.2)),
    "energy": (lambda: scene(spent=0.0), lambda: scene(spent=TIRED_M)),
}


@pytest.mark.parametrize("factor", FACTORS)
def test_each_factor_lowers_the_cushion_and_widens_the_error(factor):
    check(*FACTORS[factor])


def test_a_faster_ball_is_a_worse_touch_than_a_typical_pass():
    e, p = scene()
    foot = p.profile.absorb_mps(False)
    typical, fast = firsttouch.TYPICAL_ARRIVAL_MPS, foot + firsttouch.KEEP_MPS - 0.3
    assert worse_at(e, p, fast) > worse_at(e, p, typical) == pytest.approx(1.0)
    # Just inside what his foot alone would keep, the speed itself makes it a heavy touch.
    assert outcome(scene, fast) == "heavy"


# Planted defects: each factor taken out of the touch; its test must fail.
DEFECTS = {
    "skill": lambda mp: mp.setattr(Profile, "absorb_mps", lambda self, hands: 18.0),
    "body angle": lambda mp: mp.setattr(firsttouch, "approach_penalty", lambda a: 0.0),
    "facing it, not his back to it": lambda mp: mp.setattr(firsttouch, "approach_penalty", lambda a: 0.0),
    "pressure": lambda mp: mp.setattr(perception, "pressure_from", lambda *a: 0.0),
    "pressure in front, not behind": lambda mp: mp.setattr(
        perception, "pressure_from", lambda px, py, ox, oy, s: _real_pressure(px, py, ox, oy, -s)),
    "composure eases pressure": lambda mp: mp.setattr(
        firsttouch, "quality", lambda ang, pr, comp, *rest: _real_quality(ang, pr, 0.0, *rest)),
    "energy": lambda mp: mp.setattr(firsttouch, "FATIGUE_ERROR", 0.0),
}


@pytest.mark.parametrize("factor", DEFECTS)
def test_planted_defect_without_the_factor_its_test_fails(factor, monkeypatch):
    DEFECTS[factor](monkeypatch)
    with pytest.raises(AssertionError):
        check(*FACTORS[factor])


def test_planted_defect_without_the_speed_factor_its_test_fails(monkeypatch):
    monkeypatch.setattr(firsttouch, "SPEED_WORSE", 0.0)
    with pytest.raises(AssertionError):
        test_a_faster_ball_is_a_worse_touch_than_a_typical_pass()


def test_the_touch_is_sent_with_its_error_widened_by_how_much_worse_it_is():
    from statistics import pstdev
    e, p = scene()

    def spread(worse: float) -> float:
        angles = [math.degrees(math.atan2(*reversed(e.cushion(p, 49.6, 30.0, 6.0, 0.0, worse))))
                  for _ in range(400)]
        mid = angles[0]
        return pstdev((a - mid + 180) % 360 - 180 for a in angles)
    assert spread(2.0) / spread(1.0) == pytest.approx(2.0, rel=0.15)


def test_in_play_the_touch_is_sent_with_how_much_worse_it_is(monkeypatch):
    # contact() hands cushion() the touch's quality, so the wider error applies in a match.
    seen = []
    real = Engine.cushion

    def spy(self, p, cx, cy, speed, z=0.0, worse=1.0):
        seen.append(worse)
        return real(self, p, cx, cy, speed, z, worse)
    monkeypatch.setattr(Engine, "cushion", spy)
    monkeypatch.setattr(Engine, "touch_worse", lambda self, p, rel, foot: 1.7)
    assert outcome(scene, 6.0) == "kept" and seen == [1.7]


def test_how_much_worse_also_widens_the_speed_he_sends_it_at():
    from statistics import pstdev
    e, p = scene()

    def spread(worse: float) -> float:
        return pstdev(math.hypot(*e.cushion(p, 49.6, 30.0, 6.0, 0.0, worse)) for _ in range(400))
    assert spread(2.0) / spread(1.0) == pytest.approx(2.0, rel=0.15)


@pytest.mark.parametrize("approach", [0.0, 45.0, 90.0, -90.0])
def test_an_ordinary_reception_keeps_a4s_limits(approach):
    # Facing it or side-on, unpressed, fresh, a typical pass: A4's kill limit and error as they are.
    assert firsttouch.quality(approach, 0.0, 0.5, 1.0, firsttouch.TYPICAL_ARRIVAL_MPS, 18.0) == 1.0
    assert firsttouch.quality(180.0, 0.0, 0.5, 1.0, firsttouch.TYPICAL_ARRIVAL_MPS, 18.0) > 1.0
