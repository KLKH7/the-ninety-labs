import math

from ninety.render.camera import CUT_HOLD_S, Camera, Director, blur_vector, net_push, project_with
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
        # because restarts took 1 to 2 s. In play: 903 of 924 (lesson 37).
        if 0 <= fr["ball"]["x"] <= 105 and 0 <= fr["ball"]["y"] <= 68:
            uv = c.project((fr["ball"]["x"], fr["ball"]["y"], 0.0))
            in_shot += uv is not None and 0 <= uv[0] < 1280 and 0 <= uv[1] < 720
            on_pitch += 1
        if prev:
            max_step = max(max_step, math.dist(prev.target[:2], c.target[:2]))
        prev = c
        assert d.angle == "main"
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


def test_goal_cut_sits_behind_the_goal_and_centres_the_ball():
    d = Director(CameraParams(shake_m=0.0), 1280, 720, 25, seed=1, cuts=True)
    saw = False
    prev = None
    for _ in range(25 * 40):
        c = d.step(12.0, 34.0)  # inside the left penalty area
        if d.angle == "goal":
            saw = True
            assert c.position[0] < 0 and c.position[2] > 8
            u, v = c.project((12.0, 34.0, 0.2))
            assert abs(u - 640) < 40 and abs(v - 360) < 50
            if prev is not None and math.dist(prev.position, c.position) > 1:
                assert blur_vector(prev, c, 0.5) == (0.0, 0.0)
        prev = c
    assert saw


def test_reverse_cut_is_the_far_stand_and_holds_the_ball():
    d = Director(CameraParams(shake_m=0.0), 1280, 720, 25, seed=2, cuts=True)
    saw = False
    for _ in range(25 * 5):
        c = d.step(52.5, 54.0)  # far side, where that stand is closer and still a wide shot
        if d.angle == "reverse":
            saw = True
            assert 80 < c.position[1] < 96 and 11 < c.position[2] < 14
            u, v = c.project((52.5, 54.0, 0.2))
            assert 48 <= u < 1280 - 48 and 48 <= v < 720 - 48
            # Opposite bowl is the backdrop. A deck above the frame is the sparse overview.
            deck = c.project((52.5, -68.0, 14.0))
            lip = c.project((52.5, -46.0, 2.0))
            feet, head = c.project((52.5, 54.0, 0.0)), c.project((52.5, 54.0, 1.8))
            assert deck is not None and lip is not None and feet is not None and head is not None
            assert 80 <= deck[0] < 1280 - 80 and 0 <= deck[1] < 160 and deck[1] < lip[1] < 420
            assert 55 <= feet[1] - head[1] <= 110
        assert d.angle != "goal"
    assert saw


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


def test_a_cut_holds_long_enough_that_it_cannot_flicker():
    d = Director(CameraParams(shake_m=0.0), 1280, 720, 25, seed=3, cuts=True)
    switches = []
    prev_angle, prev = "main", None
    for i in range(25 * 12):
        # A short chance, then open play, then another chance inside the return hold.
        x, y = (12.0, 34.0) if 40 <= i < 55 or 200 <= i < 230 else (52.5, 34.0)
        c = d.step(x, y)
        if d.angle != prev_angle:
            if prev is not None and math.dist(prev.position, c.position) > 1:
                assert blur_vector(prev, c, 0.5) == (0.0, 0.0)
            if switches:
                assert d.t - switches[-1][0] >= CUT_HOLD_S - 1e-9
            switches.append((d.t, d.angle))
            prev_angle = d.angle
        prev = c
    assert [a for _, a in switches] == ["goal", "main"]


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


def test_a_shot_into_the_box_is_the_low_angle_and_a_dribble_stays_high():
    d = Director(CameraParams(shake_m=0.0), 1280, 720, 25, seed=3, cuts=True)
    d.step(16.8, 34.0)
    c = d.step(16.2, 34.0)  # 15 m/s toward the left goal, just inside the box
    assert d.angle == "net"
    u, v = c.project((16.2, 34.0, 0.4))
    assert u is not None and 36 <= u < 1280 - 36 and 36 <= v < 720 - 36
    slow = Director(CameraParams(shake_m=0.0), 1280, 720, 25, seed=3, cuts=True)
    slow.step(12.0, 34.0)
    slow.step(12.1, 34.0)
    assert slow.angle == "goal"


def test_a_goal_cuts_low_beside_the_net_and_returns_to_the_gantry():
    d = Director(CameraParams(shake_m=0.0), 1280, 720, 25, seed=3, cuts=True)
    for _ in range(10):
        d.step(12.0, 34.0)
    assert d.angle == "goal"
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


def test_the_gantry_holds_the_stand_behind_the_play():
    # A wide sampled lens aimed at the grass puts the bowl above the frame. The filmed
    # gantry is longer and looks up, so the seats are the backdrop and a player still has a body.
    stored = CameraParams(half_width_m=20, height_m=20, back_m=35, shake_m=0, pan_lag_s=0.05)
    assert stored.half_width_m == 20
    d = Director(stored, 1280, 720, 25, seed=1)
    cam = None
    for _ in range(80):
        cam = d.step(52.5, 34)
    assert d.angle == "main"
    assert abs(d.half_width - 14.5) < 0.05
    feet, head = cam.project((52.5, 34, 0)), cam.project((52.5, 34, 1.8))
    assert 55 <= head[1] and feet[1] - head[1] <= 110
    assert 55 <= feet[1] - head[1]
    ball = cam.project((52.5, 34, 0.2))
    assert ball is not None and 400 < ball[1] < 680
    seat = cam.project((52.5, 86, 8))
    assert seat is not None and 0 <= seat[1] < 200
    # Play on either touchline stays inside the picture.
    for y in (10.0, 54.0):
        d2 = Director(stored, 1280, 720, 25, seed=1)
        shot = None
        for _ in range(80):
            shot = d2.step(52.5, y)
        uv = shot.project((52.5, y, 0.2))
        assert uv is not None and 40 <= uv[0] < 1240 and 40 <= uv[1] < 700


def test_director_is_deterministic():
    m = simulate(2, 0.3)
    runs = []
    for _ in range(2):
        d = Director(CameraParams(shake_m=0.1), 1280, 720, 25, seed=2)
        runs.append([d.step(f["ball"]["x"], f["ball"]["y"]).P for f in m.frames])
    assert runs[0] == runs[1]
