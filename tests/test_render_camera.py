import math

from ninety.render.camera import Camera, Director, blur_vector, project_with
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
    prev, in_shot, max_step = None, 0, 0.0
    for fr in m.frames:
        c = d.step(fr["ball"]["x"], fr["ball"]["y"])
        uv = c.project((fr["ball"]["x"], fr["ball"]["y"], 0.0))
        in_shot += uv is not None and 0 <= uv[0] < 1280 and 0 <= uv[1] < 720
        if prev:
            max_step = max(max_step, math.dist(prev.target[:2], c.target[:2]))
        prev = c
    assert in_shot / len(m.frames) > 0.97
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


def test_director_is_deterministic():
    m = simulate(2, 0.3)
    runs = []
    for _ in range(2):
        d = Director(CameraParams(shake_m=0.1), 1280, 720, 25, seed=2)
        runs.append([d.step(f["ball"]["x"], f["ball"]["y"]).P for f in m.frames])
    assert runs[0] == runs[1]
