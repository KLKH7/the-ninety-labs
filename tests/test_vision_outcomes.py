"""Shot outcomes from the ball's path (ninety/vision/outcomes.py, through events.detect).

Every scene is built here as observations, frame by frame (lesson 47): a blue (home) shooter at
(90, 34) strikes toward the goal at x = 105, which red (away) defends, with a green keeper. The
rules are the plan's (docs/eval/shot-outcomes-plan.md); inputs that must sit by a threshold are
derived from it (lesson 36), expected outcomes are written out (lesson 190).
"""

from __future__ import annotations

import math

import pytest

from ninety.vision import events as ev
from ninety.vision import outcomes as oc
from tests.test_vision_events import BLUE, FPS, GREEN_KEEPER, RED, crowd, row

KICK = 10


def shot_scene(path, frames=60, keeper=None, others=(), heights=None, kickoff_after=None, shooter=BLUE,
               taker=None):
    """The shooter has the ball until KICK; from then the ball is at path(f - KICK) (x, y), or
    absent where path returns None. `keeper`/`others`: (x, y) or a function of the frame giving
    it. `heights`: f -> (z, se) for a fitted flight height on the ball."""
    rows = []
    for f in range(frames):
        people = crowd(f) + [(90.0, 34.0, shooter)]
        for who, colour in ([(keeper, GREEN_KEEPER)] if keeper else []) + [(o, RED) for o in others]:
            people.append((*(who(f) if callable(who) else who), colour))
        ball = (90.3, 34.0) if f <= KICK else path(f - KICK)
        r = row(f, people, ball)
        if ball is not None and heights and heights(f) is not None:
            z, se = heights(f)
            r["ball"][0] |= {"z": z, "se": se, "flight": 0}
        rows.append(r)
    if kickoff_after is not None:
        rows += kickoff_rows(kickoff_after, rows[-1]["frame"] + 1, taker=taker)
    return rows


def kickoff_rows(own_halves: bool, first: int, frames: int = 10, off_spot: float = 0.5, taker=None):
    """After a cut: the ball still on the centre spot, blue (home) in its half (x < 52.5) and red
    in the other, or everyone on the wrong side. `taker`: a player of that colour by the ball, in his
    own half (none by default: nobody inside the centre circle)."""
    out = []
    for f in range(first + 200, first + 200 + frames):  # frame numbers jump: a cut
        blue_x, red_x = (40.0, 65.0) if own_halves else (65.0, 40.0)
        people = ([(blue_x, 10.0 + 6 * k, BLUE) for k in range(4)]
                  + [(red_x, 10.0 + 6 * k, RED) for k in range(4)])
        if taker is not None:
            people.append((oc.CENTRE[0] + (1.0 if taker == RED else -1.0), oc.CENTRE[1] + 1.0, taker))
        out.append(row(f, people, (oc.CENTRE[0] + off_spot, oc.CENTRE[1])))  # E_C is 0.688 m
    return out


def into_net(rest=(106.0, 35.0), speed=25.0):
    """From (90.3, 34) straight at `rest` at `speed` m/s, stopped there by the net."""
    def at(k):
        d = math.dist((90.3, 34.0), rest)
        s = min(1.0, speed * k / FPS / d)
        return 90.3 + (rest[0] - 90.3) * s, 34.0 + (rest[1] - 34.0) * s
    return at


def run(rows, context=None, saves=True):
    # The rules are tested with saves written; the live path does not write them (lesson 258).
    events, summary = ev.detect(rows, context_rows=context, saves=saves)
    shots = [e for e in events if e["type"] == "shot"]
    goals = [e for e in events if e["type"] == "goal"]
    return shots, goals, [e["type"] for e in events], summary


def test_a_ball_at_rest_in_the_net_is_a_goal_with_a_goal_event_and_no_out_of_play():
    shots, goals, types, _ = run(shot_scene(into_net()))
    assert [s["outcome"] for s in shots] == ["goal"]
    assert len(goals) == 1 and "out_of_play" not in types
    g = goals[0]
    assert g["team"] == "home" and g["x"] == 105.0 and g["player"] == shots[0]["player"]
    # The line alone: the ball's mean score over the in-net frames, 0.8 (amendment 3: no halvings).
    assert g["confidence"] == 0.8


def test_a_kick_off_after_the_goal_adds_evidence_and_one_with_players_in_the_wrong_halves_does_not():
    _, goals, _, _ = run(shot_scene(into_net(), kickoff_after=True))
    assert goals[0]["confidence"] == round(1 - (1 - 0.8) * (1 - 0.8), 3)  # 0.96
    _, goals, _, _ = run(shot_scene(into_net(), kickoff_after=False))
    assert goals[0]["confidence"] == 0.8


def test_a_known_height_under_the_bar_keeps_the_line_evidence_whole_and_one_over_it_is_no_goal():
    under = shot_scene(into_net(), heights=lambda f: (0.11, 0.05) if f > KICK else None)
    assert run(under)[1][0]["confidence"] == 0.8
    # Law 1's bar is 2.44 m, the ball's radius 0.11 m: a centre at 2.31 m give or take 0.01 m
    # (2.33 m at two standard errors) is under it; at 2.32 m (2.34 m) it is not.
    under_edge = shot_scene(into_net(), heights=lambda f: (2.31, 0.01) if f > KICK else None)
    assert run(under_edge)[1][0]["confidence"] == 0.8
    over = shot_scene(into_net(), heights=lambda f: (2.32, 0.01) if f > KICK else None)
    shots, goals, _, _ = run(over)
    assert goals == [] and shots[0]["outcome"] != "goal"


def test_a_ball_that_lands_beyond_the_net_or_in_the_side_netting_is_no_goal():
    for rest in ((105.0 + oc.NET_DEPTH_M + oc.E_X + 1.0, 34.0),
                 (106.0, 34.0 + oc.GOAL_HALF - oc.BALL_R + oc.E_Y + 0.5)):
        shots, goals, types, _ = run(shot_scene(into_net(rest)))
        assert goals == [], rest
        assert shots[0]["outcome"] == "off_target" and "out_of_play" in types


def test_a_ball_flying_through_the_goal_footprint_without_stopping_is_no_goal():
    shots, goals, _, _ = run(shot_scene(lambda k: (90.3 + 30.0 * k / FPS, 34.0)))
    assert goals == [] and shots[0]["outcome"] == "off_target"


def test_on_the_line_is_not_over_it():
    # Rule 1: the centre must be beyond the line by more than the radius plus E_X.
    on = 105.0 + oc.BALL_R + oc.E_X
    _, goals, _, _ = run(shot_scene(into_net((on - 1e-6, 34.0))))  # on it, clear of float rounding
    assert goals == []
    _, goals, _, _ = run(shot_scene(into_net((on + 0.05, 34.0))))
    assert len(goals) == 1


def test_a_ball_within_the_posts_by_the_error_is_in():
    edge = 34.0 + oc.GOAL_HALF - oc.BALL_R + oc.E_Y  # rule 2's own edge
    assert oc.E_Y > 0  # measured (docs/eval/shot-outcomes.json): the band near a post is not empty
    _, goals, _, _ = run(shot_scene(into_net((106.0, edge - 1e-6))))
    assert goals[0]["confidence"] == 0.8  # in, at the whole evidence (amendment 3: no halvings)
    _, goals, _, _ = run(shot_scene(into_net((106.0, edge + 0.05))))
    assert goals == []
    _, goals, _, _ = run(shot_scene(into_net((106.0, edge - 2 * oc.E_Y - 0.05))))
    assert goals[0]["confidence"] == 0.8  # clear of the band: the same


def keeper_catch(at=(103.0, 34.0)):
    """The ball flies at the keeper standing at `at` and stays with him."""
    def path(k):
        d = math.dist((90.3, 34.0), at) - 0.3
        s = min(1.0, 25.0 * k / FPS / d)
        return 90.3 + (at[0] - 0.3 - 90.3) * s, 34.0 + (at[1] - 34.0) * s
    return path


def test_a_shot_on_target_the_keeper_holds_is_a_save():
    shots, goals, _, summary = run(shot_scene(keeper_catch(), keeper=(103.0, 34.0)))
    assert goals == [] and [s["outcome"] for s in shots] == ["on_target"]
    assert summary["shot_outcomes"]["on_target"] == 1


def test_the_same_turn_at_an_outfield_defender_is_a_block():
    shots, _, _, _ = run(shot_scene(keeper_catch((97.0, 34.0)), keeper=(103.0, 34.0), others=[(97.0, 34.0)]))
    assert [s["outcome"] for s in shots] == ["blocked"]


def test_a_shot_that_goes_out_wide_of_the_post_is_off_target():
    wide = 34.0 + oc.GOAL_HALF + 0.6  # inside the shot rule's margin, outside the posts
    shots, goals, types, _ = run(shot_scene(lambda k: (90.3 + 25.0 * k / FPS, 34.0 + (wide - 34.0) * min(
        1.0, 25.0 * k / FPS / (105.0 - 90.3)))))
    assert goals == [] and [s["outcome"] for s in shots] == ["off_target"] and "out_of_play" in types


def test_the_kick_off_reads_players_from_the_tactical_views_when_they_are_given():
    rows = shot_scene(into_net(), kickoff_after=True)
    # The broadcast's own players at the kick-off removed; the tactical views say they were wrong.
    broadcast = [r | {"players": []} if r["frame"] >= 200 else r for r in rows]
    wrong = [r for r in shot_scene(into_net(), kickoff_after=False)]
    _, goals, _, _ = run(broadcast, context=wrong)
    assert goals[0]["confidence"] == 0.8
    right = [r for r in shot_scene(into_net(), kickoff_after=True)]
    _, goals, _, _ = run(broadcast, context=right)
    assert goals[0]["confidence"] == 0.96


@pytest.mark.parametrize("frames_in_net,goal", [(oc.IN_NET_FRAMES, True), (oc.IN_NET_FRAMES - 1, False)])
def test_the_net_must_hold_the_ball_in_net_frames(frames_in_net, goal):
    approach = into_net((104.5, 35.0))  # up to the line, not over it
    reach = math.ceil(math.dist((90.3, 34.0), (104.5, 35.0)) / (25.0 / FPS))

    def path(k):
        if k <= reach:
            return approach(k)
        if k <= reach + frames_in_net:
            return (106.0, 35.0)
        return None  # the ball no longer seen: picked out of the net, or hidden
    _, goals, _, _ = run(shot_scene(path))
    assert bool(goals) is goal


def parried(turn_deg):
    """The ball flies at the keeper at (103, 34) and leaves him at the same speed, turned by
    `turn_deg` toward +y, and goes on until it is out."""
    at = (102.7, 34.0)
    d = math.dist((90.3, 34.0), at)
    reach = d / (25.0 / FPS)
    a = math.radians(turn_deg)

    def path(k):
        if k <= reach:
            return 90.3 + (at[0] - 90.3) * k / reach, 34.0
        s = 25.0 * (k - reach) / FPS
        return at[0] + s * math.cos(a), at[1] + s * math.sin(a)
    return path


def test_a_parry_that_turns_the_ball_wide_at_the_keeper_is_a_save_and_a_slight_swerve_is_not_a_touch():
    # The ball keeps its speed, so only the change of direction can show the touch.
    shots, goals, _, _ = run(shot_scene(parried(60.0), keeper=(103.0, 34.0)))
    assert goals == [] and [s["outcome"] for s in shots] == ["on_target"]
    shots, _, _, _ = run(shot_scene(parried(20.0), keeper=(103.0, 34.0)))
    assert [s["outcome"] for s in shots] != ["on_target"]


def test_a_ball_kicked_out_of_the_net_toward_the_pitch_is_no_shot_and_no_second_goal():
    # After the goal a blue team-mate stands by the ball at rest in the net, then rolls it out toward
    # halfway: from behind the goal line its path crosses the line between the posts, and it is still
    # in the net for a moment after he strikes it (the demo clip's case).
    reach = math.ceil(math.dist((90.3, 34.0), (106.0, 35.0)) / (25.0 / FPS))
    out_at = reach + 30

    def path(k):
        if k <= out_at:
            return into_net()(k)
        return 106.0 - 4.5 * (k - out_at) / FPS, 35.0  # rolled out: four frames still in the net
    rows = shot_scene(path, frames=KICK + out_at + 30)
    for r in rows[KICK + reach + 10:]:  # he stands still by the ball; it leaves him faster than he carries
        r["players"].append({"bbox": [600, 0, 610, 30], "score": 0.9, "x": 106.3, "y": 35.0, "rgb": BLUE})
    shots, goals, _, _ = run(rows)
    assert len(goals) == 1 and [s["outcome"] for s in shots] == ["goal"]


def test_a_goal_no_detected_shot_led_to_is_still_a_goal_and_its_strike_a_shot():
    # A lofted strike whose ground track first runs wide of the goal (it bends as the ball rises and
    # falls), then comes in and rests in the net: no shot is read at the strike.
    def path(k):
        t = k / FPS
        if t <= 0.4:
            return 90.3 + 10.0 * t, 34.0 + 30.0 * t  # heading for y = 46 at the line: wide
        return into_net((106.0, 35.0))(k)
    shots, goals, types, _ = run(shot_scene(path))
    assert len(goals) == 1 and goals[0]["team"] == "home" and "out_of_play" not in types
    # The strike: the spell's last frame, up to SPEED_FRAMES before the kick (events.py).
    assert [s["outcome"] for s in shots] == ["goal"] and KICK - ev.SPEED_FRAMES <= shots[0]["frame"] <= KICK


def test_the_goal_is_when_the_ball_crossed_the_line_not_when_it_came_to_rest():
    # The ball first sits past the net's depth (a high ball placed long, as on the demo clip), then
    # settles in the net: the goal's frame is the first frame over the line.
    deep = 105.0 + oc.NET_DEPTH_M + oc.E_X + 0.2
    reach = math.ceil(math.dist((90.3, 34.0), (deep, 35.0)) / (25.0 / FPS))

    def path(k):
        if k <= reach + 8:
            return into_net((deep, 35.0))(k)
        return 106.0, 35.0
    rows = shot_scene(path)
    over = next(r["frame"] for r in rows if r["ball"] and r["ball"][0]["x"] - 105.0 > oc.BALL_R + oc.E_X)
    _, goals, _, _ = run(rows)
    assert len(goals) == 1 and goals[0]["frame"] == over


def restart_rows(first, at, frames=10, cut=True):
    """The ball still at `at` from frame `first` (+200: after a cut), players spread on both sides."""
    out = []
    start = first + (200 if cut else 0)
    for f in range(start, start + frames):
        people = ([(30.0, 10.0 + 6 * k, BLUE) for k in range(4)]
                  + [(75.0, 10.0 + 6 * k, RED) for k in range(4)])
        out.append(row(f, people, at))
    return out


def wide_then_unseen(k):
    """A shot struck at goal that leaves the picture after 0.4 s (the broadcast cuts away)."""
    return (90.3 + 25.0 * k / FPS, 34.0) if k <= 10 else None


def test_a_kick_off_after_a_shot_the_picture_lost_is_a_goal_for_the_shooters_side():
    rows = shot_scene(wide_then_unseen, frames=30) + kickoff_rows(True, 30)
    shots, goals, _, _ = run(rows)
    assert [s["outcome"] for s in shots] == ["goal"] and len(goals) == 1 and goals[0]["team"] == "home"
    assert goals[0]["confidence"] == 0.8  # the kick-off's own evidence, the net unseen
    assert goals[0]["frame"] == KICK + 10  # the ball's last point nearest the line before the restart


def test_a_kick_off_with_the_players_in_the_wrong_halves_is_no_restart():
    rows = shot_scene(wide_then_unseen, frames=30) + kickoff_rows(False, 30)
    _, goals, _, _ = run(rows)
    assert goals == []


def test_a_goal_kick_after_a_shot_means_no_goal():
    # The shot goes on over the goal line wide of the post (crossing at y = 38.1: past the post's
    # 37.66, inside the shot rule's margin), then the ball is set in the goal area.
    def path(k):
        return 90.3 + 25.0 * k / FPS, 34.0 + 7.0 * k / FPS
    rows = shot_scene(path, frames=30) + restart_rows(30, (105.0 - 4.0, 30.0))
    shots, goals, _, _ = run(rows)
    assert goals == [] and [s["outcome"] for s in shots] == ["off_target"]


def test_a_corner_after_a_shot_on_target_is_a_save():
    rows = shot_scene(wide_then_unseen, frames=30) + restart_rows(30, (105.0 - 0.5, 0.5))
    shots, goals, _, _ = run(rows)
    assert goals == [] and [s["outcome"] for s in shots] == ["on_target"]


def test_a_keeper_holding_his_catch_in_his_goal_area_is_no_goal_kick():
    # No dead ball between: the save stands, it is not read as a shot that went out.
    rows = shot_scene(keeper_catch(), keeper=(103.0, 34.0), frames=60)
    shots, _, _, _ = run(rows)
    assert [s["outcome"] for s in shots] == ["on_target"]


@pytest.mark.parametrize("d,kind", [(5.5, "goal_kick"), (5.5 + 0.093 + 0.05, None)])
def test_the_goal_area_is_law_1s_and_the_measured_error_and_no_more(d, kind):
    # 5.5 m from the line plus E_X (0.093 m) is inside; 0.05 m beyond is not (Law 1, measured error).
    from ninety.vision.track import BallPoint
    p = BallPoint(0, 105.0 - d, 34.0, 0.9)
    assert oc.restart_kind(p, "home", [0], []) == kind


def test_a_ball_still_beyond_the_spots_measured_error_is_no_kick_off():
    # 0.75 m from the spot is beyond E_C (0.688 m, the measured position error there).
    rows = shot_scene(wide_then_unseen, frames=30) + kickoff_rows(True, 30, off_spot=0.75)
    _, goals, _, _ = run(rows)
    assert goals == []


# Amendment 3 (docs/eval/shot-outcomes-plan.md), from the validation diagnosis.


def test_a_ball_drawn_over_the_keeper_behind_the_line_is_no_goal():
    # A catch at the line: the ball in his hands, placed on the ground, lands behind it. Drawn over
    # the keeper's box (the 10th player: the crowd's 8, the shooter, then him), it is passed over, as
    # out_of_play passes it over; the same ball drawn clear of him is in the net.
    def scene(over_keeper):
        rows = shot_scene(into_net(), keeper=(104.0, 34.0))
        for r in rows:
            if r["ball"] and r["ball"][0]["x"] > oc.PITCH_X and over_keeper:
                r["ball"][0]["bbox"] = [182, 10, 188, 16]  # inside the keeper's [180, 0, 190, 30]
        return rows
    assert run(scene(over_keeper=False))[1] != []  # the premise: clear of him it is a goal
    assert run(scene(over_keeper=True))[1] == []


def lofted(end, frames_wide=8):
    """A lofted strike's ground track: for its first frames it bends wide (toward y 45 at the goal
    line), then comes down to `end` and stays there."""
    def path(k):
        if k <= frames_wide:
            return 90.3 + 1.6 * k, 34.0 + 0.8 * k
        bend = (90.3 + 1.6 * frames_wide, 34.0 + 0.8 * frames_wide)
        s = min(1.0, (k - frames_wide) / 4)
        return bend[0] + (end[0] - bend[0]) * s, bend[1] + (end[1] - bend[1]) * s
    return path


def test_a_lofted_shot_the_keeper_takes_is_a_save():
    # Its first 0.3 s heads wide (no shot by the opening line), but the move ends in the keeper's
    # hands in his area, on a line between the posts: a shot, and on target by that line.
    p, q = lofted((102.7, 34.0))(0), lofted((102.7, 34.0))(int(ev.SHOT_LOOK_S * FPS))
    opening = oc.line_y(oc.BallPoint(0, *p, 0.9), oc.BallPoint(1, *q, 0.9), "home")
    assert opening > ev.POST_Y[1] + ev.SHOT_MARGIN_M  # the premise
    shots, goals, _, _ = run(shot_scene(lofted((102.7, 34.0)), keeper=(103.0, 34.0)))
    assert goals == [] and [s["outcome"] for s in shots] == ["on_target"]


def test_the_same_move_ending_with_an_outfield_defender_is_no_shot():
    shots, _, types, _ = run(shot_scene(lofted((102.7, 34.0)), keeper=(104.5, 20.0), others=[(103.0, 34.0)]))
    assert shots == [] and "pass" in types


def test_a_shot_the_kit_reads_for_the_other_side_is_still_a_shot_for_the_side_attacking_that_goal():
    # The striker's kit reads red (away), but his strike heads at the goal home attacks and is blocked
    # by a red defender: it ends at no goal, so only testing both goals' opening lines finds the shot.
    shots, _, _, _ = run(shot_scene(keeper_catch((97.0, 34.0)), keeper=(103.0, 34.0), others=[(97.0, 34.0)],
                                    shooter=RED))
    assert [(s["team"], s["outcome"], s["team_confidence"]) for s in shots] == [("home", "blocked", None)]


# Amendment 4: a ball over a goal line, unseen in the net, then a kick-off.


def roof_of_net(k):
    """A lofted strike whose ground track bends wide (no shot is read at it) and, placed on the
    ground, lands beyond the net's depth (rules 1 to 3 cannot see it), where it stays."""
    return lofted((111.0, 45.0))(k)


def test_a_ball_over_the_goal_line_then_a_kick_off_is_a_goal():
    shots, goals, types, _ = run(shot_scene(roof_of_net, kickoff_after=True))
    assert [(g["team"], g["x"], g["confidence"]) for g in goals] == [("home", 105.0, 0.8)]  # the kick-off's
    assert [s["outcome"] for s in shots] == ["goal"]  # his strike becomes the shot
    assert "out_of_play" not in types


def test_the_same_ball_with_no_kick_off_or_a_wrong_one_is_out_of_play():
    for after in (None, False):  # no restart seen; players in the wrong halves (no kick-off by Law 8)
        shots, goals, types, _ = run(shot_scene(roof_of_net, kickoff_after=after))
        assert goals == [] and shots == [] and "out_of_play" in types


# Amendment 5: after a goal the side that conceded kicks off (Law 8); the scorer's own side kicking off
# is a half's start.


def test_a_kick_off_by_the_side_that_conceded_is_a_goal_and_by_the_scorers_side_is_not():
    _, goals, _, _ = run(shot_scene(roof_of_net, kickoff_after=True, taker=RED))
    assert [(g["team"], g["confidence"]) for g in goals] == [("home", 0.8)]
    _, goals, types, _ = run(shot_scene(roof_of_net, kickoff_after=True, taker=BLUE))
    assert goals == [] and "out_of_play" in types


def test_a_kick_off_by_the_scorers_side_adds_no_evidence_to_a_goal_seen_in_the_net():
    _, goals, _, _ = run(shot_scene(into_net(), kickoff_after=True, taker=RED))
    assert goals[0]["confidence"] == round(1 - (1 - 0.8) * (1 - 0.8), 3)
    _, goals, _, _ = run(shot_scene(into_net(), kickoff_after=True, taker=BLUE))
    assert goals[0]["confidence"] == 0.8  # the line alone


# Lesson 258: saves do not work from video yet, so the live path never says a shot was saved.


def test_the_live_path_writes_a_detected_save_as_a_shot_with_no_outcome():
    assert ev.SAVES_AIR is False
    scene = shot_scene(keeper_catch(), keeper=(103.0, 34.0))
    assert [s["outcome"] for s in run(scene)[0]] == ["on_target"]  # the premise: the rule sees a save
    shots, goals, _, summary = run(scene, saves=False)
    assert goals == [] and [s["outcome"] for s in shots] == [None]
    assert summary["shot_outcomes"]["on_target"] == 0


def test_goals_and_the_other_outcomes_are_written_as_before():
    assert [g["type"] for g in run(shot_scene(into_net()), saves=False)[1]] == ["goal"]
    shots = run(shot_scene(keeper_catch((97.0, 34.0)), keeper=(103.0, 34.0), others=[(97.0, 34.0)]),
                saves=False)[0]
    assert [s["outcome"] for s in shots] == ["blocked"]
