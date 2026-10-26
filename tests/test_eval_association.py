"""The association's grader (ninety/eval/association.py): true players by mean distance, and the
rate and error it reports."""

from ninety.eval import association as asc


def test_a_track_is_the_true_player_nearest_it_on_average_teams_ignored():
    truth = {f: {"players": [{"id": "h3", "team": "home", "x": 0.0, "y": 0.0},
                             {"id": "a5", "team": "away", "x": 4.0, "y": 0.0}]} for f in (1, 2)}
    tracked = [{"frame": 1, "players": [{"id": "h-t1", "team": "away", "x": 1.0, "y": 0.0}]},
               {"frame": 2, "players": [{"id": "h-t1", "team": "away", "x": 3.5, "y": 0.0}]}]
    assert asc.true_players(tracked, truth) == {"h-t1": ("a5", 1.75)}


def test_rate_and_error_count_tracks_and_frames():
    clip = {"tracks": [
        {"frames": 10, "track": "t1", "right": True},
        {"frames": 30, "track": "t2", "right": False},
        {"frames": 60, "track": None},
    ]}
    s = asc.summary([clip])
    assert (s["broadcast_tracks"], s["associated"], s["rate"]) == (3, 2, 0.667)
    assert (s["frames"], s["associated_frames"], s["frame_rate"]) == (100, 40, 0.4)
    assert (s["wrong"], s["error"], s["wrong_frames"]) == (1, 0.5, 30)
    assert s["error_ci"][0] < 0.5 < s["error_ci"][1]


def test_a_test_seed_is_refused(tmp_path):
    import pytest

    with pytest.raises(SystemExit, match="refused"):
        asc.main(["error", "--runs", str(tmp_path), "--clips", str(tmp_path), "--seeds", "900001",
                  "--out", str(tmp_path / "o.json")])
