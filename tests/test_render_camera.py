import math
from functools import cache

from ninety.render import edit
from ninety.render.camera import (
    CUT_HOLD_S,
    GANTRY_HALF_M,
    HOLD_SHARE,
    MAX_PAN_MPS,
    PAN_ACCEL_MPS2,
    ZOOM_ACCEL_MPS2,
    Camera,
    Director,
    blur_vector,
    corner_waits,
    net_push,
    pitch_share,
    project_with,
    well_framed,
)
from ninety.render.clip import SIM_MARGIN_S, _plan
from ninety.render.params import CameraParams, sample_params
from ninety.render.scene import drawn_ball
from ninety.sim.engine import simulate


def cam(target=(52.5, 34.0, 0.0), fov=20.0):
    return Camera((52.5, -35.0, 20.0), target, fov, 1280, 720)


def test_target_projects_to_the_image_centre():
    c = cam((30.0, 40.0, 0.0))
    u, v = c.project(c.target)
    assert abs(u - 640) < 1e-6 and abs(v - 360) < 1e-6


def test_projection_matrix_matches_the_camera():
    c = cam((70.0, 20.0, 0.0))
    for X in [(0, 0, 0), (105, 68, 0), (52.5, 34, 1.8), (88.5, 13.84, 0)]:
        a, b = c.project(X), project_with(c.P, X)
        assert math.dist(a, b) < 1e-6


def test_rotation_is_orthonormal_and_right_handed():
    R = cam((10.0, 50.0, 0.0)).R
    for i in range(3):
        for j in range(3):
            dot = sum(R[i][k] * R[j][k] for k in range(3))
            assert abs(dot - (1.0 if i == j else 0.0)) < 1e-9
    r, d, f = R
    cross = (r[1] * d[2] - r[2] * d[1], r[2] * d[0] - r[0] * d[2], r[0] * d[1] - r[1] * d[0])
    assert all(abs(cross[i] - f[i]) < 1e-9 for i in range(3))


def test_far_touchline_is_above_the_near_one():
    c = cam()
    assert c.project((52.5, 68, 0))[1] < c.project((52.5, 0, 0))[1]
    assert c.project((60, 34, 0))[0] > c.project((45, 34, 0))[0]  # x grows to the right


def test_point_behind_camera_is_none():
    assert cam().project((52.5, -60.0, 0.0)) is None


def test_director_follows_the_ball_smoothly_and_keeps_it_in_shot():
    m = simulate(4, 1)
    d = Director(CameraParams(), 1280, 720, 25, seed=4)
    prev, in_shot, on_pitch, max_step = None, 0, 0, 0.0
    for fr in m.frames:
        c = d.step(fr["ball"]["x"], fr["ball"]["y"])
        # A dead ball lying off the pitch until the restart (12 s or more, GROUNDING R1) is not
        # what the camera follows; the ball in play is. Measured at the merge of main: the camera
        # aims no nearer a touchline than 12 m (camera.py), so a ball resting beyond the near
        # line is in shot in 229 of 576 such frames on seed 4, and was never tested before
        # because restarts took 1 to 2 s. In play: 903 of 924 (lesson 37). After main's portable
        # math redrew every match, seed 4's first minute holds a foul at 14.8 s and its free kick
        # at 46.5 s (R1's free-kick wait), the dead ball lying beyond the touchline in between:
        # on the pitch 639 of 1,500 frames, all 639 in shot.
        if 0 <= fr["ball"]["x"] <= 105 and 0 <= fr["ball"]["y"] <= 68:
            uv = c.project((fr["ball"]["x"], fr["ball"]["y"], 0.0))
            in_shot += uv is not None and 0 <= uv[0] < 1280 and 0 <= uv[1] < 720
            on_pitch += 1
        if prev:
            max_step = max(max_step, math.dist(prev.target[:2], c.target[:2]))
        prev = c
        assert d.angle == "main"
    # Never vacuous, whatever the seed draws: 20 s of the ball on the pitch, so 3% is 15 frames.
    assert on_pitch >= 25 * 20 and in_shot / on_pitch > 0.97
    assert max_step <= 22.0 / 25 + 0.05  # metres per frame (plus shake): a pan, never a jump


def test_player_scale_is_broadcast_like():
    c = cam((52.5, 34, 0), fov=2 * math.degrees(math.atan(math.tan(math.atan(20 / 72)) * 720 / 1280)))

    def h(y):
        top, bottom = c.project((52.5, y, 1.84)), c.project((52.5, y, 0))
        return bottom[1] - top[1]

    assert 25 <= h(68) <= 60 and 60 <= h(5) <= 130


def test_blur_follows_the_pan():
    a, b = cam((40.0, 34.0, 0.0)), cam((41.0, 34.0, 0.0))
    dx, dy = blur_vector(a, b, 0.5)
    assert dx < 0 and abs(dy) < abs(dx)  # panning right moves the picture left
    assert blur_vector(None, b, 0.5) == (0.0, 0.0)
    assert blur_vector(a, b, 0.0) == (0.0, 0.0)


def test_live_play_stays_on_the_gantrys_side_of_the_pitch():
    """Old (0.5.0 and before): the director cut to the far stand when play was on the far side, high
    behind a goal while the ball was in that box, and low beside the net for a shot arriving, so the
    viewpoint jumped about between opposite sides of the ground. Live play now keeps the gantry:
    every camera it uses stands on the gantry's side, so left and right stay where the viewer has
    them (the 180-degree rule)."""
    paths = {
        "midfield": [(52.5, 34.0)] * 125,
        "far touchline": [(52.5, 66.0)] * 125,
        "in a box": [(12.0, 34.0)] * 125,
        "a shot arriving": [(40.0 - 0.6 * i, 34.0) for i in range(40)],
    }
    for what, path in paths.items():
        d = Director(CameraParams(shake_m=0.0), 1280, 720, 25, seed=2, cuts=True)
        first = None
        for x, y in path:
            c = d.step(x, y)
            first = first or c.position
            assert d.angle == "main", what
            assert c.position == first, what  # one camera: it pans and zooms, it does not move
            assert c.position[1] < 0.0, what


def test_a_cut_holds_long_enough_that_it_cannot_flicker():
    d = Director(CameraParams(shake_m=0.0), 1280, 720, 25, seed=3, cuts=True)
    switches = []
    prev_angle, prev = "main", None
    for i in range(25 * 12):
        # A short throw, then open play, then another throw inside the return hold.
        throw = 40 <= i < 55 or 200 <= i < 230
        actors = [(52.5, -0.2, "throw")] if throw else [(52.5, 30.0, "run")]
        c = d.step(52.5, 0.4 if throw else 30.0, actors)
        if d.angle != prev_angle:
            if prev is not None and math.dist(prev.position, c.position) > 1:
                assert blur_vector(prev, c, 0.5) == (0.0, 0.0)
            if switches:
                assert d.t - switches[-1][0] >= CUT_HOLD_S - 1e-9
            switches.append((d.t, d.angle))
            prev_angle = d.angle
        prev = c
    assert [a for _, a in switches] == ["tight", "main"]


def test_cuts_are_deterministic():
    def run():
        d = Director(CameraParams(), 1280, 720, 25, seed=9, cuts=True)
        return [(d.angle, d.step(50.0, 30.0).P) for _ in range(120)]

    assert run() == run()


def test_the_gantry_looks_down_at_a_broadcast_angle():
    d = Director(CameraParams(height_m=21.76, back_m=38.33, shake_m=0.0), 1280, 720, 25, seed=5)
    angle = math.degrees(math.atan2(d.position[2], 38.33))
    assert 22.0 <= angle <= 24.0
    assert CameraParams(height_m=21.76, back_m=38.33).height_m == 21.76


def test_a_throw_cuts_closer_and_holds():
    d = Director(CameraParams(shake_m=0.0), 1280, 720, 25, seed=3, cuts=True)
    switches = []
    prev = "main"
    for i in range(25 * 6):
        if i < 20:
            d.step(52.5, 0.4, [(52.5, -0.2, "throw")])
        else:
            d.step(52.5, 34.0, [(52.5, 34.0, "run")])
        if d.angle != prev:
            if switches:
                assert d.t - switches[-1][0] >= CUT_HOLD_S - 1e-9
            switches.append((d.t, d.angle))
            prev = d.angle
    assert [a for _, a in switches] == ["tight", "main"]
    d2 = Director(CameraParams(shake_m=0.0), 1280, 720, 25, seed=3, cuts=True)
    c = d2.step(52.5, 0.4, [(52.5, -0.2, "throw")])
    assert d2.angle == "tight"
    u, v = c.project((52.5, 0.4, 0.3))
    assert 36 <= u < 1280 - 36 and 36 <= v < 720 - 36


def test_the_net_gives_behind_the_line_and_then_settles():
    hard = net_push(0.0, 24.0, 34.0, 1.1, 34.0, 1.1)
    soft = net_push(0.0, 6.0, 34.0, 1.1, 34.0, 1.1)
    far = net_push(0.0, 24.0, 34.0, 1.1, 31.0, 0.2)
    assert 0.4 < hard < 0.9 and soft < hard and far < hard * 0.5
    assert net_push(0.02, 24.0, 37.0, 2.0, 34.0, 1.1) == 0.0  # the cloth away from the hit has not moved yet
    assert net_push(2.7, 24.0, 34.0, 1.1, 34.0, 1.1) == 0.0
    # The back of the net hangs 2 m behind the line. A full push still leaves it off the pitch.
    assert 2.0 - hard > 1.0


def test_a_goal_cuts_low_beside_the_net_and_returns_to_the_gantry():
    d = Director(CameraParams(shake_m=0.0), 1280, 720, 25, seed=3, cuts=True)
    for _ in range(10):
        d.step(12.0, 34.0)
    assert d.angle == "main"
    prev = d.step(12.0, 34.0)
    c = d.step(52.5, 34.0, goal=("L", 33.2, 1.05, 22.0))
    assert d.angle == "net"
    assert c.position[0] < -4 and 2.5 < c.position[2] < 6 and c.position[1] < 28
    assert math.dist(prev.position, c.position) > 1
    assert blur_vector(prev, c, 0.5) == (0.0, 0.0)
    mouth = c.project((0.0, 33.2, 1.05))
    near = c.project((0.0, 30.34, 1.2))
    far = c.project((0.0, 37.66, 1.2))
    bar = c.project((0.0, 34.0, 2.44))
    assert mouth is not None and abs(mouth[0] - 640) < 80 and abs(mouth[1] - 360) < 80
    for uv in (near, far, bar):
        assert uv is not None and 16 <= uv[0] < 1280 - 16 and 16 <= uv[1] < 720 - 16
    view = d.net_view()
    assert view["side"] == 0 and view["age"] == 0.0
    switches = [(d.t, "net")]
    prev_angle = "net"
    for _ in range(25 * 6):
        d.step(52.5, 34.0)
        if d.angle != prev_angle:
            assert d.t - switches[-1][0] >= CUT_HOLD_S - 1e-9
            switches.append((d.t, d.angle))
            prev_angle = d.angle
    assert [a for _, a in switches] == ["net", "main"]
    assert d.net_view() is None


def test_director_is_deterministic():
    m = simulate(2, 0.3)
    runs = []
    for _ in range(2):
        d = Director(CameraParams(shake_m=0.1), 1280, 720, 25, seed=2)
        runs.append([d.step(f["ball"]["x"], f["ball"]["y"]).P for f in m.frames])
    assert runs[0] == runs[1]


# Seeds the director's design was not tuned on (the lens, STANDS_MAX and the follow were chosen on
# seeds 7, 21 and 42).
# Seeds the camera rules were not designed on. 3 and 5 were studied while fixing #198 (lesson 175),
# so they stay for continuity only; 41 and 43 were added before anyone rendered or scored them for
# the camera (committed ahead of #198's re-score), and are the held-out check.
HELD_OUT = (3, 5, 41, 43, 47, 53)
# 47 and 53: a second fresh pair, added at the Reviewer's request before anyone rendered or scored
# them for the camera.


@cache
def _match(seed):
    """The match the 100 s window below draws from, simulated SIM_MARGIN_S past the window as a render
    simulates past its clip (clip.py, lesson 140), so a dead ball near the window's end has its
    restart in the events: without it the edit sees no dead ball and its frames count as live play."""
    return simulate(seed, (2 + 100 + SIM_MARGIN_S) / 60)


def _broadcast(seed):
    """Every drawn frame of a 100 s clip of `seed` from 0:02, as the render points the camera:
    the edit's cuts, the warm-up before each segment, the restart's shot after a cut and the time
    to the next cut (clip.py). Second angles are on, whatever the seed draws. Returns
    (frame, camera, angle, cut before it) per drawn frame."""
    m = _match(seed)
    p = sample_params(seed)
    d = Director(p.camera, 1280, 720, 25, seed, cuts=True)
    show, _ = edit.plan(2 * 25, 100 * 25, edit.cuts(m.events, 25), len(m.frames))
    goals = {e["frame"]: e for e in m.events if e["type"] == "goal"}
    corners = corner_waits(m.events)
    rows, reopen, after_cut = [], False, False
    for fi, draw, left in _plan(edit.segments(show)):
        if fi is None:
            d.cut()
            reopen = after_cut = True
            continue
        if draw and reopen:
            d.open_on_restart()
            reopen = False
        fr = m.frames[fi]
        ball = drawn_ball(fr)
        actors = [(q["x"], q["y"], q.get("action", "")) for q in fr["players"]]
        goal = None
        if fi in goals:
            b = m.frames[fi - 1]["ball"]
            goal = ("L" if goals[fi]["x"] < 52.5 else "R", goals[fi]["y"], 1.0, math.hypot(b["vx"], b["vy"]))
        cam = d.step(ball[0], ball[1], actors, goal, None if left is None else left / 25, ball_z=ball[2],
                     corner=corners.get(fi))
        if draw:
            rows.append((fi, cam, d.angle, after_cut))
            after_cut = False
    return m, rows


def _dead_frames(events: list[dict]) -> set[int]:
    """Every frame the ball is out of play: from each stoppage to the restart's first touch. The
    engine's restart event (a set piece, a kick-off) marks the ball set for it, not taken: the ball
    is in play only once it is kicked and moves (Law 17 for a corner, the same for each restart),
    so the wait between the two is still a dead ball (lesson 175, the same class as lesson 140)."""
    order = sorted(events, key=lambda e: e["frame"])
    dead: set[int] = set()
    for stop, restart, _ in edit.dead_balls(events):
        taken = next((e["frame"] for e in order if e["frame"] > restart and e["type"] not in edit.RESTARTS),
                     restart)
        dead.update(range(stop, taken))
    return dead


def test_a_restart_waiting_to_be_taken_is_a_dead_ball():
    """The harness's own labelling: a corner set at frame 30 and kicked at frame 60 is dead from the
    stoppage to the kick, and live from the kick (seed 3 on #179's engine counted its corner waits
    as live play)."""
    events = [{"frame": 10, "type": "out_of_play"}, {"frame": 30, "type": "set_piece"},
              {"frame": 60, "type": "pass"}, {"frame": 90, "type": "pass"}]
    dead = _dead_frames(events)
    assert set(range(10, 60)) <= dead and 60 not in dead and 90 not in dead


def test_the_gantry_frames_the_play_with_the_pitch_filling_the_picture():
    """Old (0.5.0 and before): the gantry aimed 4.5 m above the play to keep the stand behind it, so
    the stands filled 40 to 75% of the picture and the players were small at the bottom (well
    framed in 13 to 47% of live frames on seeds 7, 21 and 42). A broadcast keeps the play near the
    middle with the pitch filling most of the picture: in live play, at least 85% of frames have
    the pitch over PITCH_SHARE_MIN of the picture and the ball in the CENTRAL box (camera.py), and
    the median frame has 8 to 15 players in shot (docs/guides/broadcast-render.md). The bar holds
    on every held-out seed, over every live frame (lesson 175)."""
    for seed in HELD_OUT:
        m, rows = _broadcast(seed)
        dead = _dead_frames(m.events)
        live = [(fi, cam) for fi, cam, _, _ in rows[::5] if fi not in dead]
        live = [(fi, cam) for fi, cam in live if 0 <= m.frames[fi]["ball"]["x"] <= 105
                and 0 <= m.frames[fi]["ball"]["y"] <= 68]
        assert len(live) >= 200, (seed, len(live))  # never vacuous: 40 s of live play
        ok, in_shot = 0, []
        for fi, cam in live:
            b = m.frames[fi]["ball"]
            ok += well_framed(cam, (b["x"], b["y"], b["z"] + 0.11))
            seen = 0
            for q in m.frames[fi]["players"]:
                # In shot: his feet inside the picture's width and above its bottom, his head below its top.
                feet, head = cam.project((q["x"], q["y"], 0.0)), cam.project((q["x"], q["y"], 1.8))
                if feet is not None and head is not None:
                    seen += 0 <= feet[0] < 1280 and feet[1] < 720 and head[1] >= 0
            in_shot.append(seen)
        print(f"seed {seed}: well framed {ok / len(live):.3f} of {len(live)} live frames")
        assert ok / len(live) >= 0.85, (seed, ok, len(live))
        assert 8 <= sorted(in_shot)[len(in_shot) // 2] <= 15, (seed, sorted(in_shot))


def test_the_viewpoint_changes_no_faster_than_a_broadcast_and_never_flickers():
    """Old (0.5.0 and before): side-on, then the far stand, then high behind a goal, and back,
    within seconds. A shot is now the run of frames between two changes of picture, an edit cut or
    a camera that moves. None is shorter than CUT_HOLD_S (the first and last are cut by the clip),
    the picture changes no more often than a broadcast does (SoccerNet-v2: one change of shot every
    9 s on average, replays included), and every camera stands on the gantry's side."""
    for seed in HELD_OUT:
        _, rows = _broadcast(seed)
        starts = [0] + [i for i in range(1, len(rows))
                        if rows[i][3] or math.dist(rows[i - 1][1].position, rows[i][1].position) > 1.0]
        lengths = [b - a for a, b in zip(starts, starts[1:] + [len(rows)], strict=True)]
        assert all(n >= CUT_HOLD_S * 25 for n in lengths[1:-1]), (seed, lengths)
        minutes = len(rows) / 25 / 60
        assert (len(lengths) - 1) / minutes <= 60 / 9, (seed, len(lengths), minutes)
        assert all(cam.position[1] < 34.0 for _, cam, _, _ in rows), seed


def test_play_on_the_far_side_keeps_the_stands_a_band_across_the_top():
    """The far side is foreshortened: from a low gantry (13 m up, 31 m back, a sampled seed's) the
    lens aimed at a ball on the far touchline shows more stand than pitch. The gantry tilts down
    along its line of sight instead, so the far edge of the pitch stays in the top STANDS_MAX of
    the picture and the ball stays in the middle of it across."""
    low = CameraParams(height_m=13.2, back_m=31.1, offset_x_m=-1.6, half_width_m=21.0, shake_m=0.0)
    for spot in [(52.5, 64.0), (30.0, 60.0), (10.8, 65.1)]:  # last: seed 42's far corner
        d = Director(low, 1280, 720, 25, seed=1)
        for _ in range(125):
            cam = d.step(*spot)
        u, v = cam.project((*spot, 0.11))
        assert pitch_share(cam) >= 0.6, spot
        assert 0.2 * 1280 <= u <= 0.8 * 1280 and 0.15 * 720 <= v <= 0.85 * 720, (spot, u, v)


def test_the_gantry_holds_still_while_the_ball_moves_about_one_area():
    """Old (0.5.1's first clips): the aim was locked to the ball, so every short pass was a pan and
    the picture swung left and right. The operator frames the play: passes inside one area leave
    the gantry where it is."""
    d = Director(CameraParams(shake_m=0.0), 1280, 720, 25, seed=1)
    for _ in range(50):
        d.step(50.0, 34.0)
    start = tuple(d.aim)
    travel = 0.0
    for i in range(200):  # short passes, 3 m either way, a second each way
        prev = tuple(d.aim)
        d.step(50.0 + 3.0 * math.sin(2 * math.pi * i / 50), 34.0)
        travel += math.dist(prev, d.aim)
    assert travel < 1.0 and math.dist(start, d.aim) < 0.5, travel


def test_the_zoom_never_pumps_or_turns_round_in_a_frame():
    """Old: the box's closer lens came in as the ball entered a penalty area and went straight back
    out as it left, the zoom's pace flipping from in to out in one frame. Now the lens stays in
    until the ball is BOX_LEAVE_M clear of the box, and the zoom gathers pace at most
    ZOOM_ACCEL_MPS2."""
    d = Director(CameraParams(shake_m=0.0), 1280, 720, 25, seed=1)
    widths = []
    for i in range(400):  # in and out of the box's edge every second, then away up the pitch
        x = 15.0 + 3.0 * math.sin(2 * math.pi * i / 25) if i < 250 else 15.0 + 0.3 * (i - 250)
        d.step(x, 34.0)
        widths.append(d.half_width)
    rates = [(b - a) * 25 for a, b in zip(widths, widths[1:], strict=False)]
    assert max(abs(b - a) * 25 for a, b in zip(rates, rates[1:], strict=False)) <= ZOOM_ACCEL_MPS2 + 1e-6
    held = widths[60:250]
    assert max(held) - min(held) < 0.2  # the box lens stays in while the ball is about its edge
    assert widths[-1] > max(held) + 2.0  # and goes back out once play has left


def test_a_header_or_a_catch_in_live_play_stays_on_the_gantry():
    """Old: an aerial touch or a keeper's catch cut to the tighter lens in the middle of an attack.
    The director stays on the wide shot through attacks; a throw-in still cuts closer."""
    for action in ("head", "chest", "thigh", "hands"):
        d = Director(CameraParams(shake_m=0.0), 1280, 720, 25, seed=3, cuts=True)
        for _ in range(25 * 3):
            d.step(30.0, 34.0, [(30.0, 34.2, action)])
            assert d.angle == "main", action
    d = Director(CameraParams(shake_m=0.0), 1280, 720, 25, seed=3, cuts=True)
    d.step(52.5, 0.4, [(52.5, -0.2, "throw")])
    assert d.angle == "tight"


def test_a_pan_eases_in_and_out():
    """Old: the aim jumped from still to full pace in one frame when a long ball was struck and
    stopped dead, as no operator pans. It now gathers and loses speed at most PAN_ACCEL_MPS2, and
    never pans faster than MAX_PAN_MPS."""
    d = Director(CameraParams(shake_m=0.0), 1280, 720, 25, seed=1)
    path = [(30.0, 34.0)] * 50 + [(30.0 + 0.8 * i, 34.0) for i in range(1, 60)] + [(77.2, 34.0)] * 75
    aims = []
    for x, y in path:
        cam = d.step(x, y)
        aims.append(tuple(d.aim))
    speeds = [math.dist(a, b) * 25 for a, b in zip(aims, aims[1:], strict=False)]
    assert max(speeds) <= MAX_PAN_MPS + 1e-6
    changes = [abs(b - a) * 25 for a, b in zip(speeds, speeds[1:], strict=False)]
    assert max(changes) <= PAN_ACCEL_MPS2 + 1e-6, max(changes)
    # The long ball's first frame moves the aim's lead 7.8 m on; the aim gains one frame's speed.
    assert speeds[49] <= PAN_ACCEL_MPS2 / 25 + 1e-6, speeds[48:52]
    # Settled with the play inside the hold either side of the centre (HOLD_SHARE of the half-width).
    u, v = cam.project((77.2, 34.0, 0.0))
    assert speeds[-1] < 0.1 and abs(u - 640) <= HOLD_SHARE * 640 + 8 and abs(v - 360) < 72, (u, v)


def _held(d, x, y, frames, actors=None):
    cam = None
    for _ in range(frames):
        cam = d.step(x, y, actors or [])
    return cam


def test_after_a_cut_the_restart_opens_on_the_wide_shot_and_holds_it():
    """Old (0.5.2 to 0.5.9): after an edit cut the gantry came back closed up on the restart, held a
    frozen taker alone for 4 s, then pulled out (demo v1's critic, #4 and #15; lesson 175 before it).
    The picture now comes back on the gantry's own wide shot, with no pull-out, and holds that shot
    CUT_HOLD_S even when a throw-in would bring up the tight lens (bounds written before the change)."""
    d = Director(CameraParams(shake_m=0.0), 1280, 720, 25, seed=3, cuts=True)
    _held(d, 30.0, 34.0, 50)
    d.cut()
    d.open_on_restart()
    thrower = [(30.4, -0.3, "throw")]
    widths, angles = [], []
    for _ in range(round(25 * CUT_HOLD_S)):  # a throw-in set on the touchline
        d.step(30.5, 0.2, thrower)
        widths.append(d.half_width)
        angles.append(d.angle)
    assert widths[0] >= 0.8 * min(d.p.half_width_m, GANTRY_HALF_M), widths[0]
    assert max(widths) <= 1.25 * widths[0] and min(widths) >= 0.8 * widths[0], (min(widths), max(widths))
    assert set(angles) == {"main"}, set(angles)


def test_a_cut_reframes_on_the_restart_however_far_the_stoppage_was_framed():
    """The edit's cut is a new framing, not the stoppage's held over: built so the property must
    hold (the stoppage framed at the left of the pitch, the restart set far to the right), the
    restart's spot jumps more than a fifth of the picture's width across the cut and comes up in its
    middle half. Moved here from test_render_clip, where it rested on whatever seed 11's play put
    either side of the cut (lesson 187)."""
    d = Director(CameraParams(shake_m=0.0), 1280, 720, 25, seed=3, cuts=True)
    before = _held(d, 30.0, 34.0, 50)
    d.cut()
    d.open_on_restart()
    after = d.step(80.0, 12.0, [])
    spot = (80.0, 12.0, 0.0)
    now, then = after.project(spot), before.project(spot)
    assert now is not None and abs(now[0] - 640) < 0.25 * 1280, now
    assert then is None or math.dist(now, then) > 0.2 * 1280, (now, then)


def test_after_a_goal_the_scorer_and_his_celebration_are_followed():
    """Demo v1's critic (#8): after the goal a fixed low shot beside the net showed the keeper and
    never the scorer. Told who scored, the camera stays on the gantry for the goal itself, then a
    second camera follows the scorer to the corner flag: from 2.5 s after the goal to the end of the
    hold he is in the middle half of the picture, at least a sixth of its height tall (bounds written
    before the change). Without a scorer the low angle beside the net is unchanged (test above)."""
    d = Director(CameraParams(shake_m=0.0), 1280, 720, 25, seed=3, cuts=True)
    _held(d, 100.0, 34.0, 25)
    x, y = 104.0, 34.5
    d.step(105.6, 34.0, [], goal=("R", 34.0, 1.0, 20.0), scorer=(x, y))
    assert d.angle == "main"
    bad = []
    for i in range(1, 25 * 8):
        if y > 4.0:  # he runs to the corner flag at 6 m/s, then stays there with his team-mates
            y -= 6.0 / 25
            x = max(x - 0.4 / 25, 102.0)
        c = d.step(105.6, 34.0, [], scorer=(x, y), cut_in=(25 * 8 - i) / 25 + 0.5)
        t = i / 25
        if t < 2.0:
            assert d.angle == "main", (t, d.angle)
        if t >= 2.5:
            chest, feet, head = c.project((x, y, 1.0)), c.project((x, y, 0.0)), c.project((x, y, 1.8))
            ok = (d.angle == "scorer" and chest is not None and 320 <= chest[0] <= 960
                  and 180 <= chest[1] <= 540 and feet is not None and head is not None
                  and feet[1] - head[1] >= 720 / 6)
            if not ok:
                bad.append((round(t, 2), d.angle, chest))
    assert not bad, bad[:5]


def test_a_ball_run_to_the_byline_stays_in_the_middle_of_the_picture():
    """Old: the aim stopped 8 m short of each goal line, so a ball run to the byline was left at the
    edge of the picture or out of it (seed 3 on #179's engine). The aim follows the ball to the line,
    and the ball, and where it will be when the pan catches up, stay inside the CENTRAL box."""
    d = Director(CameraParams(shake_m=0.0), 1280, 720, 25, seed=3, cuts=True)
    x, y = 30.0, 20.0
    _held(d, x, y, 50)
    bad = 0
    for i in range(100):  # 4 s toward the byline at 7.5 m/s, then held there
        x = max(x - 0.3, 0.6)
        cam = d.step(x, y, [])
        bad += i >= 25 and not well_framed(cam, (x, y, 0.11))
    assert bad == 0, bad


def test_play_near_a_corner_flag_is_framed_with_the_pitch_filling_the_picture():
    """Old: aimed into a corner, the wide shot was mostly run-off and stands. The lens closes in
    there until the pitch fills the picture again, with the ball still in the middle."""
    d = Director(CameraParams(shake_m=0.0), 1280, 720, 25, seed=3, cuts=True)
    cam = _held(d, 3.0, 8.0, 150)
    assert well_framed(cam, (3.0, 8.0, 0.11)), pitch_share(cam)


def test_a_lofted_ball_is_kept_in_the_picture():
    """Old: the director aimed at the grass whatever the ball's height, so a lofted ball 5 to 7 m up
    left the top of the picture (seed 3 on #179's engine). It tilts up with a high ball, only as far
    as keeps it inside the CENTRAL box, and eases the tilt like the pan."""
    d = Director(CameraParams(shake_m=0.0), 1280, 720, 25, seed=3, cuts=True)
    for _ in range(75):
        cam = d.step(30.0, 40.0, [], ball_z=0.0)
    for _ in range(50):
        cam = d.step(30.0, 40.0, [], ball_z=7.0)
    assert well_framed(cam, (30.0, 40.0, 7.11))


def test_a_ball_on_a_corner_flag_keeps_the_wide_shot():
    """Where no lens fills the picture with pitch (the ball on the corner flag, set for a corner),
    the director does not close in: a close-up there is all run-off, and a corner kicked from it is
    lost in a whip pan (the blind critic of 0.5.5's first cut)."""
    d = Director(CameraParams(shake_m=0.0), 1280, 720, 25, seed=3, cuts=True)
    _held(d, 20.0, 20.0, 75)
    wide = d.half_width
    cam = _held(d, 0.5, 0.5, 250)
    assert d.half_width >= 0.8 * wide, (d.half_width, wide)
    uv = cam.project((0.5, 0.5, 0.11))
    assert uv is not None and 0.1 * 1280 <= uv[0] <= 0.9 * 1280


def _corner_wait(flag, frames=150, d=None, corner=True):
    d = d or Director(CameraParams(shake_m=0.0), 1280, 720, 25, seed=3, cuts=True)
    _held(d, 20.0, 20.0, 50)
    cam = None
    for _ in range(frames):
        cam = d.step(*flag, [], corner=(round(flag[0] / 105) * 105.0, round(flag[1] / 68) * 68.0)
                     if corner else None)
    return d, cam


def test_a_corner_is_framed_from_the_taker_inward():
    """Old (0.5.5): a corner waiting to be taken was shot like any ball, centred, so a near corner
    was three-quarters run-off and stands. While a corner waits (the engine's set piece at a flag),
    the taker, the ball and the penalty mark are in the picture, and the picture has more pitch than
    the same wait shot without the rule (the rule's purpose, not a number taken from a measurement)."""
    for flag in ((0.5, 0.5), (104.5, 0.5), (0.5, 67.5), (104.5, 67.5)):
        _, cam = _corner_wait(flag)
        _, plain = _corner_wait(flag, corner=False)
        taker, mark = cam.project((*flag, 0.11)), cam.project((11.0 if flag[0] < 50 else 94.0, 34.0, 0.0))
        assert 0.1 * 1280 <= taker[0] <= 0.9 * 1280 and 0.1 * 720 <= taker[1] <= 0.9 * 720, (flag, taker)
        assert 0 <= mark[0] <= 1280 and 0 <= mark[1] <= 720, (flag, mark)
        assert pitch_share(cam) > pitch_share(plain), (flag, pitch_share(cam), pitch_share(plain))


def test_each_corner_has_its_own_shot_and_the_ball_stays_in_it():
    """One director, corners at both ends in turn, the ball set anywhere in the arc: each corner gets
    its own shot, and the ball where it is set stays in the picture (the Reviewer's mutants N10 and
    N12: one shot reused for every corner, an aim that does not keep the ball)."""
    d = Director(CameraParams(shake_m=0.0), 1280, 720, 25, seed=3, cuts=True)
    for ball in ((0.9, 0.3), (104.2, 0.8), (0.4, 67.1), (104.6, 67.9)):
        _, cam = _corner_wait(ball, d=d)
        uv = cam.project((*ball, 0.11))
        assert 0.1 * 1280 <= uv[0] <= 0.9 * 1280 and 0.1 * 720 <= uv[1] <= 0.9 * 720, (ball, uv)


def test_the_corner_shot_holds_until_the_kick():
    """The corner's shot is held for the whole wait, however long, from the set piece to the kick:
    the lens and aim settle and stay, rather than giving up part way (a mutant that ends the corner
    framing early is caught)."""
    d, _ = _corner_wait((0.5, 0.5), frames=100)
    held = (d.half_width, tuple(d.aim))
    _corner_wait((0.5, 0.5), frames=300, d=d)
    assert abs(d.half_width - held[0]) < 0.05, (held, d.half_width)
    assert math.dist(d.aim, held[1]) < 0.05, (held, d.aim)


def _after_kick(flag, path, corner=True):
    """A corner waits 2 s at `flag`, is kicked along `path` (positions a frame apart), and the ball then
    rests at the path's end for 2 s: the cameras of the frames after the kick, with the ball."""
    d = Director(CameraParams(shake_m=0.0), 1280, 720, 25, seed=3, cuts=True)
    _held(d, 20.0, 20.0, 50)
    key = (round(flag[0] / 105) * 105.0, round(flag[1] / 68) * 68.0)
    for _ in range(50):
        d.step(*flag, [], corner=key if corner else None)
    out = []
    for p in list(path) + [path[-1]] * 50:
        out.append((d.step(*p, []), (*p, 0.11)))
    return out


def _line(a, b, frames):
    return [(a[0] + (b[0] - a[0]) * i / frames, a[1] + (b[1] - a[1]) * i / frames)
            for i in range(1, frames + 1)]


def test_after_the_kick_the_corner_rule_frames_no_worse_than_no_rule():
    """The Reviewer of #201: holding the corner's shot past the kick framed the delivery worse than
    no rule at all (a near-corner long cross 0/88 well framed against 41/88; a far-corner clearance
    out of the picture about 3.6 s). After the kick the rule is gone: each case frames at least as
    well as the same play without the corner's wait framed for it."""
    cases = {
        "near-corner long cross": ((0.5, 0.5), _line((0.5, 0.5), (10.0, 34.0), 38), "framed"),
        "far-corner clearance": ((0.5, 67.5), _line((0.5, 67.5), (40.0, 30.0), 78), "seen"),
        "near-corner clearance": ((0.5, 0.5), _line((0.5, 0.5), (35.0, 40.0), 78), "seen"),
        "right near-corner long cross": ((104.5, 0.5), _line((104.5, 0.5), (95.0, 34.0), 38), "framed"),
        "right far-corner clearance": ((104.5, 67.5), _line((104.5, 67.5), (65.0, 30.0), 78), "seen"),
        "right near-corner clearance": ((104.5, 0.5), _line((104.5, 0.5), (70.0, 40.0), 78), "seen"),
    }
    # Tolerance, set before the right-corner cases were measured: the camera reframes from the
    # corner's shot over one pan lag, so up to that many frames (ceil(pan_lag_s x fps)) may differ.
    tolerance = math.ceil(CameraParams(shake_m=0.0).pan_lag_s * 25)
    def score(rows, measure):
        if measure == "framed":
            return sum(well_framed(cam, ball) for cam, ball in rows)
        return sum((uv := cam.project(ball)) is not None and 0 <= uv[0] <= 1280 and 0 <= uv[1] <= 720
                   for cam, ball in rows)

    for what, (flag, path, measure) in cases.items():
        with_rule = score(_after_kick(flag, path), measure)
        without = score(_after_kick(flag, path, corner=False), measure)
        assert with_rule >= without - tolerance, (what, with_rule, without, tolerance)


def test_corner_waits_runs_from_a_corner_s_set_piece_to_the_kick_and_only_for_a_corner():
    """corner_waits (the Reviewer's mutants R7 and R8): the wait ends the frame before the kick, not
    after it; a set piece near a flag after a foul, or a throw-in out over the touchline by the flag,
    is no corner; open play along the goal line has no wait."""
    corner = [{"frame": 10, "type": "out_of_play", "x": 0.0, "y": 8.7},
              {"frame": 20, "type": "set_piece", "x": 0.5, "y": 0.5},
              {"frame": 50, "type": "pass", "x": 0.5, "y": 0.5}]
    assert corner_waits(corner) == {f: (0.0, 0.0) for f in range(20, 50)}
    foul = [{"frame": 10, "type": "foul", "x": 0.6, "y": 0.4},
            {"frame": 20, "type": "set_piece", "x": 0.6, "y": 0.4},
            {"frame": 50, "type": "pass", "x": 0.6, "y": 0.4}]
    assert corner_waits(foul) == {}
    throw = [{"frame": 10, "type": "out_of_play", "x": 0.8, "y": 0.0},
             {"frame": 20, "type": "set_piece", "x": 0.8, "y": 0.0},
             {"frame": 50, "type": "pass", "x": 0.8, "y": 0.0}]
    assert corner_waits(throw) == {}
    open_play = [{"frame": f, "type": "pass", "x": 0.5, "y": 0.5 + f / 10} for f in range(0, 50, 10)]
    assert corner_waits(open_play) == {}
    # Cases that pass the goal-line check, so they test the rest of the rule (the Reviewer's R8, R8b):
    # A goal kick from the goal area's near corner (Law 16: anywhere in the goal area), 26.6 m from
    # the flag: out over the goal line, but no corner.
    goal_kick = [{"frame": 10, "type": "out_of_play", "x": 0.0, "y": 20.0},
                 {"frame": 20, "type": "set_piece", "x": 5.5, "y": 26.0},
                 {"frame": 50, "type": "pass", "x": 5.5, "y": 26.0}]
    assert corner_waits(goal_kick) == {}
    then_foul = corner + [{"frame": 70, "type": "foul", "x": 0.6, "y": 0.4},
                          {"frame": 80, "type": "set_piece", "x": 0.6, "y": 0.4},
                          {"frame": 110, "type": "pass", "x": 0.6, "y": 0.4}]
    # The foul's free kick by the flag is no corner: only the first corner waits.
    assert corner_waits(then_foul) == {f: (0.0, 0.0) for f in range(20, 50)}


def test_open_play_through_the_corner_arc_is_framed_as_with_no_corner_rule(monkeypatch):
    """The Reviewer's R4: a ball run along the goal line through the corner arc in open play (no
    corner given) is framed exactly as by a director with no corner rule at all."""
    path = _line((12.0, 10.0), (0.3, 0.6), 30) + _line((0.3, 0.6), (8.0, 1.0), 30)

    def run():
        d = Director(CameraParams(shake_m=0.0), 1280, 720, 25, seed=3, cuts=True)
        _held(d, 20.0, 20.0, 50)
        return [d.step(*p, []).P for p in path]

    with_rule = run()
    monkeypatch.setattr(Director, "_corner", lambda self, bx, by: None)
    assert with_rule == run()


def test_a_long_ball_stays_in_the_picture_across_it():
    """A long ball (lesson 204; seed 43 on #220's engine): the ball still in midfield, then kicked
    at 20 m/s along the pitch, slowing as it flies. The aim trails a moving target by the pan's lag
    (_ease), so a target on the ball itself left the picture that lag behind it: at pan_lag_s 0.83
    and 17 m/s about 14 m, and the ball ran out of the side of the shot. Across the picture it must
    stay inside the CENTRAL box all the way (its height is the tilt's business, not tested here)."""
    left, right, _, _ = (0.2, 0.8, 0.15, 0.85)
    d = Director(CameraParams(shake_m=0.0, pan_lag_s=0.83, lead_s=0.45), 1280, 720, 25, seed=3)
    x, y, v = 80.0, 52.0, 0.0
    for _ in range(50):
        d.step(x, y)
    worst = 0.5
    for k in range(60):
        v = 20.0 - 0.15 * k  # 20 m/s off the boot, about 11 m/s 2.4 s later
        x -= v / 25
        c = d.step(x, y)
        u = c.project((x, y, 0.11))[0] / 1280
        worst = min(worst, u) if u < 0.5 else max(worst, u)
        assert left <= u <= right, (k, round(x, 1), round(u, 3))
    assert worst != 0.5


def test_a_goal_soon_after_the_restart_waits_for_the_edits_hold():
    """Seed 53 on #220's engine: the edit brings the picture back for a free kick that scores 0.44 s
    after it is taken. The goal used to start the low angle at once, over the hold the edit cut had
    just set, so the restart's shot lasted 2.4 s. The edit cut is a change of shot: the gantry
    holds CUT_HOLD_S from it, and the low angle comes up after that, while the goal is fresh."""
    d = Director(CameraParams(shake_m=0.0), 1280, 720, 25, seed=3, cuts=True)
    for _ in range(50):
        d.step(30.0, 34.0)
    d.cut()
    d.open_on_restart()
    angles = [(d.step(20.0, 34.0), d.angle)[1] for _ in range(25)]  # the free kick set, then taken
    d.step(52.5, 34.0, goal=("L", 33.2, 1.05, 24.0))
    angles.append(d.angle)
    for _ in range(25 * 6):
        d.step(52.5, 34.0)
        angles.append(d.angle)
    first_net = angles.index("net")
    assert all(a == "main" for a in angles[:first_net])
    assert first_net >= CUT_HOLD_S * 25 - 1  # the restart's shot is held its full CUT_HOLD_S
    assert first_net <= CUT_HOLD_S * 25 + 1  # and the low angle comes up as soon as it may
