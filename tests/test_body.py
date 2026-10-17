"""The body model behaves like a footballer's: force-velocity acceleration, stronger braking,
a reserve spent above critical speed and refilled below it, and a slow store that wears down."""

import math
import random

from ninety.sim import body, fmath

DT = 1 / 25


def fresh() -> body.Body:
    return body.Body(f0=5.2, v0=10.0, cs=3.9)


def sprint(b: body.Body, seconds: float) -> list[float]:
    x = y = vx = vy = 0.0
    speeds = []
    for _ in range(int(seconds / DT)):
        x, y, vx, vy = body.move(x, y, vx, vy, 1000.0, 0.0, 99.0, b, DT)
        speeds.append(math.hypot(vx, vy))
    return speeds


def test_acceleration_falls_as_speed_rises():
    speeds = sprint(fresh(), 4.0)
    early = (speeds[5] - speeds[0]) / (5 * DT)
    late = (speeds[-1] - speeds[-6]) / (5 * DT)
    assert 4.0 < early <= 5.2  # close to f0 from standing
    assert late < early / 2  # far less left near top speed


def test_flat_out_sprint_approaches_but_does_not_pass_top_speed():
    b = fresh()
    speeds = sprint(b, 8.0)
    assert max(speeds) < b.v0
    assert 7.5 < speeds[int(3.0 / DT)] < b.v0  # a long sprint gets well above match jogging pace


def test_braking_is_stronger_than_acceleration():
    b = fresh()
    x, y, vx, vy = 0.0, 0.0, 7.0, 0.0
    x2, y2, vx2, vy2 = body.move(x, y, vx, vy, -50.0, 0.0, 99.0, b, DT)  # target behind: stop
    braking = (7.0 - math.hypot(vx2, vy2)) / DT
    assert body.BRAKE_MAX * 0.99 <= braking <= body.BRAKE_MAX * 1.01
    assert braking > b.accel_limit(7.0)


def test_running_above_critical_speed_spends_and_below_refills():
    b = fresh()
    for _ in range(int(20 / DT)):
        b.spend(7.0, 0.0, DT)
    spent = b.reserve
    assert spent < body.D0 - 50
    for _ in range(int(60 / DT)):
        b.spend(1.0, 0.0, DT)
    assert b.reserve > spent  # walking refills


def test_an_empty_reserve_means_no_running_above_critical_speed():
    b = fresh()
    top_fresh = b.top_speed()
    b.reserve = 0.0
    assert b.top_speed() < top_fresh
    assert b.top_speed() == b.cs


def test_the_reserve_never_goes_below_empty():
    b = fresh()
    for _ in range(int(600 / DT)):
        b.spend(6.0, 0.0, DT)
    assert b.reserve == 0.0


def accel_from(vx: float, vy: float, tx: float, ty: float) -> tuple[float, float]:
    """Gain in speed per second, and total change per second, over one step."""
    b = fresh()
    _, _, nvx, nvy = body.move(0.0, 0.0, vx, vy, tx, ty, 99.0, b, DT)
    gain = (math.hypot(nvx, nvy) - math.hypot(vx, vy)) / DT
    return gain, math.hypot(nvx - vx, nvy - vy) / DT


def test_turning_from_almost_still_cannot_borrow_braking_grip():
    gain, _ = accel_from(0.01, 0.0, 0.0, 50.0)  # nearly still, target to the side
    assert gain <= 5.2 + 1e-6


def test_reversing_cannot_borrow_braking_grip():
    gain, total = accel_from(0.05, 0.0, -50.0, 0.0)  # barely moving, target behind
    assert gain <= 5.2 + 1e-6
    assert total <= body.BRAKE_MAX + 1e-6


def test_distance_covered_follows_force_velocity():
    b = fresh()
    one_second = b.distance_in(1.0)
    assert 2.0 < one_second < 2.7  # about f0 t² / 2 early on, a little less
    assert b.distance_in(1.0, speed_along=7.0) > 7.0  # already running covers more
    assert b.distance_in(0.0) == 0.0


def test_slow_store_lowers_how_full_the_reserve_can_get():
    b = fresh()
    ceiling = b.ceiling
    b.spent = 5 * body.D0
    assert b.ceiling < ceiling


def test_running_away_costs_time_to_turn_round():
    b = fresh()
    towards = b.time_to_cover(10.0, speed_along=6.0)
    standing = b.time_to_cover(10.0)
    away = b.time_to_cover(10.0, speed_along=-6.0)
    assert towards < standing < away
    assert abs(b.distance_in(standing) - 10.0) < 0.01


def test_the_ceiling_follows_spent_however_it_changes():
    """The ceiling is kept between calls; it must still be the slow-store formula for whatever
    `spent` is now, whether running spent it or it was set directly."""
    b = fresh()

    def formula() -> float:
        return body.D0 * fmath.exp(-b.spent / (body.SLOW_SCALE * body.D0))

    assert b.ceiling == formula() == body.D0
    for _ in range(200):
        b.spend(9.0, 2.0, DT)  # hard running spends
        assert b.ceiling == formula()
    b.spent = body.SLOW_SCALE * body.D0  # set directly: the ceiling falls to 1/e of full
    assert b.ceiling == formula() < body.D0 / 2


def reference_time_to_cover(b: body.Body, gap: float, speed_along: float) -> float:
    """time_to_cover as first written: Newton on distance_in, the speed from its own exp."""
    if gap <= 0:
        return 0.0
    brake_t = extra = 0.0
    if speed_along < 0:
        brake_t = -speed_along / body.BRAKE_MAX
        extra = speed_along * speed_along / (2 * body.BRAKE_MAX)
        speed_along = 0.0
    top = b.top_speed()
    u = body.clamp(speed_along, 0.0, top)
    tau = top / b.f0
    target = gap + extra
    t = target / max(top, 1e-6) + tau
    for _ in range(12):
        f = b.distance_in(t, u) - target
        speed = top - (top - u) * fmath.exp(-t / tau)
        step = f / max(speed, 1e-6)
        t -= step
        if abs(step) < 1e-4:
            break
    return brake_t + max(t, 0.0)


def test_time_to_cover_shares_one_exp_and_gives_the_same_bits():
    rng = random.Random(3)
    for _ in range(5000):
        b = body.Body(f0=rng.uniform(4.0, 6.5), v0=rng.uniform(9.0, 11.0), cs=rng.uniform(3.4, 4.4))
        b.spent = rng.uniform(0.0, 10 * body.D0)
        b.reserve = rng.uniform(0.0, b.ceiling)
        gap, along = rng.uniform(-1.0, 60.0), rng.uniform(-8.0, 10.0)
        assert b.time_to_cover(gap, along) == reference_time_to_cover(b, gap, along)
