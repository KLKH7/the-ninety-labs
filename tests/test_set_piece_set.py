"""The set-piece set's clips (ninety/eval/set_piece_set.py): the restart's kind read from the answer
key, one broadcast window per restart through the edit's cut, the fixed subset."""

import json

import pytest

from ninety.eval import possession_set as ps
from ninety.eval import set_piece_set as sp
from ninety.render import edit
from ninety.render.splits import RESERVED_FROM, TEST_SEEDS
from ninety.sim import engine as eng
from ninety.sim.engine import FPS, simulate

MATCH_S = 35 * 60.0


def ev(type_, s, x=50.0, y=30.0, **kw):
    return {"type": type_, "t": s, "frame": round(s * FPS), "x": x, "y": y, **kw}


def test_each_kind_is_read_from_the_stoppage_and_where_the_ball_is_placed():
    out = ev("out_of_play", 10, 40.0, 0.0)
    assert sp.restart_kind(out, ev("set_piece", 20, 40.0, 0.0), None) == "throw_in"
    out = ev("out_of_play", 10, 105.0, 50.0)
    assert sp.restart_kind(out, ev("set_piece", 20, 99.5, 34.0), None) == "goal_kick"
    assert sp.restart_kind(out, ev("set_piece", 20, 104.5, 67.5), None) == "corner"
    foul = ev("foul", 10, 94.0, 34.0)
    assert sp.restart_kind(foul, ev("set_piece", 20, 94.0, 34.0), None) == "penalty_kick"
    assert sp.restart_kind(foul, ev("set_piece", 20, 70.0, 34.0), None) == "free_kick"
    # An offside on the penalty mark is an indirect free kick, never a penalty (Law 11).
    offside = ev("offside", 10, 11.0, 34.0)
    assert sp.restart_kind(offside, ev("set_piece", 20, 11.0, 34.0), None) == "free_kick"
    assert sp.restart_kind(None, ev("kickoff", 1, 52.5, 34.0), None) == "kick_off"


def test_a_set_piece_from_the_last_restarts_spot_with_no_stoppage_is_that_restart_again():
    again = ev("set_piece", 30, 40.0, 0.0)
    assert sp.restart_kind(None, again, ("throw_in", 40.0, 0.0)) == "throw_in"
    # From elsewhere, it is not a retake.
    assert sp.restart_kind(None, again, ("throw_in", 60.0, 0.0)) == "free_kick"


def test_the_kind_rule_agrees_with_the_engine_on_every_restart_of_a_match(monkeypatch):
    """The rule reads only the answer key; the engine knows each restart's kind. Every restart of
    eight minutes of training seed 7 must be read as the engine gave it."""
    given, kinds = [], []
    stop, emit = eng.Engine.stop, eng.Engine.emit

    def record_stop(self, kind, *a, **kw):
        given.append(kind)
        return stop(self, kind, *a, **kw)

    def record_emit(self, type_, *a, **kw):
        if type_ in edit.RESTARTS:
            kinds.append(given[-1])
        return emit(self, type_, *a, **kw)

    monkeypatch.setattr(eng.Engine, "stop", record_stop)
    monkeypatch.setattr(eng.Engine, "emit", record_emit)
    match = simulate(7, 8)
    read = [r["kind"] for r in sp.restarts(match.events)]
    assert len(set(kinds)) >= 4, f"too few kinds of restart to test the rule: {sorted(set(kinds))}"
    assert read == kinds


def test_an_offence_while_the_ball_is_out_does_not_change_the_restart_or_where_the_window_starts():
    # Law 12: the restart for a ball out of play stands; the stoppage is the ball going out.
    events = [ev("out_of_play", 100.0, 40.0, 0.0), ev("foul", 103.0, 41.0, 2.0),
              ev("set_piece", 110.0, 40.0, 0.0)]
    assert sp.restarts(events) == [{"frame": 110 * FPS, "kind": "throw_in", "stop": 100 * FPS}]


def test_a_restart_window_runs_from_before_the_stoppage_through_the_cut_to_after_the_kick():
    events = [ev("kickoff", 1.0, 52.5, 34.0), ev("pass", 3.0), ev("out_of_play", 100.0, 40.0, 0.0),
              ev("set_piece", 120.0, 40.0, 0.0), ev("pass", 121.0)]
    ws, dropped = sp.windows(events, MATCH_S)
    # The kick-off's window opens with the match (no stoppage before it) and runs 6 s past the kick.
    assert ws[0] == {"start": 0.0, "seconds": 7.04, "kinds": ["kick_off"]}
    # The throw-in's: 98 s to 126 s of the match, less the cut through the 20 s wait.
    cut = edit.cuts(events, FPS)
    (c,) = cut
    assert ws[1]["start"] == 98.0 and ws[1]["kinds"] == ["throw_in"] and dropped == 0
    shown = (126 - 98) * FPS + 1 - (c.last_frame - c.first_frame + 1)
    assert round(ws[1]["seconds"] * FPS) == shown
    # The render's own plan of that many frames ends 6 s after the throw and makes the cut.
    show, made = edit.plan(98 * FPS, shown, cut, round(MATCH_S * FPS))
    assert show[-1] == 126 * FPS and made == cut


def test_a_restart_inside_the_last_window_joins_it_up_to_max_s_and_is_dropped_beyond():
    # Out at 100 s, thrown at 104 s (too short to cut), out again at 106 s, thrown at 110 s.
    quick = [ev("out_of_play", 100.0, 40.0, 0.0), ev("set_piece", 104.0, 40.0, 0.0),
             ev("out_of_play", 106.0, 40.0, 68.0), ev("set_piece", 110.0, 40.0, 68.0)]
    ws, dropped = sp.windows(quick, MATCH_S)
    assert ws == [{"start": 98.0, "seconds": 18.04, "kinds": ["throw_in", "throw_in"]}] and dropped == 0
    # Out at 112 s, thrown at 114 s: joined, 98 s to 120 s. Out at 119 s, thrown at 125 s: joined
    # it would run 98 s to 131 s, past MAX_S, so it is dropped, not shifted.
    late = quick + [ev("out_of_play", 112.0, 40.0, 0.0), ev("set_piece", 114.0, 40.0, 0.0),
                    ev("out_of_play", 119.0, 40.0, 68.0), ev("set_piece", 125.0, 40.0, 68.0)]
    ws, dropped = sp.windows(late, MATCH_S)
    assert ws == [{"start": 98.0, "seconds": 22.04, "kinds": ["throw_in"] * 3}] and dropped == 1


def test_no_window_ends_after_minute_32():
    ends_1918 = [ev("out_of_play", 1910.0, 40.0, 0.0), ev("set_piece", 1912.0, 40.0, 0.0)]
    assert [w["start"] for w in sp.windows(ends_1918, MATCH_S)[0]] == [1908.0]
    ends_1921 = [ev("out_of_play", 1910.0, 40.0, 0.0), ev("set_piece", 1915.0, 40.0, 0.0)]
    assert sp.windows(ends_1921, MATCH_S)[0] == []  # LAST_END_S is 1920 s


def test_the_subset_keeps_a_window_while_any_of_its_kinds_is_short_and_every_penalty():
    w = lambda *k: {"start": 0.0, "seconds": 10.0, "kinds": list(k)}  # noqa: E731
    per_seed = [(1, [w("throw_in"), w("throw_in"), w("throw_in", "corner")]),
                (2, [w("throw_in"), w("corner"), w("penalty_kick"), w("penalty_kick"), w("penalty_kick")])]
    kept = sp.subset(per_seed, 2)
    # The third window is kept for its corner; seed 2's throw-in is not; all three penalties are.
    assert [(s, x["kinds"]) for s, x in kept] == [
        (1, ["throw_in"]), (1, ["throw_in"]), (1, ["throw_in", "corner"]),
        (2, ["corner"]), (2, ["penalty_kick"]), (2, ["penalty_kick"]), (2, ["penalty_kick"])]


def test_the_seeds_are_new_and_split_apart_and_the_possession_set_shares_them():
    seeds = set(sp.VALIDATION) | set(sp.TEST)
    assert len(sp.VALIDATION) == 15 and len(sp.TEST) == 30 and not set(sp.VALIDATION) & set(sp.TEST)
    # Clear of the training seeds, the frozen test sets, the shot-outcome set (910001-910016) and
    # the demo seeds (8001-8050), and of the timing seed 920001 the plan names.
    assert all(s >= RESERVED_FROM and s not in TEST_SEEDS and not 910001 <= s <= 910016 for s in seeds)
    assert 920001 not in seeds
    assert (ps.VALIDATION, ps.TEST) == (sp.VALIDATION, sp.TEST)


def test_build_writes_where_and_how_long_never_the_kind(tmp_path):
    events = [ev("kickoff", 1.0, 52.5, 34.0), ev("out_of_play", 100.0, 40.0, 0.0),
              ev("set_piece", 120.0, 40.0, 0.0), ev("foul", 300.0, 94.0, 34.0),
              ev("set_piece", 400.0, 94.0, 34.0)]
    for s in sp.VALIDATION + sp.TEST:
        d = tmp_path / f"seed{s}"
        d.mkdir()
        (d / "events.jsonl").write_text("".join(json.dumps(e) + "\n" for e in events))
        (d / "meta.json").write_text(json.dumps({"minutes": 35}))
    m = sp.build(tmp_path)
    assert set(m["clips"][0]) == {"split", "seed", "start", "seconds"}
    # Validation: every penalty (15), and kick-offs and throw-ins until 15 each.
    assert m["restarts"]["validation"] == {"throw_in": 15, "goal_kick": 0, "corner": 0, "free_kick": 0,
                                           "penalty_kick": 15, "kick_off": 15}
    assert m["count"] == {"validation": 45, "test": 90}
    assert m["render"]["set"] == ["stadium=broadcast", "dead_ball_cut=true"]


def test_build_refuses_a_match_simulated_shorter_than_the_plan(tmp_path):
    for s in sp.VALIDATION + sp.TEST:
        d = tmp_path / f"seed{s}"
        d.mkdir()
        (d / "events.jsonl").write_text("")
        (d / "meta.json").write_text(json.dumps({"minutes": 30}))
    with pytest.raises(ValueError, match="30.0 minutes"):
        sp.build(tmp_path)


def test_check_passes_on_the_same_matches_and_fails_on_a_changed_one(tmp_path):
    events = [ev("out_of_play", 100.0, 40.0, 0.0), ev("set_piece", 120.0, 40.0, 0.0)]
    for s in sp.VALIDATION + sp.TEST:
        d = tmp_path / f"seed{s}"
        d.mkdir()
        (d / "events.jsonl").write_text("".join(json.dumps(e) + "\n" for e in events))
        (d / "meta.json").write_text(json.dumps({"minutes": 35}))
    out = tmp_path / "set.json"
    sp.main(["--sims", str(tmp_path), "--out", str(out)])
    sp.main(["--sims", str(tmp_path), "--out", str(out), "--check"])
    (tmp_path / f"seed{sp.TEST[0]}" / "events.jsonl").write_text(json.dumps(events[0]) + "\n")
    with pytest.raises(SystemExit, match="not what the rule gives"):
        sp.main(["--sims", str(tmp_path), "--out", str(out), "--check"])
