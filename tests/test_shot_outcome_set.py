"""The shot-outcome set's windows (ninety/eval/shot_outcome_set.py): every shot, joined on overlap."""

from ninety.eval import shot_outcome_set as so


def shot(t):
    return {"type": "shot", "t": t}


def test_every_shot_gets_three_seconds_before_and_seven_after():
    assert so.windows([shot(100.0), {"type": "pass", "t": 50.0}], 5400.0) == [
        {"start": 97.0, "seconds": 10.0, "shots": [100.0]}]


def test_overlapping_windows_join_and_touching_ones_too_but_apart_ones_do_not():
    w = so.windows([shot(100.0), shot(105.0), shot(122.0), shot(132.0)], 5400.0)
    # 97..107 and 102..112 overlap; 119..129 starts after 112; 129..139 starts where 119..129 ends.
    assert w == [{"start": 97.0, "seconds": 15.0, "shots": [100.0, 105.0]},
                 {"start": 119.0, "seconds": 20.0, "shots": [122.0, 132.0]}]


def test_a_window_stays_inside_the_match():
    assert so.windows([shot(1.0), shot(5398.0)], 5400.0) == [
        {"start": 0.0, "seconds": 8.0, "shots": [1.0]}, {"start": 5395.0, "seconds": 5.0, "shots": [5398.0]}]


def test_the_split_is_eight_and_eight_and_never_a_reserved_seed():
    assert len(so.VALIDATION) == len(so.TEST) == 8 and not set(so.VALIDATION) & set(so.TEST)
    assert min(so.VALIDATION) == 910001 and max(so.TEST) == 910016
