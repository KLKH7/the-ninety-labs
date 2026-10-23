"""The insight tools on planted scenes: each count, its bounds, and the cases that must not count."""

import itertools
import random

import pytest

from ninety.intel import counter_press, line_breaks, overloads, pass_options, roles, scene, teamsheet
from ninety.intel.scene import POSITION_ERROR_M, Count, Frames


def frame(n, home, away, ball=(52.5, 34.0), t=None):
    players = [{"id": f"h-t{i}", "team": "home", "x": x, "y": y} for i, (x, y) in enumerate(home, 1)]
    players += [{"id": f"a-t{i}", "team": "away", "x": x, "y": y} for i, (x, y) in enumerate(away, 1)]
    return {
        "frame": n,
        "t": n / 25 if t is None else t,
        "source": "tracked",
        "ball": {"x": ball[0], "y": ball[1]},
        "players": players,
    }


# Eleven players parked well away from the action in their own defensive third (x near their goal).
def parked(team, k=11, x=None):
    x = (8.0 if team == "home" else 97.0) if x is None else x
    return [(x, 4.0 + 6.0 * i) for i in range(k)]


def pass_event(
    eid="v1", team="home", start=(50.0, 34.0), end=(80.0, 34.0), frame_n=100, outcome="success", **kw
):
    return {
        "id": eid,
        "t": frame_n / 25,
        "frame": frame_n,
        "type": "pass",
        "team": team,
        "player": kw.get("player"),
        "receiver": kw.get("receiver"),
        "x": start[0],
        "y": start[1],
        "end_x": end[0],
        "end_y": end[1],
        "outcome": outcome,
        "confidence": kw.get("confidence", 0.9),
        "team_confidence": 0.9,
    }


# -- scene ---------------------------------------------------------------------------------------


def test_position_error_is_the_trackers():
    from ninety.vision.events import RIVAL_M

    assert POSITION_ERROR_M == RIVAL_M


def test_count_bounds():
    c = scene.count([5.0, -5.0, 0.5, -0.5], missing=2)
    assert (c.value, c.lo, c.hi) == (2, 1, 3 + 2)
    assert scene.count([5.0, 4.0]).sure
    with pytest.raises(ValueError):
        Count(3, 4, 5)


def test_frames_lookup_within_gap():
    f = Frames([frame(10, [], []), frame(20, [], [])])
    assert f.at(11)["frame"] == 10 and f.at(19)["frame"] == 20
    assert f.at(15) is None  # 5 frames from either: no positions stand for that moment


# -- line breaks -----------------------------------------------------------------------------------


def test_pass_bypasses_the_opponents_it_goes_past():
    away = [(60.0, 30.0), (70.0, 40.0), (95.0, 34.0)] + parked("away", 8, x=30.0)
    f = Frames([frame(100, parked("home"), away)])
    [lb] = line_breaks.line_breaks([pass_event()], f)
    assert (lb["value"], lb["lo"], lb["hi"], lb["confident"]) == (2, 2, 2, True)
    assert lb["id"] == "lb:v1" and lb["unit"] == "opponents" and len(lb["visual"]["bypassed"]) == 2


def test_away_attacks_the_other_way():
    away_attackers = parked("away")
    home = [(105 - 60.0, 30.0), (105 - 70.0, 40.0), (105 - 95.0, 34.0)] + parked("home", 8, x=105 - 30.0)
    f = Frames([frame(100, home, away_attackers)])
    e = pass_event(team="away", start=(105 - 50.0, 34.0), end=(105 - 80.0, 34.0))
    assert line_breaks.line_breaks([e], f)[0]["value"] == 2


def test_an_untracked_opponent_makes_the_count_unsure():
    away = [(60.0, 30.0), (70.0, 40.0), (95.0, 34.0)] + parked("away", 7, x=30.0)  # 10 of 11
    [lb] = line_breaks.line_breaks([pass_event()], Frames([frame(100, parked("home"), away)]))
    assert (lb["value"], lb["lo"], lb["hi"], lb["confident"]) == (2, 2, 3, False)


def test_an_opponent_on_the_line_makes_the_count_unsure():
    # Level with where the pass ends, as far from goal as the ball: either side of the line.
    end = (80.0, 34.0)
    on_line = (80.0 + POSITION_ERROR_M / 2, 34.0)
    away = [(60.0, 30.0), on_line] + parked("away", 9, x=30.0)
    [lb] = line_breaks.line_breaks([pass_event(end=end)], Frames([frame(100, parked("home"), away)]))
    assert lb["lo"] == 1 and lb["hi"] == 2 and not lb["confident"]


def test_failed_or_untracked_passes_have_no_line_break():
    f = Frames([frame(100, parked("home"), parked("away", x=70.0))])
    assert line_breaks.line_breaks([pass_event(outcome="fail")], f) == []
    assert line_breaks.line_breaks([pass_event(frame_n=200)], f) == []


def test_line_break_team_totals():
    away = [(60.0, 30.0), (70.0, 40.0)] + parked("away", 9, x=30.0)
    f = Frames([frame(100, parked("home"), away), frame(200, parked("home"), away)])
    facts = line_breaks.line_breaks([pass_event("v1"), pass_event("v2", frame_n=200)], f)
    home = next(r for r in line_breaks.team_totals(facts, 1, 90) if r["team"] == "home")
    assert home["value"] == 4 and home["also"] == [[2, "passes"]] and home["best"] == "lb:v1"


# -- overloads -------------------------------------------------------------------------------------


def overload_frames(n_frames, away_missing=0):
    # Home: 4 in the final third's centre (x 70..105, y 22.7..45.3); away: 1 there.
    home = [(85.0, 30.0), (85.0, 38.0), (90.0, 34.0), (80.0, 34.0)] + parked("home", 7, x=40.0)
    away = [(95.0, 34.0)] + parked("away", 10 - away_missing, x=50.0)
    return Frames([frame(i * 5, home, away, ball=(88.0, 34.0)) for i in range(n_frames)])


def test_an_overload_lasting_a_second_is_a_moment():
    facts = overloads.overloads(overload_frames(10))  # 10 samples, 0.2 s apart: 1.8 s
    [ov] = [f for f in facts if f["team"] == "home"]
    assert (ov["value"], ov["own_players"], ov["other_players"], ov["confident"]) == (3, 4, 1, True)
    assert (ov["third"], ov["channel"]) == ("final", "centre")


def test_a_flicker_is_no_overload():
    assert [f for f in overloads.overloads(overload_frames(3)) if f["team"] == "home"] == []


def test_untracked_opponents_may_close_the_gap():
    [ov] = [f for f in overloads.overloads(overload_frames(10, away_missing=2)) if f["team"] == "home"]
    assert ov["value"] == 3 and ov["lo"] == 1 and not ov["confident"]  # 4 - (1 + 2) = 1 < 2


def test_only_the_ball_zone_is_read():
    home = [(85.0, 30.0), (85.0, 38.0), (90.0, 34.0), (80.0, 34.0)] + parked("home", 7, x=40.0)
    away = [(95.0, 34.0)] + parked("away", 10, x=50.0)
    frames = Frames([frame(i * 5, home, away, ball=(20.0, 10.0)) for i in range(10)])
    assert [f for f in overloads.overloads(frames) if f["third"] == "final"] == []


def test_zone_named_as_the_team_attacks():
    assert overloads.zone_name("home", 2, 2) == ("final", "left")
    assert overloads.zone_name("away", 0, 0) == ("final", "left")
    assert overloads.zone_name("away", 2, 1) == ("own", "centre")


# -- counter-press ---------------------------------------------------------------------------------


def ev(eid, t, kind, team, **kw):
    return {
        "id": eid,
        "t": t,
        "frame": round(t * 25),
        "type": kind,
        "team": team,
        "x": 50.0,
        "y": 34.0,
        "confidence": 0.9,
        **kw,
    }


def test_turnover_and_regain():
    events = [
        ev("v1", 10.0, "pass", "home", outcome="success"),
        ev("v2", 12.0, "pass", "home", outcome="fail"),
        ev("v3", 13.0, "interception", "away"),
        ev("v4", 14.0, "pass", "away", outcome="success"),
        ev("v5", 16.0, "tackle", "home", outcome="success"),
    ]
    [row, back] = counter_press.turnovers(events)
    assert row["team"] == "home" and row["won"]["id"] == "v3" and row["regain_s"] == 3.0
    assert back["team"] == "away" and back["regain_s"] is None


def test_a_dead_ball_is_no_turnover_and_ends_the_regain():
    events = [
        ev("v1", 10.0, "pass", "home", outcome="success"),
        ev("v2", 11.0, "out_of_play", "home"),
        ev("v3", 13.0, "pass", "away", outcome="success"),
        ev("v4", 15.0, "interception", "home"),
        ev("v5", 16.0, "out_of_play", "home"),
        ev("v6", 18.0, "pass", "away", outcome="success"),
    ]
    rows = counter_press.turnovers(events)
    assert [r["won"]["id"] for r in rows] == ["v4"] and rows[0]["regain_s"] is None


def test_a_lost_tackle_is_the_opponents_ball():
    assert counter_press.owner({"type": "tackle", "team": "home", "outcome": "fail"}) == "away"


def test_pressers_near_the_ball_after_the_turnover():
    events = [
        ev("v1", 4.0, "pass", "home", outcome="fail"),
        ev("v2", 4.4, "interception", "away"),
        ev("v3", 6.0, "tackle", "home", outcome="success"),
    ]
    near = [(50.0 + d, 34.0) for d in (1.0, 2.0, 3.0)] + parked("home", 8)
    frames = Frames([frame(n, near, parked("away"), ball=(50.0, 34.0)) for n in range(110, 140, 5)])
    [cp] = counter_press.counter_press(events, frames)
    assert cp["team"] == "home" and (cp["value"], cp["lo"], cp["hi"]) == (3, 3, 3) and cp["confident"]
    assert cp["regained"] and cp["regain_s"] == 1.6 and [5.0, "s", counter_press.WITHIN] in cp["also"]


def test_a_presser_on_the_radius_is_unsure():
    events = [ev("v1", 4.0, "pass", "home", outcome="fail"), ev("v2", 4.4, "interception", "away")]
    near = [(50.0 + counter_press.PRESS_RADIUS_M, 34.0)] + parked("home", 10)
    [cp] = counter_press.counter_press(events, Frames([frame(115, near, parked("away"), ball=(50.0, 34.0))]))
    assert cp["lo"] == 0 and cp["hi"] == 1 and not cp["confident"]


# -- pass options ----------------------------------------------------------------------------------


def test_open_teammates_ahead():
    home = [(50.0, 34.0), (70.0, 20.0), (70.0, 50.0), (40.0, 34.0)] + parked("home", 7)
    away = [(71.0, 52.0)] + parked("away", 10, x=100.0)  # marks the one at (70, 50)
    e = pass_event(player="h-t1", end=(70.0, 20.0), outcome="fail")
    [po] = pass_options.pass_options([e], Frames([frame(100, home, away)]))
    assert (po["value"], po["lo"], po["hi"], po["confident"]) == (1, 1, 1, True)
    assert po["target_open"] is True and po["visual"]["marked"] == [[70.0, 50.0, "h-t3"]]


def test_an_untracked_opponent_leaves_no_one_surely_open():
    home = [(50.0, 34.0), (70.0, 20.0)] + parked("home", 9)
    away = parked("away", 10, x=100.0)
    [po] = pass_options.pass_options([pass_event(player="h-t1")], Frames([frame(100, home, away)]))
    assert po["value"] == 1 and po["lo"] == 0 and not po["confident"]


# -- roles and the team sheet ----------------------------------------------------------------------


def test_hungarian_matches_brute_force():
    rng = random.Random(3)
    for _ in range(30):
        n, m = rng.randint(1, 5), 6
        cost = [[rng.random() for _ in range(m)] for _ in range(n)]
        got = roles.hungarian(cost)
        best = min(itertools.permutations(range(m), n), key=lambda p: sum(cost[i][p[i]] for i in range(n)))
        assert sum(cost[i][got[i]] for i in range(n)) == pytest.approx(
            sum(cost[i][best[i]] for i in range(n))
        )
        assert len(set(got)) == n


def shape_frames(team, n=60, seed=1):
    """A team standing in its 4-3-3 (the template, shifted up the pitch), jittered by the position error."""
    rng = random.Random(seed)
    out = []
    for k in range(n):
        players = []
        for i, role in enumerate(teamsheet.ROLES, 1):
            d, across = roles.TEMPLATE[role]
            d += 10.0 + rng.gauss(0, 0.6)
            across += rng.gauss(0, 0.6)
            x, y = (d, across) if team == "home" else (105 - d, 68 - across)
            players.append({"id": f"{team[0]}-t{i}", "team": team, "x": x, "y": y})
        out.append({"frame": k * 5, "t": k * 0.2, "ball": {"x": 52.5, "y": 34.0}, "players": players})
    return out


@pytest.mark.parametrize("team", ["home", "away"])
def test_roles_from_the_shape(team):
    got = roles.assign(shape_frames(team), team)
    assert {t: r["role"] for t, r in got.items()} == {
        f"{team[0]}-t{i}": r for i, r in enumerate(teamsheet.ROLES, 1)
    }


def test_a_short_track_gets_no_role():
    frames = shape_frames("home", n=10)
    assert roles.assign(frames, "home") == {}


def test_who_says_a_name_only_past_its_gate():
    fx = teamsheet.Fixture(7, "OAK", "FEN")
    assigned = {"h-t5": {"role": "LB", "share": 0.8, "frames": 100}}
    open_gate = {"name": 0.7, "role": 0.6, "line": 0.5}
    w = roles.who("h-t5", "home", assigned, fx, open_gate)
    assert w["name"] == fx.sheet("home")[4].name and w["say"] == w["name"]
    w = roles.who("h-t5", "home", assigned, fx, {"name": 0.9, "role": 0.6, "line": 0.5})
    assert w["name"] is None and w["say"] == "Oakfield's left-back" and w["sheet_name"]
    w = roles.who("h-t5", "home", assigned, fx, {"name": None, "role": None, "line": 0.5})
    assert w["say"] == "an Oakfield defender"
    assert roles.who("h-t9", "home", assigned, fx, open_gate)["say"] == "an Oakfield player"


def test_no_calibration_names_nobody(tmp_path):
    assert roles.gates(tmp_path / "missing.json") == {"name": None, "role": None, "line": None}


def test_team_sheet_is_fictional_and_deterministic():
    from ninety.render.params import TEAM_CODES
    from ninety.sim.engine import FORMATION

    assert set(teamsheet.CLUBS) == set(TEAM_CODES)
    assert teamsheet.ROLES == tuple(r for r, _, _ in FORMATION)
    a, b = teamsheet.team_sheet(7, "OAK"), teamsheet.team_sheet(7, "OAK")
    assert a == b and a != teamsheet.team_sheet(8, "OAK")
    assert len({s.name.split()[1] for s in a}) == 11 and sorted(s.number for s in a) == list(range(1, 12))
    premier = {
        "Arsenal",
        "Aston Villa",
        "Bournemouth",
        "Brentford",
        "Brighton",
        "Burnley",
        "Chelsea",
        "Crystal Palace",
        "Everton",
        "Fulham",
        "Leeds",
        "Liverpool",
        "Manchester City",
        "Manchester United",
        "Newcastle",
        "Nottingham Forest",
        "Sunderland",
        "Tottenham",
        "West Ham",
        "Wolves",
        "Leicester",
        "Southampton",
        "Ipswich",
    }
    assert not premier & set(teamsheet.CLUBS.values())


def test_the_measured_gates_ship_in_the_package():
    # The image copies ninety/ but not docs/ (Dockerfile): a gate file outside it would name nobody.
    assert roles.CALIBRATION.is_relative_to(roles.Path(roles.__file__).parent)
    gates = roles.gates()
    assert all(gates[k] is not None for k in ("name", "role", "line")), gates


def test_club_names_are_the_screens():
    import re
    from pathlib import Path

    ts = Path(__file__).resolve().parents[1] / "web" / "viewer" / "src" / "teams.ts"
    if not ts.exists():
        pytest.skip("the viewer's club map is not on this branch yet")
    block = ts.read_text().split("export const CLUBS", 1)[1].split("};", 1)[0]
    assert dict(re.findall(r"(\w{3}): \"([^\"]+)\"", block)) == teamsheet.CLUBS
