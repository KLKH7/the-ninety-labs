"""Territory per five minutes from vision's tracked ball (ninety/match/territory.py)."""

from __future__ import annotations

import json

import pytest

from ninety.match import territory

FPS = 25


def radar(balls: list[tuple[float, float]], seen: set[int] | None = None, source: str = "tracked") -> dict:
    """A radar.json body: frame n at time t with the ball at x; `seen` the frames vision saw it in."""
    frames = [{"frame": n, "t": t, "source": source, "ball": {"x": x, "y": 34.0, "z": 0.0}, "players": []}
              for n, (t, x) in enumerate(balls)]
    seen = set(range(len(balls))) if seen is None else seen
    views = [{"frame": n, "ball_seen": n in seen, "footprint": None} for n in range(len(balls))]
    return {"format": 1, "source": source, "frames": frames, "views": views}


def test_home_owns_the_half_toward_x_105():
    # three frames in the half home attacks, one in away's
    body = territory.build(radar([(10.0, 80.0), (10.04, 90.0), (10.08, 60.0), (10.12, 20.0)]), FPS)
    (b,) = body["bins"]
    assert b["home_s"] == pytest.approx(3 / FPS, abs=0.01)
    assert b["away_s"] == pytest.approx(1 / FPS, abs=0.01)
    assert b["home"] == 0.75
    assert body["source"] == "tracked" and body["bin_s"] == 300.0


def test_a_filled_in_ball_does_not_count():
    body = territory.build(radar([(1.0, 90.0), (1.04, 90.0), (1.08, 10.0)], seen={2}), FPS)
    (b,) = body["bins"]
    assert b["home_s"] == 0 and b["away_s"] == pytest.approx(1 / FPS, abs=0.01)
    assert b["seen_s"] == pytest.approx(1 / FPS, abs=0.01)
    assert b["home"] == 0.0


def test_bins_are_five_minutes_of_match_time():
    body = territory.build(radar([(299.9, 80.0), (300.0, 20.0), (2700.5, 70.0)]), FPS)
    assert [(b["t"], b["t_end"]) for b in body["bins"]] == [(0, 300), (300, 600), (2700, 3000)]
    assert [b["home"] for b in body["bins"]] == [1.0, 0.0, 1.0]


def test_no_share_without_a_ball_in_either_half():
    (b,) = territory.build(radar([(5.0, 52.5)]), FPS)["bins"]
    assert b["home"] is None and b["seen_s"] > 0


def test_only_vision_s_tracked_ball():
    with pytest.raises(ValueError):
        territory.build(radar([(1.0, 80.0)], source="truth"), FPS)


# --- the measured team facts e2e copies into match.json (insight-scout's team_stats, #269) ----------

def test_team_stats_keep_distance_with_its_coverage_and_possession_only_when_written(tmp_path):
    from ninety import e2e

    path = tmp_path / "insights.json"
    path.write_text(json.dumps({"team_stats": {"from_footage": True, "bin_min": 5, "distance": {
        "home": {"km": 41.3, "coverage": 0.93, "bins": []},
        "away": {"km": 39.8, "coverage": 0.9, "bins": []}}}}))
    stats = e2e.read_team_stats(path)
    assert stats["distance"] == {"home": {"km": 41.3, "coverage": 0.93},
                                 "away": {"km": 39.8, "coverage": 0.9}}
    assert "possession" not in stats  # no gate passed, so no row


@pytest.mark.parametrize("away", [{"km": 39.8}, {"km": -1, "coverage": 0.9},
                                  {"km": 39.8, "coverage": 1.4}])
def test_a_distance_without_a_sound_coverage_stops_the_bundle(tmp_path, away):
    from ninety import e2e

    path = tmp_path / "insights.json"
    home = {"km": 41.3, "coverage": 0.93}
    path.write_text(json.dumps({"team_stats": {"distance": {"home": home, "away": away}}}))
    with pytest.raises(SystemExit):
        e2e.read_team_stats(path)


def test_the_stats_block_keeps_rows_by_group_in_minute_order_and_refuses_a_row_without_a_group(tmp_path):
    from ninety import e2e

    path = tmp_path / "insights.json"
    row = {"group": "Pressing", "key": "turnovers", "label": "Turnovers", "unit": "turnovers",
           "series": [{"minute_to": 2, "home": 3, "away": 1, "confident": True},
                      {"minute_to": 1, "home": 1, "away": 0, "confident": True}]}
    path.write_text(json.dumps({"stats": {"bin_min": 5, "rows": [row]}}))
    (kept,) = e2e.read_stats(path)["rows"]
    assert [v["minute_to"] for v in kept["series"]] == [1, 2]
    path.write_text(json.dumps({"stats": {"rows": [{**row, "group": "Vibes"}]}}))
    with pytest.raises(SystemExit):
        e2e.read_stats(path)


def test_the_team_sheet_keeps_names_shirts_and_positions_and_refuses_a_row_without_an_id(tmp_path):
    from ninety import e2e

    path = tmp_path / "insights.json"
    path.write_text(json.dumps({"lineup": [{"id": "h1", "name": "A. Keeper", "number": 1, "position": "GK",
                                            "confident": True, "extra": "dropped"}]}))
    assert e2e.read_lineup(path) == [{"id": "h1", "name": "A. Keeper", "number": 1, "position": "GK",
                                      "confident": True}]
    path.write_text(json.dumps({"lineup": [{"name": "No Id"}]}))
    with pytest.raises(SystemExit):
        e2e.read_lineup(path)
