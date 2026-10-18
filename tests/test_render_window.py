"""The renderer's clip window (ninety.render.clip.choose_start): seeded, and never a dead ball off
camera for the whole clip."""

import random

from ninety.render.clip import FPS, WARMUP, choose_start
from ninety.render.params import sample_params


def frames_with_ball(on_pitch, length=300 * FPS):
    """One frame per index; the ball on the pitch where on_pitch(i), else behind a goal line."""
    return [{"ball": {"x": 52.5 if on_pitch(i) else 109.0, "y": 34.0, "z": 0.0}} for i in range(length)]


def test_a_window_with_the_ball_on_the_pitch_is_the_seeded_draw_unchanged():
    p = sample_params(7, occlusion="natural")
    start = choose_start(frames_with_ball(lambda i: True), p, 50, 7, 10.0, 240.0)
    assert start == random.Random("window-7").randint(max(int(10.0 * FPS), WARMUP), int(240.0 * FPS))


def test_a_window_where_the_ball_is_off_the_pitch_throughout_is_redrawn():
    p = sample_params(7, occlusion="natural")
    first = random.Random("window-7").randint(max(int(10.0 * FPS), WARMUP), int(240.0 * FPS))
    off = range(first - 100, first + 150)  # a dead ball behind the goal around the first draw
    start = choose_start(frames_with_ball(lambda i: i not in off), p, 50, 7, 10.0, 240.0)
    assert start != first
    assert start + 50 <= off.start or start >= off.stop - 49  # some of the window has the ball on the pitch
