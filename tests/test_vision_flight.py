"""The ball's height from its flight (ninety/vision/flight.py), on synthetic clips whose answer is
known: a ball moved by stated physics (gravity, drag K_TRUE, bounces, rolling), projected through a
broadcast-like camera that follows it, with 1 px of noise on every detected centre. The generator
is this file's own, so an engine change cannot move these tests.

The mutation tests run the same scenes with drag removed and with the segmenting broken, and
check that the recovery criterion of the real tests then fails: those tests can go red."""

from __future__ import annotations

import base64
import json
import math
import zlib

import numpy as np
import pytest

from ninety.vision import flight as fl
from ninety.vision.pitch import View

K_TRUE = 0.0133  # 1/m: Cd 0.25 for a Law 2 ball, a stated answer for these tests
R = 0.11
FPS = 25
NOISE = 1.0
AIR_Z = 0.5  # the scorer's "in the air": the ball's bottom above knee height
SIZE_BIAS, SIZE_NOISE = -0.016, 0.03  # the synthetic detector's box: log bias and spread, stated
RECORD_SHOT_MPS = 58.6  # the fastest shot on record, 211 km/h (Heberson 2006, media reports)


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


def observations(path, cams, seed=1, noise=NOISE, sizes="true"):
    """Detected rows: the centre with `noise` px on each axis, the box as wide as a 0.22 m ball at
    its depth (SIZE_BIAS and SIZE_NOISE: a stated detector bias and spread, in log units). With
    sizes="ground" the box is as wide as a ball at observe.py's ground place: a size that speaks
    against a flight, as on the validation pieces with impossible speeds."""
    rng = np.random.default_rng(seed)
    rng_size = np.random.default_rng((seed, 1))  # its own stream, so the centres' noise is unchanged
    rows = []
    for i, ((t, x, y, z), v) in enumerate(zip(path, cams, strict=True)):
        u = v.project(np.array([[x, y, z]]))[0][0] + rng.normal(0, noise, 2)
        g = v.to_ground(u[None], z=R)[0]
        at = np.array([[x, y, z]]) if sizes == "true" else np.array([[g[0], g[1], R]])
        spread = math.exp(SIZE_BIAS + rng_size.normal(0, SIZE_NOISE))
        half = 0.5 * v.focal * 0.22 / v.project(at)[1][0] * spread
        rows.append({"frame": i, "t": t, "camera": {"ok": True, "P": v.P().tolist()}, "players": [],
                     "ball": [{"bbox": [u[0] - half, u[1] - half, u[0] + half, u[1] + half], "score": 0.9,
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


def no_sizes(rows):
    """The rows with each box shrunk to its centre: no size to judge a flight by, so the pixels'
    own safeguards (the anchor, the floor, the uncertainty gate) must do the work alone."""
    out = json.loads(json.dumps(rows))
    for r in out:
        for b in r["ball"]:
            cx, cy = (b["bbox"][0] + b["bbox"][2]) / 2, (b["bbox"][1] + b["bbox"][3]) / 2
            b["bbox"] = [cx, cy, cx, cy]
    return out


@pytest.fixture(scope="module")
def bare_scene(scene):
    path, rows, _ = scene
    rows = no_sizes(rows)
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


@pytest.mark.parametrize("which", ["scene", "bare_scene"])
def test_low_hops_are_placed_from_their_bounce(which, request):
    # a hop after a bounce has few frames and little curve; it starts where the last piece left
    # the ball, and where the fit is still unsure the ball keeps its ground place (with sizes, a
    # hop fit the ball's size speaks against is not a flight at all)
    path, _, out = request.getfixturevalue(which)
    assert np.percentile(low_errors(path, out), 90) < 1.0


def test_the_shot_is_never_fitted_under_the_ground():
    path = shot()
    out = fl.heights(observations(path, views(path), seed=3), k=K_TRUE, noise_px=NOISE)
    assert np.median(low_errors(path, out)) < 0.3
    assert all(r["ball"][0]["z"] >= R - fl.Z_TOL_M for r in out)


def test_an_unsure_place_is_not_used():
    path = kick_and_bounces()
    tr = fl.ball_track(no_sizes(observations(path, views(path))))
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


def test_mutation_without_the_anchor_the_low_hop_check_fails(bare_scene, monkeypatch):
    path, rows, _ = bare_scene
    monkeypatch.setattr(fl, "ANCHOR_SD_M", 1e9)  # a piece's start no longer tied to the last's end
    assert not np.percentile(low_errors(path, fl.heights(rows, k=K_TRUE, noise_px=NOISE)), 90) < 1.0


def test_mutation_without_the_floor_the_shot_check_fails(monkeypatch):
    monkeypatch.setattr(fl, "GROUND_SD_M", 1e9)  # a centre under the ground costs nothing
    path = shot()
    out = fl.heights(observations(path, views(path), seed=3), k=K_TRUE, noise_px=NOISE)
    assert not np.median(low_errors(path, out)) < 0.3


def test_mutation_without_the_gate_the_low_hop_check_fails(bare_scene, monkeypatch):
    path, rows, out = bare_scene
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


# ---------------------------------------------------------------------------------------------
# The ball's size and the launch speed: a flight the physics forbids is not used


def validation_window():
    """Observation rows 87 to 167 of validation seed 2041 (VALIDATION_2041 below): the old fit flew
    a 9-frame piece there at 85 m/s and moved 2 of its frames metres away."""
    return json.loads(zlib.decompress(base64.b64decode("".join(VALIDATION_2041))))


def test_the_validation_window_flies_nothing_faster_than_a_football_is_struck():
    rows = validation_window()
    tr = fl.ball_track(rows)
    speeds = [float(np.linalg.norm(p.flight.p[3:6])) for p in fl.segment(tr) if p.in_flight]
    assert all(s <= RECORD_SHOT_MPS for s in speeds), speeds
    assert not [r["frame"] for r in fl.heights(rows) for b in r["ball"] if b.get("flight") is not None]


def test_a_flight_its_size_speaks_against_is_not_used():
    # the kick's pixels exactly, but every box as big as a ball at its ground place: the size says
    # the ball never left the grass, so no frame may be moved into the air
    path = kick_and_bounces()
    out = fl.heights(observations(path, views(path), sizes="ground"), k=K_TRUE, noise_px=NOISE)
    assert not [r["frame"] for r in out if r["ball"][0]["flight"] is not None]


def test_a_flight_its_size_agrees_with_is_kept(scene):
    path, _, out = scene  # true box sizes: the real flight must still be flown
    assert sum(r["ball"][0]["flight"] is not None for r in out) > 30


def test_the_launch_speed_bound():
    def flight(speed):
        return fl.Fit("flight", np.r_[0.0, 0.0, 1.0, speed, 0.0, 0.0], 0.0, 0.0, np.zeros(1),
                      np.array([[0.0, 0.0, 1.0]]), np.zeros(1), K_TRUE, None)
    assert fl._physical(flight(35.0)) and fl._physical(flight(fl.MAX_LAUNCH_MPS))
    assert not fl._physical(flight(85.0))
    assert fl.MAX_LAUNCH_MPS >= RECORD_SHOT_MPS  # never below a shot that has been struck


def test_the_size_spread_is_derived_from_ground_pieces():
    path = simulate((20.0, 15.0, R, 9.0, 4.0, 0.0), 3.0)  # one long roll
    tr = fl.ball_track(observations(path, views(path), seed=6))
    d = fl.derive_size([tr], K_TRUE, NOISE)
    assert d["frames"] >= 60
    assert abs(d["bias_log"] - SIZE_BIAS) < 0.01 and abs(d["sd_log"] - SIZE_NOISE) < 0.01, d


def test_mutation_without_the_size_check_the_size_test_fails(monkeypatch):
    monkeypatch.setattr(fl, "SIZE_SD_LOG", 1e9)  # every size agrees with every depth
    path = kick_and_bounces()
    out = fl.heights(observations(path, views(path), sizes="ground"), k=K_TRUE, noise_px=NOISE)
    assert [r["frame"] for r in out if r["ball"][0]["flight"] is not None]


def test_mutation_without_both_checks_the_validation_window_fails(monkeypatch):
    monkeypatch.setattr(fl, "SIZE_SD_LOG", 1e9)
    monkeypatch.setattr(fl, "MAX_LAUNCH_MPS", 1e9)
    rows = validation_window()
    speeds = [float(np.linalg.norm(p.flight.p[3:6])) for p in fl.segment(fl.ball_track(rows)) if p.in_flight]
    assert any(s > RECORD_SHOT_MPS for s in speeds), speeds


# Validation seed 2041 (observations-seed2041.jsonl, sha256
# a086a43ca6c59a3c928fd4e0ffdeca541a0522dcf940223597fb9f67e3be1b83
# as in docs/eval/detector-derive-observations.sha256, branch pr-assets/detector-validation-observations
# 4d42fbf), rows 87 to 167, each kept to frame, t, camera ok and P, and the ball boxes: zlib, then
# base64. Validation data, never a test seed.
VALIDATION_2041 = (
    "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")
