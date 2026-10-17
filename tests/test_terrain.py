import pytest

from ninety.intel import terrain as terrain_module
from ninety.intel.terrain import HOLD_MINUTES, ZONES, build_terrain, turning_points
from ninety.match.facts import minute_of
from ninety.sim import decisions
from ninety.sim.engine import simulate

MINUTES = 12


@pytest.fixture(scope="module")
def played():
    match = simulate(7, MINUTES)
    return match, build_terrain(match.events, match.frames, match.roster, MINUTES)


def test_terrain_values_the_ball_by_the_engines_rule():
    # one rule for what the ball is worth: the terrain calls the function the players decide with
    assert terrain_module.ball_value is decisions.value
    assert decisions.value(100, 34, 105.0) > decisions.value(5, 34, 105.0)


def test_grid_signs_follow_the_team_in_possession(played):
    match, terrain = played
    assert len(terrain["grid"]) == MINUTES and all(len(row) == ZONES for row in terrain["grid"])
    for m in range(MINUTES):
        assert round(sum(v for v in terrain["grid"][m] if v > 0), 1) <= terrain["home_threat"][m] + 0.1
        assert round(-sum(v for v in terrain["grid"][m] if v < 0), 1) <= terrain["away_threat"][m] + 0.1


def test_turning_points_alternate_hold_and_cite_real_events(played):
    match, terrain = played
    ids = {e["id"]: e for e in match.events}
    points = terrain["turning_points"]
    assert [p["minute"] for p in points] == sorted(p["minute"] for p in points)
    assert all(a["team"] != b["team"] for a, b in zip(points, points[1:], strict=False))
    for point in points:
        sign = 1 if point["team"] == "home" else -1
        assert sign * terrain["momentum"][point["minute"] - 1] > 0
        assert point["held"] >= HOLD_MINUTES
        assert point["minute"] <= point["peak_minute"] <= point["until"]
        assert set(point["source_ids"]) <= ids.keys()
        passes = [i for i in point["source_ids"] if ids[i]["type"] == "pass"]
        assert len(passes) == point["passes"]
        assert all(point["minute"] - 3 <= minute_of(ids[i]) <= point["minute"] for i in point["source_ids"])


def test_player_threads_cover_the_roster(played):
    match, terrain = played
    assert {p["id"] for p in terrain["players"]} == {r["id"] for r in match.roster}
    involved = sum(sum(p["involvement"]) for p in terrain["players"])
    assert involved == sum(e["type"] in ("pass", "shot", "tackle", "interception", "pressure")
                           and bool(e.get("player")) for e in match.events)


def test_a_swing_inside_one_spell_is_not_a_turning_point():
    away_spell_with_a_dip = [-3, -3, -3, -3, -3, -3, -1, -3, -3, -3, -3, -3]
    points = turning_points([], away_spell_with_a_dip, len(away_spell_with_a_dip))
    assert [(p["minute"], p["team"]) for p in points] == [(1, "away")]


def test_a_short_flicker_is_not_a_turning_point():
    flicker = [-3] * 6 + [3, 3] + [-3] * 6 + [3] * 6
    points = turning_points([], flicker, len(flicker))
    assert [(p["minute"], p["team"]) for p in points] == [(1, "away"), (15, "home")]


def test_turning_point_minutes_are_football_minutes():
    # planted defect: the first version labelled clock minute 33 (33:00-33:59) as "33'"
    momentum = [3.0] * 5 + [-3.0] * 7
    events = [{"id": "e1", "t": 5 * 60 + 10, "type": "pass", "team": "away", "outcome": "success"}]
    away = next(p for p in turning_points(events, momentum, len(momentum)) if p["team"] == "away")
    assert away["minute"] == minute_of(events[0]) == 6
    assert away["source_ids"] == ["e1"]
