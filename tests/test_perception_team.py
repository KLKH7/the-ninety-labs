"""Players act on what they believe, not the truth; the team brain sets shape, never outcomes."""

import math
import random

from ninety.sim import perception
from ninety.sim.team import BLOCKS, TeamBrain


def sees(heading_deg: float, target: tuple[float, float], scanning: bool = False) -> bool:
    belief = perception.Belief(next_scan=0.0 if scanning else 99.0)
    vx, vy = math.cos(math.radians(heading_deg)) * 5, math.sin(math.radians(heading_deg)) * 5
    perception.observe(belief, (0.0, 0.0, vx, vy), [("q", *target, 0.0, 0.0)], (50, 0), 1.0,
                       random.Random(1))
    return "q" in belief.seen


def test_a_player_sees_in_front_but_not_behind_unless_he_scans():
    assert sees(0, (20.0, 0.0))
    assert not sees(0, (-20.0, 0.0))
    assert sees(0, (-20.0, 0.0), scanning=True)


def test_anyone_very_close_is_noticed_whichever_way_he_faces():
    assert sees(0, (-2.0, 0.0))


def test_a_far_sighting_is_less_accurate_than_a_near_one():
    errors = {}
    for dist in (5.0, 60.0):
        rng, total = random.Random(3), 0.0
        for _ in range(200):
            belief = perception.Belief(next_scan=0.0)
            perception.observe(belief, (0.0, 0.0, 0.0, 0.0), [("q", dist, 0.0, 0.0, 0.0)], (1, 0), 0.0, rng)
            total += abs(belief.seen["q"].x - dist)
        errors[dist] = total / 200
    assert errors[60.0] > 5 * errors[5.0]


def test_an_unseen_player_is_carried_forward_and_goes_stale():
    belief = perception.Belief()
    belief.seen["q"] = perception.Sighting(10.0, 0.0, 2.0, 0.0, t=0.0)
    assert belief.where("q", 3.0) == (16.0, 0.0)
    assert belief.age("q", 3.0) == 3.0
    assert belief.where("nobody", 3.0) is None


def test_the_brain_marks_a_transition_then_settles():
    brain = TeamBrain("home")
    brain.update(10.0, True, 50.0, {})
    assert brain.phase(11.0) == "attack_transition"
    assert brain.phase(20.0) == "attack"


def test_the_defensive_line_stays_inside_its_block():
    for block, (lo, hi) in BLOCKS.items():
        brain = TeamBrain("home", block=block)
        for ball_x in (5.0, 50.0, 100.0):
            brain.update(0.0, False, ball_x, {})
            assert lo <= brain.line_x <= hi


def test_the_quickest_to_the_ball_presses_and_the_next_covers():
    brain = TeamBrain("away")
    brain.update(0.0, False, 50.0, {"a7": 1.2, "a4": 0.6, "a9": 2.0})
    assert brain.pressers == ["a4", "a7"]
    brain.update(1.0, True, 50.0, {"a7": 1.2, "a4": 0.6})
    assert brain.pressers == []  # nobody presses with the ball


def test_out_of_possession_the_shape_is_narrower_and_shifts_to_the_ball():
    brain = TeamBrain("home")
    brain.update(0.0, False, 40.0, {})
    wide = brain.slot("RB", anchor_y=10.0, ball_y=34.0)
    toward_ball = brain.slot("RB", anchor_y=10.0, ball_y=60.0)
    assert wide[1] > 10.0  # squeezed toward the centre
    assert toward_ball[1] > wide[1]  # and shifted toward the ball
    assert brain.slot("GK", 34.0, 34.0) is None
