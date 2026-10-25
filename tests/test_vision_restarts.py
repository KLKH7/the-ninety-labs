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
    assert summary["events"]["kick_off"] == 1 and sum(summary["events"].values()) == 1


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
    assert summary["still_spells"] == 1 and [e for e in found if e["type"] == "kickoff"] == []


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


# Set pieces. Phase A names the sides as above; in phase B the players stand as each Law says.
PX = 105.0  # the goal home attacks
# A set piece follows a stoppage: here the set ball is seen still for the whole of it.
STOPPAGE = int(rs.MIN_STOPPAGE_S * FPS) + 1


def set_scene(set_up, **kw):
    return scene(set_up, still=STOPPAGE, **kw)


def test_where_a_still_ball_lies_says_which_restart_it_can_be():
    e = rs.POSITION_ERROR_M
    assert rs.place_kind(CX, CY) == "kick_off"
    assert rs.place_kind(PX - 0.5, 0.5) == rs.place_kind(0.5, 67.5) == "corner"
    assert rs.place_kind(PX - rs.GOAL_AREA_X, CY + rs.GOAL_AREA_HALF_Y) == "goal_kick"
    assert rs.place_kind(rs.GOAL_AREA_X + e + 0.1, CY) == "free_kick"
    assert rs.place_kind(PX - rs.PENALTY_MARK_M, CY) == rs.place_kind(rs.PENALTY_MARK_M, CY) == "penalty_kick"
    assert rs.place_kind(40.0, 20.0) == "free_kick"
    assert rs.place_kind(40.0, -e - 0.1) is None  # off the field: out of play, not set


CORNER = [(PX - 1.5, 1.5, BLUE), (PX - 12.0, 30.0, BLUE), (PX - 8.0, 40.0, RED), (PX - 4.0, 34.0, RED),
          (PX - 14.0, 12.0, RED), (60.0, 30.0, BLUE), (55.0, 40.0, RED), (30.0, 34.0, BLUE)]


def test_a_corner_is_found_for_the_side_attacking_that_goal():
    found, _ = rs.detect(set_scene(CORNER, ball_at=(PX - 0.5, 0.5), kick_dx=-1.0))
    assert [(e["type"], e.get("restart"), e["team"]) for e in found] == [("set_piece", "corner", "home")]


def test_a_corner_with_an_opponent_at_the_ball_is_not_taken_as_one():
    crowded = CORNER + [(PX - 3.0, 3.0, RED)]
    assert rs.detect(set_scene(crowded, ball_at=(PX - 0.5, 0.5)))[0] == []


GOAL_KICK = [(2.0, CY + 2.0, BLUE), (16.0, 20.0, BLUE), (16.0, 48.0, BLUE), (40.0, 34.0, BLUE),
             (rs.PENALTY_AREA_X + 3.0, 30.0, RED), (rs.PENALTY_AREA_X + 6.0, 45.0, RED), (50.0, 20.0, RED),
             (70.0, 34.0, RED)]


def test_a_goal_kick_is_found_for_the_side_defending_that_goal():
    found, _ = rs.detect(set_scene(GOAL_KICK, ball_at=(3.0, CY + 3.0), kick_dx=1.0))
    assert [(e.get("restart"), e["team"]) for e in found] == [("goal_kick", "home")]


def test_an_attacker_inside_the_penalty_area_stops_a_goal_kick():
    inside = GOAL_KICK + [(10.0, 40.0, RED)]
    assert rs.detect(set_scene(inside, ball_at=(3.0, CY + 3.0), kick_dx=1.0))[0] == []


FREE_KICK = [(39.4, 20.0, RED), (30.0, 30.0, RED), (45.0, 40.0, RED), (60.0, 34.0, RED),
             (40.0 - rs.CIRCLE_M - 0.5, 20.0, BLUE), (25.0, 26.0, BLUE), (25.0, 14.0, BLUE),
             (20.0, 34.0, BLUE)]


def test_a_free_kick_is_the_taker_side_with_opponents_kept_back():
    found, _ = rs.detect(set_scene(FREE_KICK, ball_at=(40.0, 20.0), kick_dx=-1.0))
    assert [(e.get("restart"), e["team"]) for e in found] == [("free_kick", "away")]


def test_a_ball_held_still_with_an_opponent_close_is_open_play_not_a_free_kick():
    pressed = FREE_KICK + [(43.0, 22.0, BLUE)]
    assert rs.detect(set_scene(pressed, ball_at=(40.0, 20.0)))[0] == []


def test_a_still_ball_with_nobody_at_it_is_not_a_free_kick():
    far = [(x + 8.0, y, c) if c == RED else (x, y, c) for x, y, c in FREE_KICK]
    assert rs.detect(set_scene(far, ball_at=(40.0, 20.0)))[0] == []


GREEN = [60.0, 230.0, 170.0]  # a goalkeeper's kit, far from both outfield kits
WHITE = [240.0, 240.0, 240.0]  # another, far in brightness (the kit feature this scene's sides choose)
PENALTY = [(PX - rs.PENALTY_MARK_M - 0.6, CY, BLUE), (PX - 0.2, CY, WHITE),
           (PX - rs.PENALTY_AREA_X - 3.0, 20.0, BLUE), (PX - rs.PENALTY_AREA_X - 3.0, 48.0, BLUE),
           (PX - rs.PENALTY_AREA_X - 2.0, 30.0, RED), (PX - rs.PENALTY_AREA_X - 2.0, 40.0, RED),
           (60.0, 20.0, RED), (40.0, 34.0, BLUE)]


def test_a_penalty_is_found_with_only_the_taker_and_the_keeper_in_the_area():
    tracks = tr.track_players(set_scene(PENALTY))
    tr.assign_teams(tracks)
    assert [t.keeper for t in tracks if t.at(SET + 1) == (PX - 0.2, CY)] == [True]  # the premise
    found, _ = rs.detect(set_scene(PENALTY, ball_at=(PX - rs.PENALTY_MARK_M, CY), kick_dx=1.0))
    assert [(e.get("restart"), e["team"]) for e in found] == [("penalty_kick", "home")]


def test_a_third_player_in_the_area_stops_a_penalty():
    inside = PENALTY + [(PX - 8.0, CY + 5.0, RED)]
    assert rs.detect(set_scene(inside, ball_at=(PX - rs.PENALTY_MARK_M, CY), kick_dx=1.0))[0] == []


def test_a_keeper_holding_the_ball_in_his_area_is_not_a_free_kick():
    hold = [(12.0, CY + 10.0, GREEN), (25.0, 20.0, BLUE), (25.0, 48.0, BLUE), (40.0, 34.0, BLUE),
            (35.0, 30.0, RED), (45.0, 50.0, RED), (60.0, 20.0, RED), (70.0, 34.0, RED)]
    tracks = tr.track_players(set_scene(hold, ball_at=(12.0, CY + 10.3)))
    tr.assign_teams(tracks)
    assert [t.keeper for t in tracks if t.at(SET + 1) == (12.0, CY + 10.0)] == [True]  # the premise
    assert rs.detect(set_scene(hold, ball_at=(12.0, CY + 10.3), kick_dx=1.0))[0] == []


def test_every_restart_is_a_valid_match_event():
    import json
    from pathlib import Path

    import jsonschema
    schema = json.loads((Path(__file__).parents[1] / "schemas" / "match_event.schema.json").read_text())
    found = (rs.detect(scene(LAW8))[0] + rs.detect(set_scene(CORNER, ball_at=(PX - 0.5, 0.5)))[0]
             + rs.detect(set_scene(GOAL_KICK, ball_at=(3.0, CY + 3.0), kick_dx=1.0))[0]
             + rs.detect(set_scene(FREE_KICK, ball_at=(40.0, 20.0)))[0]
             + rs.detect(set_scene(PENALTY, ball_at=(PX - rs.PENALTY_MARK_M, CY), kick_dx=1.0))[0])
    assert {e.get("restart") for e in found} == {None, "corner", "goal_kick", "free_kick", "penalty_kick"}
    for e in found:
        jsonschema.validate(e, schema)


def test_a_set_ball_needs_a_stoppage_seen_before_it():
    at = {"ball_at": (40.0, 20.0)}
    assert rs.detect(scene(FREE_KICK, **at))[0] == []  # 2 s still in play, nothing cut: held, not set
    assert rs.detect(scene(FREE_KICK, still=STOPPAGE - LAG - 2, **at))[0] == []
    assert rs.detect(set_scene(FREE_KICK, **at))[0] != []
    # Just after a cut, the wait having been left out, 2 s is enough; not as the clip happens to start.
    rows = scene(FREE_KICK, **at)
    cut = rows[:SET - 1] + [r | {"frame": r["frame"] + 300} for r in rows[SET - 1:]]
    assert [e.get("restart") for e in rs.detect(cut)[0]] == ["free_kick"]
    assert rs.detect(rows[SET:])[0] == []


THROW = [(60.0, -0.5, RED), (66.0, 6.0, RED), (75.0, 20.0, RED), (85.0, 34.0, RED),
         (55.0, 5.0, BLUE), (50.0, 20.0, BLUE), (40.0, 40.0, BLUE), (30.0, 34.0, BLUE)]


def test_a_throw_in_is_the_side_holding_the_ball_on_the_touchline():
    found, _ = rs.detect(set_scene(THROW, ball_at=(60.2, -0.3), kick_dx=1.0))
    assert [(e.get("restart"), e["team"]) for e in found] == [("throw_in", "away")]
    near = THROW + [(60.6, 0.2, BLUE)]  # an opponent at the thrower, within 2 m by more than the error
    assert rs.detect(set_scene(near, ball_at=(60.2, -0.3), kick_dx=1.0))[0] == []


def test_a_kick_hidden_by_the_taker_for_up_to_a_second_is_still_seen():
    rows = set_scene(FREE_KICK, ball_at=(40.0, 20.0))
    kick = SET + STOPPAGE - 1
    hidden = tr.MAX_GAP_FRAMES - 1  # the tracker's wait for a hidden player, the rule's source
    for r in rows[kick + 1:kick + 1 + hidden]:
        r["ball"] = []
    assert [e.get("restart") for e in rs.detect(rows)[0]] == ["free_kick"]
    for r in rows[kick + 1:kick + 3 + tr.MAX_GAP_FRAMES]:
        r["ball"] = []  # lost longer than that: whether it was kicked is not seen
    assert rs.detect(rows)[0] == []


def test_a_ball_seen_rolling_to_a_stop_after_a_cut_does_not_open_the_picture():
    rows = scene(FREE_KICK, ball_at=(40.0, 20.0))
    cut = rows[:SET - 1] + [r | {"frame": r["frame"] + 300} for r in rows[SET - 1:]]
    for k, r in enumerate(cut[SET - 1:SET + 2]):  # seen rolling in for three frames, then still
        r["ball"] = [{"bbox": [0, 500, 8, 508], "score": 0.8, "x": 40.0 - 4.0 + 1.0 * k, "y": 20.0}]
    assert rs.detect(cut)[0] == []


def test_each_place_has_the_position_error_and_no_more():
    e, d = rs.POSITION_ERROR_M, 0.05
    arc_in, arc_out = (rs.CORNER_ARC_M + e - d) / math.sqrt(2), (rs.CORNER_ARC_M + e + d) / math.sqrt(2)
    assert rs.place_kind(PX - arc_in, arc_in) == "corner"
    assert rs.place_kind(PX - arc_out, arc_out) == "free_kick"
    assert rs.place_kind(rs.GOAL_AREA_X + e - d, CY) == "goal_kick"
    assert rs.place_kind(rs.GOAL_AREA_X + e + d, CY) == "free_kick"
    assert rs.place_kind(40.0, 68.0 - e + d) == "throw_in"  # the far touchline too
    assert rs.place_kind(40.0, 68.0 - e - d) == "free_kick"


def test_an_opponent_is_held_to_9_15_m_only_beyond_the_position_error():
    at = {"ball_at": (40.0, 20.0)}
    edge = rs.CIRCLE_M - rs.POSITION_ERROR_M
    assert rs.detect(set_scene(FREE_KICK + [(40.0, 20.0 + edge + 0.1, BLUE)], **at))[0] != []
    assert rs.detect(set_scene(FREE_KICK + [(40.0, 20.0 + edge - 0.1, BLUE)], **at))[0] == []


def test_a_taker_must_be_within_reach_of_the_ball():
    reach = rs.ev.CONTROL_M + rs.POSITION_ERROR_M
    for d, n in ((reach - 0.2, 1), (reach + 0.2, 0)):
        moved = [(40.0 - d, 20.0, RED) if (x, y) == (39.4, 20.0) else (x, y, c) for x, y, c in FREE_KICK]
        assert len(rs.detect(set_scene(moved, ball_at=(40.0, 20.0)))[0]) == n


def test_an_attacker_inside_the_area_by_less_than_the_error_does_not_stop_a_goal_kick():
    edge = [(rs.PENALTY_AREA_X - rs.POSITION_ERROR_M + 0.2, 30.0, RED)]
    found, _ = rs.detect(set_scene(GOAL_KICK + edge, ball_at=(3.0, CY + 3.0), kick_dx=1.0))
    assert [e.get("restart") for e in found] == ["goal_kick"]


def test_a_corner_at_the_other_end_is_the_other_side_with_its_taker_named():
    mirrored = [(PX - x, 68.0 - y, RED if c == BLUE else BLUE) for x, y, c in CORNER]
    found, _ = rs.detect(set_scene(mirrored, ball_at=(0.5, 67.5), kick_dx=1.0))
    assert [(e.get("restart"), e["team"]) for e in found] == [("corner", "away")]
    home, _ = rs.detect(set_scene(CORNER, ball_at=(PX - 0.5, 0.5)))
    assert home[0]["player"] is not None and home[0]["confidence"] == 0.8  # the ball detection's score


def test_a_keeper_holding_the_ball_in_his_goal_area_is_not_a_goal_kick():
    keeper = [(2.0, CY + 2.0, WHITE)] + GOAL_KICK[1:]
    rows = set_scene(keeper, ball_at=(2.3, CY + 2.3), kick_dx=1.0)
    assert [e.get("restart") for e in rs.detect(rows)[0]] == ["goal_kick"]  # the ball on the grass
    for r in rows[SET:SET + STOPPAGE]:  # now drawn over him: in his hands
        r["ball"][0]["bbox"] = [2, 10, 8, 16]
    assert rs.detect(rows)[0] == []


def test_a_set_piece_names_no_taker_when_nobody_of_its_side_is_at_the_ball():
    no_taker = [p for p in CORNER if p[:2] != (PX - 1.5, 1.5)]
    found, _ = rs.detect(set_scene(no_taker, ball_at=(PX - 0.5, 0.5)))
    assert [(e.get("restart"), e["player"], e["team_confidence"]) for e in found] == [("corner", None, None)]



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


def test_a_possession_change_while_the_ball_is_set_is_the_restart_not_a_change():
    from ninety.vision import events as ev
    rows = scene(LAW8)
    for r in rows[50:SET]:  # before it, red holds the ball at (70, 34) in play: his spell
        r["ball"] = [{"bbox": [0, 500, 8, 508], "score": 0.8, "x": 70.3, "y": 34.0}]
    found, summary = rs.detect(rows)
    events, _ = ev.detect(rows)
    [(a, b)] = summary["dead_balls"]
    changes = [e for e in events if e["type"] == "possession_change"]
    assert [e["frame"] for e in changes if a <= e["frame"] <= b] != []  # the premise: events gives one
    merged = rs.merge(events, found, summary["dead_balls"])
    assert [e for e in merged if e["type"] == "possession_change" and a <= e["frame"] <= b] == []
    assert [e["id"] for e in rs.merge(events, found)] == [e["id"] for e in sorted(
        events + found, key=lambda e: (e["frame"], e["type"]))]  # without the dead balls, nothing is dropped
    other = {"id": "v99999", "frame": a + 1, "type": "pass"}  # only possession changes are dropped
    assert other in rs.merge(events + [other], found, summary["dead_balls"])


def test_the_side_confidence_is_the_takers_and_a_taker_with_a_rival_as_near_is_unnamed():
    duller = [44.0, 62.0, 186.0]  # the taker's shirt a little off his kit: his side less firmly told
    set_up = [(x, y, duller) if (x, y) == (CX - 0.6, CY) else (x, y, c) for x, y, c in LAW8]
    rows = scene(set_up)
    tracks = tr.track_players(rows)
    tr.assign_teams(tracks)
    taker = next(t for t in tracks if t.at(SET + 1) == (CX - 0.6, CY))
    assert taker.team == "home" and taker.side_confidence < 1.0  # the premise
    [k] = rs.detect(rows)[0]
    assert k["team_confidence"] == taker.side_confidence and k["player"] is not None
    crowded = LAW8 + [(CX - 0.6, CY + 1.0, BLUE)]  # a team-mate within the position error of as near
    [k] = rs.detect(scene(crowded))[0]
    assert k["player"] is None and k["team"] == "home"


def test_a_set_piece_still_is_a_dead_ball_too():
    found, summary = rs.detect(set_scene(FREE_KICK, ball_at=(40.0, 20.0)))
    assert [e.get("restart") for e in found] == ["free_kick"]
    assert summary["dead_balls"] == [[SET, found[0]["frame"]]]
