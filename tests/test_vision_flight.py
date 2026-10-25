"""The ball's height from its flight (ninety/vision/flight.py), on synthetic clips whose answer is
known: a ball moved by stated physics (gravity, drag K_TRUE, bounces, rolling), projected through a
broadcast-like camera that follows it, with 1 px of noise on every detected centre. The generator
is this file's own, so an engine change cannot move these tests.

The mutation tests run the same scenes with drag removed and with the segmenting broken, and
check that the recovery criterion of the real tests then fails: those tests can go red."""

from __future__ import annotations

import json
import math

import numpy as np
import pytest

from ninety.vision import flight as fl
from ninety.vision.pitch import View

K_TRUE = 0.0133  # 1/m: Cd 0.25 for a Law 2 ball, a stated answer for these tests
R = 0.11
FPS = 25
NOISE = 1.0
AIR_Z = 0.5  # the scorer's "in the air": the ball's bottom above knee height


def simulate(start, seconds, kicks=(), dt=0.001):
    """Centres (t, x, y, z) every frame. start and kicks' velocities are (x, y, z, vx, vy, vz)
    and (frame, (vx, vy, vz)); bounces keep 60% of the vertical and 85% of the horizontal speed,
    a ball on the grass slows by 1.2 m/s^2."""
    x, v = np.array(start[:3], float), np.array(start[3:], float)
    kicks, out, per = dict(kicks), [], round(1 / (FPS * dt))
    for i in range(round(seconds / dt) + 1):
        if i % per == 0:
            f = i // per
            if f in kicks:
                v = np.array(kicks[f], float)
            out.append((f / FPS, *x))
        on_ground = x[2] <= R + 1e-9 and v[2] <= 0
        if on_ground:
            sp = math.hypot(v[0], v[1])
            v[:2] *= max(sp - 1.2 * dt, 0.0) / sp if sp > 0 else 0.0
            v[2] = 0.0
        else:
            v = v - K_TRUE * np.linalg.norm(v) * v * dt
            v[2] -= 9.81 * dt
        x = x + v * dt
        if x[2] < R:
            x[2] = R
            if v[2] < -0.6:
                v = np.array([0.85 * v[0], 0.85 * v[1], -0.6 * v[2]])
            else:
                v[2] = 0.0
    return out


def views(path, gantry=(52.5, -35.0, 18.0), hfov_deg=20.0):
    out = []
    for _, x, y, z in path:
        dx, dy, dz = x - gantry[0], y - gantry[1], z - gantry[2]
        out.append(View(*gantry, math.atan2(dx, dy), math.atan2(-dz, math.hypot(dx, dy)),
                        640 / math.tan(math.radians(hfov_deg / 2)), 1280, 720))
    return out


def observations(path, cams, seed=1, noise=NOISE):
    rng = np.random.default_rng(seed)
    rows = []
    for i, ((t, x, y, z), v) in enumerate(zip(path, cams, strict=True)):
        u = v.project(np.array([[x, y, z]]))[0][0] + rng.normal(0, noise, 2)
        g = v.to_ground(u[None], z=R)[0]
        rows.append({"frame": i, "t": t, "camera": {"ok": True, "P": v.P().tolist()}, "players": [],
                     "ball": [{"bbox": [u[0] - 5, u[1] - 5, u[0] + 5, u[1] + 5], "score": 0.9,
                               "x": float(g[0]), "y": float(g[1])}]})
    return rows


def kick_and_bounces():
    """A roll, a lofted kick at frame 25 (peak about 3.5 m), two bounces, a roll."""
    return simulate((30.0, 30.0, R, 6.0, 1.0, 0.0), 4.0, kicks=[(25, (18.0, 6.0, 9.0))])


def shot():
    """A low drive like seed 900001's shot: struck at 26 m/s, its bottom rising to about 1.6 m."""
    return simulate((75.0, 30.0, R, 0.0, 0.0, 0.0), 1.6, kicks=[(2, (25.0, 3.0, 6.0))])


def air_errors(path, rows_out):
    """Position errors (m) and height errors over the frames whose ball is in the air."""
    pos, hgt = [], []
    for (_, x, y, z), r in zip(path, rows_out, strict=True):
        if z - R > AIR_Z:
            b = r["ball"][0]
            pos.append(math.hypot(b["x"] - x, b["y"] - y))
            hgt.append(abs(b.get("z", R) - z))
    return np.array(pos), np.array(hgt)


def low_errors(path, rows_out):
    """Position errors (m) over every frame whose ball is off the ground at all (bottom above
    5 cm), the low hops included: the scorer's in-the-air group leaves those out."""
    return np.array([math.hypot(r["ball"][0]["x"] - x, r["ball"][0]["y"] - y)
                     for (_, x, y, z), r in zip(path, rows_out, strict=True) if z - R > 0.05])


@pytest.fixture(scope="module")
def scene():
    path = kick_and_bounces()
    rows = observations(path, views(path))
    return path, rows, fl.heights(rows, k=K_TRUE, noise_px=NOISE)


# ---------------------------------------------------------------------------------------------
# The physics


def test_without_drag_a_flight_is_the_parabola():
    p = np.array([[10.0, 20.0, 0.5, 15.0, -3.0, 8.0]])
    t = np.linspace(0, 1.2, 31)
    got = fl.flight_paths(p, t, 0.0)[0]
    want = p[0, :3] + np.outer(t, p[0, 3:]) + 0.5 * np.outer(t**2, [0, 0, -fl.GRAVITY])
    assert np.abs(got - want).max() < 1e-9


def test_drag_slows_a_ball_as_the_closed_form_says(monkeypatch):
    # with no gravity, v' = -K v^2 has v = v0 / (1 + K v0 t) and x = ln(1 + K v0 t) / K
    monkeypatch.setattr(fl, "GRAVITY", 0.0)
    t = np.linspace(0, 2.0, 51)
    got = fl.flight_paths(np.array([[0, 0, 1.0, 30.0, 0, 0]]), t, K_TRUE)[0][:, 0]
    assert np.abs(got - np.log1p(K_TRUE * 30.0 * t) / K_TRUE).max() < 1e-4


def test_a_rolling_ball_only_slows_and_stops():
    t = np.linspace(0, 6, 61)
    for decel in (1.5, -1.5):  # the size of the deceleration, either sign
        xy = fl.ground_paths(np.array([[0, 0, 3.0, 4.0, decel]]), t)[0]
        d = np.hypot(xy[:, 0], xy[:, 1])
        assert np.all(np.diff(d) >= -1e-12) and abs(d[-1] - 25 / 3.0) < 1e-9  # v^2/2a
        assert np.all(xy[:, 2] == fl.BALL_CENTRE_Z)


# ---------------------------------------------------------------------------------------------
# Recovery through a known camera


def test_one_flight_through_the_camera_gives_its_height():
    path = kick_and_bounces()
    tr = fl.ball_track(observations(path, views(path)))
    lo, hi = 26, 68  # the kick to the first bounce
    f = fl.fit("flight", tr, lo, hi, np.ones(hi - lo, bool), K_TRUE)
    truth = np.array([p[1:] for p in path[lo:hi]])
    assert np.abs(f.centres[:, 2] - truth[:, 2]).max() < 0.1
    assert np.linalg.norm(f.centres[:, :2] - truth[:, :2], axis=1).max() < 0.3


def test_the_ground_places_a_lofted_ball_metres_away(scene):
    path, rows, _ = scene
    on_ground, _ = air_errors(path, rows)  # the input rows: observe.py's ground placement
    assert len(on_ground) > 40 and np.median(on_ground) > 5.0


def test_the_flight_puts_the_ball_back_in_the_air(scene):
    path, _, out = scene
    pos, hgt = air_errors(path, out)
    assert np.median(pos) < 0.3 and pos.max() < 1.0, pos
    assert np.median(hgt) < 0.1 and hgt.max() < 0.3, hgt


def test_the_pieces_break_at_the_kick_and_the_bounces(scene):
    path, rows, out = scene
    tr = fl.ball_track(rows)
    pieces = fl.segment(tr, K_TRUE, NOISE)
    starts = [p.lo for p in pieces if p.in_flight]
    lands = [i for i in range(1, len(path)) if path[i][3] - R < 0.02 and path[i - 1][3] - R > 0.02]
    for want in [26] + [i + 1 for i in lands[:2]]:  # the first frame after each kick or bounce
        assert min(abs(s - want) for s in starts) <= 1, (starts, want)
    rolling = [i for i in range(len(path)) if i < 25]
    assert all(out[i]["ball"][0]["flight"] is None for i in rolling)
    assert all(out[i]["ball"][0]["x"] == rows[i]["ball"][0]["x"] for i in rolling)  # not moved


def test_a_low_shot_is_lifted_too():
    path = shot()
    out = fl.heights(observations(path, views(path), seed=3), k=K_TRUE, noise_px=NOISE)
    pos, hgt = air_errors(path, out)
    assert len(pos) >= 10 and np.median(pos) < 0.5 and np.median(hgt) < 0.15, (pos, hgt)


def test_low_hops_are_placed_from_their_bounce(scene):
    # a hop after a bounce has few frames and little curve; it starts where the last piece left
    # the ball, and where the fit is still unsure the ball keeps its ground place
    path, _, out = scene
    assert np.percentile(low_errors(path, out), 90) < 1.0


def test_the_shot_is_never_fitted_under_the_ground():
    path = shot()
    out = fl.heights(observations(path, views(path), seed=3), k=K_TRUE, noise_px=NOISE)
    assert np.median(low_errors(path, out)) < 0.3
    assert all(r["ball"][0]["z"] >= R - fl.Z_TOL_M for r in out)


def test_an_unsure_place_is_not_used():
    path = kick_and_bounces()
    tr = fl.ball_track(observations(path, views(path)))
    hop = [p for p in fl.segment(tr, K_TRUE, NOISE) if p.in_flight][-1]  # 9 frames, under 0.4 m high
    assert fl.centre_se(hop.flight, NOISE).max() > fl.MAX_SE_M


def test_a_ball_rolling_along_the_grass_stays_on_it():
    path = simulate((20.0, 15.0, R, 9.0, 4.0, 0.0), 3.0)
    out = fl.heights(observations(path, views(path), seed=4), k=K_TRUE, noise_px=NOISE)
    assert all(r["ball"][0]["flight"] is None for r in out)


def test_a_stray_detection_is_left_out_and_not_moved():
    path = kick_and_bounces()
    rows = observations(path, views(path))
    bad = 45
    for c in (0, 2):
        rows[bad]["ball"][0]["bbox"][c] += 40.0  # 40 px off: a wrong box for one frame
    out = fl.heights(rows, k=K_TRUE, noise_px=NOISE)
    assert out[bad]["ball"][0]["flight"] is None
    assert out[bad]["ball"][0]["x"] == rows[bad]["ball"][0]["x"]
    pos, _ = air_errors(path[:bad] + path[bad + 1:], out[:bad] + out[bad + 1:])
    assert np.median(pos) < 0.3


def test_frames_without_a_trusted_camera_are_untouched():
    path = kick_and_bounces()
    rows = observations(path, views(path))
    for i in range(40, 44):
        rows[i]["camera"]["ok"] = False
    out = fl.heights(rows, k=K_TRUE, noise_px=NOISE)
    assert all("flight" not in out[i]["ball"][0] for i in range(40, 44))
    assert all(out[i]["ball"][0]["x"] == rows[i]["ball"][0]["x"] for i in range(40, 44))


# ---------------------------------------------------------------------------------------------
# The constants come from pixels alone


def test_the_noise_is_derived_from_the_residuals():
    path = kick_and_bounces()
    tr = fl.ball_track(observations(path, views(path), seed=5))
    assert abs(fl.derive_noise([tr], K_TRUE, rounds=2) - NOISE) < 0.15


def test_drag_is_derived_from_the_pixels():
    trs = []
    for seed in (1, 2):
        path = kick_and_bounces()
        trs.append(fl.ball_track(observations(path, views(path), seed=seed)))
    d = fl.derive_drag(trs, np.linspace(0.004, 0.022, 7), NOISE)
    assert d["flights"] >= 4
    assert abs(d["k"] - K_TRUE) < 0.15 * K_TRUE, d
    assert d["k_se"] is not None and abs(d["k"] - K_TRUE) < 3 * d["k_se"] + 0.05 * K_TRUE, d


# ---------------------------------------------------------------------------------------------
# Mutations: the checks above must fail when the physics or the segmenting is broken


def test_mutation_without_drag_the_height_check_fails(scene):
    path, rows, _ = scene
    pos, hgt = air_errors(path, fl.heights(rows, k=0.0, noise_px=NOISE))
    assert not (np.median(pos) < 0.3 and pos.max() < 1.0), "a drag-free fit should not pass"


def test_mutation_without_segments_the_height_check_fails(scene, monkeypatch):
    path, rows, _ = scene
    monkeypatch.setattr(fl, "_grow", lambda tr, piece, hi, k: None)  # no piece grows past 5 frames
    pos, _ = air_errors(path, fl.heights(rows, k=K_TRUE, noise_px=NOISE))
    assert not (np.median(pos) < 0.3 and pos.max() < 1.0), "unsegmented fits should not pass"


def test_mutation_one_piece_for_everything_fails(scene, monkeypatch):
    path, rows, _ = scene
    real = fl._fits
    monkeypatch.setattr(fl, "_fits", lambda f, use, gate: real(f, use, 1e9))  # nothing ends a piece
    pos, _ = air_errors(path, fl.heights(rows, k=K_TRUE, noise_px=NOISE))
    assert not (np.median(pos) < 0.3 and pos.max() < 1.0), "a piece across bounces should not pass"


def test_mutation_without_the_anchor_the_low_hop_check_fails(scene, monkeypatch):
    path, rows, _ = scene
    monkeypatch.setattr(fl, "ANCHOR_SD_M", 1e9)  # a piece's start no longer tied to the last's end
    assert not np.percentile(low_errors(path, fl.heights(rows, k=K_TRUE, noise_px=NOISE)), 90) < 1.0


def test_mutation_without_the_floor_the_shot_check_fails(monkeypatch):
    monkeypatch.setattr(fl, "GROUND_SD_M", 1e9)  # a centre under the ground costs nothing
    path = shot()
    out = fl.heights(observations(path, views(path), seed=3), k=K_TRUE, noise_px=NOISE)
    assert not np.median(low_errors(path, out)) < 0.3


def test_mutation_without_the_gate_the_low_hop_check_fails(scene, monkeypatch):
    path, rows, out = scene
    assert low_errors(path, out).max() < 3.0  # the real one passes this bound
    monkeypatch.setattr(fl, "MAX_SE_M", 1e9)  # every fitted place used, however unsure
    assert not low_errors(path, fl.heights(rows, k=K_TRUE, noise_px=NOISE)).max() < 3.0


# ---------------------------------------------------------------------------------------------
# The command line


def test_the_command_writes_heights(tmp_path, scene):
    _, rows, _ = scene
    src, dst = tmp_path / "observations-seed7.jsonl", tmp_path / "out.jsonl"
    src.write_text("".join(json.dumps(r) + "\n" for r in rows), encoding="utf-8")
    fl.main([str(src), "--out", str(dst)])
    got = [json.loads(line) for line in dst.read_text(encoding="utf-8").splitlines()]
    assert len(got) == len(rows) and any(r["ball"][0]["flight"] is not None for r in got)


def test_deriving_on_a_test_seed_is_refused(tmp_path):
    src = tmp_path / "observations-seed900001.jsonl"
    src.write_text("", encoding="utf-8")
    with pytest.raises(SystemExit, match="refused"):
        fl.main([str(src), "--derive"])
