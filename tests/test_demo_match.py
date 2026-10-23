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


# ---- the pool, and the rule it supersedes ----

def load(name):
    path = Path(__file__).resolve().parents[1] / f"scripts/{name}.py"
    sp = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(sp)
    sp.loader.exec_module(mod)
    return mod


def test_the_pool_is_8051_to_8090_and_never_overlaps_the_watched_or_superseded_seeds():
    assert (dm.FIRST_SEED, dm.LAST_SEED, dm.EXTRA_SEEDS) == (8051, 8090, (8091, 8130))
    clip = load("demo_clip")
    assert clip.LAST_SEED < dm.FIRST_SEED


def test_the_demo_clip_rule_is_superseded_and_never_chooses():
    clip = load("demo_clip")
    with pytest.raises(SystemExit) as stop:
        clip.main()
    assert "superseded by docs/eval/demo-match.md" in str(stop.value)
    doc = (Path(__file__).resolve().parents[1] / "docs/eval/demo-clip.md").read_text()
    assert doc.startswith("# Demo clip") and "Status: **superseded, never applied.**" in doc


# ---- every bound, at its edge ----

def gated(completion=0.85, goals=1):
    r = row(8051, [e for t in range(600, 600 + 600 * goals, 600) for e in goal(t)])
    r["counts"]["completion"] = completion
    return dm.gate_table([r])[0]


def test_completion_passes_from_75_to_88_percent_inclusive():
    assert [gated(c)["gates"]["G2_completion"] for c in (0.7499, 0.75, 0.88, 0.8801)] == \
        [False, True, True, False]


def test_goals_pass_from_one_to_six_inclusive():
    assert [gated(goals=n)["gates"]["G4_goals"] for n in (0, 1, 6, 7)] == [False, True, True, False]


def test_the_gated_football_sense_types_are_the_seven_with_a_pass_line_and_each_one_counts():
    from ninety.eval.football_sense import TYPES

    assert dm.FS_GATED == ("chaser_moves_away", "pass_out_unpressed", "keeper_stays_home", "bunching",
                           "own_box_pass", "loose_ball_ignored", "camped_in_own_box")
    assert set(dm.FS_GATED) <= set(TYPES)
    for k in dm.FS_GATED:  # two seeds alike but for one type: the worse one ranks lower
        a, b = row(8051, goal(600)), row(8052, goal(600))
        b["fs_per90"][k] = 2.0
        ra, rb = dm.gate_table([a, b])
        assert ra["fs_mean_rank"] < rb["fs_mean_rank"], k


def spans(events):
    return [(s["start_s"], s["end_s"]) for s in dm.condense(events, END)["segments"]]


def test_each_kind_of_moment_keeps_its_stated_window():
    assert (998.0, 1012.0) in spans(corner(1000))
    fk = [ev(970, "foul", "away", x=80.0), ev(1000, "set_piece", "home", x=80.0, y=30.0)]
    assert (998.0, 1012.0) in spans(fk)
    assert (998.0, 1012.0) in spans([*passes(1000, 5), ev(1030, "interception", "away")])  # 1000 to 1008
    assert (988.0, 1006.0) in spans(save(1000))
    assert spans([])[0] == (0.0, 20.0) and spans([])[-1] == (5380.0, 5400.0)
    assert (2690.0, 2710.0) in spans([])


def test_windows_exactly_five_seconds_apart_stay_apart_and_closer_ones_merge():
    assert (988.0, 1006.0) in spans([*save(1000), *save(1023)])  # 1006 to 1011: 5 s
    assert (988.0, 1028.95) in spans([*save(1000), *save(1022.95)])  # 4.95 s


def shots_then(k, last_gap, extra=()):
    """k shots off target 30 s apart (18 s windows, never merging), the last last_gap after the one
    before it, a goal at 4000, and extra events: 60 s of kick-off, 45:00 and the end, 45 s of goal."""
    ts = [100 + 30 * i for i in range(k - 1)]
    ts.append(ts[-1] + last_gap)
    events = [ev(t, "shot", outcome="off_target") for t in ts] + goal(4000) + list(extra)
    return sorted(events, key=lambda e: e["t"])


def test_an_edit_of_exactly_twenty_minutes_is_kept_and_one_second_more_drops_a_moment():
    at = dm.condense(shots_then(61, 15), END)  # 60 + 45 + 61 x 18 - 3 s of overlap = 1200 s
    assert at["total_s"] == 1200.0 and at["adjust"] == []
    over = dm.condense(shots_then(61, 16), END)  # 1201 s
    assert len(over["adjust"]) == 1 and over["total_s"] == 1183.0


def nine_moves():
    out = []
    for j in range(9):  # 5 passes, 10 s windows, 40 s apart
        out += [*passes(3000 + 40 * j, 5, step=1.0), ev(3000 + 40 * j + 10, "interception", "away")]
    return out


def test_an_edit_of_exactly_fifteen_minutes_is_kept_and_one_second_less_adds_a_move():
    # 60 + 45 + 8 moves x 10 + 40 shots x 18 - 5 s of overlap = 900 s
    at = dm.condense(shots_then(40, 13, nine_moves()), END)
    assert at["total_s"] == 900.0 and at["adjust"] == []
    under = dm.condense(shots_then(40, 12, nine_moves()), END)  # 899 s
    assert under["adjust"] == ["added move of 5 at 55:20"] and under["total_s"] == 909.0


def test_the_doc_states_the_scripts_numbers():
    doc = (Path(__file__).resolve().parents[1] / "docs/eval/demo-match.md").read_text()
    g = "{:g}".format
    want = [f"**Seeds {dm.FIRST_SEED} to {dm.LAST_SEED}**",
            f"extends to {dm.EXTRA_SEEDS[0]} to {dm.EXTRA_SEEDS[1]}",
            f"complete {g(dm.COMPLETION[0] * 100)}% to {g(dm.COMPLETION[1] * 100)}%",
            f"| {dm.GOALS[0]} to {dm.GOALS[1]} goals in the match |",
            f"| each goal | {g(dm.W_GOAL)} |", f"| {g(dm.W_CONTESTED)} |\n| each keeper save",
            f"not scored) | {g(dm.W_SAVE)} |", f"(goals included) | {g(dm.W_ON_TARGET)} |",
            f"(a penalty counts here) | {g(dm.W_SET_PIECE)} |",
            f"at least {dm.MOVE_PASSES} completed passes by one side | {g(dm.W_MOVE)} |",
            f"| goal | {g(dm.WINDOWS['goal'][0])} | {g(dm.WINDOWS['goal'][1])} |",
            f"| shot or save | {g(dm.WINDOWS['shot'][0])} | {g(dm.WINDOWS['shot'][1])} |",
            f"| corner | {g(dm.WINDOWS['corner'][0])} | {g(dm.WINDOWS['corner'][1])} |",
            f"in the final third | {g(dm.WINDOWS['free_kick'][0])} | {g(dm.WINDOWS['free_kick'][1])} |",
            f"(N = {dm.TOP_MOVES};",
            f"to its last | {g(dm.WINDOWS['move'][0])} | {g(dm.WINDOWS['move'][1])} |",
            f"the first {g(dm.OPEN_S)} s", f"({g(dm.HALF_S)} s either side)", f"the last {g(dm.CLOSE_S)} s",
            f"less than {g(dm.MERGE_GAP_S)} s apart",
            f"misses {g(dm.TARGET_S[0] / 60)} to {g(dm.TARGET_S[1] / 60)} minutes",
            "FS1, FS2, FS3,\n  FS5, FS6 (own-box passes), FS8 and FS9", dm.RENDER_FLAGS]
    missing = [w for w in want if w not in doc]
    assert not missing
    assert "stadium=broadcast" in dm.RENDER_FLAGS and "views=tactical" in dm.RENDER_FLAGS
