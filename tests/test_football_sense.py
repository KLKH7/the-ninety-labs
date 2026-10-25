"""Football sense: each defect type gets a small hand-made scene that must be flagged and legal
scenes that must not be. IDs match docs/GROUNDING.md (FS1 to FS9)."""

import json
import math

from ninety.eval import football_sense as fs

FPS = 25


def still(x, y):
    return lambda f: (x, y)


def moving(x, y, vx, vy, start=0):
    """At (x, y) until frame `start`, then at a constant velocity in m/s."""
    return lambda f: (x + vx * max(f - start, 0) / FPS, y + vy * max(f - start, 0) / FPS)


KEEPERS = {"h1": ("home", "GK", still(5.0, 34.0)), "a1": ("away", "GK", still(100.0, 34.0))}


def ev(frame, type_, team, player=None, x=50.0, y=34.0, **kw):
    return {"id": f"e{frame}{type_}", "t": frame / FPS, "frame": frame, "type": type_, "team": team,
            "player": player, "x": x, "y": y, "source": "truth", **kw}


def scene(players, ball, n, events, possessor=lambda f: None):
    """A match from per-frame functions: players {id: (team, role, f -> (x, y))}, ball f -> (x, y, z)."""
    frames = []
    for f in range(n):
        bx, by, bz = ball(f)
        frames.append({
            "frame": f, "t": f / FPS, "ball": {"x": bx, "y": by, "z": bz}, "possessor": possessor(f),
            "players": [{"id": pid, "team": team, "role": role, "x": pos(f)[0], "y": pos(f)[1]}
                        for pid, (team, role, pos) in players.items()],
        })
    return fs.build(frames, events, {"fps": FPS})


def rolling(x, y, vx, vy, start=0):
    return lambda f: (*moving(x, y, vx, vy, start)(f), 0.0)


# --- FS1 chaser runs away from a loose ball -------------------------------------------------------

def loose_ball_scene(chaser_vx, chaser_vy, extra=None, events=None):
    """h4's touch comes off him (a deflection) and the ball rolls on at 2 m/s; h7 stands beside it,
    then from frame 10 runs at the given velocity."""
    players = {**KEEPERS, "h4": ("home", "LCB", still(40.0, 20.0)),
               "h7": ("home", "CM", moving(51.0, 34.0, chaser_vx, chaser_vy, start=10)),
               "a7": ("away", "CM", still(70.0, 50.0)), **(extra or {})}
    evs = events or [ev(0, "pass", "home", "h4", 40, 20, end_x=50, end_y=34, outcome="success"),
                     ev(5, "deflection", "home", "h4", 50, 34)]
    return scene(players, rolling(50.0, 34.0, 2.0, 0.0, start=5), 60, evs)


def test_fs1_chaser_running_away_from_a_loose_ball_is_flagged():
    found = fs.chaser_moves_away(loose_ball_scene(0.0, 5.0))
    assert [f.player for f in found] == ["h7"]


def test_fs1_chaser_going_to_the_ball_passes():
    assert fs.chaser_moves_away(loose_ball_scene(1.5, 0.0)) == []


def test_fs1_a_ball_flying_over_his_head_passes():
    players = {**KEEPERS, "h4": ("home", "LCB", still(40.0, 20.0)),
               "h7": ("home", "CM", moving(51.0, 34.0, 0.0, 5.0, start=10))}
    evs = [ev(0, "pass", "home", "h4", 40, 20, end_x=50, end_y=34), ev(5, "deflection", "home", "h4", 50, 34)]
    high = lambda f: (50.0 + 2.0 * max(f - 5, 0) / FPS, 34.0, 3.0)  # noqa: E731
    assert fs.chaser_moves_away(scene(players, high, 60, evs)) == []


def test_fs1_kicker_leaving_his_own_kick_passes():
    # h7's pass goes astray and nobody takes it: walking off his own kick is not running from it.
    players = {**KEEPERS, "h7": ("home", "CM", moving(50.5, 34.0, 0.0, 5.0, start=2))}
    evs = [ev(0, "pass", "home", "h7", 50, 34, end_x=58, end_y=34, outcome="fail", intended="h9")]
    assert fs.chaser_moves_away(scene(players, rolling(50.0, 34.0, 2.0, 0.0), 60, evs)) == []


def test_fs1_a_pass_in_flight_is_not_a_loose_ball():
    # The same movement while a completed pass goes past him to a team-mate: he is not its chaser.
    evs = [ev(5, "pass", "home", "h4", 50, 34, end_x=60, end_y=34, outcome="success", receiver="h8")]
    assert fs.chaser_moves_away(loose_ball_scene(0.0, 5.0, events=evs)) == []


def test_fs1_braking_out_of_a_run_is_not_running_away():
    # Sprinting away at 6 m/s as the ball comes loose at frame 5, then braking at 8.5 m/s2 (P2): he
    # still drifts on almost 2 m, which is physics, not a choice.
    def run(f):
        tau = (f - 5) / FPS
        if tau <= 0:
            return 51.0, 34.0 + 6.0 * tau
        tau = min(tau, 6.0 / 8.5)
        return 51.0, 34.0 + 6.0 * tau - 4.25 * tau * tau

    players = {**KEEPERS, "h4": ("home", "LCB", still(40.0, 20.0)), "h7": ("home", "CM", run)}
    evs = [ev(0, "pass", "home", "h4", 40, 20, end_x=50, end_y=34), ev(5, "deflection", "home", "h4", 50, 34)]
    m = scene(players, rolling(50.0, 34.0, 0.0, 0.0), 60, evs)
    assert m.loose[6]
    assert fs.chaser_moves_away(m) == []


def test_fs1_offside_player_keeping_away_passes():
    # h7's team-mate played it, and h7 stands beyond the last defender in the opponents' half.
    players = {**KEEPERS, "h4": ("home", "LCB", still(40.0, 20.0)),
               "h7": ("home", "ST", moving(91.0, 34.0, 0.0, 5.0, start=10)),
               "a4": ("away", "CB", still(80.0, 20.0))}
    evs = [ev(0, "pass", "home", "h4", 40, 20, end_x=90, end_y=34, outcome="fail"),
           ev(5, "deflection", "away", "a4", 88, 34)]
    m = scene(players, rolling(90.0, 34.0, -2.0, 0.0, start=5), 60, evs)
    assert fs.chaser_moves_away(m) == []
    m.attack = {"home": -1.0, "away": 1.0}  # the same run, onside the other way round, is flagged
    assert [f.player for f in fs.chaser_moves_away(m)] == ["h7"]


# --- FS2 unpressed pass out of play ---------------------------------------------------------------

def out_scene(opponent_at, touch=False, controlled=False):
    players = {**KEEPERS, "h7": ("home", "CM", still(50.0, 60.0)), "a7": ("away", "CM", still(*opponent_at))}
    evs = [ev(0, "pass", "home", "h7", 50, 60, end_x=50, end_y=68, outcome="fail", intended="h11")]
    if touch:
        evs.append(ev(10, "deflection", "away", "a7", 50, 64))
    evs.append(ev(20, "out_of_play", "home", None, 50, 68))
    return scene(players, rolling(50.0, 60.0, 0.0, 10.0), 30, evs,
                 possessor=lambda f: "h7" if f == 0 or (controlled and f == 10) else None)


def test_fs2_unpressed_pass_into_touch_is_flagged():
    found = fs.pass_out_unpressed(out_scene((70.0, 40.0)))
    assert [f.player for f in found] == ["h7"] and "touchline" in found[0].detail


def test_fs2_pass_out_under_pressure_passes():
    assert fs.pass_out_unpressed(out_scene((52.0, 60.0))) == []


def test_fs2_pass_controlled_on_the_way_out_passes():
    assert fs.pass_out_unpressed(out_scene((70.0, 40.0), controlled=True)) == []


def test_fs2_pass_touched_on_the_way_out_passes():
    assert fs.pass_out_unpressed(out_scene((70.0, 40.0), touch=True)) == []


# --- FS3 keeper stays home ------------------------------------------------------------------------

def through_ball_scene(keeper=None, defender=None, ball=None, possessor=lambda f: None):
    """a9's pass rolls toward the home goal at 4 m/s; a9 chases from 2 m behind and 6 m wide. The
    keeper, at the edge of his area, would meet it about 0.4 s before him."""
    players = {"h1": ("home", "GK", keeper or still(16.0, 34.0)), "a1": KEEPERS["a1"],
               "h4": ("home", "LCB", defender or still(60.0, 10.0)), "a9": ("away", "ST", still(34.0, 40.0))}
    evs = [ev(0, "pass", "away", "a9", 34, 40, end_x=12, end_y=34, outcome="fail", intended="a10")]
    return scene(players, ball or rolling(32.0, 34.0, -4.0, 0.0), 130, evs, possessor)


def test_fs3_keeper_who_would_win_the_race_and_stays_is_flagged():
    found = fs.keeper_stays_home(through_ball_scene())
    assert [f.player for f in found] == ["h1"]


def test_fs3_keeper_who_comes_out_passes():
    # He comes at 5 m/s and gathers it where they meet, 1.78 s in.
    meet = 16 / 9 * FPS
    keeper = lambda f: (16.0 + 5.0 * min(f, meet) / FPS, 34.0)  # noqa: E731
    ball = lambda f: (32.0 - 4.0 * min(f, meet) / FPS, 34.0, 0.0)  # noqa: E731
    m = through_ball_scene(keeper=keeper, ball=ball, possessor=lambda f: "h1" if f >= meet else None)
    assert fs.keeper_stays_home(m) == []


def test_fs3_keeper_who_takes_it_where_he_stands_passes():
    # A slower attacker and a 5 m/s ball: the keeper stays, but it reaches him and he takes it.
    ball = lambda f: (32.0 - 5.0 * min(f, 3 * FPS) / FPS, 34.0, 0.0)  # noqa: E731
    took = through_ball_scene(ball=ball, possessor=lambda f: "h1" if f >= 3 * FPS else None)
    assert fs.keeper_stays_home(took) == []
    loose = through_ball_scene(ball=ball)  # the same, but the ball stops short of him
    assert [f.player for f in fs.keeper_stays_home(loose)] == ["h1"]


def test_fs3_defender_covering_lets_the_keeper_hold():
    assert fs.keeper_stays_home(through_ball_scene(defender=still(24.0, 34.0))) == []


# --- FS4 static team ------------------------------------------------------------------------------

def squad(team, still_count, x0, holder=None):
    """A team's ten outfield players in a row; the first `still_count` stand, the rest jog."""
    out = {}
    s = "h" if team == "home" else "a"
    for k in range(10):
        pid = f"{s}{k + 2}"
        y = 4.0 + 6.5 * k
        jog = moving(x0, y, 0.0, 2.0 if y < 34 else -2.0)
        out[pid] = (team, "CM", still(x0, y) if k < still_count else jog)
    return out


def test_fs4_counts_still_players_of_each_team():
    players = {**KEEPERS, **squad("home", 4, 30.0), **squad("away", 10, 70.0)}
    m = scene(players, lambda f: (30.0, 4.0, 0.0), 6 * FPS,
              [ev(0, "pass", "home", "h2", 30, 4, end_x=30, end_y=4)], possessor=lambda f: "h2")
    with_ball, without, n = fs.static_team(m)
    assert n == 3 * FPS  # six seconds less the three after the restart
    assert with_ball[4] == n and without[10] == n


# --- FS5 bunching ---------------------------------------------------------------------------------

def bunch_scene(near_each, start_restart=0):
    """near_each players of each team within 8 m of the ball, the rest spread out."""
    players = dict(KEEPERS)
    for s, team, x0 in (("h", "home", 30.0), ("a", "away", 75.0)):
        for k in range(10):
            pid = f"{s}{k + 2}"
            if k < near_each:
                a = 2 * math.pi * k / near_each + (0.3 if s == "a" else 0.0)
                players[pid] = (team, "CM", still(52.5 + 8 * math.cos(a), 34.0 + 8 * math.sin(a)))
            else:
                players[pid] = (team, "CM", still(x0, 4.0 + 7.0 * k))
    return scene(players, lambda f: (52.5, 34.0, 0.0), 6 * FPS,
                 [ev(start_restart, "pass", "home", "h2", 52.5, 34.0)])


def test_fs5_more_than_half_the_outfield_round_the_ball_is_flagged():
    found = fs.bunching(bunch_scene(6))
    assert len(found) == 1 and found[0].detail.startswith("12 outfield players")


def test_fs5_half_the_outfield_round_the_ball_passes():
    assert fs.bunching(bunch_scene(5)) == []


def test_fs5_a_clump_at_a_restart_passes():
    # The restart at 3.2 s: the clump is inside the restart grace until the scene ends.
    assert fs.bunching(bunch_scene(6, start_restart=80)) == []


# --- FS6 own-box recycling ------------------------------------------------------------------------

def box_passes(spots):
    players = {**KEEPERS, "h3": ("home", "RCB", still(8.0, 26.0)), "h4": ("home", "LCB", still(8.0, 42.0))}
    evs = [ev(0, "kickoff", "home", "h10", 52.5, 34.0)]
    for k, ((x, y), (ex, ey)) in enumerate(spots):
        evs.append(ev(10 + 20 * k, "pass", "home", "h3" if k % 2 == 0 else "h4", x, y, end_x=ex, end_y=ey,
                      outcome="success", receiver="h4" if k % 2 == 0 else "h3"))
    return scene(players, lambda f: (8.0, 26.0, 0.0), 100, evs)


def test_fs6_three_passes_inside_own_box_are_flagged():
    m = box_passes([((8, 26), (8, 42)), ((8, 42), (8, 26)), ((8, 26), (8, 42))])
    passes = fs.own_box_passes(m)
    assert len(passes) == 3 and len(fs.own_box_recycling(m, passes)) == 1


def test_fs6_a_pass_out_of_the_box_passes():
    m = box_passes([((8, 26), (30, 42)), ((8, 42), (8, 26))])
    passes = fs.own_box_passes(m)
    assert len(passes) == 1 and fs.own_box_recycling(m, passes) == []


def test_fs6_two_passes_inside_own_box_are_not_recycling():
    m = box_passes([((8, 26), (8, 42)), ((8, 42), (8, 26))])
    passes = fs.own_box_passes(m)
    assert len(passes) == 2 and fs.own_box_recycling(m, passes) == []


def test_fs6_passes_in_the_opponents_box_pass():
    assert fs.own_box_passes(box_passes([((95, 30), (97, 40))])) == []


# --- FS7 square or back pass with a forward option open -------------------------------------------

def back_pass_scene(end, blocker=None):
    players = {**KEEPERS, "h4": ("home", "LCB", still(40.0, 34.0)), "h3": ("home", "RCB", still(30.0, 34.0)),
               "h9": ("home", "ST", still(55.0, 34.0)), "a4": ("away", "CB", still(80.0, 20.0)),
               "a3": ("away", "CB", still(82.0, 50.0))}
    if blocker:
        players["a7"] = ("away", "CM", still(*blocker))
    evs = [ev(5, "pass", "home", "h4", 40, 34, end_x=end[0], end_y=end[1], outcome="success", receiver="h3")]
    return scene(players, lambda f: (40.0, 34.0, 0.0), 20, evs, possessor=lambda f: "h4" if f < 5 else None)


def test_fs7_back_pass_with_a_free_man_ahead_is_flagged():
    found = fs.safe_pass_with_forward_option(back_pass_scene((30, 34)))
    assert len(found) == 1 and "h9 free 15 m ahead" in found[0].detail


def test_fs7_forward_option_with_the_lane_blocked_passes():
    assert fs.safe_pass_with_forward_option(back_pass_scene((30, 34), blocker=(47.0, 34.5))) == []


def test_fs7_forward_option_marked_passes():
    assert fs.safe_pass_with_forward_option(back_pass_scene((30, 34), blocker=(57.0, 36.0))) == []


def test_fs7_forward_pass_passes():
    assert fs.safe_pass_with_forward_option(back_pass_scene((55, 34))) == []


# --- FS8 loose ball nobody goes to ----------------------------------------------------------------

def resting_ball_scene(runner):
    players = {**KEEPERS, "h7": ("home", "CM", runner), "a7": ("away", "CM", still(50.0, 50.0))}
    evs = [ev(0, "pass", "home", "h4", 40, 34), ev(2, "deflection", "away", "a7", 50, 34)]
    return scene(players, lambda f: (50.0, 34.0, 0.0), 4 * FPS, evs)


def test_fs8_ball_at_rest_nobody_goes_to_is_flagged():
    assert len(fs.loose_ball_ignored(resting_ball_scene(still(50.0, 24.0)))) == 1


def test_fs8_ball_at_rest_someone_runs_to_passes():
    assert fs.loose_ball_ignored(resting_ball_scene(moving(50.0, 24.0, 0.0, 3.0))) == []


# --- FS9 camped in own box ------------------------------------------------------------------------

def camp_scene(inside):
    players = dict(KEEPERS)
    for k in range(10):
        pid = f"h{k + 2}"
        spot = (10.0, 18.0 + 3.2 * k) if k < inside else (35.0, 4.0 + 6.5 * k)
        players[pid] = ("home", "CM", still(*spot))
    for k in range(10):
        players[f"a{k + 2}"] = ("away", "CM", still(60.0, 4.0 + 6.5 * k))
    return scene(players, lambda f: (10.0, 18.0, 0.0), 7 * FPS, [ev(0, "pass", "home", "h1", 5, 34)],
                 possessor=lambda f: "h2")


def test_fs9_most_of_the_team_in_its_own_box_with_the_ball_is_flagged():
    found = fs.camped_in_own_box(camp_scene(6))
    assert len(found) == 1 and "6 outfield players" in found[0].detail


def test_fs9_half_the_team_in_its_own_box_passes():
    assert fs.camped_in_own_box(camp_scene(5)) == []


# --- the match around the checks ------------------------------------------------------------------

def test_dead_ball_from_a_stoppage_until_the_restart_is_kicked():
    evs = [ev(0, "pass", "home", "h7"), ev(10, "out_of_play", "home"), ev(30, "set_piece", "away", "a2"),
           ev(40, "pass", "away", "a2")]
    m = scene(dict(KEEPERS), lambda f: (50.0, 34.0, 0.0), 60, evs)
    assert [m.in_play[f] for f in (5, 10, 35, 40, 50)] == [1, 0, 0, 1, 1]


def test_attack_direction_comes_from_where_the_keepers_stand():
    swapped = {"h1": ("home", "GK", still(100.0, 34.0)), "a1": ("away", "GK", still(5.0, 34.0))}
    m = scene(swapped, lambda f: (50.0, 34.0, 0.0), 30, [])
    assert m.attack == {"home": -1.0, "away": 1.0}


def test_cli_prints_a_table_per_90(tmp_path, capsys):
    m_dir = tmp_path / "seedX"
    m_dir.mkdir()
    players = {**KEEPERS, "h7": ("home", "CM", still(50.0, 60.0)), "a7": ("away", "CM", still(70.0, 40.0))}
    frames = []
    for f in range(30):
        frames.append({"frame": f, "t": f / FPS, "ball": {"x": 50.0, "y": 60.0 + 10.0 * f / FPS, "z": 0.0},
                       "possessor": "h7" if f == 0 else None,
                       "players": [{"id": p, "team": t, "role": r, "x": pos(f)[0], "y": pos(f)[1]}
                                   for p, (t, r, pos) in players.items()]})
    evs = [ev(0, "pass", "home", "h7", 50, 60, end_x=50, end_y=68, outcome="fail"),
           ev(20, "out_of_play", "home", None, 50, 68)]
    (m_dir / "frames.jsonl").write_text("".join(json.dumps(fr) + "\n" for fr in frames))
    (m_dir / "events.jsonl").write_text("".join(json.dumps(e) + "\n" for e in evs))
    (m_dir / "meta.json").write_text(json.dumps({"fps": FPS}))
    out = tmp_path / "found.json"
    fs.main([str(m_dir), "--json", str(out)])
    table = capsys.readouterr().out
    row = next(line for line in table.splitlines() if line.startswith("| FS2"))
    # One defect in 1.2 s of match is 4,500 per 90 minutes.
    assert "| 1 | 4500.0 |" in row and "seedX 00:00.0 h7" in row
    assert json.loads(out.read_text())["seedX"]["findings"]["pass_out_unpressed"][0]["player"] == "h7"


def test_the_ball_is_dead_from_the_end_of_the_half_to_the_kick_off():
    """Law 7, lesson 213: from the half_time event the ball is dead until the second half's kick-off;
    football sense does not judge play in that gap."""
    players = {**KEEPERS, "h7": ("home", "CM", still(50.0, 34.0)), "a7": ("away", "CM", still(60.0, 34.0))}
    evs = [ev(0, "kickoff", "home", "h7", 52.5, 34.0), ev(1, "pass", "home", "h7", 52.5, 34.0),
           ev(30, "half_time", "away", None, 50.0, 34.0),
           ev(50, "kickoff", "away", "a7", 52.5, 34.0), ev(51, "pass", "away", "a7", 52.5, 34.0)]
    live, _ = fs.play_mask(scene(players, lambda f: (52.5, 34.0, 0.0), 80, evs))
    assert live[20] == 1 and live[40] == 0 and live[60] == 1
