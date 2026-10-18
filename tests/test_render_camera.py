import math

from ninety.render.camera import (
    GOAL_LOOK_S,
    GOAL_PAN_S,
    SIDE_BACK_M,
    SIDE_HALF_M,
    SIDE_HEIGHT_M,
    SIDE_X_MAX,
    SIDE_X_MIN,
    Camera,
    Director,
    blur_vector,
    net_push,
    project_with,
)
from ninety.render.params import CameraParams
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


def _on_sideline(c) -> None:
    assert c.position[1] == -SIDE_BACK_M
    assert c.position[2] == SIDE_HEIGHT_M
    assert SIDE_X_MIN - 1e-6 <= c.position[0] <= SIDE_X_MAX + 1e-6


def test_director_follows_the_ball_smoothly_and_keeps_it_in_shot():
    m = simulate(4, 1)
    d = Director(CameraParams(), 1280, 720, 25, seed=4)
    prev, prev_ball, in_shot, on_pitch, max_step = None, None, 0, 0, 0.0
    for fr in m.frames:
        bx, by = fr["ball"]["x"], fr["ball"]["y"]
        c = d.step(bx, by)
        # A restart places the ball. That frame is a cut. Every other frame is a pan.
        moved = 0.0 if prev_ball is None else math.hypot(bx - prev_ball[0], by - prev_ball[1])
        if 0 <= bx <= 105 and 0 <= by <= 68:
            uv = c.project((bx, by, 0.0))
            in_shot += uv is not None and 0 <= uv[0] < 1280 and 0 <= uv[1] < 720
            on_pitch += 1
        if prev and moved <= 8.0:
            max_step = max(max_step, math.dist(prev.target[:2], c.target[:2]))
        prev, prev_ball = c, (bx, by)
        assert d.angle == "main"
        _on_sideline(c)
    assert on_pitch > len(m.frames) / 2 and in_shot / on_pitch > 0.97
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


def _in_frame(uv, pad=36) -> None:
    assert uv is not None and pad <= uv[0] < 1280 - pad and pad <= uv[1] < 720 - pad


def test_a_placed_ball_cuts_to_the_spot():
    # A goal kick moves the ball about 18 m. Leading that step throws the camera back to halfway.
    d = Director(CameraParams(shake_m=0.0, lead_s=0.35), 1280, 720, 25, seed=1)
    for _ in range(30):
        d.step(105.0, 16.4)
    c = d.step(99.5, 34.0)
    assert d.angle == "main"
    _on_sideline(c)
    assert c.position[0] > 90.0
    _in_frame(c.project((99.5, 34.0, 0.2)))
    corner = Director(CameraParams(shake_m=0.0, lead_s=0.35), 1280, 720, 25, seed=1)
    corner.step(70.0, 30.0)
    c2 = corner.step(104.5, 0.5)
    _on_sideline(c2)
    assert c2.position[0] > 95.0
    _in_frame(c2.project((104.5, 0.5, 0.2)))


def test_the_box_stays_on_the_sideline_and_holds_the_ball():
    d = Director(CameraParams(shake_m=0.0), 1280, 720, 25, seed=1, cuts=True)
    prev = None
    for _ in range(25 * 3):
        c = d.step(12.0, 34.0)  # inside the left penalty area
        assert d.angle == "main"
        _on_sideline(c)
        assert c.position[0] >= SIDE_X_MIN  # in front of the end stand, not behind the goal
        _in_frame(c.project((12.0, 34.0, 0.2)))
        if prev is not None and math.dist(prev.position, c.position) > 1:
            assert blur_vector(prev, c, 0.5) == (0.0, 0.0)
        prev = c


def test_the_far_side_stays_on_the_near_sideline():
    d = Director(CameraParams(shake_m=0.0), 1280, 720, 25, seed=2, cuts=True)
    for _ in range(25 * 3):
        c = d.step(52.5, 54.0)
        assert d.angle == "main"
        _on_sideline(c)
        assert c.position[1] < 0  # the far-stand tier is y 74 to 91
        _in_frame(c.project((52.5, 54.0, 0.2)))
        # The near stand lip is behind this camera, so it cannot fill the foreground.
        assert c.project((52.5, -46.0, 2.0)) is None


def test_open_play_stays_on_the_gantry():
    d = Director(CameraParams(shake_m=0.0), 1280, 720, 25, seed=2, cuts=True)
    for _ in range(25 * 20):
        d.step(52.5, 34.0)
        assert d.angle == "main"
    # The far touchline is closer to the far stand, but that shot loses the stand and
    # pushes the ball off the bottom, so it is not the better angle.
    d = Director(CameraParams(shake_m=0.0), 1280, 720, 25, seed=2, cuts=True)
    for _ in range(25 * 5):
        d.step(52.5, 66.0)
        assert d.angle == "main"


def test_play_in_the_box_does_not_cut_away_from_the_sideline():
    d = Director(CameraParams(shake_m=0.0), 1280, 720, 25, seed=3, cuts=True)
    prev = None
    for i in range(25 * 12):
        # Two trips into the box. Neither leaves the sideline camera.
        x, y = (12.0, 34.0) if 40 <= i < 55 or 200 <= i < 230 else (52.5, 34.0)
        c = d.step(x, y)
        assert d.angle == "main"
        _on_sideline(c)
        if prev is not None and math.dist(prev.position, c.position) > 1:
            assert blur_vector(prev, c, 0.5) == (0.0, 0.0)
        prev = c


def test_cuts_are_deterministic():
    def run():
        d = Director(CameraParams(), 1280, 720, 25, seed=9, cuts=True)
        return [(d.angle, d.step(50.0, 30.0).P) for _ in range(120)]

    assert run() == run()


def test_the_sideline_camera_looks_down_and_keeps_the_stored_sample():
    stored = CameraParams(height_m=21.76, back_m=38.33, shake_m=0.0)
    assert stored.height_m == 21.76 and stored.back_m == 38.33
    d = Director(stored, 1280, 720, 25, seed=5)
    _on_sideline(d)
    angle = math.degrees(math.atan2(d.position[2], -d.position[1]))
    assert 28.0 <= angle <= 40.0  # atan(10.5 / 18) is about 30°, steeper than the old gantry


def test_a_throw_stays_on_the_sideline_and_holds_the_ball():
    d = Director(CameraParams(shake_m=0.0), 1280, 720, 25, seed=3, cuts=True)
    for i in range(25 * 2):
        if i < 20:
            c = d.step(52.5, 0.4, [(52.5, -0.2, "throw")])
            assert d.angle == "main"
            _on_sideline(c)
            _in_frame(c.project((52.5, 0.4, 0.3)))
        else:
            d.step(52.5, 34.0, [(52.5, 34.0, "run")])
            assert d.angle == "main"


def test_the_net_gives_behind_the_line_and_then_settles():
    hard = net_push(0.0, 24.0, 34.0, 1.1, 34.0, 1.1)
    soft = net_push(0.0, 6.0, 34.0, 1.1, 34.0, 1.1)
    far = net_push(0.0, 24.0, 34.0, 1.1, 31.0, 0.2)
    assert 0.4 < hard < 0.9 and soft < hard and far < hard * 0.5
    assert net_push(0.02, 24.0, 37.0, 2.0, 34.0, 1.1) == 0.0  # the cloth away from the hit has not moved yet
    assert net_push(2.7, 24.0, 34.0, 1.1, 34.0, 1.1) == 0.0
    # The back of the net hangs 2 m behind the line. A full push still leaves it off the pitch.
    assert 2.0 - hard > 1.0


def test_a_shot_into_the_box_stays_on_the_sideline():
    d = Director(CameraParams(shake_m=0.0), 1280, 720, 25, seed=3, cuts=True)
    d.step(16.8, 34.0)
    c = d.step(16.2, 34.0)  # 15 m/s toward the left goal, just inside the box
    assert d.angle == "main"
    _on_sideline(c)
    _in_frame(c.project((16.2, 34.0, 0.4)))
    slow = Director(CameraParams(shake_m=0.0), 1280, 720, 25, seed=3, cuts=True)
    slow.step(12.0, 34.0)
    c2 = slow.step(12.1, 34.0)
    assert slow.angle == "main"
    _on_sideline(c2)
    _in_frame(c2.project((12.1, 34.0, 0.4)))


def test_a_goal_cuts_low_beside_the_net_and_returns_to_the_sideline():
    d = Director(CameraParams(shake_m=0.0), 1280, 720, 25, seed=3, cuts=True)
    for _ in range(10):
        c = d.step(12.0, 34.0)
        assert d.angle == "main"
        _on_sideline(c)
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
            switches.append((d.t, d.angle))
            prev_angle = d.angle
    assert [a for _, a in switches] == ["net", "kickoff", "main"]
    assert switches[1][0] - switches[0][0] >= GOAL_LOOK_S - 0.05
    assert switches[2][0] - switches[0][0] >= GOAL_LOOK_S + GOAL_PAN_S - 0.05
    assert d.net_view() is None


def _show(ball):
    d = Director(CameraParams(half_width_m=20, height_m=20, back_m=35, shake_m=0, pan_lag_s=0.05),
                 1280, 720, 25, seed=1)
    shot = None
    for _ in range(100):
        shot = d.step(*ball)
    return d, shot


def test_the_sideline_holds_a_readable_player_and_a_corner():
    # The sampled lens is stored. The live picture uses the sideline width, so a player at the
    # aim is about 1.84 * 640 / half_width pixels tall.
    stored = CameraParams(half_width_m=20, height_m=20, back_m=35, shake_m=0, pan_lag_s=0.05)
    assert stored.half_width_m == 20 and stored.height_m == 20 and stored.back_m == 35
    d, cam = _show((52.5, 34.0))
    assert d.angle == "main"
    assert abs(d.half_width - SIDE_HALF_M) < 0.05
    _on_sideline(cam)
    feet, head = cam.project((52.5, 34, 0)), cam.project((52.5, 34, 1.84))
    tall = feet[1] - head[1]
    assert abs(tall - (1.84 * 640 / d.half_width)) < 12
    assert tall > 110  # the old gantry topped out at 110 px
    _in_frame(cam.project((52.5, 34, 0.2)), pad=80)
    # The near lip is behind the lens. The far tier is not the camera.
    assert cam.project((52.5, -46.0, 2.0)) is None
    assert cam.position[1] < 70
    for ball in ((52.5, 0.5), (52.5, 67.5), (12.0, 34.0), (94.0, 34.0), (104.5, 0.5), (0.5, 67.5)):
        _, shot = _show(ball)
        _on_sideline(shot)
        _in_frame(shot.project((*ball, 0.2)))


def test_director_is_deterministic():
    m = simulate(2, 0.3)
    runs = []
    for _ in range(2):
        d = Director(CameraParams(shake_m=0.1), 1280, 720, 25, seed=2)
        runs.append([d.step(f["ball"]["x"], f["ball"]["y"]).P for f in m.frames])
    assert runs[0] == runs[1]
