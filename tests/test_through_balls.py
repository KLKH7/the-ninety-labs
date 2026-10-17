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


def test_the_carrier_knows_how_team_mates_and_opponents_are_moving():
    e = Engine(1)
    carrier, runner = e.by_id["h7"], e.by_id["h10"]
    e.possessor = carrier.id
    from ninety.sim import perception
    e.beliefs[carrier.id].seen[runner.id] = perception.Sighting(70.0, 34.0, 6.0, 1.0, t=e.t)
    defender = e.by_id["a4"]
    e.beliefs[carrier.id].seen[defender.id] = perception.Sighting(76.0, 30.0, -2.0, 3.0, t=e.t)
    s = e.scene_for(carrier)
    assert s.mate_velocity[runner.id] == (6.0, 1.0)
    assert (-2.0, 3.0) in s.opponent_velocity and len(s.opponent_velocity) == len(s.opponents)


def test_each_team_mate_is_one_option_aimed_where_it_is_worth_most():
    """Where to put the ball is part of choosing him: one pass per team-mate, never three near-equal
    entries that would win the softmax by being counted three times."""
    mates = [("h10", 72.0, 34.0, 0.0), ("h7", 45.0, 20.0, 0.0)]
    s = scene(mates=mates, opponents=BACK_LINE, keeper=BACK_LINE[-1], mate_velocity={"h10": (7.0, 0.0)})
    passes = [o for o in D.options(s) if o.kind == "pass"]
    assert sorted(o.receiver for o in passes) == ["h10", "h7"]
    best = max([D.pass_option(s, mates[0]), *D.through_options(s, mates[0])], key=lambda o: o.value)
    assert next(o for o in passes if o.receiver == "h10").target == best.target
    assert best.target[0] > 72.0  # a runner with space behind the line is played into it


def test_never_into_space_from_a_throw_in():
    mate = ("h10", 72.0, 34.0, 0.0)
    thrown = scene(mates=[mate], opponents=BACK_LINE, keeper=BACK_LINE[-1], throw=True,
                   mate_velocity={"h10": (7.0, 0.0)})
    assert all(tx < 72.0 + D.THROUGH_LEADS_M[0] for tx, _ in (o.target for o in D.options(thrown)))


def test_a_defender_already_running_into_the_space_is_counted_too():
    """The receiver's run counts, so a defender's run toward the ball's path counts as well."""
    mate, defender = ("h10", 72.0, 34.0, 0.0), (80.0, 40.0)
    base = dict(mates=[mate], opponents=[*BACK_LINE, defender], keeper=BACK_LINE[-1],
                mate_velocity={"h10": (7.0, 0.0)})
    standing = scene(**base, opponent_velocity=[(0.0, 0.0)] * 4)
    closing = scene(**base, opponent_velocity=[(0.0, 0.0)] * 3 + [(0.0, -6.0)])  # toward y = 34
    six = lambda s: next(o for o in D.through_options(s, mate) if math.isclose(o.target[0], 78.0))  # noqa: E731
    assert six(closing).value < six(standing).value


def test_level_with_the_second_last_opponent_is_onside_and_behind_the_ball_is_onside():
    s = scene(x=60.0, opponents=BACK_LINE)
    assert D.believed_onside(s, 75.0)  # level
    assert not D.believed_onside(s, 75.5)
    ahead = scene(x=85.0, opponents=BACK_LINE)
    assert D.believed_onside(ahead, 80.0)  # beyond the line but behind the ball


def test_offside_reads_the_other_way_for_the_away_side():
    """Away attacks x = 0: their second-last defender stands at 30, so 29 is offside, 31 is not."""
    s = scene(x=45.0, goal_x=0.0, opponents=[(30.0, 28.0), (30.0, 40.0), (2.0, 34.0)])
    assert not D.believed_onside(s, 29.0) and D.believed_onside(s, 31.0) and D.believed_onside(s, 30.0)


def test_running_time_matches_the_body_model_integrated_step_by_step():
    """Same reaction and body as generic_time; he keeps v0 while reacting, then accelerates as
    v = vmax - (vmax - v0) exp(-t / tau). Integrated with 1 ms steps."""
    vmax, tau, dt = 9.9, 9.9 / 5.2, 0.001
    for distance, v0 in ((6.0, 3.0), (12.0, 7.0), (20.0, 0.5)):
        x = v0 * D.GENERIC_REACTION_S
        t, v = 0.0, v0
        while x < distance:
            v = vmax - (vmax - v0) * math.exp(-t / tau)
            x += v * dt
            t += dt
        assert math.isclose(D.running_time(distance, v0), D.GENERIC_REACTION_S + t, abs_tol=0.01)
