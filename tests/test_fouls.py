"""Fouls (Law 12): a lunge that arrives with the ball gone and sweeps through the man he went for."""

import pytest

from ninety.sim.engine import Engine


def lunge_scene(victim_y: float):
    """a4 at (60, 34) lunging at the ball at (61, 34); h9 standing at (60.6, victim_y)."""
    e = Engine(3)
    dfd, att = e.by_id["a4"], e.by_id["h9"]
    for p in e.players:
        p.vx = p.vy = 0.0
        if p not in (att, dfd):
            p.x, p.y = (2.0, 2.0) if p.team == "home" else (103.0, 66.0)
    dfd.x, dfd.y = 60.0, 34.0
    att.x, att.y = 60.6, victim_y
    return e, dfd, att


def test_his_leg_meets_a_man_in_its_sweep_and_misses_one_off_it():
    e, dfd, att = lunge_scene(34.0)
    assert e.leg_meets(dfd.x, dfd.y, att.x, att.y, 61.0, 34.0, att.heading)
    e, dfd, att = lunge_scene(35.5)
    assert not e.leg_meets(dfd.x, dfd.y, att.x, att.y, 61.0, 34.0, att.heading)


def test_a_late_lunge_through_the_man_is_a_foul_and_a_free_kick_to_his_side():
    e, dfd, att = lunge_scene(34.0)
    e.possessor = None
    e.ball = (63.0, 34.0, 0.0, 0.0, 0.0, 0.0)  # he moved it on: beyond a foot's reach
    e.lunges[dfd.id] = e.t
    e.lunge_at[dfd.id] = att.id
    e.duels()
    fouls = [ev for ev in e.match.events if ev["type"] == "foul"]
    assert fouls and fouls[0]["player"] == dfd.id and fouls[0]["receiver"] == att.id
    assert e.restart and e.restart.kind == "free_kick" and e.restart.team == att.team


def test_a_lunge_that_misses_the_ball_and_the_man_is_no_foul():
    e, dfd, att = lunge_scene(36.0)
    e.possessor = None
    e.ball = (63.0, 34.0, 0.0, 0.0, 0.0, 0.0)
    e.lunges[dfd.id] = e.t
    e.lunge_at[dfd.id] = att.id
    e.duels()
    assert not [ev for ev in e.match.events if ev["type"] == "foul"]
    assert e.off_balance[dfd.id] > e.t and e.restart is None


def test_no_foul_while_the_ball_is_dead_for_a_restart():
    from ninety.sim.engine import Restart

    e, dfd, att = lunge_scene(34.0)
    e.possessor = None
    e.ball = (63.0, 34.0, 0.0, 0.0, 0.0, 0.0)
    e.restart = Restart("throw_in", "home", 63.0, 0.0, "h2", e.t + 10.0)
    e.lunges[dfd.id] = e.t
    e.lunge_at[dfd.id] = att.id
    e.duels()
    assert not [ev for ev in e.match.events if ev["type"] == "foul"]


def test_a_foul_closes_the_pass_in_flight_and_counts_one_in_his_own_box():
    e, dfd, att = lunge_scene(34.0)
    dfd.x, att.x = 95.0, 95.6  # inside the away side's own box (it defends the goal at x = 105)
    e.possessor = None
    e.ball = (98.0, 34.0, 0.0, 0.0, 0.0, 0.0)
    e.kicked = e.emit("pass", "home", 95.6, 34.0, player=att.id, receiver="h10", outcome=None)
    e.lunges[dfd.id] = e.t
    e.lunge_at[dfd.id] = att.id
    e.duels()
    passes = [ev for ev in e.match.events if ev["type"] == "pass"]
    assert passes[0]["outcome"] == "fail" and e.kicked is None
    assert e.penalties == 1


def test_whether_the_leg_meets_him_depends_on_which_way_he_faces():
    # The leg sweeps along y = 34; he stands 0.2 m off that line (GROUNDING P11: his body is wide
    # across the shoulders and shallow through the chest).
    e, dfd, att = lunge_scene(34.2)
    att.heading = 0.0  # facing along the leg's line: his shoulder is in its way
    assert e.leg_meets(dfd.x, dfd.y, att.x, att.y, 61.0, 34.0, att.heading)
    att.heading = 1.5708  # facing across it: it passes in front of his chest
    assert not e.leg_meets(dfd.x, dfd.y, att.x, att.y, 61.0, 34.0, att.heading)


def test_his_leg_reaches_a_foot_from_his_body_and_no_further():
    # The ball 3 m away along y = 34; h9 stands 1.5 m out on that line, beyond a foot's reach
    # (CONTROL_M): the lunge's leg stops short of him.
    e, dfd, att = lunge_scene(34.0)
    att.x = 61.5
    assert not e.leg_meets(dfd.x, dfd.y, att.x, att.y, 63.0, 34.0, att.heading)
    att.x = 60.6
    assert e.leg_meets(dfd.x, dfd.y, att.x, att.y, 63.0, 34.0, att.heading)


def box_foul():
    """a4 fouls h9 inside the away side's own box (it defends the goal at x = 105)."""
    e, dfd, att = lunge_scene(34.0)
    dfd.x, att.x = 95.0, 95.6
    e.possessor = None
    e.ball = (98.0, 34.0, 0.0, 0.0, 0.0, 0.0)
    e.lunges[dfd.id] = e.t
    e.lunge_at[dfd.id] = att.id
    e.duels()
    return e


def test_a_foul_in_his_own_box_is_a_penalty_from_the_mark_by_the_best_finisher():
    e = box_foul()
    r = e.restart
    assert r.kind == "penalty_kick" and r.team == "home" and (r.x, r.y) == (105.0 - 11.0, 34.0)
    outfield = [q for q in e.players if q.team == "home" and q.role != "GK"]
    best = max(outfield, key=lambda q: q.profile["finishing"])
    assert r.taker == best.id


def test_while_a_penalty_waits_everyone_stands_where_law_14_puts_them():
    from ninety.sim import decisions
    from ninety.sim.engine import PITCH_Y

    e = box_foul()
    r = e.restart
    for p in e.players:
        if p.id == r.taker:
            continue
        x, y = e.penalty_wait_spot(p)
        if p.role == "GK" and p.team == "away":
            assert (x, y) == (105.0, PITCH_Y / 2)
            continue
        assert not decisions.in_box(x, y, 105.0)
        assert ((x - r.x) ** 2 + (y - r.y) ** 2) ** 0.5 >= 9.15
        assert x <= r.x  # behind the mark


def test_when_the_penalty_is_taken_he_shoots_from_the_mark():
    e = box_foul()
    r = e.restart
    taker = e.by_id[r.taker]
    taker.x, taker.y, taker.heading = r.x - 0.9, r.y, 0.0  # in reach of the mark, not on it
    e.t = r.ready_at
    e.decide = lambda *a, **k: None  # only Law 14 may make him shoot
    for _ in range(25):
        e.step()
        if any(ev["type"] == "shot" for ev in e.match.events):
            break
    shots = [ev for ev in e.match.events if ev["type"] == "shot"]
    assert shots and shots[0]["player"] == taker.id and abs(shots[0]["x"] - r.x) < 0.05
    assert ((taker.x - r.x) ** 2 + (taker.y - r.y) ** 2) ** 0.5 < 0.4  # stepped up: struck at his foot


def test_a_taker_facing_away_turns_to_the_goal_before_he_strikes_the_penalty():
    """P16: the ball on the mark is at his feet, not in his hands, so he faces the goal to strike it;
    nobody may challenge him first (Law 14), so he squares up to it rather than strike it at 60°."""
    import math

    from ninety.sim.engine import DT, TURN_RATE

    e = box_foul()
    r = e.restart
    taker = e.by_id[r.taker]
    taker.x, taker.y, taker.heading = r.x, r.y, math.pi  # on the mark, his back to the goal
    e.t = r.ready_at
    e.decide = lambda *a, **k: None  # only Law 14 may make him shoot
    heading_at_shot = None
    keeper, other = e.keeper("away"), e.by_id["a4"]
    for _ in range(4 * 25):
        e.step()
        if e.placed:  # placed, not yet kicked: Law 14 still holds everyone else
            assert e.shape_target(keeper)[:2] == (105.0, 34.0)
            assert e.shape_target(other)[:2] == e.penalty_wait_spot(other)
        if any(ev["type"] == "shot" for ev in e.match.events):
            heading_at_shot = taker.heading
            break
    assert heading_at_shot is not None
    shot = next(ev for ev in e.match.events if ev["type"] == "shot")
    assert (shot["x"], shot["y"]) == (r.x, r.y)  # Law 14: from the mark, the ball unmoved by his turn
    to_goal = math.atan2(34.0 - r.y, 105.0 - r.x)  # from the mark to the middle of the goal
    off = abs((heading_at_shot - to_goal + math.pi) % (2 * math.pi) - math.pi)
    assert off <= TURN_RATE * DT + 1e-9  # square to it, to one frame's turn


def law14(e, taker, keeper):
    """Everyone else where Law 14 puts them, as the wait before the kick would (out of the area,
    behind the mark, 9.15 m from it)."""
    for q in e.players:
        if q is not taker and q is not keeper:
            q.x, q.y = e.penalty_wait_spot(q)
            q.vx = q.vy = 0.0


def test_at_a_penalty_the_keeper_commits_at_the_strike_the_way_he_read_it():
    """A2: he must commit before he can react to the ball, so he dives the way he read it, even
    when the kick goes the other way, and has no second dive at the same kick."""
    from ninety.sim.engine import DT

    e = box_foul()
    r = e.restart
    taker, keeper = e.by_id[r.taker], e.keeper("away")
    taker.x, taker.y, taker.heading = r.x - 0.3, r.y, 0.0  # behind the ball, facing goal
    keeper.x, keeper.y, keeper.vx, keeper.vy = 105.0, 34.0, 0.0, 0.0  # on his line (Law 14)
    law14(e, taker, keeper)
    e.t = r.ready_at
    e.decide = lambda *a, **k: None
    e.keeper_read = lambda k, c, aim: 34.0 - 3.0 if aim > 34.0 else 34.0 + 3.0  # always the wrong way
    dives, struck_at = [], None
    for _ in range(3 * 25):
        e.step()
        if struck_at is None and any(ev["type"] == "shot" for ev in e.match.events):
            struck_at = e.kicked_at
        if e.dive and (not dives or dives[-1] != e.dive[:2]):
            dives.append(e.dive[:2])
            aim_side = 1.0 if e.ball[4] > 0 else -1.0  # the way the kick is going across the goal
            assert e.dive[3] * aim_side < 0  # the way he read it, not the way it went
    assert struck_at is not None and len(dives) == 1  # one dive, never a second at the same kick
    assert dives[0][1] - struck_at <= 2 * DT  # at the strike, not after reacting (0.32 s or more)
    from ninety.sim.engine import PENALTY_DIVE_LEAD_S

    assert dives[0][1] < struck_at  # set off just before it
    assert dives[0][1] == pytest.approx(struck_at - PENALTY_DIVE_LEAD_S)
    assert keeper.profile.reaction() > 2 * DT


def test_a_keeper_who_reads_a_penalty_down_the_middle_stays_there():
    """A2: committing to the middle is staying put; he does not dive later at the same kick, even
    at one going wide of him."""
    import random

    from ninety.sim import offball

    wide = 0
    for k in range(10):
        e = box_foul()
        r = e.restart
        taker, keeper = e.by_id[r.taker], e.keeper("away")
        taker.x, taker.y, taker.heading = r.x - 0.3, r.y, 0.0
        keeper.x, keeper.y, keeper.vx, keeper.vy = 105.0, 34.0, 0.0, 0.0  # on his line (Law 14)
        law14(e, taker, keeper)
        e.t = r.ready_at
        e.rng = random.Random(k)
        e.decide = lambda *a, **k: None
        e.keeper_read = lambda k, c, aim: k.y  # read on the spot where he stands
        cross = None
        for _ in range(3 * 25):
            e.step()
            assert not (e.dive and e.dive[0] == keeper.id)
            if cross is None and e.kicked and e.kicked["type"] == "shot":
                arrival = e.ball_at_x(keeper.x)
                cross = arrival[1] if arrival else 34.0
        wide += abs(cross - 34.0) > offball.arm_reach_m(10.0)  # beyond his arms at full stretch
    assert wide  # some went beyond his reach standing, and still he did not dive


def test_in_open_play_the_keeper_dives_only_once_he_has_reacted():
    """A2, P15: only a penalty is committed to before the strike; any other shot he reacts to."""
    from ninety.sim.engine import DT
    from ninety.sim.saves import shoot_once

    dives = []
    real = __import__("ninety.sim.engine", fromlist=["Engine"]).Engine.keeper_dive

    def spy(self, p):
        moved = real(self, p)
        if self.dive and self.dive[0] == p.id and not dives:
            dives.append(self.dive[1] - self.kicked_at - self.reaction(p))
        return moved
    import ninety.sim.engine as en
    en.Engine.keeper_dive = spy
    try:
        for seed in range(6):
            shoot_once(seed, 16, "line")
    finally:
        en.Engine.keeper_dive = real
    assert dives and all(late >= -DT / 2 for late in dives)


def test_in_his_own_box_a_lunge_through_the_man_needs_a_surer_win():
    from ninety.sim.engine import COMMIT_P

    e, dfd, att = lunge_scene(34.0)
    dfd.x, att.x = 95.0, 95.6  # behind him, the ball beyond: the man is in his line
    line = e.foul_line(dfd, att, 96.0, 34.0)
    assert line > COMMIT_P
    dfd.x, att.x = 45.0, 45.6  # the same challenge in midfield: a miss is a free kick there
    assert e.foul_line(dfd, att, 46.0, 34.0) == 0.0
    dfd.x, dfd.y, att.x, att.y = 96.0, 36.0, 95.6, 34.0  # in the box, from in front and wide,
    e.dribble_to = (100.0, 34.0)  # the man carrying it on, not holding it
    assert e.foul_line(dfd, att, 96.0, 34.0) == 0.0


def test_he_foresees_the_man_running_on_into_his_lunge():
    e, dfd, att = lunge_scene(34.0)
    dfd.x, dfd.y = 95.5, 34.6  # beside him: his leg to the ball misses the man as they stand
    att.x, att.y, att.vx = 95.5, 34.0, 0.0
    e.dribble_to = (100.0, 34.0)  # carrying it, so not shielding it from him
    assert not e.leg_meets(dfd.x, dfd.y, att.x, att.y, 95.87, 34.0, att.heading)
    assert e.foul_line(dfd, att, 95.87, 34.0) == 0.0  # standing still: no risk
    att.vx = 5.0  # running on toward goal with it: by the time his foot arrives, the man is there
    assert e.foul_line(dfd, att, 95.87, 34.0) > 0.0


def test_at_a_penalty_the_keeper_guesses_the_side_about_as_often_as_keepers_do():
    import random

    from ninety.sim.engine import PENALTY_CORRECT_SIDE, PENALTY_SIDE_AIM_M, PENALTY_STAYS, SHOT_AIM_OFF_M

    e = box_foul()
    keeper, taker = e.keeper("away"), e.by_id[e.restart.taker]
    keeper.x, keeper.y, keeper.heading = 105.0, 34.0, 3.14159  # on his line, facing the kicker
    taker.x, taker.y = 93.6, 34.0
    e.rng = random.Random(5)

    def right_side(restart_kind, aims):
        e.from_restart = restart_kind
        n = right = stays = 0
        for _ in range(4000):
            aim = 34.0 + random.choice([-1, 1]) * random.uniform(*aims)
            read = e.keeper_read(keeper, taker, aim)
            if read == keeper.y:  # stays where he stands
                stays += 1
                continue
            n += 1
            right += (read - 34.0) * (aim - 34.0) > 0
        return right / n, stays / 4000

    right, stays = right_side("penalty_kick", PENALTY_SIDE_AIM_M)
    assert abs(right - PENALTY_CORRECT_SIDE) < 0.03  # of the dives on kicks to a side (Bar-Eli, 113 of 196)
    assert abs(stays - PENALTY_STAYS) < 0.015  # stayed in the middle (18 of 286)
    right, stays = right_side(None, SHOT_AIM_OFF_M)
    assert right > 0.75 and stays == 0  # open play keeps his own read, and he never just stays


def test_he_foresees_a_holding_man_shielding_it_from_him():
    e, dfd, att = lunge_scene(34.0)
    dfd.x, dfd.y = 95.5, 34.6
    att.x, att.y, att.vx = 95.5, 34.0, 0.0
    e.dribble_to = (100.0, 34.0)
    carrying = e.foul_line(dfd, att, 95.87, 34.0)
    e.dribble_to = None  # holding: the ball goes to his far side from the defender
    assert carrying == 0.0 and e.foul_line(dfd, att, 95.87, 34.0) > 0.0
