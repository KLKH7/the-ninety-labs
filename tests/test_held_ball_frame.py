"""P17: a ball in a keeper's hands or at a player's feet never passes through the goal frame.

Found on render/latest: a keeper caught a ball over the bar beside the post (its centre just past
the goal line, so still in play) and the held ball dropped straight to his feet through the post."""

import math

from ninety.sim import ball
from ninety.sim.engine import DT, PITCH_X, POST_RADIUS, Engine, frame_gap

TOUCHING = ball.RADIUS + POST_RADIUS


def keeper_holding(bx: float, by: float, bz: float) -> tuple[Engine, object]:
    e = Engine(32)
    k = e.by_id["a1"]  # the away keeper defends the goal at x = 105 in the first half
    for q in e.players:
        q.vx = q.vy = 0.0
        if q is not k:
            q.x, q.y = 60.0, 34.0  # nobody near
    k.x, k.y, k.heading = 104.4, 30.6, math.pi
    e.possessor = e.last_touch = k.id
    e.restart = None
    e.ball = (bx, by, bz, 0.0, 0.0, 0.0)
    return e, k


def closest_to_frame(e: Engine, frames: int) -> float:
    worst = math.inf
    for _ in range(frames):
        e.tick_carrier()
        e.t += DT
        b = e.ball
        worst = min(worst, frame_gap((b[0], b[1], b[2] + ball.RADIUS), PITCH_X)[0])
    return worst


def test_a_ball_caught_over_the_bar_beside_the_post_comes_down_on_his_side_of_it():
    # Caught as in the match: just past the line, above the bar, a ball's width from the post.
    e, k = keeper_holding(105.07, 30.16, 2.8)
    assert closest_to_frame(e, 50) >= TOUCHING - 1e-6
    assert e.ball[2] == 0.0 and e.ball[0] < PITCH_X  # at his feet, on the pitch


def test_a_held_ball_away_from_the_frame_settles_as_before():
    # Nowhere near the goal: the straight drop to his feet is untouched (no detour, no delay).
    e, _ = keeper_holding(100.0, 34.0, 2.0)
    before = e.ball
    e.tick_carrier()
    assert e.ball[2] < before[2]  # it came down this frame
