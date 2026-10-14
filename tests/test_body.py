"""The body model behaves like a footballer's: force-velocity acceleration, stronger braking,
a reserve spent above critical speed and refilled below it, and a slow store that wears down."""

import math

from ninety.sim import body

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


def test_a_tired_player_is_slower():
    b = fresh()
    top_fresh = b.top_speed()
    b.reserve = 0.0
    assert b.top_speed() < top_fresh
    assert b.top_speed() > b.cs  # still faster than jogging pace


def test_slow_store_lowers_how_full_the_reserve_can_get():
    b = fresh()
    ceiling = b.ceiling
    b.spent = 5 * body.D0
    assert b.ceiling < ceiling
