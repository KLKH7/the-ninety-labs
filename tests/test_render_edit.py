"""The broadcast's edit (ninety/render/edit.py): it cuts only through a dead ball, never over an
event, holds the stoppage and the restart, and maps video time to match time across its cuts."""

from ninety.render import edit
from ninety.render.edit import Cut, Timeline

FPS = 25


def ev(frame, kind):
    return {"frame": frame, "type": kind, "t": frame / FPS}


def test_a_long_dead_ball_is_cut_from_after_the_stoppage_to_before_the_restart():
    # A throw-in 16 s after the ball went out (GROUNDING R1).
    events = [ev(100, "pass"), ev(130, "out_of_play"), ev(530, "set_piece"), ev(560, "pass")]
    (c,) = edit.cuts(events, FPS)
    assert c.first_frame == 130 + round(edit.HOLD_AFTER_STOP_S * FPS) + 1
    assert c.last_frame == 530 - round(edit.SHOW_BEFORE_RESTART_S * FPS) - 1


def test_a_goal_is_held_longer_before_the_cut_to_the_kickoff():
    events = [ev(100, "shot"), ev(120, "goal"), ev(1100, "kickoff")]
    (c,) = edit.cuts(events, FPS)
    assert c.first_frame == 120 + round(edit.HOLD_AFTER_GOAL_S * FPS) + 1


def test_a_short_wait_is_shown_whole():
    # The frames held after the stoppage and before the restart, the stoppage's own frame, and a
    # cut of at least MIN_CUT_S between them.
    held = round(edit.HOLD_AFTER_STOP_S * FPS) + round(edit.SHOW_BEFORE_RESTART_S * FPS) + 1
    shortest = held + round(edit.MIN_CUT_S * FPS)
    assert edit.cuts([ev(100, "out_of_play"), ev(100 + shortest - 1, "set_piece")], FPS) == []
    (c,) = edit.cuts([ev(100, "out_of_play"), ev(100 + shortest, "set_piece")], FPS)
    assert c.last_frame - c.first_frame + 1 == round(edit.MIN_CUT_S * FPS)


def test_play_is_never_cut():
    # No stoppage before the restart (a window that opens on one), a kickoff on the goal's own frame
    # (the engine resetting the teams at once), and an event inside the dead ball: no cut.
    assert edit.cuts([ev(100, "pass"), ev(900, "set_piece")], FPS) == []
    assert edit.cuts([ev(100, "goal"), ev(100, "kickoff")], FPS) == []
    events = [ev(100, "out_of_play"), ev(400, "pressure"), ev(900, "set_piece")]
    assert edit.cuts(events, FPS) == []


def test_a_second_stoppage_before_the_restart_does_not_start_another_dead_ball():
    events = [ev(100, "foul"), ev(105, "out_of_play"), ev(900, "set_piece"), ev(950, "out_of_play"),
              ev(1300, "set_piece")]
    assert [(s, r) for s, r, _ in edit.dead_balls(events)] == [(100, 900), (950, 1300)]


def test_the_shown_frames_skip_the_cuts_and_a_start_inside_one_opens_after_it():
    cuts = [Cut(10, 19), Cut(30, 39)]
    assert edit.shown(5, 12, cuts, 100) == [5, 6, 7, 8, 9, 20, 21, 22, 23, 24, 25, 26]
    assert edit.shown(12, 3, cuts, 100) == [20, 21, 22]
    assert edit.shown(25, 10, cuts, 45) == [25, 26, 27, 28, 29, 40, 41, 42, 43, 44]
    assert edit.used(cuts, edit.shown(5, 12, cuts, 100)) == [Cut(10, 19)]


def test_the_timeline_maps_video_time_to_match_time_across_a_cut():
    shown = edit.shown(5, 12, [Cut(10, 19)], 100)
    segs = edit.segments(shown)
    assert [s.as_dict() for s in segs] == [{"index": 0, "frame": 5, "frames": 5},
                                          {"index": 5, "frame": 20, "frames": 7}]
    tl = Timeline([s.as_dict() for s in segs], FPS)
    for i, f in enumerate(shown):
        assert abs(tl.to_match(i / FPS) - f / FPS) < 1e-9
        assert abs(tl.to_video(f / FPS) - i / FPS) < 1e-9
    # A match time inside the cut is shown where the cut is, and before the clip at its start.
    assert tl.to_video(15 / FPS) == 5 / FPS
    assert tl.to_video(0.0) == 0.0


def test_a_clip_cuts_only_a_dead_ball_whose_stoppage_and_restart_it_shows():
    """Coordinator decision (Oct 20): the dead ball is on screen at both ends of a cut. A clip that
    opens inside a dead ball, or ends before its restart, shows every frame of it instead."""
    c = Cut(110, 189, stop=100, restart=200)
    frames, made = edit.plan(90, 60, [c], 1000)  # from before the stoppage to past the restart
    assert made == [c] and frames[:20] == list(range(90, 110)) and frames[20:] == list(range(190, 230))
    frames, made = edit.plan(105, 60, [c], 1000)  # opens after the stoppage
    assert made == [] and frames == list(range(105, 165))
    frames, made = edit.plan(90, 25, [c], 1000)  # ends before the restart
    assert made == [] and frames == list(range(90, 115))
    # With both cuts the clip would end at 349, one frame before b's restart: b is left out, and the
    # clip shows b's wait up to its own end instead.
    a, b = Cut(110, 189, stop=100, restart=200), Cut(260, 339, stop=250, restart=350)
    frames, made = edit.plan(90, 100, [a, b], 1000)
    assert made == [a] and frames == list(range(90, 110)) + list(range(190, 270))


def test_every_hold_is_at_least_the_shortest_shot():
    """No shot before a cut flickers (CUT_HOLD_S). The shot after it runs on into the restart's play,
    and the camera holds it CUT_HOLD_S (test_render_camera)."""
    from ninety.render.camera import CUT_HOLD_S

    assert edit.HOLD_AFTER_STOP_S >= CUT_HOLD_S and edit.HOLD_AFTER_GOAL_S >= CUT_HOLD_S


def test_the_picture_comes_back_when_the_restart_is_imminent():
    """Demo v1's critic (#4, #5): the picture came back 6 s before each restart, on a frozen close-up
    of the taker alone. It now comes back between 1 and 2.5 s before the restart: the taker is seen
    set, and nobody stands still for long (bounds written before the change)."""
    events = [ev(100, "pass"), ev(130, "out_of_play"), ev(530, "set_piece"), ev(560, "pass")]
    (c,) = edit.cuts(events, FPS)
    back = 530 - (c.last_frame + 1)
    assert 1.0 * FPS <= back <= 2.5 * FPS, back


def test_a_goal_is_held_for_the_scorers_celebration():
    """Demo v1's critic (#5, #8): the goal was cut to the kick-off with no celebration. The goal is
    held at least 7 s: the engine's scorer reaches the corner flag about 5 s after a goal and his
    team-mates join him (seed 8001), and the picture stays on them until the cut."""
    assert edit.HOLD_AFTER_GOAL_S >= 7.0


def test_each_cut_has_a_stinger_centred_on_it():
    """Demo v1's critic (#6): the clock jumped at each cut with no transition. Every cut gets a
    stinger: progress from -1 to 1 over at most STINGER_S, crossing 0 between the last frame before
    the cut and the first after it, the same number of frames each side; frames away from a cut and
    a clip with no cut have none."""
    shown = list(range(100, 160)) + list(range(400, 460))
    marks = edit.stingers(shown, FPS)
    covered = sorted(marks)
    assert covered, marks
    assert len(covered) <= round(edit.STINGER_S * FPS) + 1
    before = [i for i in covered if marks[i] < 0]
    after = [i for i in covered if marks[i] > 0]
    assert before and after and len(before) == len(after)
    assert max(before) == 59 and min(after) == 60
    seq = [marks[i] for i in covered]
    assert seq == sorted(seq) and -1 <= seq[0] and seq[-1] <= 1
    assert 0 not in marks and 119 not in marks
    assert edit.stingers(list(range(100, 220)), FPS) == {}
