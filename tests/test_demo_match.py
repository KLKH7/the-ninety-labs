"""The condensed-match rule (docs/eval/demo-match.md): pure, deterministic, from the events only."""

import copy
import importlib.util
from pathlib import Path

import pytest

spec = importlib.util.spec_from_file_location(
    "demo_match", Path(__file__).resolve().parents[1] / "scripts/demo_match.py")
dm = importlib.util.module_from_spec(spec)
spec.loader.exec_module(dm)

END = 5400.0


def ev(t, kind, team="home", **kw):
    return {"t": float(t), "type": kind, "team": team, "x": 52.5, "y": 34.0, **kw}


def passes(t0, n, team="home", step=2.0):
    return [ev(t0 + i * step, "pass", team, outcome="success") for i in range(n)]


def goal(t, team="home"):
    return [ev(t - 1, "shot", team, outcome="goal"), ev(t, "goal", team)]


def save(t, team="home"):
    return [ev(t, "shot", team, outcome="on_target")]


def corner(t, team="home"):
    # The ball went out over the away goal line, off a defender: a corner at the arc (Law 17).
    return [ev(t - 30, "out_of_play", "away", x=105.0, y=20.0), ev(t, "set_piece", team, x=104.5, y=0.5)]


def row(seed, events, valid=True, fs=1.0):
    return {"seed": seed, "valid": valid, "counts": dm.counts(events),
            "fs_per90": {k: fs for k in dm.FS_GATED}}


# ---- what a match holds ----

def test_a_move_is_five_completed_passes_by_one_side_and_pressure_does_not_break_it():
    events = [*passes(10, 3), ev(15, "pressure", "away"), *passes(16, 2), ev(30, "interception", "away"),
              *passes(40, 4)]
    assert [(m["start"], m["end"], m["passes"]) for m in dm.passing_moves(events)] == [(10.0, 18.0, 5)]


def test_a_failed_pass_a_stop_or_the_other_sides_touch_ends_a_move():
    for breaker in (ev(19, "pass", outcome="fail"), ev(19, "out_of_play", "away"),
                    ev(19, "tackle", "away"), ev(19, "shot", outcome="off_target")):
        assert dm.passing_moves([*passes(10, 4), breaker, *passes(20, 4)]) == []
    # Our own tackle, or a run straight on into the other side's run, keeps or splits them cleanly.
    assert len(dm.passing_moves([*passes(10, 4), ev(19, "tackle"), *passes(20, 1)])) == 1
    assert [m["team"] for m in dm.passing_moves([*passes(10, 5), *passes(30, 5, "away")])] == ["home", "away"]


def test_corners_and_direct_free_kicks_in_the_final_third_count_and_other_restarts_do_not():
    fk_far = [ev(100, "foul", "away", x=80.0), ev(120, "set_piece", "home", x=80.0, y=30.0)]
    fk_own = [ev(200, "foul", "away", x=50.0), ev(220, "set_piece", "home", x=50.0, y=30.0)]
    fk_offside = [ev(300, "offside", "away", x=80.0), ev(320, "set_piece", "home", x=80.0, y=30.0)]
    away_fk = [ev(400, "foul", "home", x=20.0), ev(420, "set_piece", "away", x=20.0, y=30.0)]
    throw = [ev(500, "out_of_play", "away", x=90.0, y=68.0), ev(510, "set_piece", "home", x=90.0, y=68.0)]
    goal_kick = [ev(600, "out_of_play", "home", x=105.0, y=40.0),
                 ev(620, "set_piece", "away", x=99.5, y=34.0)]
    kinds = [(m["kind"], m["t"]) for m in dm.moments(
        [*corner(50), *fk_far, *fk_own, *fk_offside, *away_fk, *throw, *goal_kick])]
    assert kinds == [("corner", 50.0), ("free_kick", 120.0), ("free_kick", 420.0)]


def test_a_shot_on_target_not_scored_is_a_save_and_a_goal_is_a_shot_on_target():
    c = dm.counts([*goal(100), *save(200), *save(300, "away"), ev(400, "shot", outcome="off_target")])
    assert c["goals"] == {"home": 1, "away": 0}
    assert c["on_target"] == {"home": 2, "away": 1}
    assert c["saves"] == 2


def test_contested_means_both_scored_or_the_side_behind_tested_the_keeper_twice():
    assert dm.contested(dm.counts([*goal(100), *goal(200, "away")]))
    assert not dm.contested(dm.counts([*goal(100), *save(200, "away")]))
    assert dm.contested(dm.counts([*goal(100), *save(200, "away"), *save(300, "away")]))
    assert not dm.contested(dm.counts([*save(200), *save(300)]))  # 0-0 is never contested


def test_the_score_adds_the_stated_weights():
    events = [*goal(100), *goal(200, "away"), *save(300), *corner(400), *passes(500, 5)]
    # 2 goals x 3, contested 4, 1 save x 1, 3 on target x 1, 1 corner x 0.5, 1 move x 0.2
    assert dm.action_score(dm.counts(events)) == pytest.approx(6 + 4 + 1 + 3 + 0.5 + 0.2)


# ---- the choice: planted pools ----

def busy_but_goalless():
    events = [e for t in range(100, 3000, 100) for e in save(t)]
    for t in range(3000, 5000, 60):
        events += [*passes(t, 6), ev(t + 30, "interception", "away")]
    return events


def test_the_rule_picks_the_planted_seed_from_a_pool():
    winner = [*goal(600), *goal(1200, "away"), *save(1800), *corner(2400)]
    weaker = [*goal(600), *save(1800)]
    # every pass failed: completion 0, outside R3
    sloppy = [*winner, *goal(3000), *[ev(3100 + i, "pass", outcome="fail") for i in range(10)]]
    defective = [*winner, *goal(3000)]
    pool = [row(8002, weaker), row(8003, sloppy), row(8004, defective, fs=9.0), row(8005, winner),
            row(8006, weaker), row(8007, weaker, fs=0.5)]
    for r in pool:
        if r["seed"] != 8003:  # completion inside R3's range
            r["counts"]["completion"] = 0.85
    rows = dm.gate_table(pool)
    by = {r["seed"]: r for r in rows}
    assert not by[8003]["gates"]["G2_completion"]
    assert not by[8004]["gates"]["G3_football_sense"]
    assert by[8004]["score"] > by[8005]["score"] and by[8003]["score"] > by[8005]["score"]
    assert dm.choose(rows)["seed"] == 8005


def test_a_match_with_no_goal_never_wins_however_busy():
    goalless = busy_but_goalless()
    one_goal = [*goal(600)]
    pool = [row(8002, goalless), row(8003, one_goal)]
    for r in pool:
        r["counts"]["completion"] = 0.85
    rows = dm.gate_table(pool)
    assert rows[0]["score"] > 10 * rows[1]["score"]
    assert not rows[0]["gates"]["G4_goals"]
    assert dm.choose(rows)["seed"] == 8003
    assert dm.choose(dm.gate_table([row(8002, goalless)])) is None


def test_more_than_six_goals_or_a_contract_failure_is_out():
    seven = [e for t in range(600, 4800, 600) for e in goal(t)]
    pool = [row(8002, seven), row(8003, goal(600), valid=False), row(8004, goal(900))]
    for r in pool:
        r["counts"]["completion"] = 0.85
    rows = dm.gate_table(pool)
    assert [r["passed"] for r in rows] == [False, False, True]


def test_a_tie_goes_to_the_lowest_seed_whatever_the_order():
    pool = [row(s, goal(600)) for s in (8009, 8004, 8007)]
    for r in pool:
        r["counts"]["completion"] = 0.85
    assert dm.choose(dm.gate_table(pool))["seed"] == 8004


def test_the_football_sense_gate_ranks_each_type_and_passes_the_better_half():
    assert dm.ranks([3.0, 1.0, 3.0, 2.0]) == [3.5, 1.0, 3.5, 2.0]
    pool = [row(8002 + i, goal(600), fs=float(i)) for i in range(5)]
    for r in pool:
        r["counts"]["completion"] = 0.85
    assert [r["gates"]["G3_football_sense"] for r in dm.gate_table(pool)] == [True, True, True, False, False]


# ---- the edit ----

def test_every_goal_is_kept_with_its_build_up_and_the_match_ends_are_always_in():
    edit = dm.condense([*goal(600), *goal(4000, "away")], END)
    segs = [(s["start_s"], s["end_s"]) for s in edit["segments"]]
    assert segs == [(0.0, 20.0), (575.0, 620.0), (2690.0, 2710.0), (3975.0, 4020.0), (5380.0, 5400.0)]
    assert [c["type"] for c in edit["chapters"]] == ["kickoff", "goal", "half", "goal", "full_time"]


def test_overlapping_and_near_windows_merge_and_far_ones_do_not():
    # Shots keep [t - 12, t + 6]: at 1000 and 1020 they are 2 s apart and merge; at 1025, 7 s apart.
    near = dm.condense([*save(1000), *save(1020)], END)["segments"]
    assert (988.0, 1026.0) in [(s["start_s"], s["end_s"]) for s in near]
    far = dm.condense([*save(1000), *save(1025)], END)["segments"]
    assert (988.0, 1006.0) in [(s["start_s"], s["end_s"]) for s in far]
    assert (1013.0, 1031.0) in [(s["start_s"], s["end_s"]) for s in far]


def test_chapters_carry_the_match_clock_and_where_they_start_in_the_video():
    edit = dm.condense([*save(1000), *goal(1010)], END)
    ch = [c for c in edit["chapters"] if c["type"] == "goal"][0]
    assert ch["clock"] == "16:50" and ch["video_s"] == 20.0  # after the 20 s kick-off segment
    assert edit["segments"][1]["video_start_s"] == 20.0
    assert edit["total_s"] == sum(s["end_s"] - s["start_s"] for s in edit["segments"])


def test_too_long_drops_moves_then_set_pieces_then_off_target_shots_and_never_a_goal_or_save():
    events = []
    for t in range(60, 5300, 40):
        events += [ev(t, "shot", outcome="off_target")]
    for t in range(80, 5300, 200):
        events += [*save(t)]
    events += [*goal(2000), *corner(3000), *passes(4100, 9)]
    events.sort(key=lambda e: e["t"])
    edit = dm.condense(events, END)
    assert edit["total_s"] <= dm.TARGET_S[1]
    kept = {c["type"] for c in edit["chapters"]}
    assert {"goal", "save", "kickoff", "half", "full_time"} <= kept
    dropped = [a.split()[1] for a in edit["adjust"]]
    assert dropped[0] == "move" and "corner" in dropped
    assert dropped.index("corner") < dropped.index("shot")
    assert all(d not in ("goal", "save") for d in dropped)


def test_too_short_adds_the_next_longest_moves():
    events = [*goal(600)]
    for i, t in enumerate(range(800, 5000, 60)):  # 70 moves of 5 to 9 passes
        events += passes(t, 5 + i % 5, step=1.0)
        events += [ev(t + 20, "interception", "away")]
    edit = dm.condense(events, END)
    assert any(a.startswith("added move") for a in edit["adjust"])
    assert edit["total_s"] >= dm.TARGET_S[0]


def test_the_rule_is_pure_and_deterministic():
    events = [*goal(600), *save(900), *corner(1500), *passes(2000, 7)]
    before = copy.deepcopy(events)
    assert dm.condense(events, END) == dm.condense(events, END)
    assert events == before


def test_the_doc_states_the_scripts_numbers_and_command():
    doc = (Path(__file__).resolve().parents[1] / "docs/eval/demo-match.md").read_text()
    assert f"Seeds {dm.FIRST_SEED} to {dm.LAST_SEED}" in doc
    assert dm.RENDER_FLAGS in doc
    assert "stadium=broadcast" in dm.RENDER_FLAGS and "views=tactical" in dm.RENDER_FLAGS


def ten_moves():
    """Moves of 5 to 14 passes, one a minute from 10:00, each ended by an interception."""
    events = []
    for i, n in enumerate(range(5, 15)):
        t = 600 + 60 * i
        events += [*passes(t, n, step=1.0), ev(t + 30, "interception", "away")]
    return events


def test_the_eight_longest_moves_are_kept():
    kept = [it["passes"] for it in dm.items(ten_moves(), END) if it["kind"] == "move"]
    assert sorted(kept, reverse=True) == [14, 13, 12, 11, 10, 9, 8, 7]


def test_a_long_edit_drops_the_move_with_fewest_passes_first():
    events = [*ten_moves(), *(ev(t, "shot", outcome="off_target") for t in range(1500, 5300, 25))]
    events.sort(key=lambda e: e["t"])
    first = dm.condense(events, END)["adjust"][0]
    assert first == "dropped move at 12:00"  # the 7-pass move, which starts at 600 + 2 * 60 s
