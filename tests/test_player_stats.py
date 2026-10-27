"""Per-player stats keyed by the Player ID feed (ninety/intel/player_stats.py): never after the
moment asked, stitched only through feed-named seconds, withheld under the coverage rule or an
unmet bar, ranked by a stated formula."""

from __future__ import annotations

import pytest

from ninety.intel import player_stats as ps

ROSTER = [
    {"player": "LON09", "name": "Alex Finnet", "number": 9, "team": "home", "position": "striker"},
    {"player": "LON07", "name": "Theo Dounton", "number": 7, "team": "home", "position": "right winger"},
]
ON = {k: {"on": True} for k in (*ps.RUNNING, *ps.COUNTS, *(f"rank:{m}" for m in ps.METRICS))}


def frames(seconds: int, tracks, start: float = 0.0):
    """One frame a second (frame = t * 25); tracks(t) -> [(id, x, y)]."""
    out = []
    for s in range(seconds):
        t = start + s
        out.append(
            {
                "frame": round(t * 25),
                "t": t,
                "players": [{"id": i, "team": "home", "x": x, "y": y} for i, x, y in tracks(t)],
            }
        )
    return out


def named(*tracks, player="LON09"):
    return {t: {"player": player, "team": "home", "share": 1.0} for t in tracks}


def body(fr, nm, events=()):
    run = ps.running(fr, nm)
    return {
        "roster": ROSTER,
        "running": run["rows"],
        "footage": {str(k): v for k, v in run["footage"].items()},
        "events": list(events),
    }


def test_running_is_stitched_only_through_seconds_the_feed_names():
    # 5 m/s along x; track h-t1 for 0-9 s, an unnamed h-t2 for 10-19 s, then named h-t3 for 20-29 s.
    def tracks(t):
        tid = "h-t1" if t < 10 else "h-t2" if t < 20 else "h-t3"
        return [(tid, 5.0 * t, 30.0)]

    run = ps.running(frames(30, tracks), named("h-t1", "h-t3"))
    rows = [r for r in run["rows"] if r["player"] == "LON09"]
    assert sum(r["tracked_s"] for r in rows) == 20
    assert sum(r["m"] for r in rows) == pytest.approx(9 * 5 + 9 * 5)  # the unnamed 10 s are never bridged


def test_two_named_tracks_of_one_player_in_consecutive_seconds_are_one_run():
    def tracks(t):
        return [("h-t1" if t < 10 else "h-t2", 5.0 * t, 30.0)]

    rows = ps.running(frames(20, tracks), named("h-t1", "h-t2"))["rows"]
    assert sum(r["m"] for r in rows) == pytest.approx(19 * 5)


def test_a_step_past_the_jump_rule_is_skipped_and_restarts_the_window():
    def tracks(t):
        return [("h-t1", 5.0 * t + (40.0 if t >= 5 else 0.0), 30.0)]  # a 45 m jump at 5 s

    rows = ps.running(frames(10, tracks), named("h-t1"))["rows"]
    assert sum(r["m"] for r in rows) == pytest.approx(8 * 5)
    assert max(r["top_mps"] for r in rows) == pytest.approx(5.0)


def test_top_speed_is_a_sustained_mean_not_one_second():
    # 4 m/s, one second at 10 m/s, then 4 m/s: the 3 s mean is (4 + 10 + 4) / 3 = 6.
    xs = [0.0]
    for v in [4, 4, 4, 10, 4, 4, 4]:
        xs.append(xs[-1] + v)
    rows = ps.running(frames(len(xs), lambda t: [("h-t1", xs[int(t)], 30.0)]), named("h-t1"))["rows"]
    assert max(r["top_mps"] for r in rows) == pytest.approx(6.0)


def test_nothing_after_the_moment_asked_is_counted():
    fr = frames(180, lambda t: [("h-t1", 50 + 2.0 * ((t // 10) % 2) * (t % 10), 30.0)])
    ev = [
        {
            "event": "e1",
            "t": 30.0,
            "type": "pass",
            "player": "LON09",
            "role": "player",
            "outcome": "success",
            "had_shot": False,
        },
        {
            "event": "e2",
            "t": 130.0,
            "type": "pass",
            "player": "LON09",
            "role": "player",
            "outcome": "success",
            "had_shot": False,
        },
    ]
    b = body(fr, named("h-t1"), ev)
    at = {r["player"]: r for r in ps.stats(b, 125.0, ON)}["LON09"]
    assert at["passes"] == 1 and at["running_to_minute"] == 2
    assert at["tracked_s"] == 120 and at["footage_s"] == 120  # minute 3 has not ended at 2:05
    later = {r["player"]: r for r in ps.stats(b, 180.0, ON)}["LON09"]
    assert later["passes"] == 2 and later["tracked_s"] == 180


def test_running_is_withheld_under_the_coverage_rule_and_counts_are_not():
    fr = frames(
        120, lambda t: [("h-t1", 50 + t % 7, 30.0)] + ([("h-t7", 40 + t % 5, 20.0)] if t < 59 else [])
    )
    nm = {**named("h-t1"), **named("h-t7", player="LON07")}
    rows = {r["player"]: r for r in ps.stats(body(fr, nm), 120.0, ON)}
    assert rows["LON07"]["footage_coverage"] < ps.MIN_FOOTAGE_COVERAGE
    assert rows["LON07"]["distance_m"] is None and "distance_m" in rows["LON07"]["withheld"]
    assert rows["LON07"]["passes"] == 0  # counts come from events, not tracks
    assert rows["LON09"]["distance_m"] is not None and rows["LON09"]["source_label"] == "Player ID feed"
    assert rows["LON09"]["coverage"] == pytest.approx(1.0)


def test_a_stat_not_measured_or_off_is_withheld_and_so_is_its_ranking():
    fr = frames(60, lambda t: [("h-t1", 50 + t, 30.0)])
    b = body(fr, named("h-t1"))
    rows = ps.stats(b, 60.0, {})
    assert all(r["distance_m"] is None and r["withheld"]["distance_m"] for r in rows)
    off = {**ON, "passes": {"on": False, "why": "missed its bar"}}
    assert ps.rank(ps.stats(b, 60.0, off), "passes", off)["withheld"] == "passes: missed its bar"
    assert ps.rank(ps.stats(b, 60.0, off), "best", off)["facts"] == []
    unranked = {k: v for k, v in ON.items() if k != "rank:fastest"}
    assert ps.rank(ps.stats(b, 60.0, unranked), "fastest", unranked)["withheld"]


def test_best_is_the_stated_formula_and_fastest_ranks_only_the_covered():
    ev = [
        {
            "event": f"p{i}",
            "t": 1.0 + i,
            "type": "pass",
            "player": "LON07",
            "role": "player",
            "outcome": "success",
            "had_shot": False,
        }
        for i in range(3)
    ]
    ev += [
        {
            "event": "s",
            "t": 20.0,
            "type": "shot",
            "player": "LON09",
            "role": "player",
            "outcome": None,
            "had_shot": False,
        },
        {
            "event": "g",
            "t": 21.0,
            "type": "goal_credit",
            "player": "LON09",
            "role": "scorer",
            "outcome": None,
            "had_shot": True,
        },
    ]
    fr = frames(60, lambda t: [("h-t1", 50 + 3 * t, 30.0)] + ([("h-t7", 40 + 6 * t, 20.0)] if t < 20 else []))
    nm = {**named("h-t1"), **named("h-t7", player="LON07")}
    rows = ps.stats(body(fr, nm, ev), 60.0, ON)
    by = {r["player"]: r for r in rows}
    assert by["LON07"]["best_score"] == 3 + 3  # 3 involvements + 3 completed passes
    assert by["LON09"]["best_score"] == 1 + 2 * 1 + 5 * 1  # 1 involvement (the shot), a shot, a goal
    best = ps.rank(rows, "best", ON)
    assert [f["name"] for f in best["facts"]] == ["Alex Finnet", "Theo Dounton"] and best[
        "formula"
    ] == ps.BEST_FORMULA
    fastest = ps.rank(rows, "fastest", ON)  # LON07 runs faster but was tracked a third of the footage
    assert [f["player"] for f in fastest["facts"]] == ["LON09"] and fastest["facts"][0]["leads"]


def test_a_player_is_found_by_full_name_number_or_a_unique_word():
    rows = [{**r} for r in ROSTER]
    assert [r["player"] for r in ps.find(rows, "alex finnet")] == ["LON09"]
    assert [r["player"] for r in ps.find(rows, "#7")] == ["LON07"]
    assert [r["player"] for r in ps.find(rows, "Dounton")] == ["LON07"]
    assert ps.find(rows, "Messi") == []


def test_goal_credit_goes_to_the_shot_s_named_player_on_the_goal_s_side():
    events = [
        {"id": "s", "t": 10.0, "type": "shot", "team": "home", "player": "b1"},
        {"id": "g", "t": 11.0, "type": "goal", "team": "home", "player": "b2"},
    ]
    nb = {"b1": {"player": "LON09", "team": "home"}, "b2": {"player": "LIS04", "team": "away"}}
    rows = ps.event_rows(events, nb)
    assert [r["player"] for r in rows if r["type"] == "goal_credit"] == ["LON09"]
    counts = ps._counts([r for r in rows if r["player"] == "LON09"])
    assert counts["shots"] == 1 and counts["goals"] == 1 and counts["involvements"] == 1


def test_the_live_module_never_reads_the_truth_or_the_feed_s_positions():
    src = ps.__file__ and open(ps.__file__).read()
    assert "ninety.eval" not in src and "ninety.sim" not in src and "frames.jsonl" not in src
    assert "at_ball" not in src and "feed.at" not in src  # names only; never the feed's own positions
