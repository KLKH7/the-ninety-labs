"""Team shape from tracked positions (ninety/intel/shape.py): the definitions, the coverage rule, and
the same code reading the broadcast camera's tracked frames and a whole-pitch fused output."""

import json
from pathlib import Path

import pytest

from ninety.intel import shape
from ninety.match import tracking

ROOT = Path(__file__).resolve().parents[1]
FIXTURE = ROOT / "tests" / "fixtures" / "tracked-seed900001.json"

# A home 4-4-2 in its own depth (metres from its own goal line) and width: keeper, back four at 30 m,
# midfield four at 45 m, two forwards at 60 m.
HOME_442 = [(5.0, 34.0)] + [(30.0, y) for y in (10.0, 26.0, 42.0, 58.0)] + [
    (45.0, y) for y in (12.0, 28.0, 40.0, 56.0)] + [(60.0, 28.0), (60.0, 40.0)]


def team(side: str, spots, shift: float = 0.0) -> list[dict]:
    """Players of one side at depth + shift from their own goal line (away mirrored in x)."""
    letter = "h" if side == "home" else "a"
    return [{"id": f"{letter}-t{i}", "team": side,
             "x": (d + shift) if side == "home" else 105.0 - (d + shift), "y": y}
            for i, (d, y) in enumerate(spots, 1)]


def frames(minute: int, players: list[dict], ball=(52.5, 34.0), n: int = 30) -> list[dict]:
    t0 = 60.0 * (minute - 1)
    return [{"frame": int((t0 + i * 0.04) * 25), "t": round(t0 + i * 0.04, 2), "source": "tracked",
             "ball": {"x": ball[0], "y": ball[1], "z": 0.0}, "players": players} for i in range(n)]


def by_id(rows):
    return {r["id"]: r for r in rows}


def test_a_four_four_two_measures_as_its_definitions_say():
    f = shape.frame_shape("home", team("home", HOME_442), {"x": 50.0, "y": 34.0})
    # The keeper (5 m, inside his area) is left out of every outfield measure.
    assert f["width"] == 48.0  # widest outfield players at y 10 and 58
    assert f["length"] == 30.0  # back four at 30 m to forwards at 60 m
    assert f["line_height"] == 30.0  # the deepest outfield player
    # The hull of the outfield players: (30,10) (30,58) (45,56) (60,40) (60,28) (45,12), by shoelace.
    assert f["area"] == pytest.approx(1110.0)
    assert f["back_to_mid"] == 15.0 and f["mid_to_front"] == 15.0
    # Ball at 50 m: keeper, back four and midfield four are goal-side of it; the forwards beyond.
    assert f["behind_ball"] == 9 and f["ahead_of_ball"] == 2


def test_away_is_measured_from_its_own_goal_at_x_105():
    home = shape.frame_shape("home", team("home", HOME_442), {"x": 50.0, "y": 34.0})
    away = shape.frame_shape("away", team("away", HOME_442), {"x": 55.0, "y": 34.0})
    assert {k: away[k] for k in shape.METRICS} == pytest.approx({k: home[k] for k in shape.METRICS})


def test_a_deepest_player_outside_his_area_is_no_keeper():
    # Keeper caught upfield at 20 m: he is the deepest outfield-like player, and the line is his.
    spots = [(20.0, 34.0)] + HOME_442[1:]
    f = shape.frame_shape("home", team("home", spots), {"x": 50.0, "y": 34.0})
    assert f["line_height"] == 20.0


def test_a_minute_with_all_eleven_tracked_is_confident_and_its_change_is_the_difference():
    rows = shape.shape_rows(frames(3, team("home", HOME_442)) + frames(4, team("home", HOME_442, 8.0)))
    rows = by_id(rows)
    m3, m4 = rows["shape:line_height:home:m3"], rows["shape:line_height:home:m4"]
    assert (m3["value"], m4["value"]) == (30, 38)
    assert m3["confident"] and m4["confident"] and m4["tracked"] == 11
    assert m3["change"] is None and m4["change"] == 8  # pushed up 8 m
    assert rows["shape:width:home:m4"]["change"] == 0
    assert rows["shape:area:home:m4"]["unit"] == "m²" and rows["shape:area:home:m4"]["value"] == 1110


def test_a_fact_on_fewer_than_min_tracked_players_is_not_confident_and_has_no_change():
    few = team("home", HOME_442)[: shape.MIN_TRACKED - 1]
    rows = by_id(shape.shape_rows(frames(3, team("home", HOME_442)) + frames(4, few)))
    for metric in shape.METRICS:
        assert rows[f"shape:{metric}:home:m3"]["confident"]
        if f"shape:{metric}:home:m4" in rows:
            row = rows[f"shape:{metric}:home:m4"]
            assert not row["confident"] and row["change"] is None
            assert row["tracked"] == shape.MIN_TRACKED - 1


def test_a_count_needs_all_eleven():
    ten = team("home", HOME_442)[:10]
    row = by_id(shape.shape_rows(frames(2, ten)))["shape:behind_ball:home:m2"]
    assert not row["confident"] and row["need"] == 11


def test_twelve_players_of_one_team_in_a_frame_is_a_false_track_and_nothing_is_confident():
    extra = team("home", HOME_442) + [{"id": "h-t99", "team": "home", "x": 70.0, "y": 34.0}]
    rows = shape.shape_rows(frames(2, team("home", HOME_442), n=29) + frames(2, extra, n=1))
    assert not any(r["confident"] for r in rows if r["team"] == "home")


def test_under_a_second_of_frames_is_not_confident():
    rows = shape.shape_rows(frames(2, team("home", HOME_442), n=shape.MIN_FRAMES - 1))
    assert not any(r["confident"] for r in rows)
    rows = shape.shape_rows(frames(2, team("home", HOME_442), n=shape.MIN_FRAMES))
    assert all(r["confident"] for r in rows)


def test_a_change_is_only_from_the_minute_just_before():
    rows = by_id(shape.shape_rows(frames(2, team("home", HOME_442)) + frames(4, team("home", HOME_442, 8.0))))
    assert rows["shape:line_height:home:m4"]["change"] is None


def test_values_are_stated_to_the_metre_and_area_to_ten_square_metres_rounding_half_up():
    assert shape.stated("width", 37.5) == 38 and shape.stated("width", 37.49) == 37
    assert shape.stated("area", 1155.0) == 1160 and shape.stated("area", 1154.9) == 1150


def test_the_position_error_is_the_vision_measurement():
    from ninety.vision.events import RIVAL_M

    assert shape.POSITION_ERROR_M == RIVAL_M


def test_the_broadcast_cameras_tracked_frames_give_no_confident_fact():
    # The broadcast camera sees 5 to 8 of the 22: every shape fact from it is held. This is why the
    # agents need the whole-pitch tactical camera for shape.
    rows = shape.shape_rows(json.loads(FIXTURE.read_text())["frames"])
    assert rows and not any(r["confident"] for r in rows)
    assert max(r["tracked"] for r in rows) < shape.MIN_TRACKED


def test_a_whole_pitch_fused_output_in_the_same_schema_goes_through_unchanged(tmp_path):
    # The tactical camera's fused output keeps tracked.json's schema: both teams, all 22, through the
    # same loader that refuses anything not tracked.
    both = team("home", HOME_442) + team("away", HOME_442, 4.0)
    body = {"restarts": [], "frames": frames(2, both) + frames(3, team("home", HOME_442, 6.0)
                                                            + team("away", HOME_442, 4.0))}
    path = tmp_path / "tracked-seed900001.json"
    path.write_text(json.dumps(body))
    tracking.tracked.cache_clear()
    try:
        track = tracking.tracked("seed900001", str(path))
    finally:
        tracking.tracked.cache_clear()
    rows = by_id(shape.shape_rows(track.frames))
    assert all(r["confident"] for r in rows.values())
    assert rows["shape:line_height:home:m3"]["change"] == 6
    away = rows["shape:line_height:away:m3"]
    assert away["value"] == 34 and away["change"] == 0


def test_truth_frames_are_refused_by_the_loader_the_live_path_uses(tmp_path):
    body = {"restarts": [], "frames": [{**f, "source": "truth"} for f in frames(2, team("home", HOME_442))]}
    path = tmp_path / "tracked-seed900001.json"
    path.write_text(json.dumps(body))
    tracking.tracked.cache_clear()
    try:
        with pytest.raises(tracking.NotTracked, match="source 'truth'"):
            tracking.tracked("seed900001", str(path))
    finally:
        tracking.tracked.cache_clear()


def test_min_tracked_is_the_committed_measurement():
    # Written out (lesson 190): 11, as docs/eval/shape-coverage.json measured by its committed plan.
    measured = json.loads((ROOT / "docs" / "eval" / "shape-coverage.json").read_text())
    assert shape.MIN_TRACKED == 11 == measured["min_tracked"]
    assert measured["position_error_m"] == shape.POSITION_ERROR_M
    # Line height alone would pass at 10 tracked, missing at random: a finding, not yet a rule.
    assert measured["p90_error_over_tolerance"]["random"]["10"]["line_height"] <= 1.0
