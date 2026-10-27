"""Code-computed stats never break a football invariant or state an unmeasured number (lesson 292).

Each case comes from the Oct 27 audit of seed 8324's facts.json (the demo bundle): an 85th-minute goal
after a shot read off target (3 goals, 2 on target), a shot speed from 1 of 5 shots, a measured zero of
pressure from a detector that writes none, window stats asked at minute 35 counting later passes,
"Lisbon Esportes's", and a London goal credited to a Lisbon track.
"""

from __future__ import annotations

import asyncio
import json
import random

import pytest

from ninety.agents import live
from ninety.intel import roles
from ninety.intel.stats import (
    STRIKE_GAP_S,
    calculate_facts,
    control_vs_chaos,
    goal_moments,
    pressure_facts,
    shot_facts,
)
from ninety.intel.teamsheet import possessive
from ninety.intel.windows import WINDOW_S, agent_rows, territory_shifts, window_facts
from ninety.match import detected


def by_id(facts):
    return {f.id: f for f in facts}


def ev(id_, type_, team, t, **kw):
    return {"id": id_, "type": type_, "team": team, "t": float(t), "x": 50.0, "y": 34.0, "player": None,
            "end_x": None, "end_y": None, "outcome": None, "ball_speed_kmh": None, **kw}


def scopes(facts):
    out: dict[str, dict[str, float]] = {}
    for f in facts:
        out.setdefault(f.scope, {})[f.metric] = f.value
    return out


def assert_ordered(facts, where=""):
    for scope, m in scopes(facts).items():
        if "shots" in m:
            assert m["goals"] <= m["shots_on_target"] <= m["shots"], (where, scope, m)


# ---- 1. goals <= shots on target <= shots

def lisbon_8324():
    """Lisbon's shots and goals on seed 8324, as detected (ids, times, outcomes and speeds kept)."""
    return [
        ev("s18-v00011", "shot", "away", 2041.88, player="a-t18090", outcome="goal", confidence=0.72),
        ev("s18-v00012", "goal", "away", 2044.0, player="a-t18090", confidence=1.0),
        ev("s29-v00005", "shot", "away", 3224.68, player="a-t29047", outcome="off_target", confidence=0.27),
        ev("s38-v00002", "shot", "away", 4520.4, player="a-t38010", outcome="goal", confidence=0.58),
        ev("s38-v00003", "goal", "away", 4522.52, player="a-t38010", confidence=1.0),
        ev("s42-v00008", "shot", "away", 5067.24, player="a-t42059", ball_speed_kmh=18.9, confidence=0.78),
        ev("s42-v00009", "shot", "away", 5067.96, outcome="off_target", confidence=0.73),
        ev("s42-v00010", "out_of_play", "away", 5068.4, confidence=0.9),  # the ball over the goal line
        ev("g00001", "goal", "away", 5068.48, confidence=0.998),
    ]


def test_a_goal_after_a_shot_read_off_target_counts_that_shot_on_target():
    """8324: Lisbon read 3 goals, 2 shots on target, 5 shots. The goal proves its strike was on target."""
    f = by_id(shot_facts(lisbon_8324()))
    assert f["goals:team_away"].value == 3
    assert f["shots:team_away"].value == 5  # the strike is not counted twice
    assert f["shots_on_target:team_away"].value == 3
    assert "s42-v00009" in f["shots_on_target:team_away"].source_ids
    assert_ordered(shot_facts(lisbon_8324()))


def test_a_goal_with_no_strike_seen_is_an_implied_shot_on_target_cited_by_the_goal():
    events = [ev("p1", "pass", "home", 10.0), ev("g1", "goal", "home", 12.0, confidence=0.99)]
    f = by_id(shot_facts(events))
    assert [f[f"{m}:team_home"].value for m in ("goals", "shots_on_target", "shots")] == [1, 1, 1]
    assert f["shots_on_target:team_home"].source_ids == ("g1",)
    assert f["shots:team_home"].source_ids == ("g1",)


def test_a_shot_long_before_a_goal_is_not_its_strike():
    """A goal 300 s after the side's last shot (another passage, or a cut between them): that shot keeps
    its own outcome, and the goal is an implied shot on target (STRIKE_GAP_S)."""
    events = [ev("s1", "shot", "home", 10.0, outcome="off_target"), ev("g1", "goal", "home", 310.0)]
    f = by_id(shot_facts(events))
    assert f["shots_on_target:team_home"].source_ids == ("g1",)
    assert [f[f"{m}:team_home"].value for m in ("goals", "shots_on_target", "shots")] == [1, 1, 2]
    near = [events[0], ev("g1", "goal", "home", 10.0 + STRIKE_GAP_S)]  # at the bound: still its strike
    assert by_id(shot_facts(near))["shots_on_target:team_home"].source_ids == ("s1",)


def test_a_goal_after_the_other_sides_shot_is_an_implied_shot_of_the_scoring_side():
    """The strike seen just before a goal is the other side's: it is not the scoring side's strike."""
    events = [ev("s1", "shot", "away", 10.0, outcome="off_target"), ev("g1", "goal", "home", 11.0)]
    f = by_id(shot_facts(events))
    assert (f["goals:team_home"].value, f["shots_on_target:team_home"].value) == (1, 1)
    assert f["shots_on_target:team_away"].value == 0
    assert_ordered(shot_facts(events))


def test_a_shot_that_went_in_the_ball_out_of_play_and_the_goal_are_one_goal():
    """The detector can write the ball over the goal line as `out_of_play` before the goal event: it is
    the goal's own crossing, not a second goal."""
    events = [ev("s1", "shot", "home", 10.0, outcome="goal"), ev("o1", "out_of_play", "home", 10.4),
              ev("g1", "goal", "home", 10.5)]
    assert [(g["id"], s["id"]) for g, s in goal_moments(events)] == [("g1", "s1")]
    f = by_id(shot_facts(events))
    assert [f[f"{m}:team_home"].value for m in ("goals", "shots_on_target", "shots")] == [1, 1, 1]


def random_match(rng: random.Random, n: int = 60) -> list[dict]:
    """Shots, goals and passes in any order and outcome a detector might write, including goals with no
    shot, goals after the other side's shot, shots that went in with no goal event, and the ball out of
    play between a shot and a goal."""
    events, t = [], 0.0
    players = ["h-t1", "h-t2", "a-t3", "a-t4", None]
    for k in range(n):
        t += rng.uniform(1, 200)
        kind = rng.choice(["shot", "shot", "goal", "pass", "out_of_play"])
        team = rng.choice(["home", "away"])
        outcome = rng.choice([None, "on_target", "off_target", "goal", "blocked"]) if kind == "shot" else None
        events.append(ev(f"e{k:03d}", kind, team, t, player=rng.choice(players), outcome=outcome))
    return events


@pytest.mark.parametrize("seed", range(200))
def test_goals_never_exceed_shots_on_target_nor_those_shots_in_any_scope(seed):
    """Every team and player scope, over the whole match, each 15-minute window and a random slice."""
    rng = random.Random(seed)
    events = random_match(rng)
    assert_ordered(shot_facts(events), "match")
    end = max(e["t"] for e in events)
    for w in range(int(end // WINDOW_S) + 1):
        window = [e for e in events if w * WINDOW_S <= e["t"] < (w + 1) * WINDOW_S]
        assert_ordered(shot_facts(window), f"window {w}")
    a, b = sorted(rng.uniform(0, end) for _ in range(2))
    assert_ordered(shot_facts([e for e in events if a <= e["t"] <= b]), f"slice {a:.0f}-{b:.0f}")


# ---- 2. shot speed only from shots whose speed may be said, enough of them

def test_one_detected_shot_speed_does_not_stand_for_five_shots():
    """8324: shot_speed_mean/max 18.9 km/h for Lisbon from 1 of 5 shots, citing all 5."""
    f = by_id(shot_facts([{**e, "source": "vision"} for e in lisbon_8324()]))
    assert not any(k.startswith("shot_speed") for k in f)


def test_a_detected_shot_speed_is_never_stated_vision_does_not_measure_it():
    """Every shot carries a detected speed: still none is stated (EVALUATION: shot speed is not measured)."""
    events = [ev(f"s{k}", "shot", "home", k, ball_speed_kmh=90.0 + k, source="vision", confidence=0.9)
              for k in range(4)]
    assert not any(f.metric.startswith("shot_speed") for f in shot_facts(events))


def test_shot_speed_cites_only_the_measured_shots_and_needs_more_than_half():
    truth = [ev("s1", "shot", "home", 1, ball_speed_kmh=100.0),
             ev("s2", "shot", "home", 2, ball_speed_kmh=80.0),
             ev("s3", "shot", "home", 3)]
    f = by_id(shot_facts(truth))
    assert f["shot_speed_mean:team_home"].value == 90
    assert f["shot_speed_mean:team_home"].source_ids == ("s1", "s2")
    assert f["shot_speed_max:team_home"].source_ids == ("s1", "s2")
    assert f["shot_speeds_measured:team_home"].value == 2 and f["shots:team_home"].value == 3
    half = truth[:1] + [ev("s4", "shot", "home", 4)]  # 1 of 2: not more than half
    assert "shot_speed_mean:team_home" not in by_id(shot_facts(half))


# ---- 3. no count from a source that cannot see the thing counted

def vision_passes(n: int = 40, step: float = 30.0) -> list[dict]:
    return [ev(f"p{k:03d}", "pass", "home" if k % 2 else "away", k * step, outcome="success",
               x=80.0 if k % 2 else 25.0, source="vision", confidence=0.9) for k in range(n)]


def test_no_pressure_or_chaos_from_a_source_that_detects_no_pressing():
    """8324: pressure_events 0 per team, from a detector that writes no pressure, tackle or interception."""
    events = vision_passes()
    assert pressure_facts(events) == []
    assert control_vs_chaos(events) == []
    unmeasured = {"pressure_events", "control_vs_chaos", "ppda"}
    assert not any(f.metric in unmeasured for f in calculate_facts(events))


def test_a_source_that_detects_pressing_still_gets_a_sides_zero():
    events = vision_passes() + [ev("t1", "tackle", "home", 5.0, outcome="success")]
    f = by_id(pressure_facts(events))
    assert f["pressure_events:team_home"].value == 0 and f["pressure_events:team_away"].value == 0
    assert control_vs_chaos(events)


# ---- 4. a stat asked for at minute 35 counts nothing after it

def detected_match(minutes: int = 50) -> list[dict]:
    """A pass every 20 s for both sides, from their attacking thirds, as the detector writes them."""
    return [{"id": f"d{k:04d}", "t": k * 20.0, "frame": k * 500, "type": "pass",
             "team": "home" if k % 2 else "away", "player": None, "x": 85.0 if k % 2 else 15.0, "y": 34.0,
             "end_x": 90.0, "end_y": 30.0, "outcome": "success", "receiver": None, "intended": None,
             "interceptor": None, "deflected_by": None, "ball_speed_kmh": None, "source": "vision",
             "confidence": 0.9} for k in range(minutes * 3)]


def test_window_stats_at_minute_35_count_no_event_after_it_and_end_there():
    events = detected_match()
    now = 35 * 60.0
    t = {e["id"]: e["t"] for e in events}
    facts = window_facts(events, now=now) + territory_shifts(events, now=now)
    assert facts and all(t[i] < now for f in facts for i in f.source_ids)
    rows = {r["id"]: r for r in agent_rows(events, now=now)}
    tilt = rows["field_tilt:team_home_window_2"]
    assert (tilt["minute_from"], tilt["minute_to"]) == (31, 35)
    whole = {r["id"]: r for r in agent_rows(events)}
    assert whole["field_tilt:team_home_window_2"]["events"] > tilt["events"]
    assert rows["passes_per_minute:team_home_window_2"]["value"] == 1.4  # 7 home passes in 5 minutes


def test_the_agents_asked_at_minute_35_are_given_nothing_after_it(monkeypatch):
    """ninety/agents/live.py handed the fact-checker agent_rows(events) over the whole match."""
    seen = {}

    async def fake_workflow(ask, judge, minute, plant, seed, minutes, live_, rows, stats, inline=False):
        seen.update(minute=minute, rows=rows, stats=stats)
        raise ValueError("no model here")

    monkeypatch.setattr(live, "run_workflow", fake_workflow)
    events = detected_match()
    result = asyncio.run(live.run(events, clip="seed8324", ask=object(), judge=object(), minute=35))
    assert result.agents_error and seen["minute"] == 35
    assert seen["rows"] and max(r["minute"] for r in seen["rows"]) == 35
    assert all(r["minute_to"] <= 35 for r in seen["stats"])
    t = {e["id"]: e["t"] for e in events}
    tilt = next(s for s in seen["stats"] if s["id"] == "field_tilt:team_home_window_2")
    counted = by_id(window_facts(events, now=35 * 60.0))["field_tilt:team_home_window_2"]
    assert tilt["events"] == len(counted.source_ids) and all(t[i] < 2100 for i in counted.source_ids)


# ---- 5. possessive club names

def test_a_club_ending_in_s_takes_the_apostrophe_alone():
    assert possessive("Lisbon Esportes") == "Lisbon Esportes'"
    assert possessive("London Athletic") == "London Athletic's"
    assert roles.say({"club": "Lisbon Esportes", "position": "left-back"}) == "Lisbon Esportes' left-back"
    assert roles.say({"club": "Lisbon Esportes", "line": "goalkeeper"}) == "Lisbon Esportes' goalkeeper"
    assert roles.say({"club": "London Athletic", "position": "left-back"}) == "London Athletic's left-back"


# ---- 6. a player read on the other side from his event is not named for it

def test_a_track_read_on_the_other_side_is_dropped_and_the_side_kept(tmp_path):
    """8324: s07-v00002, London's goal (team home), credited to the away track a-t7007."""
    shot = {"id": "s07-v00002", "t": 714.72, "frame": 17868, "type": "shot", "team": "home",
            "player": "a-t7007", "x": 90.0, "y": 34.0, "end_x": None, "end_y": None, "outcome": "goal",
            "ball_speed_kmh": None, "source": "vision", "confidence": 0.68, "team_confidence": None}
    fed = {**shot, "id": "s07-v00001", "t": 700.0, "type": "pass", "outcome": "success",
           "team_confidence": 1.0, "team_source": "id_feed"}
    same = {**shot, "id": "s07-v00004", "t": 720.0, "player": "h-t7001"}
    path = tmp_path / "detected.jsonl"
    path.write_text("".join(json.dumps(e) + "\n" for e in (fed, shot, same)))
    out = {e["id"]: e for e in detected.load(path)}
    assert (out["s07-v00002"]["team"], out["s07-v00002"]["player"]) == ("home", None)
    assert out["s07-v00001"]["player"] == "a-t7007"  # the feed sided him: his own side (lesson 283)
    assert out["s07-v00004"]["player"] == "h-t7001"


def test_the_feed_names_a_mismatched_shooter_before_the_load_could_drop_him(tmp_path):
    """The detector keeps a shot's player whose track was read on the other side: the feed's side step
    (identity.sided, on the detector's raw file) may name him and give his side, and the load keeps him.
    Dropped in the detector, the feed could not have named him."""
    from ninety.intel import identity

    raw = {"id": "s1", "t": 714.72, "frame": 17868, "type": "shot", "team": "home", "player": "a-t7007",
           "x": 90.0, "y": 34.0, "end_x": None, "end_y": None, "outcome": "goal", "ball_speed_kmh": None,
           "source": "vision", "confidence": 0.68, "team_confidence": None}
    named = {"a-t7007": {"team": "home", "name": "Eli Hourrick"}}  # the feed: a home player after all
    path = tmp_path / "detected.sided.jsonl"
    path.write_text("".join(json.dumps(e) + "\n" for e in identity.sided([raw], named)))
    (out,) = detected.load(path)
    assert (out["team"], out["player"], out["team_source"]) == ("home", "a-t7007", "id_feed")
