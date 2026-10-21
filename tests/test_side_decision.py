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
