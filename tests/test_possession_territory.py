"""Possession share (time on the ball) and territory (where the ball was): GROUNDING I17b, I18."""

import pytest

from ninety.agents import companion_match as cm
from ninety.intel import ball_share as terr


def fr(n, ball, players):
    """One tracked frame at 25 fps: the ball (x, y) or None, and players (id, team, x, y)."""
    return {"frame": n, "t": n / 25, "source": "tracked",
            "ball": None if ball is None else {"x": ball[0], "y": ball[1]},
            "players": [{"id": i, "team": t, "x": x, "y": y} for i, t, x, y in players]}


def carry(n0, frames, pid, team, x0, speed=2.0):
    """A player running with the ball at his feet (0.3 m ahead) along x."""
    out = []
    for k in range(frames):
        x = x0 + speed * k / 25
        out.append(fr(n0 + k, (x + 0.3, 30.0), [(pid, team, x, 30.0)]))
    return out


def secs(rows):
    return {t: round(sum(r[t] for r in rows), 2) for t in ("home", "away")}


def test_a_side_keeps_the_ball_from_its_touch_until_the_other_side_wins_it():
    # Home carries 2 s, the ball rolls 1 s to nobody (still home's), then away carries 2 s.
    rows = carry(0, 50, "h-t1", "home", 40.0)
    rows += [fr(50 + k, (44.3 + 8 * k / 25, 30.0), [("h-t1", "home", 44.0, 30.0)]) for k in range(25)]
    rows += carry(75, 50, "a-t1", "away", 52.0)
    got = secs(terr.possession_rows(rows))
    assert got["home"] == pytest.approx(3.0, abs=0.1) and got["away"] == pytest.approx(2.0, abs=0.1)


def test_a_dead_ball_and_a_cut_belong_to_nobody():
    rows = carry(0, 50, "h-t1", "home", 40.0)
    rows += [fr(50 + k, (105.5, 30.0), []) for k in range(25)]  # over the goal line
    rows += [fr(75 + k, (100.0, 30.0), []) for k in range(25)]  # back in, nobody has touched it
    got = secs(terr.possession_rows(rows))
    assert got["home"] == pytest.approx(2.0, abs=0.1)
    cut = carry(0, 50, "h-t1", "home", 40.0) + [fr(500 + k, (60.0, 30.0), []) for k in range(25)]
    assert secs(terr.possession_rows(cut))["home"] == pytest.approx(2.0, abs=0.1)


def test_a_cut_ends_possession_even_within_the_hold():
    # The footage cuts 0.4 s after home's touch, to a loose ball: nobody's, though HOLD_S has not run out.
    rows = carry(0, 50, "h-t1", "home", 40.0) + [fr(60 + k, (60.0, 30.0), []) for k in range(25)]
    assert secs(terr.possession_rows(rows))["home"] == pytest.approx(2.0, abs=0.1)


def test_a_dead_ball_counts_for_nobody_until_a_side_touches_it_again():
    # Out over the touchline for 1 s, within the hold, then loose in play: nobody's throughout.
    rows = carry(0, 50, "h-t1", "home", 40.0)
    rows += [fr(50 + k, (60.0, 68.5), []) for k in range(25)]
    rows += [fr(75 + k, (60.0, 67.0), []) for k in range(25)]
    assert secs(terr.possession_rows(rows))["home"] == pytest.approx(2.0, abs=0.1)
    # A ball on the line (within its radius) is in play, Law 9: still home's.
    rows = carry(0, 50, "h-t1", "home", 40.0) + [fr(50 + k, (60.0, 68.05), []) for k in range(25)]
    assert secs(terr.possession_rows(rows))["home"] == pytest.approx(3.0, abs=0.1)


def test_possession_is_gained_by_two_frames_running_never_by_scattered_touches():
    lone = []
    for k in range(100):
        near = k in (10, 60)  # two single frames at an away player's feet, 2 s apart
        lone.append(fr(k, (40.3 if near else 50.0, 30.0), [("a-t1", "away", 40.0, 30.0)]))
    assert secs(terr.possession_rows(lone))["away"] == 0
    two = [fr(k, (40.3 if k in (10, 11) else 50.0, 30.0), [("a-t1", "away", 40.0, 30.0)]) for k in range(20)]
    assert secs(terr.possession_rows(two))["away"] > 0


def test_a_loose_ball_is_nobody_s_after_the_hold():
    rows = carry(0, 25, "h-t1", "home", 40.0)
    rows += [fr(25 + k, (60.0, 30.0), []) for k in range(250)]  # 10 s loose
    assert secs(terr.possession_rows(rows))["home"] == pytest.approx(1.0 + 4.0, abs=0.1)


def test_control_is_within_1_5_m_and_moving_with_the_player():
    far = [fr(k, (40.0 + 1.6, 30.0), [("h-t1", "home", 40.0, 30.0)]) for k in range(50)]
    assert secs(terr.possession_rows(far))["home"] == 0
    near = [fr(k, (40.0 + 1.4, 30.0), [("h-t1", "home", 40.0, 30.0)]) for k in range(50)]
    assert secs(terr.possession_rows(near))["home"] == pytest.approx(2.0, abs=0.1)
    # A pass rolling past a standing player at 10 m/s is near him for frames, never his.
    past = [fr(k, (30.0 + 10 * k / 25, 30.0), [("a-t1", "away", 40.0, 30.0)]) for k in range(50)]
    assert secs(terr.possession_rows(past))["away"] == 0


def test_the_share_is_always_said_after_a_minute_of_possession_and_never_before():
    rows = terr.possession_rows(carry(0, 25 * 40, "h-t1", "home", 0.0, 0.05)
                                + carry(1000, 25 * 19, "a-t1", "away", 60.0, 0.05))
    got = terr.possession(rows, 1, 2)
    assert got["home"]["value"] is None and not got["home"]["confident"]  # 59 s: "—"
    assert cm.code_texts({**got["home"], "club": "London Athletic"}) == []
    rows = terr.possession_rows(carry(0, 25 * 40, "h-t1", "home", 0.0, 0.05)
                                + carry(1000, 25 * 21, "a-t1", "away", 60.0, 0.05))
    got = terr.possession(rows, 1, 2)
    assert got["home"]["confident"] and got["home"]["value"] + got["away"]["value"] == 100
    assert got["home"]["value"] == round(100 * 40 / 61)
    assert cm.code_texts({**got["home"], "club": "London Athletic", "minute_from": 1, "minute_to": 2}) == [
        f"London Athletic had {got['home']['value']}% of possession from minute 1 to minute 2, "
        f"counted by time on the ball, give or take {terr.ERROR_POINTS} points."]


def frame(k, x):
    return {"frame": 25 * k, "t": float(k), "ball": None if x is None else {"x": x, "y": 30.0}, "players": []}


def test_territory_is_the_ball_by_third_along_each_teams_attack():
    # 10 seconds: home's final third (x > 70) 6 s, its own third 2 s, near the 35 m line 1 s, unseen 1 s.
    xs = [80, 90, 100, 75, 72, 95, 10, 20, 35.5, None]
    rows = terr.territory_rows([frame(k, x) for k, x in enumerate(xs)])
    got = terr.territory(rows, 1, 1)
    home, away = got["home"], got["away"]
    assert home["shares"]["final"] == round(100 * 6 / 9) and (home["lo"], home["hi"]) == (67, 78)
    assert away["shares"]["final"] == round(100 * 2 / 9)  # away attacks toward x = 0
    assert home["seconds"] == 9 and home["confident"]
    assert cm.code_texts({**home, "club": "London Athletic"}) == [
        f"The ball was in London Athletic's attacking third between 67% and 78% {SHOWN}"
    ]


SHOWN = "of the footage shown in minute 1."  # one minute is "in minute 1", never "from minute 1 to minute 1"
XS = [80, 90, 100, 75, 72, 95, 10, 20, 35.5, None]


@pytest.mark.parametrize(
    "text, ok",
    [
        (f"The ball was in London Athletic's attacking third between 67% and 78% {SHOWN}", True),
        (f"The ball was in London Athletic's attacking third 90% {SHOWN}", False),
        (f"The ball was rarely in London Athletic's attacking third between 67% and 78% {SHOWN}", False),
        (f"The ball was in Lisbon Esportes's attacking third between 67% and 78% {SHOWN}", False),
    ],
)
def test_a_territory_sentence_is_said_in_its_own_words(text, ok):
    from ninety.agents.factcheck import Claim
    from ninety.agents.insight_check import verify
    from ninety.intel.teamsheet import Fixture

    rows = terr.territory_rows([frame(k, x) for k, x in enumerate(XS)])
    fx = Fixture(7, "OAK", "FEN")
    fact = {**terr.territory(rows, 1, 1)["home"], "club": "London Athletic", "clubs": fx.clubs}
    names = [s.name for t in ("home", "away") for s in fx.sheet(t)]
    v = verify(Claim(text, [fact["id"]]), {fact["id"]: fact}, fx.clubs, {}, names)
    assert v.ok is ok, v.reasons


@pytest.mark.parametrize(
    "q, tool",
    [
        ("Who has had more possession?", "possession"),
        ("Are London Athletic dominating the ball?", "possession"),
        ("Where has the ball been?", "territory"),
        ("Are Lisbon Esportes pinned back?", "territory"),
    ],
)
def test_possession_and_territory_questions_route_to_their_tools(q, tool):
    assert tool in cm.route(q)


def test_the_headline_of_a_territory_answer_is_its_range():
    fact = {"metric": "final_third_share", "lo": 25, "hi": 31, "value": 25, "unit": "%"}
    assert cm._figure(fact) == "25 to 31%"


@pytest.mark.parametrize("x", [-3.0, -0.5, 106.0, 108.0])
def test_a_ball_beyond_a_goal_line_is_in_no_third(x):
    # The merge queue's review of #314: a ball off the pitch gave a depth past the thirds, and
    # THIRDS[-1] is "final", so both clubs got final-third seconds.
    rows = terr.territory_rows([frame(k, xk) for k, xk in enumerate([50.0, x])])
    got = terr.territory(rows, 1, 1)
    assert got["home"]["seconds"] == got["away"]["seconds"] == 1
    assert got["home"]["shares"]["final"] == got["away"]["shares"]["final"] == 0


def test_the_error_said_beside_possession_is_the_committed_measurement():
    import json
    import math
    from pathlib import Path

    body = json.loads((Path(__file__).resolve().parents[1] / "docs/eval/possession-time.json").read_text())
    worst = max([body["gate"]["max_error"], *(m["so_far_max"] for m in body["matches"])])
    assert terr.ERROR_POINTS == math.ceil(worst)
    assert body["gate"]["mae_points_at_most"] == 5.0


@pytest.mark.parametrize("error, ok", [(None, True), (5, False)])
def test_the_possession_sentence_carries_its_measured_error_and_no_other(error, ok):
    from ninety.agents.factcheck import Claim
    from ninety.agents.insight_check import verify
    from ninety.intel.teamsheet import Fixture

    rows = [{"id": f"poss:m{m}", "kind": "possession_minute", "team": None, "minute": m, "frames": 60.0,
             "home": 30.0, "away": 20.0} for m in range(1, 3)]
    fx = Fixture(7, "OAK", "FEN")
    fact = {**terr.possession(rows, 1, 2)["home"], "club": "London Athletic", "clubs": fx.clubs}
    text = cm.code_texts(fact)[0]
    assert f"give or take {terr.ERROR_POINTS} points" in text
    if error is not None:
        text = text.replace(f"give or take {terr.ERROR_POINTS} points", f"give or take {error} points")
    names = [s.name for t in ("home", "away") for s in fx.sheet(t)]
    assert verify(Claim(text, [fact["id"]]), {fact["id"]: fact}, fx.clubs, {}, names).ok is ok

