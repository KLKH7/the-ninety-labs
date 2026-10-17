"""Players act on what they believe, not the truth; the team brain sets shape, never outcomes."""

import math
import random

from ninety.sim import perception
from ninety.sim import team as team_mod
from ninety.sim.team import BLOCKS, TeamBrain


def sees(heading_deg: float, target: tuple[float, float], scanning: bool = False) -> bool:
    belief = perception.Belief(next_scan=0.0 if scanning else 99.0)
    perception.observe(belief, (0.0, 0.0, math.radians(heading_deg)), [("q", *target, 0.0, 0.0)], 1.0,
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
            perception.observe(belief, (0.0, 0.0, 0.0), [("q", dist, 0.0, 0.0, 0.0)], 0.0, rng)
            total += abs(belief.seen["q"].x - dist)
        errors[dist] = total / 200
    assert errors[60.0] > 5 * errors[5.0]


def test_an_unseen_player_is_carried_forward_and_goes_stale():
    belief = perception.Belief()
    belief.seen["q"] = perception.Sighting(10.0, 0.0, 2.0, 0.0, t=0.0)
    assert belief.where("q", 0.5) == (11.0, 0.0)
    assert belief.where("q", 3.0) == belief.where("q", 9.0)  # carried forward at most so long, then held
    assert belief.age("q", 3.0) == 3.0
    assert belief.where("nobody", 3.0) is None


def test_the_defensive_line_holds_its_block_while_the_ball_is_in_front_of_it():
    for team in ("home", "away"):
        own = 0.0 if team == "home" else 105.0
        for block, (lo, hi) in BLOCKS.items():
            brain = TeamBrain(team, block=block)
            for ball_from_goal in (hi + 6.0, 60.0, 100.0):
                brain.update(0.0, False, abs(own - ball_from_goal), {})
                assert lo <= abs(brain.line_x - own) <= hi


def test_a_ball_inside_the_block_pulls_the_line_back_toward_goal():
    for team in ("home", "away"):
        own = 0.0 if team == "home" else 105.0
        brain = TeamBrain(team, block="mid")
        brain.update(0.0, False, abs(own - 3.0), {})  # a corner
        assert abs(brain.line_x - own) == team_mod.LINE_FLOOR_M
        brain.update(0.0, False, abs(own - 20.0), {})
        assert abs(brain.line_x - own) == 20.0 - team_mod.GOAL_SIDE_OF_BALL_M


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


def test_a_team_presses_inside_its_line_of_engagement_or_straight_after_losing_the_ball():
    for team, own in (("home", 0.0), ("away", 105.0)):
        brain = TeamBrain(team, block="low")
        brain.update(0.0, True, 50.0, {})
        brain.update(10.0, False, abs(own - 80.0), {})  # just lost it, far from goal
        assert brain.presses(12.0, abs(own - 80.0))  # counter-press window
        assert not brain.presses(20.0, abs(own - 80.0))  # then they drop off
        assert brain.presses(20.0, abs(own - 30.0))  # inside the low block's line of engagement
    high = TeamBrain("home", block="high")
    high.update(0.0, False, 95.0, {})
    assert high.presses(10.0, 95.0)  # a high block presses everywhere


def test_each_side_draws_its_own_block():
    from ninety.sim.engine import Engine
    blocks = {(Engine(seed).brains["home"].block, Engine(seed).brains["away"].block) for seed in range(30)}
    assert len({b for pair in blocks for b in pair}) == 3 and any(h != a for h, a in blocks)


def test_the_forwards_wait_at_their_line_of_engagement_never_past_the_ball():
    for team, own in (("home", 0.0), ("away", 105.0)):
        brain = TeamBrain(team, block="mid")  # engages 60 m from its goal
        brain.update(0.0, False, abs(own - 95.0), {})  # their keeper's ball
        assert abs(abs(brain.slot("ST", 34.0, 34.0)[0] - own) - 60.0) < 1e-9
        brain.update(1.0, False, abs(own - 56.0), {})  # 4 m inside it: up to the ball, not past it
        assert abs(abs(brain.slot("ST", 34.0, 34.0)[0] - own) - 56.0) < 1e-9
        brain.update(1.0, False, abs(own - 40.0), {})  # deep in our half: the block's own front
        front = abs(brain.line_x - own) + team_mod.LINE_GAPS_M["attack"]
        assert abs(abs(brain.slot("ST", 34.0, 34.0)[0] - own) - front) < 1e-9
        high = TeamBrain(team, block="high")  # engages everywhere, but never stands past the ball
        high.update(0.0, False, abs(own - 80.0), {})
        assert abs(high.slot("ST", 34.0, 34.0)[0] - own) <= 80.0 + 1e-9
        # With the ball 40 m out the midfield screens goal-side of it, still in front of the defence.
        cm = abs(brain.slot("CM", 34.0, 34.0)[0] - own)
        assert cm == 40.0 - team_mod.GOAL_SIDE_OF_BALL_M
        assert cm - abs(brain.line_x - own) >= team_mod.MID_SCREEN_M
        brain.update(2.0, False, abs(own - 95.0), {})  # the ball far away: the usual gap
        assert abs(brain.slot("CM", 34.0, 34.0)[0] - brain.line_x) == team_mod.LINE_GAPS_M["midfield"]


def test_the_back_four_keeps_its_defenders_six_to_eight_metres_apart_and_shuffles_across_together():
    from ninety.sim.team import BACK_FOUR_GAP_M
    assert 6.0 <= BACK_FOUR_GAP_M <= 8.0  # T2: the cited coaching range
    for team, anchors in (("home", {"RB": 10.2, "RCB": 25.8, "LCB": 42.2, "LB": 57.8}),
                          ("away", {"RB": 57.8, "RCB": 42.2, "LCB": 25.8, "LB": 10.2})):
        brain = TeamBrain(team)
        brain.update(0.0, False, 40.0 if team == "home" else 65.0, {})
        for ball_y in (34.0, 45.0):  # the ball inside the line's width
            ys = sorted(brain.slot(role, anchor_y=ay, ball_y=ball_y)[1] for role, ay in anchors.items())
            gaps = [b - a for a, b in zip(ys, ys[1:], strict=False)]
            assert all(abs(g - BACK_FOUR_GAP_M) < 1e-9 for g in gaps), gaps
            centre = sum(ys) / 4
            assert abs(centre - (34.0 + (ball_y - 34.0) * 0.3)) < 1e-9  # the whole line shifts with the ball
        at = {role: brain.slot(role, anchor_y=ay, ball_y=34.0)[1] for role, ay in anchors.items()}
        assert (at["RB"] < 34.0) == (anchors["RB"] < 34.0)  # each on his own side, mirrored for the away team
        assert abs(at["RB"] - 34.0) > abs(at["RCB"] - 34.0)  # full-backs outside their centre-backs
        assert abs(at["LB"] - 34.0) > abs(at["LCB"] - 34.0)
        # The ball gone wide on the right back's side: he goes with it; the other three keep their gaps.
        wide_y = 2.0 if anchors["RB"] < 34.0 else 66.0
        wide = {role: brain.slot(role, anchor_y=ay, ball_y=wide_y)[1] for role, ay in anchors.items()}
        assert wide["RB"] == wide_y
        rest = sorted(wide[r] for r in ("RCB", "LCB", "LB"))
        assert all(abs(b - a - BACK_FOUR_GAP_M) < 1e-9 for a, b in zip(rest, rest[1:], strict=False))
