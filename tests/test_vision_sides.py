"""A track's side from its kit and where it stands (ninety/vision/sides.py, variant S)."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from ninety.vision import sides
from ninety.vision import track as tr

ROOT = Path(__file__).resolve().parents[1]
RED, BLUE = [200.0, 30.0, 40.0], [40.0, 60.0, 190.0]
PURPLE = [120.0, 45.0, 115.0]  # halfway between the two kits


def rows(players, frames=30, ball=None, view=True):
    """players: (x, y, rgb), standing still; boxes carry a view, as fused tactical lines do."""
    out = []
    for f in range(frames):
        out.append({"frame": f, "t": f / 25, "camera": {"ok": True, "P": None},
                    "players": [{"bbox": [20 * i, 0, 20 * i + 10, 30], "score": 0.9, "x": x, "y": y, "rgb": c}
                                | ({"view": "tac-l"} if view else {}) for i, (x, y, c) in enumerate(players)],
                    "ball": [] if ball is None else [{"bbox": [0, 500, 8, 508], "score": 0.9,
                                                      "x": ball[0], "y": ball[1]}]})
    return out


# Blue deeper toward x = 0 (home), red toward x = 105 (away).
TEAMS = ([(20 + 4 * k, 10.0 + 8 * k, BLUE) for k in range(5)]
         + [(70 + 4 * k, 10.0 + 8 * k, RED) for k in range(5)])


def sided(players, **kw):
    r = rows(players, **kw)
    tracks = tr.track_players(r)
    info = tr.assign_teams(tracks)
    return tracks, info, r


def test_a_track_whose_kit_says_nothing_takes_the_side_of_where_it_stands():
    for x, team in ((15.0, "home"), (90.0, "away")):
        tracks, info, r = sided(TEAMS + [(x, 60.0, PURPLE)])
        sides.apply(tracks, info, r)
        odd = next(t for t in tracks if tuple(t.rgb[0]) == tuple(PURPLE))
        assert odd.team == team


def test_the_confidence_is_the_probability_of_the_side_it_gives():
    tracks, info, r = sided(TEAMS)
    feats = sides.features(tracks, info, r)
    sides.apply(tracks, info, r)
    for t in tracks:
        if t.id in feats:
            p = sides.p_home(feats[t.id])
            assert t.side_confidence == round(max(p, 1 - p), 3)
            assert t.team == ("home" if p >= 0.5 else "away")


def test_a_kick_off_puts_each_player_on_his_own_side_of_halfway():
    # Everyone stands by halfway; with the ball still on the spot a player in the left half has
    # kick-off evidence +1 (home), one in the right half -1; with no kick-off seen, 0.
    near = [(50.0, 10.0 + 8 * k, BLUE) for k in range(5)] + [(55.0, 10.0 + 8 * k, RED) for k in range(5)]
    tracks, info, r = sided(near, ball=(52.5 + 0.6, 34.0))  # 0.6 m from the spot: inside the 1.0 m
    feats = sides.features(tracks, info, r)
    by_x = sorted((t.xy[0][0], feats[t.id][2]) for t in tracks if t.id in feats)
    assert len(by_x) == 10
    assert [k for x, k in by_x if x < 52.5] == [1.0] * 5 and [k for x, k in by_x if x > 52.5] == [-1.0] * 5
    for ball in (None, (52.5 + 1.05, 34.0)):  # no ball, or 1.05 m from the spot
        tracks, info, r = sided(near, ball=ball)
        assert [f[2] for f in sides.features(tracks, info, r).values()] == [0.0] * 10


def test_only_the_tactical_views_are_re_sided():
    assert sides.whole_pitch(rows(TEAMS))
    assert not sides.whole_pitch(rows(TEAMS, view=False))


def test_the_weights_are_the_committed_validation_fit():
    body = json.loads((ROOT / "docs/eval/sides-tactical/S-validation.json").read_text())
    assert list(sides.WEIGHTS) == body["weights_all"]
    assert body["calibration_error"] <= 0.05 and not any(s >= 900000 for s in body["seeds"])


@pytest.mark.parametrize("weights", [(0.0, 1.0, 0.0, 0.0), (0.0, 0.0, 1.0, 0.0)])
def test_each_piece_of_evidence_alone_moves_the_side(weights):
    tracks, info, r = sided(TEAMS + [(15.0, 60.0, PURPLE)])
    feats = sides.features(tracks, info, r)
    assert any(sides.p_home(f, weights) != 0.5 for f in feats.values())


def test_the_radar_gives_the_tactical_views_the_sides_the_events_do():
    from ninety.vision import tracked_frames

    reddish = [195.0, 31.0, 43.0]  # within noise of the red kit: the kit alone says away
    scene = TEAMS + [(5.0, 60.0, reddish)]  # but he stands deepest of all in home's half
    tracks, info, r = sided(scene, frames=40, ball=(30.0, 30.0))  # the radar draws frames with a ball
    assert next(t for t in tracks if tuple(t.rgb[0]) == tuple(reddish)).team == "away"
    sides.apply(tracks, info, r)
    assert next(t for t in tracks if tuple(t.rgb[0]) == tuple(reddish)).team == "home"
    built = tracked_frames.build(r, "clip")
    near_him = [p for f in built["frames"] for p in f["players"]
                if abs(p["x"] - 5.0) < 0.5 and abs(p["y"] - 60.0) < 0.5]
    assert near_him and all(p["team"] == "home" for p in near_him)


def test_law_3_judges_the_sides_s_gives_too():
    # Twelve blue players: S re-sides them, and Law 3 still makes no side sure.
    twelve = ([(15 + 3 * k, 5.0 + 5 * k, BLUE) for k in range(12)]
              + [(80 + 3 * k, 10.0 + 8 * k, RED) for k in range(5)])
    tracks, info, r = sided(twelve)
    sides.apply(tracks, info, r)
    assert info["law3"] is not None and all(t.side_confidence == 0.0 for t in tracks if t.team is not None)
