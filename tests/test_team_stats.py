"""The phone's team distance on planted tracks: steps a second, jumps skipped, coverage told."""

from ninety.intel import team_stats


def run(n_s, speed, team="home", ids=("h-t1",), jump_at=None):
    frames = []
    for k in range(n_s * 25 + 1):
        t = k / 25
        players = []
        for i, pid in enumerate(ids):
            x = 10.0 + speed * t + (40.0 if jump_at is not None and t >= jump_at else 0.0)
            players.append({"id": pid, "team": team, "x": x, "y": 10.0 + 5 * i})
        frames.append({"frame": k, "t": t, "ball": {"x": 50, "y": 34}, "players": players})
    return frames


def test_a_steady_run_is_its_distance():
    d = team_stats.distance(run(10, 5.0), "home")
    assert abs(d["m"] - 50.0) < 1e-6 and d["jumps"] == 0
    assert abs(d["coverage"] - 1 / 11) < 1e-9  # one of eleven tracked


def test_a_track_jumping_is_not_running():
    d = team_stats.distance(run(10, 5.0, jump_at=4.0), "home")
    assert d["jumps"] == 1 and abs(d["m"] - 45.0) < 1e-6  # the one jumping second is left out


def test_frame_to_frame_jitter_is_not_summed():
    frames = run(10, 0.0)
    for k, f in enumerate(frames):  # 0.4 m of jitter every frame, standing still
        f["players"][0]["x"] += 0.4 if k % 2 else -0.4
    # Summed frame to frame it would read 250 steps of 0.8 m, 200 m; a step a second reads at most
    # one jitter per second, 10 steps of 0.8 m.
    assert team_stats.distance(frames, "home")["m"] <= 8.0 + 1e-9


def test_team_stats_have_bins_and_no_possession():
    stats = team_stats.team_stats(run(600, 2.0, ids=tuple(f"h-t{i}" for i in range(11))))
    home = stats["distance"]["home"]
    assert home["coverage"] == 1.0 and [b["minute_from"] for b in home["bins"]] == [1, 6, 11]
    assert "possession" not in stats  # no measured gate has opened: the phone hides the row
