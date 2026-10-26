"""The fuse gate's track-count score (ninety/eval/fuse_tracks.py)."""

from __future__ import annotations

from ninety.eval.fuse_tracks import adopted, grade, summary


def frame(n, tracks):
    return {"frame": n, "players": [{"id": i, "team": t, "x": x, "y": y} for i, t, x, y in tracks]}


def test_a_player_tracked_twice_is_counted_twice_matched_once_and_a_lost_id_is_a_switch():
    key = {0: {"h1": ("home", 50.0, 30.0)}, 1: {"h1": ("home", 50.0, 30.0)}}
    tracked = {"frames": [frame(0, [("h-t1", "home", 50.1, 30.0), ("h-t2", "home", 50.4, 30.0)]),
                          frame(1, [("h-t2", "home", 50.0, 30.0)])]}
    g = grade(tracked, key)
    assert g["tracks"] == 3 and g["abs_diff"] == 1 and g["found"] == 2 and g["id_switches"] == 1
    assert g["right_side"] == 2 and g["over"] == 0


def test_twelve_tracks_of_a_side_is_over_eleven_and_a_far_track_is_not_a_match():
    key = {0: {f"h{k}": ("home", 10.0 * k, 30.0) for k in range(11)}}
    tracked = {"frames": [frame(0, [(f"t{k}", "home", 10.0 * k + 0.3, 30.0) for k in range(11)]
                                + [("t99", "away", 5.0, 30.0)] + [("t98", "home", 5.0, 50.0)])]}
    g = grade(tracked, key)
    assert g["over"] == 1 and g["found"] == 11 and g["right_side"] == 11


def test_the_rule_needs_every_part():
    b = summary({"side_frames": 10, "tracks": 120, "over": 5, "abs_diff": 10, "true_frames": 100,
                 "found": 98, "matched": 98, "right_side": 97, "id_switches": 4})
    better = summary(b | {"tracks": 110, "over": 0, "abs_diff": 1})
    assert adopted(b, better)["adopt"]
    assert not adopted(b, better | {"id_switches": 5})["adopt"]
    assert not adopted(b, summary(b | {"tracks": 110, "over": 0, "abs_diff": 1, "found": 80}))["adopt"]


def test_lower_side_accuracy_alone_blocks_adoption():
    b = summary({"side_frames": 10, "tracks": 120, "over": 5, "abs_diff": 10, "true_frames": 10000,
                 "found": 9800, "matched": 9800, "right_side": 9000, "id_switches": 4})
    c = summary(b | {"tracks": 110, "over": 0, "abs_diff": 1, "right_side": 8800})
    rule = adopted(b, c)
    failed = [k for k, v in rule.items() if not v]
    assert failed == ["side_not_below_baseline_lower_bound", "adopt"]


def test_a_track_beyond_the_gate_is_not_matched_even_to_a_free_player():
    key = {0: {"h1": ("home", 50.0, 30.0)}}
    g = grade({"frames": [frame(0, [("h-t1", "home", 51.5, 30.0)])]}, key)
    assert g["found"] == 0 and g["true_frames"] == 1
