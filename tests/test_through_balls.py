"""D9: passes into space ahead of a team-mate, judged like any pass, never to a man believed offside."""

import math

import pytest

from ninety.sim import decisions as D
from ninety.sim.engine import Engine


@pytest.fixture(autouse=True)
def hand_written_values(monkeypatch):
    """Pin the decision rules, not whatever possession table was last measured."""
    monkeypatch.setattr(D, "POSSESSION", None)


def scene(**kw) -> D.Scene:
    base = dict(x=50.0, y=34.0, goal_x=105.0, mates=[], opponents=[], keeper=None, decisions=0.5,
                composure=0.5, dribbling=0.5, traits=(), risk=0.0)
    base.update(kw)
    return D.Scene(**base)


# Home attacks x = 105. Away's back line at x = 75 (two centre-backs) and the keeper at 103.
BACK_LINE = [(75.0, 28.0), (75.0, 40.0), (103.0, 34.0)]


def test_a_runner_already_moving_gets_there_sooner_than_one_standing():
    assert D.running_time(10.0, 0.0) == D.generic_time(10.0)
    assert D.running_time(10.0, 7.0) < D.running_time(10.0, 3.0) < D.generic_time(10.0)


def test_a_pass_into_space_is_offered_ahead_of_an_onside_team_mate():
    s = scene(mates=[("h10", 72.0, 34.0, 0.0)], opponents=BACK_LINE, keeper=BACK_LINE[-1])
    through = D.through_options(s, s.mates[0])
    assert through and all(o.target[0] > 72.0 and o.receiver == "h10" for o in through)


def test_never_into_space_for_a_team_mate_believed_offside():
    s = scene(mates=[("h10", 80.0, 34.0, 0.0)], opponents=BACK_LINE, keeper=BACK_LINE[-1])
    assert not D.believed_onside(s, 80.0)
    assert D.through_options(s, s.mates[0]) == []
    assert D.believed_onside(s, 74.0)  # level with the line or behind it is onside


def test_in_his_own_half_a_team_mate_is_never_offside():
    """Law 11: an offside position needs the opponents' half (halfway is x = 52.5). A deep line at
    45 m leaves a team-mate at 50 m beyond it but onside; at 55 m he is offside."""
    s = scene(x=30.0, opponents=[(45.0, 30.0), (46.0, 40.0)])
    assert D.believed_onside(s, 50.0)
    assert not D.believed_onside(s, 55.0)


def test_a_run_already_under_way_makes_the_pass_into_space_more_likely_to_arrive():
    mate = ("h10", 72.0, 34.0, 0.0)
    standing = scene(mates=[mate], opponents=BACK_LINE, keeper=BACK_LINE[-1])
    running = scene(mates=[mate], opponents=BACK_LINE, keeper=BACK_LINE[-1],
                    mate_velocity={"h10": (7.0, 0.0)})
    far = lambda s: max(D.through_options(s, mate), key=lambda o: o.target[0])  # noqa: E731
    assert far(running).value > far(standing).value


def test_a_defender_in_the_space_makes_the_pass_into_it_worse():
    mate = ("h10", 72.0, 34.0, 0.0)
    open_space = scene(mates=[mate], opponents=BACK_LINE, keeper=BACK_LINE[-1])
    covered = scene(mates=[mate], opponents=BACK_LINE + [(82.0, 34.0)], keeper=BACK_LINE[-1])
    six = lambda s: next(o for o in D.through_options(s, mate) if math.isclose(o.target[0], 78.0))  # noqa: E731
    assert six(covered).value < six(open_space).value


def test_never_aimed_at_the_goal_line():
    s = scene(x=90.0, mates=[("h10", 98.0, 34.0, 0.0)], opponents=[(99.0, 30.0), (99.0, 38.0)])
    assert all(105.0 - o.target[0] >= D.GOAL_LINE_SPACE_M for o in D.through_options(s, s.mates[0]))


def test_the_carrier_knows_how_his_team_mates_are_moving():
    e = Engine(1)
    carrier, runner = e.by_id["h7"], e.by_id["h10"]
    e.possessor = carrier.id
    from ninety.sim import perception
    e.beliefs[carrier.id].seen[runner.id] = perception.Sighting(70.0, 34.0, 6.0, 1.0, t=e.t)
    assert e.scene_for(carrier).mate_velocity[runner.id] == (6.0, 1.0)


def test_the_carrier_is_offered_passes_into_space_and_not_from_a_throw_in():
    mate = ("h10", 72.0, 34.0, 0.0)
    s = scene(mates=[mate], opponents=BACK_LINE, keeper=BACK_LINE[-1])
    targets = {o.target for o in D.options(s) if o.kind == "pass"}
    assert any(tx > 72.0 + D.THROUGH_LEADS_M[0] - 0.01 for tx, _ in targets)
    thrown = scene(mates=[mate], opponents=BACK_LINE, keeper=BACK_LINE[-1], throw=True)
    assert all(tx < 72.0 + D.THROUGH_LEADS_M[0] for tx, _ in (o.target for o in D.options(thrown)))
