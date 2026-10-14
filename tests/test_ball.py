"""Ball physics behaves like a ball, and each kick solver hits what it was asked to."""

import math

from ninety.sim import ball

DT = 1 / 25


def test_dropped_ball_bounces_lower_each_time_then_rests():
    path = ball.predict((0, 0, 2.0, 0, 0, 0), DT, 10)
    peaks, rising = [], False
    for prev, cur in zip(path, path[1:], strict=False):
        if prev[5] > 0 and cur[5] <= 0:
            peaks.append(cur[2])
        rising = cur[5] > 0
    assert len(peaks) >= 2 and all(a > b for a, b in zip(peaks, peaks[1:], strict=False))
    assert peaks[0] < 2.0 * ball.RESTITUTION**2 * 1.05  # bounce height scales with restitution²
    assert path[-1][2] == 0 and not rising


def test_rolling_ball_slows_and_stops():
    path = ball.predict((0, 0, 0, 10, 0, 0), DT, 20)
    speeds = [math.hypot(s[3], s[4]) for s in path]
    assert all(a >= b for a, b in zip(speeds, speeds[1:], strict=False))
    assert speeds[-1] == 0


def test_ground_pass_arrives_at_the_requested_speed():
    for distance, arrive in ((10, 4), (25, 6)):
        v0 = ball.ground_pass(distance, arrive, DT)
        for s in ball.predict((0, 0, 0, v0, 0, 0), DT, 10):
            if s[0] >= distance:
                assert abs(math.hypot(s[3], s[4]) - arrive) < 0.5
                break
        else:
            raise AssertionError("pass never arrived")


def test_lofted_pass_lands_at_the_distance():
    vx, vz = ball.lofted_pass(35, 35, DT)
    path = ball.predict((0, 0, 0, vx, 0, vz), DT, 10)
    landing = next(s for s in path[1:] if s[2] == 0)
    assert abs(landing[0] - 35) < 1.0


def test_shot_is_at_the_aimed_height_when_it_reaches_the_goal():
    vx, vz = ball.shot(20, 30, 1.5, DT)
    at_goal = next(s for s in ball.predict((0, 0, 0, vx, 0, vz), DT, 5) if s[0] >= 20)
    assert abs(at_goal[2] - 1.5) < 0.2
    assert abs(math.hypot(vx, vz) - 30) < 0.01
