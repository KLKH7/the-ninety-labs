"""The viewer's radar (ninety/radar.py, web/viewer/src/radar.ts): vision's tracked positions and its
camera fit, drawn from above beside the broadcast video.

The Python half: the camera footprint's geometry, the truth refusal, and the ball marked as seen
only where vision found it. The browser half (needs the built viewer and Playwright's Chromium, as
tests/test_viewer.py): the radar follows the clip's timeline across a cut, never drawing a player
from the far side of it, and a position not seen in the frame on screen is drawn hollow.
"""

from __future__ import annotations

import functools
import json
import math
import shutil
import threading
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import pytest

from ninety import e2e, radar
from ninety.vision import track
from tests.e2e_clip import H, W, write_clip
from tests.test_viewer import DIST, unavailable
from tests.test_vision_live_path import run_audited, truth_reads

ROOT = Path(__file__).resolve().parents[1]
TRACKED = ROOT / "tests" / "fixtures" / "tracked-seed900001.json"
OBSERVATIONS = ROOT / "tests" / "fixtures" / "observations-seed900001.jsonl"


# ---------------------------------------------------------------- a camera, by hand


def _sub(a, b):
    return [x - y for x, y in zip(a, b, strict=True)]


def _unit(a):
    n = math.sqrt(sum(x * x for x in a))
    return [x / n for x in a]


def _cross(a, b):
    return [a[1] * b[2] - a[2] * b[1], a[2] * b[0] - a[0] * b[2], a[0] * b[1] - a[1] * b[0]]


def camera(at, look, f=1000.0, w=1280, h=720):
    """P = K [R | -R C] for a pinhole at `at` looking at `look`, image x to the right, y down."""
    fwd = _unit(_sub(look, at))
    right = _unit(_cross(fwd, [0.0, 0.0, 1.0]))
    down = _cross(fwd, right)
    R = [right, down, fwd]
    t = [-sum(r[i] * at[i] for i in range(3)) for r in R]
    K = [[f, 0.0, w / 2], [0.0, f, h / 2], [0.0, 0.0, 1.0]]
    Rt = [R[i] + [t[i]] for i in range(3)]
    return [[sum(K[i][k] * Rt[k][j] for k in range(3)) for j in range(4)] for i in range(3)]


def project(P, x, y):
    u, v, s = (P[i][0] * x + P[i][1] * y + P[i][3] for i in range(3))
    return u / s, v / s, s


def test_a_camera_looking_down_covers_the_ground_its_four_corners_show():
    P = camera([52.5, -20.0, 40.0], [52.5, 30.0, 0.0])
    poly = radar.footprint(P, 1280, 720)
    assert poly is not None and len(poly) == 4
    corners = {(0, 0), (1280, 0), (1280, 720), (0, 720)}
    for x, y in poly:
        u, v, depth = project(P, x, y)
        assert depth > 0
        assert any(math.hypot(c[0] - u, c[1] - v) < 1.0 for c in corners), (u, v)
    # Nearer the camera, the picture covers less ground: the near edge is the shorter one.
    near = sorted(poly, key=lambda p: p[1])[:2]
    far = sorted(poly, key=lambda p: p[1])[2:]
    assert abs(near[0][0] - near[1][0]) < abs(far[0][0] - far[1][0])


def test_a_camera_that_sees_sky_is_cut_at_the_horizon_and_never_runs_off_without_end():
    P = camera([52.5, -30.0, 12.0], [52.5, 200.0, 8.0])  # aimed just under the horizon
    poly = radar.footprint(P, 1280, 720)
    assert poly is not None and len(poly) >= 3
    for x, y in poly:
        assert -radar.FAR_M - 1e-6 <= x <= radar.PITCH_X + radar.FAR_M + 1e-6
        assert -radar.FAR_M - 1e-6 <= y <= radar.PITCH_Y + radar.FAR_M + 1e-6
        u, v, depth = project(P, x, y)
        assert depth > 0  # in front of the camera, never the mirror image behind it
        assert -1 <= u <= 1281 and -1 <= v <= 721
    assert max(y for _, y in poly) == pytest.approx(radar.PITCH_Y + radar.FAR_M)  # cut, not unbounded


def test_the_same_camera_scaled_by_minus_one_covers_the_same_ground():
    P = camera([52.5, -30.0, 12.0], [52.5, 200.0, 8.0])
    flipped = [[-v for v in row] for row in P]
    assert radar.footprint(flipped, 1280, 720) == radar.footprint(P, 1280, 720)


def test_on_the_fixture_every_ball_vision_saw_is_inside_the_picture_it_was_seen_in():
    body = radar.build(json.loads(TRACKED.read_text()), radar.read_observations(OBSERVATIONS), 1280, 720)
    seen = {b.frame: b for b in track.ball_path(radar.read_observations(OBSERVATIONS))}
    views = {v["frame"]: v for v in body["views"]}
    checked = 0
    for f, b in seen.items():
        poly = views[f]["footprint"]
        assert poly is not None
        assert inside(poly, b.x, b.y), f
        checked += 1
    assert checked > 150


def inside(poly, x, y) -> bool:
    hit = False
    for (x0, y0), (x1, y1) in zip(poly, poly[1:] + poly[:1], strict=True):
        if (y0 > y) != (y1 > y) and x < x0 + (y - y0) * (x1 - x0) / (y1 - y0):
            hit = not hit
    return hit


def test_the_fixture_has_balls_filled_in_by_the_tracked_file_that_the_radar_marks_unseen():
    body = radar.build(json.loads(TRACKED.read_text()), radar.read_observations(OBSERVATIONS), 1280, 720)
    tracked = {f["frame"] for f in body["frames"]}
    unseen = [v["frame"] for v in body["views"] if not v["ball_seen"] and v["frame"] in tracked]
    assert unseen, "the fixture should have gap-filled balls"
    assert body["source"] == "tracked" and body["clip"] == "seed900001"


def test_positions_that_are_not_vision_s_are_refused():
    body = json.loads(TRACKED.read_text())
    body["frames"][3]["source"] = "truth"
    with pytest.raises(ValueError, match="tracked"):
        radar.build(body, radar.read_observations(OBSERVATIONS), 1280, 720)
    del body["frames"][3]["source"]  # absent means truth (frame.schema.json)
    with pytest.raises(ValueError):
        radar.build(body, radar.read_observations(OBSERVATIONS), 1280, 720)


BUILD_STAGE = """
    from pathlib import Path
    from ninety import radar
    tracked = json.loads(open("tests/fixtures/tracked-seed900001.json").read())
    rows = radar.read_observations(Path("tests/fixtures/observations-seed900001.jsonl"))
    body = radar.build(tracked, rows, 1280, 720)
    OUT = {"frames": len(body["frames"]),
           "footprints": sum(v["footprint"] is not None for v in body["views"])}
"""


def test_building_the_radar_opens_no_truth():
    run = run_audited(BUILD_STAGE)
    assert run["out"]["frames"] > 200 and run["out"]["footprints"] > 200  # it did the work
    assert truth_reads(run) == []


def test_e2e_wants_both_radar_inputs_or_neither(tmp_path):
    with pytest.raises(SystemExit):
        e2e.main([str(tmp_path), "--out", str(tmp_path / "b"), "--tracked", str(TRACKED)])


# ---------------------------------------------------------------- in the browser

FPS = 25
# The clip: 40 images of match frames 1500-1539, then a cut to frames 1550-1584 (35 images).
SEGMENTS = [{"index": 0, "frame": 1500, "frames": 40}, {"index": 40, "frame": 1550, "frames": 35}]
SHOWN = list(range(1500, 1540)) + list(range(1550, 1585))
HOME_RGB = (0x3A, 0x68, 0xC0)  # London navy (src/radar.ts COLORS.home), the club's colour


def tracked_clip() -> dict:
    """h-t1 runs along y 30, unseen in 1510-1514. h-t2 stands at y 50 before the cut, unseen in its
    last three frames, and is far away after it: within the tracker's gap, so only the cut keeps
    the radar from drawing him on his way there. h-t4 is the same the other way round: seen up to
    the cut, unseen in the first three frames after it. a-t3 stands still at (70, 20)."""
    frames = []
    for f in SHOWN:
        players = []
        if not 1510 <= f <= 1514:
            players.append({"id": "h-t1", "team": "home", "x": 20.0 + 0.2 * (f - 1500), "y": 30.0})
        if f < 1537:
            players.append({"id": "h-t2", "team": "home", "x": 40.0, "y": 50.0})
        elif f >= 1550:
            players.append({"id": "h-t2", "team": "home", "x": 90.0, "y": 10.0})
        if f < 1550 or f >= 1553:
            players.append({"id": "h-t4", "team": "home", "x": 30.0 if f < 1550 else 80.0, "y": 60.0})
        players.append({"id": "a-t3", "team": "away", "x": 70.0, "y": 20.0})
        frames.append({"frame": f, "t": round(f / FPS, 2), "source": "tracked", "clip": "seed42",
                       "ball": {"x": 50.0, "y": 34.0, "z": 0.0}, "players": players})
    return {"restarts": [], "frames": frames}


def observations_clip() -> list[dict]:
    P = camera([52.5, -30.0, 25.0], [52.5, 34.0, 0.0], w=W, h=H, f=300.0)
    rows = []
    for f in SHOWN:
        ball = [] if f == 1520 else [{"bbox": [150, 80, 154, 84], "score": 0.9, "x": 50.0, "y": 34.0}]
        rows.append({"frame": f, "t": round(f / FPS, 2), "camera": {"ok": True, "P": P}, "players": [],
                     "ball": ball})
    return rows


def test_a_frame_fused_from_the_fixed_views_has_no_broadcast_footprint():
    """Observations fused from the tactical lenses carry each view's fit, not the broadcast camera's
    matrix: the broadcast picture's footprint is unknown there, never an error or a guess."""
    rows = observations_clip()
    rows[0]["camera"] = {"ok": True, "views": {"tac-l": {"ok": True}, "tac-r": {"ok": False}}}
    body = radar.build(tracked_clip(), rows, W, H)
    assert body["views"][0]["footprint"] is None
    assert body["views"][1]["footprint"] is not None


@pytest.fixture(scope="module")
def browser():
    if not (DIST / "index.html").exists():
        unavailable(f"{DIST} is not built: npm run build --prefix web/viewer")
    try:
        from playwright.sync_api import sync_playwright

        with sync_playwright() as p:
            b = p.chromium.launch(args=["--mute-audio"])  # never a sound on the machine running it
            yield b
            b.close()
    except Exception as e:  # no Chromium installed
        if "Executable doesn't exist" in str(e):
            unavailable(str(e))
        raise


@pytest.fixture(scope="module")
def site(browser, tmp_path_factory):
    """dist/ with the cut clip's bundle at bundle/ (with the radar), and at plain/ without it."""
    root = tmp_path_factory.mktemp("radar-site")
    page = browser.new_page(viewport={"width": W, "height": H})
    page.set_content('<body style="margin:0;background:#2e7d32"></body>')
    jpeg = page.screenshot(type="jpeg")
    page.close()
    clip, detections, events = write_clip(tmp_path_factory.mktemp("clip"), jpeg)
    meta = json.loads((clip / "clip.json").read_text())
    (clip / "clip.json").write_text(json.dumps({**meta, "segments": SEGMENTS}))
    tracked = root / "tracked.json"
    tracked.write_text(json.dumps(tracked_clip()))
    observations = root / "observations.jsonl"
    observations.write_text("".join(json.dumps(r) + "\n" for r in observations_clip()))
    www = root / "www"
    shutil.copytree(DIST, www)
    common = [str(clip), "--detections", str(detections), "--frames", "--events-file", str(events)]
    for out, extra in (("bundle", ["--tracked", str(tracked), "--observations", str(observations)]),
                       ("plain", [])):
        worker = threading.Thread(target=e2e.main, args=(common + ["--out", str(www / out)] + extra,))
        worker.start()
        worker.join()
        assert (www / out / "manifest.json").exists()
    handler = functools.partial(SimpleHTTPRequestHandler, directory=str(www))
    handler.log_message = lambda *a: None
    server = ThreadingHTTPServer(("127.0.0.1", 0), handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    yield f"http://127.0.0.1:{server.server_address[1]}/", www
    server.shutdown()


def open_viewer(browser, url, **context):
    ctx = browser.new_context(viewport={"width": 1280, "height": 900}, **context)
    page = ctx.new_page()
    errors: list[str] = []
    page.on("pageerror", lambda e: errors.append(str(e)))
    page.goto(url)
    page.wait_for_selector("body[data-state=ready] #overlay[data-t]")
    return page, errors


def at(page, image: float) -> dict:
    """The radar's state at the middle of clip image `image` (video time, not match time)."""
    return page.evaluate(f"window.ninetyRadar.at({(image + 0.5) / FPS})")


def player(state: dict, pid: str) -> dict | None:
    return next((p for p in state["players"] if p["id"] == pid), None)


def test_a_cut_frame_maps_to_the_tracked_frame_after_the_cut(browser, site):
    page, errors = open_viewer(browser, site[0])
    assert at(page, 39)["frame"] == 1539  # the last image before the cut
    after = at(page, 40)  # the first image after it shows match frame 1550, not 1540
    assert after["frame"] == 1550
    assert player(after, "h-t1")["x"] == pytest.approx(20.0 + 0.2 * 50.5)
    h2 = player(after, "h-t2")
    assert (h2["x"], h2["y"], h2["estimated"]) == (pytest.approx(90.0), pytest.approx(10.0), False)
    assert h2.get("number") is None  # the tracker reads no shirt numbers, so none is drawn
    assert not errors


def test_nothing_is_drawn_across_a_cut(browser, site):
    page, _ = open_viewer(browser, site[0])
    assert player(at(page, 36), "h-t2")["estimated"] is False  # seen in 1536
    # 1537-1539: unseen, and his next sighting is across the cut (13 frames on, inside the tracker's
    # gap). Drawn on the way there, he would cross half the pitch in a frame on the radar.
    for image in (37, 38, 39):
        assert player(at(page, image), "h-t2") is None, image
    # h-t4, the other way: after the cut, his last sighting is from before it.
    for image in (40, 41, 42):
        assert player(at(page, image), "h-t4") is None, image
    assert player(at(page, 43), "h-t4")["x"] == pytest.approx(80.0)


def test_a_player_unseen_in_the_frame_on_screen_is_placed_between_sightings_and_marked(browser, site):
    page, _ = open_viewer(browser, site[0])
    seen = player(at(page, 5), "h-t1")
    assert seen["estimated"] is False
    gap = player(at(page, 12), "h-t1")  # 1510-1514 unseen: between 1509 and 1515
    assert gap["estimated"] is True
    assert gap["x"] == pytest.approx(20.0 + 0.2 * 12.5)
    assert player(at(page, 15), "h-t1")["estimated"] is False


def test_a_ball_vision_did_not_find_is_marked_estimated(browser, site):
    page, _ = open_viewer(browser, site[0])
    assert at(page, 19)["ball"]["estimated"] is False
    assert at(page, 20)["ball"]["estimated"] is True  # the tracked file has it; vision did not see it
    assert at(page, 21)["ball"]["estimated"] is False


def rgb_near(px, rgb, tol=40) -> bool:
    return all(abs(a - b) <= tol for a, b in zip(px[:3], rgb, strict=True))


def test_seen_is_drawn_filled_and_estimated_hollow(browser, site):
    page, _ = open_viewer(browser, site[0])
    seen = page.evaluate(f"""(() => {{
        window.ninetyRadar.drawAt({5.5 / FPS});
        const p = 20.0 + 0.2 * 5.5;
        return [window.ninetyRadar.pixel(p, 30), window.ninetyRadar.pixel(p, 30, 4.5)];
    }})()""")
    assert rgb_near(seen[0], HOME_RGB), seen  # a filled dot: home blue at its centre
    hollow = page.evaluate(f"""(() => {{
        window.ninetyRadar.drawAt({12.5 / FPS});
        const p = 20.0 + 0.2 * 12.5;
        return [window.ninetyRadar.pixel(p, 30), window.ninetyRadar.pixel(p, 30, 4.5)];
    }})()""")
    assert not rgb_near(hollow[0], HOME_RGB, tol=80), hollow  # grass shows through its centre
    # Its ring is drawn in the club's colour: nearer it than the grass at the centre is (a test of
    # which colour, not of how bright one channel is, so it holds for any club colour).
    dist = lambda px: sum((a - b) ** 2 for a, b in zip(px[:3], HOME_RGB, strict=True))  # noqa: E731
    assert dist(hollow[1]) < dist(hollow[0]) / 2, hollow


def test_the_radar_toggles_from_the_keyboard_and_says_what_it_shows(browser, site):
    page, errors = open_viewer(browser, site[0])
    page.wait_for_function("document.querySelector('#radar').getAttribute('aria-label').startsWith('Radar:')")
    label = page.get_attribute("#radar", "aria-label")
    # The clubs by the names of the codes the clip was rendered with (CRW, DUN), never home and away.
    assert "Crowmere" in label and "Dunhollow" in label and "broadcast camera" in label
    assert "home" not in label.lower() and "away" not in label.lower()
    assert page.is_visible("#radar")
    page.keyboard.press("m")
    assert not page.is_visible("#radar")
    page.keyboard.press("m")
    assert page.is_visible("#radar")
    assert not errors


def test_a_bundle_without_tracked_positions_says_so(browser, site):
    page, errors = open_viewer(browser, site[0] + "?bundle=plain/")
    assert "no tracked positions" in page.inner_text("#radar-note")
    assert not page.is_visible("#radar")
    assert not errors


def test_positions_from_the_answer_key_are_refused_in_the_browser_too(browser, site):
    url, www = site
    bad = www / "bad"
    shutil.copytree(www / "bundle", bad)
    body = json.loads((bad / "radar.json").read_text())
    body["frames"][0]["source"] = "truth"
    (bad / "radar.json").write_text(json.dumps(body))
    page, errors = open_viewer(browser, url + "?bundle=bad/")
    assert "not vision's tracked output" in page.inner_text("#radar-note")
    assert not page.is_visible("#radar")
    assert not errors
