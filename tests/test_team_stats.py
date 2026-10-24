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


def test_the_step_rule_takes_the_smallest_step_under_the_share_or_none():
    from ninety.eval import team_distance_eval as e

    rows = [{"step_s": 1.0, "share": 0.2}, {"step_s": 2.0, "share": 0.04}, {"step_s": 3.0, "share": 0.01}]
    assert e.pick(rows) == 2.0
    assert e.pick([{"step_s": 1.0, "share": 0.2}, {"step_s": 10.0, "share": 0.1}]) is None


def test_the_label_is_the_worst_bin_rounded_up():
    from ninety.eval import team_distance_eval as e

    cases = [{"ratio": {"min": 0.936, "max": 1.122}}, {"ratio": {"min": 0.856, "max": 0.954}}]
    assert e.label_pct(cases) == 15
    assert e.label_pct([{"ratio": {"min": 0.95, "max": 1.05}}]) == 5


def test_the_phone_is_told_how_far_the_distance_may_be_off(tmp_path, monkeypatch):
    from ninety.intel import stats_table

    cal = tmp_path / "cal.json"
    cal.write_text('{"within_pct": 15}')
    monkeypatch.setattr(team_stats, "CALIBRATION", cal)
    assert team_stats.team_stats([])["within_pct"] == 15
    assert stats_table._distance_label() == "Distance covered (tracked, ±15%)"
    monkeypatch.setattr(team_stats, "CALIBRATION", tmp_path / "none.json")
    assert team_stats.team_stats([])["within_pct"] is None


def test_the_committed_label_is_the_worst_of_every_freeze_match_graded():
    # The merge queue's review of #300: a label from one held-out match was narrower than the demo's.
    import json
    from pathlib import Path

    from ninety.eval import team_distance_eval as e

    report = json.loads((Path(__file__).parents[1] / "docs" / "eval" / "team-distance.json").read_text())
    runs = report["runs"]
    assert "f8076-65247ba3" in runs, "the demo's own match is graded"
    assert all(name.endswith("-65247ba3") for name in runs), "every match is at the freeze engine"
    for name, r in runs.items():
        assert r["within_pct"] == e.label_pct(r["cases"]), name
    assert report["within_pct"] == max(r["within_pct"] for r in runs.values())
    assert team_stats.within_pct() == report["within_pct"]
