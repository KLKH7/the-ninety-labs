"""The possession set's clips (ninety/eval/possession_set.py): a fixed grid of 10 s windows, the
two busiest of each match kept."""

import json

from ninety.eval import possession_set as ps
from ninety.sim.engine import FPS


def ev(type_, s):
    return {"type": type_, "t": s, "frame": round(s * FPS)}


def test_the_grid_starts_at_the_first_frame_and_ends_by_minute_32():
    ws = ps.windows([])
    assert [w["start"] for w in ws[:3]] == [0.0, 10.0, 20.0] and all(w["seconds"] == 10.0 for w in ws)
    assert ws[-1]["start"] + 10.0 == 1920.0 and len(ws) == 192


def test_a_window_counts_its_own_events_by_frame_and_nothing_else():
    ws = ps.windows([ev("possession_change", 9.96), ev("interception", 10.0), ev("tackle", 19.96),
                     ev("pass", 15.0), ev("possession_change", 1925.0)])
    assert ws[0]["counts"] == {"possession_change": 1, "interception": 0, "tackle": 0}
    assert ws[1]["counts"] == {"possession_change": 0, "interception": 1, "tackle": 1}
    assert sum(sum(w["counts"].values()) for w in ws) == 3  # not the pass, not the minute-32 change


def test_the_two_busiest_windows_are_kept_in_time_order_ties_to_interceptions_and_tackles_then_earlier():
    events = ([ev("possession_change", 55.0)] * 3                                   # 50 s: 3
              + [ev("possession_change", 105.0)] * 2 + [ev("tackle", 106.0)]       # 100 s: 3
              + [ev("possession_change", 305.0)] * 2 + [ev("interception", 306.0)]  # 300 s: 3
              + [ev("possession_change", 705.0)] * 2)                              # 700 s: 2
    kept = ps.best(ps.windows(events))
    # 100 s and 300 s beat the earlier 50 s on interceptions and tackles.
    assert [w["start"] for w in kept] == [100.0, 300.0]
    # The busier window is the later one; they are kept in time order.
    kept = ps.best(ps.windows([ev("possession_change", 505.0)] * 2 + [ev("possession_change", 105.0)]))
    assert [w["start"] for w in kept] == [100.0, 500.0]


def test_build_writes_where_and_how_long_never_what_a_clip_holds(tmp_path):
    events = [ev("possession_change", 105.0), ev("interception", 106.0), ev("tackle", 305.0)]
    for s in ps.VALIDATION + ps.TEST:
        d = tmp_path / f"seed{s}"
        d.mkdir()
        (d / "events.jsonl").write_text("".join(json.dumps(e) + "\n" for e in events))
        (d / "meta.json").write_text(json.dumps({"minutes": 35}))
    m = ps.build(tmp_path)
    assert set(m["clips"][0]) == {"split", "seed", "start", "seconds"}
    assert m["count"] == {"validation": 30, "test": 60}
    assert m["events"]["test"] == {"possession_change": 30, "interception": 30, "tackle": 30}
    assert m["render"]["set"] == ["stadium=broadcast", "dead_ball_cut=false"]


def test_each_clip_gets_one_render_and_validate_line_at_the_render_commit(tmp_path):
    from ninety.eval import set_commands

    render = {"views": None, "set": ["stadium=broadcast", "dead_ball_cut=false"]}
    manifest = {"render_commit": "abc123", "render": render,
                "clips": [{"split": "validation", "seed": 920101, "start": 100.0, "seconds": 10.0},
                          {"split": "test", "seed": 920201, "start": 30.4, "seconds": 14.2}]}
    (line,) = set_commands.commands(manifest, tmp_path, "test")
    d = tmp_path / "test" / "seed920201-760"
    assert '[ "$(git rev-parse HEAD)" = abc123 ] || ' in line
    assert (f"uv run ninety-render --seed 920201 --start 30.4 --seconds 14.2 --set stadium=broadcast "
            f"--set dead_ball_cut=false --out {d}") in line
    assert f"uv run ninety-validate {d}" in line and "--views" not in line
    assert len(set_commands.commands(manifest, tmp_path)) == 2


def test_check_passes_on_the_same_matches_and_fails_on_a_changed_one(tmp_path):
    import pytest

    for s in ps.VALIDATION + ps.TEST:
        d = tmp_path / f"seed{s}"
        d.mkdir()
        (d / "events.jsonl").write_text(json.dumps(ev("tackle", 105.0)) + "\n")
        (d / "meta.json").write_text(json.dumps({"minutes": 35}))
    out = tmp_path / "set.json"
    ps.main(["--sims", str(tmp_path), "--out", str(out)])
    ps.main(["--sims", str(tmp_path), "--out", str(out), "--check"])
    (tmp_path / f"seed{ps.TEST[0]}" / "events.jsonl").write_text(json.dumps(ev("tackle", 305.0)) + "\n")
    with pytest.raises(SystemExit, match="not what the rule gives"):
        ps.main(["--sims", str(tmp_path), "--out", str(out), "--check"])
