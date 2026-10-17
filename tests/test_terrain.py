import pytest

from ninety.intel.terrain import ZONES, build_terrain, threat_table
from ninety.sim.engine import simulate

MINUTES = 12


@pytest.fixture(scope="module")
def played():
    match = simulate(7, MINUTES)
    return match, build_terrain(match.events, match.frames, match.roster, MINUTES, threat_table())


def test_threat_table_matches_the_value_grid():
    table = threat_table()
    assert len(table.values) == 21 and all(len(row) == 10 for row in table.values)
    near, far = table.at(100, 34, 105.0), table.at(5, 34, 105.0)
    assert near > far, "the ball near the goal attacked is worth more than near your own"


def test_grid_signs_follow_the_team_in_possession(played):
    match, terrain = played
    assert len(terrain["grid"]) == MINUTES and all(len(row) == ZONES for row in terrain["grid"])
    for m in range(MINUTES):
        assert round(sum(v for v in terrain["grid"][m] if v > 0), 1) <= terrain["home_threat"][m] + 0.1
        assert round(-sum(v for v in terrain["grid"][m] if v < 0), 1) <= terrain["away_threat"][m] + 0.1


def test_turning_points_are_spaced_and_cite_real_events(played):
    match, terrain = played
    ids = {e["id"]: e for e in match.events}
    minutes = [p["minute"] for p in terrain["turning_points"]]
    assert minutes == sorted(minutes)
    assert all(b - a >= 8 for a, b in zip(minutes, minutes[1:], strict=False))
    for point in terrain["turning_points"]:
        assert (point["swing"] > 0) == (point["team"] == "home")
        assert set(point["source_ids"]) <= ids.keys()
        passes = [i for i in point["source_ids"] if ids[i]["type"] == "pass"]
        assert len(passes) == point["passes"]
        assert all(point["minute"] - 3 < ids[i]["t"] / 60 < point["minute"] + 1 for i in point["source_ids"])


def test_player_threads_cover_the_roster(played):
    match, terrain = played
    assert {p["id"] for p in terrain["players"]} == {r["id"] for r in match.roster}
    involved = sum(sum(p["involvement"]) for p in terrain["players"])
    assert involved == sum(e["type"] in ("pass", "shot", "tackle", "interception", "pressure")
                           and bool(e.get("player")) for e in match.events)
