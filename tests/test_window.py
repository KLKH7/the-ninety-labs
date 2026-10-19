"""One player's window facts (ninety/intel/window.py): by hand, and on the engine."""

import pytest

from ninety.intel.stats import player_movement_facts
from ninety.intel.window import HEAT_NX, HEAT_NY, SPEED_NOW_S, player_window, team_flow


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


# The team flow field (the wind map).


def team_frames(velocities, n=26, team="home"):
    """Players of one team, each at its own start, moving at its own (vx, vy) m/s; one away player
    who stands still."""
    out = []
    for i in range(n):
        players = [{"id": f"h{k + 1}", "team": team, "x": x + vx * i / 25, "y": y + vy * i / 25}
                   for k, ((x, y), (vx, vy)) in enumerate(velocities)]
        players.append({"id": "a1", "team": "away", "x": 100.0, "y": 60.0})
        out.append({"frame": i, "t": i / 25, "players": players})
    return out


def test_a_team_running_plus_x_gives_a_field_pointing_plus_x():
    starts = [(10.0 + 10 * k, 10.0 + 6 * k) for k in range(8)]
    field = team_flow(team_frames([(s, (5.0, 0.0)) for s in starts]), "home", 0, 1.0)
    crossed = [i for i, n in enumerate(field.count) if n]
    assert crossed and all(field.vx[i] == 5.0 and field.vy[i] == 0.0 for i in crossed)
    assert sum(field.count) == 8 * 25  # every step of every home player, nothing of the away team


def test_an_empty_cell_has_count_zero_and_no_velocity():
    field = team_flow(team_frames([((10.0, 10.0), (3.0, 1.0))]), "home", 0, 1.0, nx=3, ny=2)
    assert field.count == (25, 0, 0, 0, 0, 0)
    assert field.vx[1:] == (None,) * 5 and field.vy[1:] == (None,) * 5
    away = team_flow(team_frames([((10.0, 10.0), (3.0, 1.0))]), "away", 0, 1.0, nx=3, ny=2)
    assert away.count == (0, 0, 0, 0, 0, 25) and away.vx[5] == 0.0  # stood still: zero, not none


def test_a_cell_is_the_mean_of_its_steps_weighted_by_steps():
    # Two players in one cell at 2 and 4 m/s for the same time: 3 (not the sum 6, nor the max 4).
    field = team_flow(team_frames([((10.0, 10.0), (2.0, 0.0)), ((11.0, 12.0), (4.0, 0.0))]), "home", 0, 1.0,
                      nx=1, ny=1)
    assert field.vx == (3.0,) and field.count == (50,)
    # One of them for half the time: each step counts once, so 2 m/s for 25 steps and 4 m/s for 12.
    frames = team_frames([((10.0, 10.0), (2.0, 0.0)), ((11.0, 12.0), (4.0, 0.0))])
    for f in frames[13:]:
        f["players"] = [p for p in f["players"] if p["id"] != "h2"]
    field = team_flow(frames, "home", 0, 1.0, nx=1, ny=1)
    assert field.count == (37,) and field.vx == (round((25 * 2 + 12 * 4) / 37, 2),)


def test_a_kickoff_reset_does_not_blow_through_the_flow_field():
    frames = team_frames([((60.0, 30.0), (2.0, 0.0))])
    for f in frames[13:]:
        f["players"][0]["x"] -= 30.0  # back to his own half at frame 13
    field = team_flow(frames, "home", 0, 1.0, restarts=[13], nx=1, ny=1)
    assert field.vx == (2.0,) and field.count == (24,)


def test_the_flow_message_carries_its_source():
    message = team_flow(team_frames([((10.0, 10.0), (3.0, 1.0))]), "home", 0, 1.0).message("truth")
    assert message["type"] == "flow" and message["source"] == "truth"
    assert len(message["vx"]) == len(message["count"]) == message["nx"] * message["ny"]
