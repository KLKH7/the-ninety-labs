"""The shot-outcome set's clips (ninety/eval/shot_outcome_set.py): every shot's window, joined on
overlap up to MAX_S, then the fixed subset."""

import json

from ninety.eval import shot_outcome_set as so

MATCH_S = 5400.0


def shot(t, outcome="off_target"):
    return {"type": "shot", "t": t, "outcome": outcome}


def spans(ws):
    return [(w["start"], w["seconds"]) for w in ws]


def test_every_shot_gets_three_seconds_before_and_seven_after_in_any_order():
    ws = so.windows([shot(200.0), {"type": "pass", "t": 50.0}, shot(100.0)], MATCH_S)
    assert spans(ws) == [(97.0, 10.0), (197.0, 10.0)]


def test_overlapping_windows_join_and_touching_ones_too_but_apart_ones_do_not():
    ws = so.windows([shot(100.0), shot(105.0), shot(122.0), shot(132.0)], MATCH_S)
    # 97..107 and 102..112 overlap; 119..129 starts after 112; 129..139 starts where 119..129 ends.
    assert spans(ws) == [(97.0, 15.0), (119.0, 20.0)]


def test_a_run_of_rebounds_joins_no_longer_than_max_s():
    ws = so.windows([shot(100.0), shot(106.0), shot(112.0)], MATCH_S)
    # 97..113 joined (16 s); 112's window would run to 119, 22 s from 97: a new window.
    assert spans(ws) == [(97.0, 16.0), (109.0, 10.0)]


def test_a_window_stays_inside_the_match_and_a_late_shot_keeps_its_seven_seconds():
    ws = so.windows([shot(1.0), shot(5380.0)], MATCH_S)
    assert spans(ws) == [(0.0, 8.0), (5377.0, 10.0)]  # the last event is not the match's end


def test_the_subset_keeps_every_goal_six_save_windows_and_two_others_in_time_order():
    events = ([shot(100.0 + 100 * k, "on_target") for k in range(8)]
              + [shot(2000.0 + 100 * k) for k in range(4)] + [shot(3000.0, "goal"), shot(4000.0, "goal")])
    kept = so.subset(so.windows(events, MATCH_S))
    starts = [w["start"] for w in kept]
    assert starts == [97.0, 197.0, 297.0, 397.0, 497.0, 597.0, 1997.0, 2097.0, 2997.0, 3997.0]


def test_a_window_with_a_goal_and_a_save_is_a_goal_window():
    (w,) = so.windows([shot(100.0, "on_target"), shot(103.0, "goal")], MATCH_S)
    assert so.kind(w) == "goal"


def test_the_seeds_are_new_and_split_eight_and_eight():
    seeds = set(so.VALIDATION) | set(so.TEST)
    assert len(so.VALIDATION) == len(so.TEST) == 8 and not set(so.VALIDATION) & set(so.TEST)
    # Clear of the frozen test sets (900001-900030), the training seeds (below 900000) and the demo (8001).
    assert all(910001 <= s <= 910016 for s in seeds)


def test_build_writes_where_and_how_long_never_the_outcome(tmp_path):
    for s in so.VALIDATION + so.TEST:
        d = tmp_path / f"seed{s}"
        d.mkdir()
        events = [shot(100.0, "goal"), shot(500.0, "on_target"), shot(900.0)]
        (d / "events.jsonl").write_text("".join(json.dumps(e) + "\n" for e in events))
        (d / "meta.json").write_text(json.dumps({"minutes": 90}))
    m = so.build(tmp_path)
    assert m["count"] == {"validation": 24, "test": 24}
    assert set(m["clips"][0]) == {"split", "seed", "start", "seconds"}
    assert m["render"]["views"] is None and m["seconds"] == 48 * 10.0
