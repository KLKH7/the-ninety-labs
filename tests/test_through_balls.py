"""D11: passes into space ahead of a team-mate, judged by the same race as any pass (D1).

Ported from #46 (claude/passes-into-space) onto the engine's own pass race: the aims are new, the
judgement of each aim is pass_confidence's, unchanged."""

import math

from ninety.sim import decisions as D
from tests.test_decisions import scene

DEFENCE = [(80.0, 20.0), (80.0, 48.0), (95.0, 34.0)]  # last line at 80 m, a keeper-like deepest man
RUNNER = ("h9", 75.0, 34.0, 0.0, 7.0, 0.0)  # seen running toward goal at 7 m/s


def aims_for(s, mate, monkeypatch):
    """Every spot pass_option weighs for this team-mate."""
    seen = []
    real = D.aimed_pass

    def record(scene_, mid, mx, my, age, tx, ty):
        seen.append((round(tx, 2), round(ty, 2)))
        return real(scene_, mid, mx, my, age, tx, ty)

    monkeypatch.setattr(D, "aimed_pass", record)
    D.pass_option(s, mate)
    return seen


def test_a_pass_into_space_is_weighed_ahead_of_an_onside_team_mate(monkeypatch):
    s = scene(x=60.0, opponents=DEFENCE)
    seen = aims_for(s, RUNNER, monkeypatch)
    assert (75.0 + 6.0, 34.0) in seen and (75.0 + 12.0, 34.0) in seen


def test_never_into_space_for_a_team_mate_who_is_not_running_toward_goal(monkeypatch):
    # render/latest: half of all passes went into space ahead of standing team-mates; the run is
    # what makes the space his. Standing, or running back toward his own goal: only to him.
    s = scene(x=60.0, opponents=DEFENCE)
    for mate in (("h9", 75.0, 34.0, 0.0), ("h9", 75.0, 34.0, 0.0, -7.0, 0.0),
                 ("h9", 75.0, 34.0, 0.0, 0.0, 7.0)):
        assert len(aims_for(s, mate, monkeypatch)) == 1, mate


def test_never_into_space_for_a_team_mate_believed_offside(monkeypatch):
    s = scene(x=60.0, opponents=DEFENCE)
    seen = aims_for(s, ("h9", 85.0, 34.0, 0.0), monkeypatch)  # beyond the second-last (80 m)
    assert seen == [(86.5, 34.0)]  # only to where he is: the O7 step ahead


def test_in_his_own_half_a_team_mate_is_never_offside():
    s = scene(x=20.0, opponents=[(30.0, 30.0), (31.0, 40.0)])
    assert D.believed_onside(s, 45.0)


def test_level_with_the_second_last_opponent_is_onside_and_behind_the_ball_is_onside():
    s = scene(x=70.0, opponents=DEFENCE)
    assert D.believed_onside(s, 80.0)  # level with the second-last
    assert not D.believed_onside(s, 80.5)
    deep = scene(x=90.0, opponents=DEFENCE)
    assert D.believed_onside(deep, 85.0)  # behind the ball


def test_offside_reads_the_other_way_for_the_away_side():
    mirror = [(105 - x, y) for x, y in DEFENCE]
    s = scene(x=45.0, goal_x=0.0, opponents=mirror)
    assert D.believed_onside(s, 25.0) and not D.believed_onside(s, 24.5)


def test_never_aimed_at_the_goal_line(monkeypatch):
    s = scene(x=80.0, opponents=[(97.0, 30.0), (98.0, 38.0)])
    seen = aims_for(s, ("h9", 94.0, 34.0, 0.0, 7.0, 0.0), monkeypatch)
    assert all(105.0 - tx >= D.GOAL_LINE_SPACE_M for tx, _ in seen[1:])
    assert (100.0, 34.0) in seen and (106.0, 34.0) not in seen  # 5 m from the line is fine; past it is not


def test_never_into_space_beyond_a_touchline(monkeypatch):
    s = scene(x=60.0, y=10.0, opponents=DEFENCE)
    seen = aims_for(s, ("h7", 70.0, 0.5, 0.0), monkeypatch)
    assert len(seen) == 1  # believed past the touchline: only the O7 aim, kept on the pitch


def test_never_into_space_from_a_throw_in(monkeypatch):
    s = scene(x=60.0, y=0.5, opponents=DEFENCE, throw=True)
    seen = aims_for(s, ("h9", 70.0, 10.0, 0.0), monkeypatch)
    assert len(seen) == 1  # Law 15: thrown to him


def test_each_team_mate_is_one_option_aimed_where_it_is_worth_most():
    mates = [("h9", 75.0, 34.0, 0.0), ("h10", 70.0, 20.0, 0.0), ("h7", 65.0, 50.0, 0.0)]
    s = scene(x=60.0, opponents=DEFENCE, mates=mates)
    passes = [o for o in D.options(s) if o.kind == "pass"]
    assert len({o.receiver for o in passes}) == len(passes) <= len(mates)
    for o in passes:
        mate = next(m for m in mates if m[0] == o.receiver)
        best = D.pass_option(s, mate)
        assert o.target == best.target and math.isclose(o.value, best.value)


def test_a_defender_in_the_space_makes_the_pass_into_it_worse():
    # The same aim, judged by the engine's race: a defender standing on the spot ruins it.
    mate = ("h9", 75.0, 34.0, 0.0)
    open_space = scene(x=60.0, opponents=DEFENCE, mates=[mate])
    blocked = scene(x=60.0, opponents=[*DEFENCE, (86.0, 34.0)], mates=[mate])
    a = D.aimed_pass(open_space, "h9", 75.0, 34.0, 0.0, 87.0, 34.0)
    b = D.aimed_pass(blocked, "h9", 75.0, 34.0, 0.0, 87.0, 34.0)
    assert a is not None and b is not None and b.value < a.value


def test_a_run_already_under_way_makes_the_pass_into_space_more_likely_to_arrive():
    standing = scene(x=60.0, opponents=DEFENCE, mates=[("h9", 75.0, 34.0, 0.0)])
    running = scene(x=60.0, opponents=DEFENCE, mates=[("h9", 75.0, 34.0, 0.0, 7.0, 0.0)])
    still = D.pass_confidence(standing, 87.0, 34.0, 75.0, 34.0, 0.0, False, D.PASS_PACES[-1], "h9")
    going = D.pass_confidence(running, 87.0, 34.0, 75.0, 34.0, 0.0, False, D.PASS_PACES[-1], "h9")
    assert going > still


def test_the_aim_chosen_for_a_team_mate_is_the_best_of_all_his_aims():
    s = scene(x=60.0, opponents=DEFENCE)
    mate = RUNNER
    o7 = 75.0 + 7.0 * min(D.LEAD_MAX_S, 15.0 / D.PASS_SPEED_EST_MPS)  # O7: led by his run
    aims = [(o7, 34.0), (81.0, 34.0), (87.0, 34.0)]  # O7's lead, then the two leads into space
    s = scene(x=60.0, opponents=DEFENCE, mates=[mate])
    scored = [o for o in (D.aimed_pass(s, "h9", 75.0, 34.0, 0.0, tx, ty) for tx, ty in aims) if o]
    assert len(scored) == 3 and len({round(o.value, 9) for o in scored}) == 3  # they differ
    chosen = D.pass_option(s, mate)
    assert math.isclose(chosen.value, max(o.value for o in scored))
