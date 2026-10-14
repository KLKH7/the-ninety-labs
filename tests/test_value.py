"""The possession and shot values are counted correctly: possessions, goals, shots, both directions."""

import math

from ninety.sim import value as V


def frame(t: float, holder: str | None, x: float, y: float = 34.0) -> dict:
    return {"t": t, "possessor": holder, "ball": {"x": x, "y": y, "z": 0.0}}


def test_cells_are_counted_from_the_goal_attacked_and_mirrored_across_for_the_away_side():
    assert V.cell_of(95.0, 10.0, 105.0) == (2, 1)  # home: 10 m from the away goal, 10 m from its right
    assert V.cell_of(10.0, 58.0, 0.0) == (2, 1)  # away: the same spot from its own point of view


def test_a_possession_that_ends_in_its_goal_is_credited_in_every_cell_it_passed_through():
    frames = [frame(0.0, "h6", 50.0), frame(0.5, None, 70.0), frame(1.0, "h9", 95.0), frame(2.0, None, 104.0)]
    frames += [frame(3.0, "a4", 50.0), frame(3.5, "a4", 40.0)]
    seen, scored, _, _ = V.count(frames, [{"type": "goal", "team": "home", "t": 2.5}])
    for x in (50.0, 70.0, 95.0):  # including the loose ball after h6's touch
        i, j = V.cell_of(x, 34.0, 105.0)
        assert seen[i][j] == scored[i][j] == 1
    i, j = V.cell_of(40.0, 34.0, 0.0)
    assert seen[i][j] == 1 and scored[i][j] == 0  # the away possession after it did not score


def test_a_possession_lost_before_any_goal_counts_but_scores_nothing():
    frames = [frame(0.0, "h6", 50.0), frame(1.0, "a2", 60.0)]
    seen, scored, _, _ = V.count(frames, [{"type": "goal", "team": "away", "t": 9.0}])
    i, j = V.cell_of(50.0, 34.0, 105.0)
    assert seen[i][j] == 1 and scored[i][j] == 0


def test_a_loose_ball_before_anyone_has_it_is_not_counted():
    seen, _, _, _ = V.count([frame(0.0, None, 52.0), frame(0.5, None, 53.0)], [])
    assert all(v == 0 for row in seen for v in row)


def test_shots_and_their_goals_are_counted_where_they_were_struck():
    events = [{"type": "shot", "team": "away", "x": 12.0, "y": 34.0, "outcome": "goal"},
              {"type": "shot", "team": "away", "x": 12.0, "y": 34.0, "outcome": "on_target"}]
    _, _, shots, goals = V.count([], events)
    i, j = V.cell_of(12.0, 34.0, 0.0)
    assert shots[i][j] == 2 and goals[i][j] == 1


def test_a_thin_cell_leans_on_its_neighbours_not_on_zero():
    hits = [[50.0] * V.CELLS_Y for _ in range(V.CELLS_X)]
    trials = [[100.0] * V.CELLS_Y for _ in range(V.CELLS_X)]
    hits[5][5], trials[5][5] = 0.0, 1.0  # one possession, no goal, among neighbours at 0.5
    assert 0.4 < V.smooth(hits, trials)[5][5] < 0.5


def test_a_cell_centre_reads_its_own_value_and_between_centres_is_the_average():
    values = [[i + j / 10 for j in range(V.CELLS_Y)] for i in range(V.CELLS_X)]
    t = V.Table(values)
    # Centre of cell (4, 3) for the home side: 22.5 m from x=105, 23.8 m across.
    assert math.isclose(t.at(105 - 22.5, 23.8, 105.0), 4.3)
    assert math.isclose(t.at(105 - 25.0, 23.8, 105.0), (4.3 + 5.3) / 2)  # half way along the pitch
    assert math.isclose(t.at(22.5, 68 - 23.8, 0.0), 4.3)  # the away side, mirrored


def test_damping_moves_half_way():
    assert V.blend([[0.0] * V.CELLS_Y for _ in range(V.CELLS_X)],
                   [[1.0] * V.CELLS_Y for _ in range(V.CELLS_X)])[0][0] == 0.5


def test_an_own_goal_ends_the_possession_without_crediting_the_side_that_had_it():
    frames = [frame(0.0, "h4", 20.0), frame(1.0, "h4", 8.0), frame(2.0, None, 52.0)]
    seen, scored, _, _ = V.count(frames, [{"type": "goal", "team": "away", "t": 1.5}])
    i, j = V.cell_of(20.0, 34.0, 105.0)
    assert seen[i][j] == 1 and scored[i][j] == 0
