"""The side-decision measurement (ninety/eval/side_decision.py): a flip swaps the outfield sides
inside the real pipeline, keepers keep theirs, and everything is put back afterwards."""

from __future__ import annotations

from ninety.eval import side_decision as sd
from ninety.vision import events as ev
from ninety.vision import track as tr
from tests.test_vision_events import BLUE, GREEN_KEEPER, crowd, pass_scene, row


def test_a_flip_swaps_outfield_sides_keeps_the_keeper_and_is_undone():
    rows = [row(f, crowd(f) + [(101.0, 34.0, GREEN_KEEPER)]) for f in range(30)]
    tracks = tr.track_players(rows)
    tr.assign_teams(tracks)
    before = {t.id: t.team for t in tracks}
    keeper = next(t.id for t in tracks if t.keeper)
    with sd.flipped(True):
        tracks2 = tr.track_players(rows)
        ev.assign_teams(tracks2)
        after = {t.id: t.team for t in tracks2}
    assert after[keeper] == before[keeper] == "away"
    assert all(after[i] != before[i] for i in before if i != keeper)
    assert tr.assign_teams is ev.assign_teams and tr.assign_teams.__name__ == "assign_teams"
    tracks3 = tr.track_players(rows)
    tr.assign_teams(tracks3)
    assert {t.id: t.team for t in tracks3} == before


def test_a_flipped_pass_keeps_everything_but_its_side():
    plain, _ = ev.detect(pass_scene(BLUE))
    with sd.flipped(True):
        swapped, _ = ev.detect(pass_scene(BLUE))
    assert [e["team"] for e in plain] == ["home"] and [e["team"] for e in swapped] == ["away"]
    assert [(e["outcome"], e["frame"]) for e in plain] == [(e["outcome"], e["frame"]) for e in swapped]


def tracks(*items):
    """(cluster label, true side, frames), outfield."""
    return [{"team": c, "truth": t, "frames": n, "keeper": False} for c, t, n in items]


def test_two_pure_clusters_are_sound_and_say_whether_they_are_named_right():
    right = sd.clusters(tracks(("home", "home", 50), ("away", "away", 40)))
    assert right["sound"] and right["named_right"] is True
    wrong = sd.clusters(tracks(("home", "away", 50), ("away", "home", 40)))
    assert wrong["sound"] and wrong["named_right"] is False


def test_a_cluster_is_sound_at_exactly_the_share_and_not_below():
    at = sd.clusters(tracks(("home", "home", 80), ("home", "away", 20), ("away", "away", 40)))
    below = sd.clusters(tracks(("home", "home", 79), ("home", "away", 21), ("away", "away", 40)))
    assert at["sound"] and not below["sound"] and below["named_right"] is None


def test_two_clusters_with_the_same_majority_are_not_sound():
    # Clip 120's case: both clusters mostly away players.
    out = sd.clusters(tracks(("home", "away", 90), ("home", "home", 5), ("away", "away", 95)))
    assert out["majority"] == {"home": "away", "away": "away"} and not out["sound"]


def test_a_cluster_split_evenly_has_no_majority_and_is_not_sound():
    out = sd.clusters(tracks(("home", "home", 50), ("home", "away", 50), ("away", "away", 40)))
    assert out["majority"]["home"] is None and not out["sound"]


def test_keepers_and_unmatched_tracks_do_not_count():
    out = sd.clusters(tracks(("home", "home", 50), ("away", "away", 40))
                      + [{"team": "home", "truth": "away", "frames": 500, "keeper": True},
                         {"team": "away", "truth": None, "frames": 500, "keeper": False}])
    assert out["sound"] and out["shares"] == {"home": 1.0, "away": 1.0}


def test_the_ordering_interval_is_hanley_and_mcneils():
    # A = 0.5 with 10 wrong and 10 right: Q1 = Q2 = 1/3, variance 0.0175, so 0.5 +- 1.96 * 0.1323.
    pairs = [(0.5, False)] * 10 + [(0.5, True)] * 10
    out = sd.ordering_95(pairs)
    assert out == {"ordering": 0.5, "ordering_95": [0.24, 0.76], "wrong": 10, "right": 10}
    assert sd.ordering_95([(0.5, True)])["ordering"] is None
