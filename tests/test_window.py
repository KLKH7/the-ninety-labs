"""One player's window facts (ninety/intel/window.py): by hand, and on the engine."""

import pytest

from ninety.intel.stats import player_movement_facts
from ninety.intel.window import HEAT_NX, HEAT_NY, SPEED_NOW_S, player_window


def frame(i, **players):
    return {
        "frame": i,
        "t": i / 25,
        "players": [{"id": p, "team": "home", "x": x, "y": y} for p, (x, y) in players.items()],
    }


def run(speeds_mps, start=(10.0, 10.0)):
    """h7 running along x at the given speed in each frame step (25 fps), a7 standing still."""
    x, frames = start[0], [frame(0, h7=start, a7=(80.0, 60.0))]
    for i, v in enumerate(speeds_mps, start=1):
        x += v / 25
        frames.append(frame(i, h7=(x, start[1]), a7=(80.0, 60.0)))
    return frames


def test_speed_now_is_the_last_second_and_peak_is_the_fastest_step():
    # 3 s at 4 m/s, then 1 s at 8 m/s: peak 28.8 km/h, now 28.8 km/h, 12 + 8 m covered.
    w = player_window(run([4.0] * 75 + [8.0] * 25), "h7", 0, 4.0)
    assert w.peak_speed.value == 28.8 and w.peak_speed.unit == "km/h"
    assert w.speed_now.value == 28.8 and w.speed_now.unit == "km/h"
    assert w.distance_run.value == 12 + 8 and w.distance_run.unit == "m"
    # Slow down for the last second: now is the last second's mean, the peak stays.
    w = player_window(run([8.0] * 25 + [2.0] * 25), "h7", 0, 2.0)
    assert w.speed_now.value == 7.2 and w.peak_speed.value == 28.8
    assert SPEED_NOW_S == 1.0  # the sentence above and the numbers assume a one-second "now"


def test_the_window_bounds_the_facts_and_names_them():
    w = player_window(run([4.0] * 100), "h7", 1.0, 2.0)
    assert w.distance_run.value == 4  # one second at 4 m/s, not the four seconds of frames given
    assert w.distance_run.id == "distance_run:player_h7_window_1.00-2.00"
    assert w.distance_run.scope == "player:h7:window:1.00-2.00"
    assert w.distance_run.source_ids == ("frames:25-50",)
    assert w.speed_now.source_ids == ("frames:25-50",)


def test_the_movement_is_player_movement_facts_on_the_slice():
    frames = run([3.0, 5.0, 9.0, 1.0] * 30)
    w = player_window(frames, "h7", 0.4, 3.6)
    sliced = [f for f in frames if 0.4 <= f["t"] <= 3.6]
    ref = {f.metric: f for f in player_movement_facts(sliced) if f.scope == "player:h7"}
    assert w.peak_speed.value == round(ref["peak_speed"].value, 1)
    assert w.distance_run.value == round(ref["distance_run"].value)


def test_a_kickoff_reset_in_the_window_is_not_movement():
    frames = run([4.0] * 50)
    for f in frames[25:]:
        f["players"][0]["x"] -= 40.0  # everyone back to his own half at frame 25
    w = player_window(frames, "h7", 0, 2.0, restarts=[25])
    assert w.peak_speed.value == 14.4 and w.distance_run.value == 8
    assert player_window(frames, "h7", 0, 2.0).peak_speed.value > 3000  # without it, a teleport


def test_the_heat_map_is_laid_out_row_by_row_from_y_zero():
    # Half the frames in the bottom-left cell, half in the top-right one.
    frames = [frame(i, h7=(1.0, 1.0)) for i in range(10)] + [
        frame(i, h7=(104.0, 67.0)) for i in range(10, 20)
    ]
    w = player_window(frames, "h7", 0, 1.0, nx=3, ny=2)
    assert w.heat.cells == (0.5, 0, 0, 0, 0, 0.5)
    assert len(player_window(frames, "h7", 0, 1.0).heat.cells) == HEAT_NX * HEAT_NY


def test_a_player_just_over_a_line_counts_in_the_edge_cell():
    frames = [frame(i, h7=(-0.5, 68.4)) for i in range(5)]
    assert player_window(frames, "h7", 0, 1.0, nx=2, ny=2).heat.cells == (0, 0, 1.0, 0)


def test_the_card_carries_the_facts_and_where_the_positions_came_from():
    w = player_window(run([4.0] * 75 + [8.0] * 25), "h7", 0, 4.0)
    card = w.card("truth")
    assert (card["speed_kmh"], card["peak_kmh"], card["distance_m"]) == (28.8, 28.8, 20)
    assert card["source"] == "truth" and card["heat"]["nx"] * card["heat"]["ny"] == len(card["heat"]["cells"])


def test_too_few_frames_give_no_window_and_a_bad_window_raises():
    frames = run([4.0] * 10)
    assert player_window(frames, "h7", 0, 0.0) is None  # one frame: no speed
    assert player_window(frames, "h9", 0, 1.0) is None  # not in the frames
    with pytest.raises(ValueError):
        player_window(frames, "h7", 2.0, 1.0)
