"""Restart detection on the live path: a kick-off is the ball still on the centre mark, the sides in
their own halves (Law 8), then the ball played.

Every scene is built here as observations (what ninety.vision.observe writes), so each test's
premise holds by construction (docs/LESSONS.md, lesson 47). Constants come from the module under
test (lesson 36). A legal kick-off must be found; each broken premise must stop it.
"""

from __future__ import annotations

import math

from ninety.vision import restarts as rs
from ninety.vision import track as tr

RED, BLUE = [200.0, 30.0, 40.0], [40.0, 60.0, 190.0]
FPS = tr.FPS
CX, CY = rs.CENTRE
SET, STILL, KICK_SPEED = 100, 50, 10.0  # phase B starts at SET; the ball lies still STILL frames


def row(frame, players, ball=None):
    return {
        "frame": frame, "t": round(frame / FPS, 2),
        "camera": {"ok": True, "median_px": 0.5, "points": 500, "P": None},
        "players": [{"bbox": [20 * i, 0, 20 * i + 10, 30], "score": 0.9, "x": x, "y": y, "rgb": c}
                    for i, (x, y, c) in enumerate(players)],
        "ball": [] if ball is None else [{"bbox": [0, 500, 8, 508], "score": 0.8,
                                          "x": ball[0], "y": ball[1]}],
    }


# Phase A: open play with no ball seen, blue (home) in the half toward x = 0 and red (away) toward
# x = 105, so the clip's colour vote names the sides before any restart (track.assign_teams).
OPEN = [(20.0, 20.0, BLUE), (20.0, 48.0, BLUE), (35.0, 34.0, BLUE), (40.0, 10.0, BLUE),
        (85.0, 20.0, RED), (85.0, 48.0, RED), (70.0, 34.0, RED), (65.0, 58.0, RED)]
# Law 8: a blue taker at the ball, every player in his own half, red outside the circle.
LAW8 = [(CX - 0.6, CY, BLUE), (40.0, 20.0, BLUE), (40.0, 48.0, BLUE), (45.0, 34.0, BLUE),
        (CX + rs.CIRCLE_M + 1.0, CY, RED), (65.0, 20.0, RED), (65.0, 48.0, RED), (75.0, 34.0, RED)]


def scene(set_up, ball_at=(CX, CY), still=STILL, kick_dx=-1.0, end=None):
    """Phase A, then from SET the players stand at `set_up` with the ball still at `ball_at` for
    `still` frames, then kicked along x by kick_dx at KICK_SPEED, up to frame `end`."""
    end = end if end is not None else SET + still + 50
    rows = [row(f, OPEN) for f in range(SET)]
    for f in range(SET, end):
        k = max(0, f - (SET + still - 1))
        rows.append(row(f, set_up, (ball_at[0] + kick_dx * KICK_SPEED * k / FPS, ball_at[1])))
    return rows


LAST_STILL = SET + STILL - 1
# The ball is still within STILL_M of the mark for these frames after it is kicked.
LAG = math.ceil(rs.STILL_M / (KICK_SPEED / FPS))


def test_a_kick_off_is_found_at_its_kick_with_the_side_taking_it():
    found, summary = rs.detect(scene(LAW8))
    assert [e["type"] for e in found] == ["kickoff"]
    k = found[0]
    assert LAST_STILL <= k["frame"] <= LAST_STILL + LAG
    assert k["team"] == "home" and k["source"] == "vision"
    assert math.hypot(k["x"] - CX, k["y"] - CY) <= rs.SPOT_M
    assert 0 < k["confidence"] <= 1
    assert summary["events"] == {"kickoff": 1}


def test_the_side_taking_it_is_the_one_inside_the_circle():
    away_takes = [(CX + 0.6, CY, RED) if c == BLUE and x == CX - 0.6 else (x, y, c) for x, y, c in LAW8]
    away_takes = [(CX - rs.CIRCLE_M - 1.0, CY, BLUE) if (x, c) == (CX + rs.CIRCLE_M + 1.0, RED) else (x, y, c)
                  for x, y, c in away_takes]
    found, _ = rs.detect(scene(away_takes, kick_dx=1.0))
    assert [e["team"] for e in found] == ["away"]


def test_a_still_ball_on_the_mark_with_the_sides_mixed_is_not_a_kick_off():
    mixed = [(CX - 0.6, CY, BLUE), (40.0, 20.0, BLUE), (65.0, 30.0, BLUE), (70.0, 44.0, BLUE),
             (CX + rs.CIRCLE_M + 1.0, CY, RED), (35.0, 20.0, RED), (30.0, 48.0, RED), (75.0, 34.0, RED)]
    found, summary = rs.detect(scene(mixed))
    assert summary["on_centre_mark"] == 1  # the ball was still on the mark; the players said no
    assert found == []


def test_an_opponent_inside_the_circle_counts_against_law_8():
    s = rs.stills(tr.ball_path(scene(LAW8)), [])[0]
    tracks = tr.track_players(scene(LAW8))
    tr.assign_teams(tracks)
    clean = rs.kick_off_arrangement(s, tracks)
    near = [(CX + 3.0, CY, RED) if (x, c) == (CX + rs.CIRCLE_M + 1.0, RED) else (x, y, c) for x, y, c in LAW8]
    tracks = tr.track_players(scene(near))
    tr.assign_teams(tracks)
    crowded = rs.kick_off_arrangement(s, tracks)
    assert clean["share"] == 1.0
    assert crowded["share"] < clean["share"]


def test_a_still_ball_off_the_centre_mark_is_not_a_kick_off():
    found, summary = rs.detect(scene(LAW8, ball_at=(CX - 3 * rs.SPOT_M, CY)))
    assert summary["still_spells"] == 1 and found == []


def test_too_short_a_still_is_not_a_set_ball():
    short = int(rs.MIN_STILL_S * FPS) - LAG - 2  # shorter than MIN_STILL_S even with the kick's lag
    assert rs.detect(scene(LAW8, still=short))[0] == []
    assert rs.detect(scene(LAW8, still=int(rs.MIN_STILL_S * FPS) + 1))[0] != []


def test_a_clip_that_ends_with_the_ball_still_says_nothing_yet():
    assert rs.detect(scene(LAW8, end=SET + STILL))[0] == []
    rows = scene(LAW8, end=SET + STILL)
    rows[-1]["ball"][0]["x"] = CX + 5 * rs.STILL_M  # one sighting off the spot, then the clip ends
    assert rs.detect(rows)[0] == []


def test_each_side_must_be_seen_in_its_own_half():
    blue_only = [p for p in LAW8 if p[2] == BLUE]
    assert rs.detect(scene(blue_only))[0] == []


def test_one_sighting_off_the_spot_does_not_end_the_still():
    rows = scene(LAW8)
    # The detector's error on one frame, late enough that the still before it is long enough alone.
    rows[LAST_STILL - 10]["ball"][0]["x"] = CX + 5 * rs.STILL_M
    found, summary = rs.detect(rows)
    assert summary["still_spells"] == 1
    assert [e["frame"] for e in found] == [rs.detect(scene(LAW8))[0][0]["frame"]]


def test_a_cut_between_the_still_ball_and_the_kick_says_nothing():
    rows = scene(LAW8)
    gap = 1  # one frame left out: a cut, though far shorter than a missing-ball gap
    assert gap < rs.SPELL_GAP_FRAMES
    rows = rows[:LAST_STILL + 1] + [r | {"frame": r["frame"] + gap} for r in rows[LAST_STILL + 1:]]
    assert rs.cut_frames(rows) == [LAST_STILL]
    assert rs.detect(rows)[0] == []


def test_merge_keeps_both_detectors_ids_in_time_order():
    a = [{"id": "v00001", "frame": 5, "type": "pass"}, {"id": "v00002", "frame": 30, "type": "shot"}]
    b = [{"id": "r00001", "frame": 20, "type": "kickoff"}]
    assert [e["id"] for e in rs.merge(a, b)] == ["v00001", "r00001", "v00002"]



# Boundaries, from the sources rather than the module's own constants (the merge queue's review):
# the position error is events.RIVAL_M (the players' measured p90), the circle Law 1's 9.15 m.
E = rs.ev.RIVAL_M


def test_the_centre_mark_is_found_within_the_position_error_and_not_beyond():
    assert [e["type"] for e in rs.detect(scene(LAW8, ball_at=(CX - (E - 0.3), CY)))[0]] == ["kickoff"]
    assert rs.detect(scene(LAW8, ball_at=(CX - (E + 0.4), CY)))[0] == []


def test_a_still_of_well_under_a_second_is_not_a_set_ball():
    assert rs.detect(scene(LAW8, still=12))[0] == []  # about half a second, the kick's lag included


def test_a_player_beyond_halfway_by_more_than_the_error_counts_against_law_8():
    s = rs.stills(tr.ball_path(scene(LAW8)), [])[0]
    over = [(CX + E + 1.0, 20.0, BLUE) if (x, y) == (40.0, 20.0) else (x, y, c) for x, y, c in LAW8]
    tracks = tr.track_players(scene(over))
    tr.assign_teams(tracks)
    assert rs.kick_off_arrangement(s, tracks)["share"] < 1.0


def test_nobody_inside_the_circle_means_nobody_is_taking_a_kick_off():
    away = [(CX - (9.15 - E) - 0.5, CY, BLUE) if (x, y) == (CX - 0.6, CY) else (x, y, c) for x, y, c in LAW8]
    away = [(38.0, 34.0, c) if (x, y) == (45.0, 34.0) else (x, y, c) for x, y, c in away]  # out of the circle
    assert rs.detect(scene(away, ball_at=(CX, CY)))[0] == []


def test_a_keeper_is_no_evidence_that_his_side_stands_in_its_half():
    white = [240.0, 240.0, 240.0]  # a keeper's kit, far in brightness from both outfield kits
    blue_and_away_keeper = [p for p in LAW8 if p[2] == BLUE] + [(104.5, CY, white)]
    tracks = tr.track_players(scene(blue_and_away_keeper))
    tr.assign_teams(tracks)
    assert [t.team for t in tracks if t.keeper] == ["away"]  # the premise: he is read as away's keeper
    assert rs.detect(scene(blue_and_away_keeper))[0] == []


def test_a_kick_off_confidence_is_the_ball_score_times_the_law_8_share():
    assert rs.detect(scene(LAW8))[0][0]["confidence"] == 0.8  # every player where Law 8 puts him
