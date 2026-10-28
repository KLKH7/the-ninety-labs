"""Smoke test of the viewer (web/viewer) in headless Chromium, on a bundle ninety-e2e wrote.

Needs the built viewer (`npm ci --prefix web/viewer && npm run build --prefix web/viewer`) and
Playwright's Chromium. Skipped without them, unless NINETY_REQUIRE_VIEWER=1 (the CI viewer job sets
it, so the test can never silently stop running there).
"""

import functools
import json
import os
import shutil
import threading
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import pytest

from ninety import e2e
from tests.e2e_clip import T_START, H, W, write_clip

ROOT = Path(__file__).resolve().parent.parent
DIST = ROOT / "web" / "viewer" / "dist"


def unavailable(reason: str):
    if os.environ.get("NINETY_REQUIRE_VIEWER") == "1":
        pytest.fail(reason)
    pytest.skip(reason)


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
    """dist/ with a bundle at bundle/, served over HTTP the way a static host would."""
    yield from serve_site(browser, tmp_path_factory, "--plant")


def serve_site(browser, tmp_path_factory, *extra, events: list[dict] | None = None):
    root = tmp_path_factory.mktemp("site")
    page = browser.new_page(viewport={"width": W, "height": H})
    page.set_content('<body style="margin:0;background:#2e7d32"></body>')
    jpeg = page.screenshot(type="jpeg")
    page.close()
    clip, detections, events_file = write_clip(tmp_path_factory.mktemp("clip"), jpeg)
    if events is not None:
        events_file.write_text("".join(json.dumps(e) + "\n" for e in events))
    www = root / "www"
    shutil.copytree(DIST, www)
    args = [str(clip), "--out", str(www / "bundle"), "--detections", str(detections), "--frames", *extra,
            "--events-file", str(events_file)]
    # Playwright's sync API holds this thread's event loop; ninety-e2e runs its own in another.
    worker = threading.Thread(target=e2e.main, args=(args,))
    worker.start()
    worker.join()
    assert (www / "bundle" / "manifest.json").exists()
    handler = functools.partial(SimpleHTTPRequestHandler, directory=str(www))
    handler.log_message = lambda *a: None
    server = ThreadingHTTPServer(("127.0.0.1", 0), handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    yield f"http://127.0.0.1:{server.server_address[1]}/"
    server.shutdown()


def open_viewer(browser, site, **context):
    ctx = browser.new_context(viewport={"width": 1280, "height": 900}, **context)
    page = ctx.new_page()
    errors: list[str] = []
    page.on("pageerror", lambda e: errors.append(str(e)))
    page.goto(site)
    page.wait_for_selector("body[data-state=ready] #overlay[data-t]")
    return page, errors


def on_air(page) -> list[str]:
    return (page.get_attribute("#overlay", "data-on-air") or "").split()


def match_t(page) -> float:
    return float(page.get_attribute("#overlay", "data-t"))


def test_trace_shows_the_rejection_and_the_accepted_claim(browser, site):
    page, errors = open_viewer(browser, site)
    claim = page.locator("#claims .claim")
    assert claim.count() == 1
    assert claim.locator(".chip").text_content() == "Accepted"
    # The fixture's speed is not measured, so the trace says the claim without it (src/speed.ts); the
    # fact-checker's reason still names the planted 143 it rejected.
    assert "h8 shoots, on target." in claim.inner_text()
    assert "km/h" not in claim.inner_text()
    assert claim.locator(".step.reject").count() == 1
    assert "143" in claim.locator(".step.reject").inner_text()
    assert "Events" in page.locator("#pipeline").inner_text()
    assert not errors


def test_graphics_follow_the_clock_and_the_persona(browser, site):
    page, errors = open_viewer(browser, site)
    assert match_t(page) == pytest.approx(T_START, abs=0.05)
    page.get_by_role("button", name="Watch it").click()  # to just before the shot
    page.wait_for_function("document.querySelector('#overlay').dataset.t > 60.6")
    page.keyboard.press("2")  # the analyst's graphics
    page.keyboard.press(".")  # frame by frame up to the shot at 61.2 s
    for _ in range(25):
        if "cue-e2-analyst" in on_air(page):
            break
        page.keyboard.press(".")
    assert page.get_by_role("radio", name="Analyst").get_attribute("aria-checked") == "true"
    # The agents' claim about the shot only restates it, so it is not an INSIGHT (ninety/agents/
    # insight_bar.py): the shot's own graphic airs, and the claim stays in the trace (How we know).
    assert set(on_air(page)) == {"cue-e2-analyst"}
    assert "insight" not in page.locator("#on-air").inner_text().lower()
    assert page.locator("#claims .claim").count() >= 1

    page.keyboard.press("1")
    page.wait_for_function("document.querySelector('#overlay').dataset.onAir === 'cue-e2-casual'")
    assert page.get_by_role("radio", name="Casual").get_attribute("aria-checked") == "true"
    assert page.locator("#claims .claim").get_attribute("aria-current") is None
    assert not errors


def test_keyboard_alone_drives_the_viewer(browser, site):
    page, errors = open_viewer(browser, site)
    page.keyboard.press("Tab")
    assert page.evaluate("document.activeElement.className") == "skip"
    page.keyboard.press("Tab")
    assert page.evaluate("document.activeElement.getAttribute('role')") == "radio"
    page.keyboard.press("ArrowRight")  # the radio group moves with arrows
    assert page.get_by_role("radio", name="Analyst").get_attribute("aria-checked") == "true"
    page.keyboard.press("Tab")
    assert page.evaluate("document.activeElement.id") == "reduce-motion"
    page.keyboard.press("Tab")  # onto the footage itself
    assert page.evaluate("document.activeElement.id") == "overlay"
    page.keyboard.press("ArrowRight")  # one second on
    page.wait_for_function(f"document.querySelector('#overlay').dataset.t > {T_START + 0.9}")
    assert match_t(page) == pytest.approx(T_START + 1, abs=0.05)
    page.keyboard.press("Space")
    page.wait_for_function(f"document.querySelector('#overlay').dataset.t > {T_START + 1.2}")
    page.keyboard.press("Space")
    page.wait_for_function("document.querySelector('#play').textContent === 'Play'")
    paused = match_t(page)
    page.wait_for_timeout(300)
    assert match_t(page) == paused
    assert not errors


def test_reduced_motion_is_on_when_the_system_asks(browser, site):
    page, errors = open_viewer(browser, site, reduced_motion="reduce")
    assert page.is_checked("#reduce-motion")
    assert page.evaluate("document.documentElement.dataset.motion") == "reduce"
    page, _ = open_viewer(browser, site, reduced_motion="no-preference")
    assert not page.is_checked("#reduce-motion")
    assert not errors


def test_the_described_caption_is_a_slim_lower_third_inside_title_safe(browser, site):
    """Audio description's caption as a broadcast lower third (Kian, Oct 27): about 28 px type at 1080
    lines, one line where it fits, inside title-safe (EBU R 95: the middle 90%), placed by its pan,
    and a long line wraps rather than leaving the picture."""
    page, errors = open_viewer(browser, site)
    W, H = 1920, 1080

    def box(text, pan, w=W, h=H):  # type about 14 px a character at 1080 lines
        measure = f"(s) => s.length * {w} / 1920 * 14"
        return page.evaluate(f"window.ninetyDraw.captionBox({measure}, {json.dumps(text)}, {pan}, {w}, {h})")

    short = "Goal! Ben Vomble scores for Lisbon, on the left. It's 1–1."
    mid = box(short, 0)
    assert 26 <= mid["size"] <= 30 and mid["lines"] == [short]
    assert mid["h"] < 0.07 * H  # slim: one line, not a subtitle wall
    left, right = box(short, -1), box(short, 1)
    assert left["x"] < mid["x"] < right["x"]
    # Hard left and hard right sit on title-safe's edges; centre is centred.
    assert left["x"] == pytest.approx(0.05 * W) and right["x"] + right["w"] == pytest.approx(0.95 * W)
    assert mid["x"] + mid["w"] / 2 == pytest.approx(W / 2)
    line = "The pass from Isaac Thinton is cut out by a Lisbon player, in the middle, near side."
    long = f"{line} {line}"
    for b in (left, right, mid, box(long, -1), box(long, 1), box(long, 0, 1280, 720)):
        w, h = (1280, 720) if b["size"] < 20 else (W, H)
        assert 0.05 * w - 1e-6 <= b["x"] and b["x"] + b["w"] <= 0.95 * w + 1e-6
        assert 0.05 * h <= b["y"] and b["y"] + b["h"] <= 0.95 * h + 1e-6
    lines = box(long, 0)["lines"]
    assert len(lines) == 2 and " ".join(lines) == long  # wrapped, every word kept
    assert not errors


def narrator(page) -> dict:
    return page.evaluate("({...window.ninetyNarrator.state})")


def play_to(page, t: float) -> None:
    page.keyboard.press("Space")
    page.wait_for_function(f"document.querySelector('#overlay').dataset.t >= {t}")
    page.keyboard.press("Space")


def test_audio_description_speaks_each_line_once_in_time(browser, site):
    page, errors = open_viewer(browser, site)
    page.keyboard.press("3")
    assert page.get_by_role("radio", name="Audio description").get_attribute("aria-checked") == "true"
    assert "not voiced" in page.locator("#audio-note").inner_text()  # this bundle has no recorded lines
    # No voice in the bundle: no voice switch or its keys, and the live region is how a screen reader
    # hears the description (aria-live off would leave a blind fan nothing).
    assert not page.is_visible("#voice-toggle") and not page.is_visible("#audio-keys")
    assert page.get_attribute("#on-air", "aria-live") == "polite"
    page.get_by_role("button", name="Watch it").click()  # seeks past the first line, to 60.7 s
    page.keyboard.press("3")
    play_to(page, 62.85)
    # mutation: say every line whose start is behind the clock (no SEEK_S guard) -> ad-e1 is said late
    assert narrator(page)["spoken"] == ["ad-insight-m-e2"]
    assert "ad-insight-m-e2" in on_air(page)
    # The line due is the text of #on-air, shown and read by a screen reader in place of the graphics.
    line = page.evaluate("window.ninetyNarrator.at(document.querySelector('#overlay').dataset.t * 1)")
    assert line and page.inner_text("#on-air") == line["spoken"]
    assert "143" not in page.locator("#on-air").inner_text()  # the planted number is never on air
    assert not errors


def test_the_viewer_never_speaks_with_the_browser_s_voice(browser, site):
    """A line with no recorded audio is silent, its caption kept: audio description and commentary are
    the bundle's voiced files or nothing (Kian, Oct 27: the browser's voice sounds robotic)."""
    ctx = browser.new_context(viewport={"width": 1280, "height": 900})
    ctx.add_init_script("""window.__speak = 0;
        if (window.speechSynthesis) speechSynthesis.speak = () => { window.__speak += 1; };""")
    page = ctx.new_page()
    page.goto(site)
    page.wait_for_selector("body[data-state=ready] #overlay[data-t]")
    page.keyboard.press("3")  # audio description, voice on
    page.get_by_role("button", name="Watch it").click()
    page.keyboard.press("3")
    play_to(page, 62.85)
    assert narrator(page)["spoken"], "a line came due, or this proves nothing"
    assert narrator(page)["voice"] == "none"
    # mutation: speak a line without a file through speakAloud -> ninetySpokenAloud holds it
    assert page.evaluate("window.ninetySpokenAloud") is None and page.evaluate("window.__speak") == 0
    ctx.close()


def test_audio_description_is_silent_with_the_voice_off(browser, site):
    page, errors = open_viewer(browser, site)
    page.keyboard.press("3")
    page.keyboard.press("v")
    assert not page.is_checked("#voice")
    assert page.get_attribute("#on-air", "aria-live") == "polite"
    # mutation: ignore the voice switch in Narrator.update -> lines are said anyway
    play_to(page, 62.85)
    assert narrator(page)["spoken"] == []
    page.keyboard.press("1")
    assert not page.is_visible("#voice-toggle")
    assert not errors


def test_a_fallback_cue_says_so_on_screen_and_to_a_screen_reader(browser, site):
    # A template graphic that stayed because the agents' claim was held carries `fallback`
    # (schemas/overlay_cue.schema.json); the viewer badges it and says it.
    import json

    ctx = browser.new_context(viewport={"width": 1280, "height": 900})

    def badged(route):
        cues = [json.loads(line) for line in route.fetch().text().splitlines() if line.strip()]
        cues = [c if c["kind"] == "insight" else {**c, "fallback": "held: timeout"} for c in cues]
        route.fulfill(body="".join(json.dumps(c) + "\n" for c in cues), content_type="application/x-ndjson")

    ctx.route("**/bundle/cues.jsonl", badged)
    page = ctx.new_page()
    errors: list[str] = []
    page.on("pageerror", lambda e: errors.append(str(e)))
    page.goto(site)
    page.wait_for_selector("body[data-state=ready] #overlay[data-t]")
    page.get_by_role("button", name="Watch it").click()
    for _ in range(40):
        if "fallback" in page.inner_text("#on-air"):
            break
        page.keyboard.press(".")
    assert "(fallback: held: timeout)" in page.inner_text("#on-air")
    assert not errors


# Tracked players (dry run of the demo, Oct 24): h-t4's side was told surely, a-t9's was not, and
# h-t8 is only the receiver, whose side that pass did not measure.
TRACKED = [
    {"id": "e1", "t": 60.4, "frame": 1510, "type": "pass", "team": "home", "team_confidence": 0.99,
     "player": "h-t4", "receiver": "h-t8", "intended": "h-t8", "interceptor": None, "deflected_by": None,
     "x": 40.0, "y": 30.0, "end_x": 52.0, "end_y": 35.0, "outcome": "success", "ball_speed_kmh": 48.0,
     "source": "vision", "confidence": 0.9},
    {"id": "e2", "t": 61.2, "frame": 1530, "type": "shot", "team": "away", "team_confidence": 0.3,
     "player": "a-t9", "receiver": None, "x": 80.0, "y": 34.0, "end_x": 104.0, "end_y": 33.0,
     "outcome": "on_target", "ball_speed_kmh": 101.4, "source": "vision", "confidence": 0.9},
]


@pytest.fixture(scope="module")
def tracked_site(browser, tmp_path_factory):
    yield from serve_site(browser, tmp_path_factory, events=TRACKED)


def test_a_tracked_player_on_an_unsure_side_is_a_player_on_screen(browser, tracked_site):
    # A track id's letter is the tracker's side vote. The screen names the club only for a side the
    # fact-checker vouches for (the bundle's sides_known); every other tracked player is "a player".
    page, errors = open_viewer(browser, tracked_site)
    page.get_by_role("button", name="Watch it").click()
    page.wait_for_function("document.querySelector('#overlay').dataset.t > 60.3")
    page.keyboard.press("1")  # casual: the templates' sentences
    seen = set()
    for _ in range(40):
        seen.add(page.locator("#on-air").inner_text().strip())
        page.keyboard.press(".")
    text = " | ".join(t for t in seen if t)
    assert "Crowmere player" in text, text  # h-t4: a side told surely
    assert "Dunhollow" not in text, text  # a-t9: the tracker's vote alone never names a club
    assert "a player" in text or "A player" in text, text
    assert not errors


def aired_speeds(page) -> list[str]:
    import re

    texts = page.evaluate("window.ninetyCues.map((c) => c.text)")
    return [m for t in texts for m in re.findall(r"[\d.]+(?: ± \d+)? km/h", t)]


def test_no_ball_speed_airs_while_vision_s_speed_error_is_unmeasured(browser, tracked_site):
    import re

    # Option H (Oct 25): vision's ball speeds (48 and 101 km/h here) are held until #331's error is
    # measured; the bundle says nothing about it, so no graphic states one, and the shot still airs.
    page, errors = open_viewer(browser, tracked_site)
    assert aired_speeds(page) == []
    texts = page.evaluate("window.ninetyCues.map((c) => c.text)")
    assert any("shoots" in t for t in texts), texts
    said = page.evaluate("window.ninetyNarrator.lines.flatMap((l) => [l.text, l.spoken])")
    assert said and not any(re.search(r"\d\s*(km/h|kilomet)", t) for t in said), said  # the voice too
    assert "km/h" not in page.locator("#claims").inner_text()
    page.get_by_role("button", name="Watch it").click()
    page.wait_for_function("document.querySelector('#overlay').dataset.t > 60.3")
    page.keyboard.press("2")  # the analyst's graphics, which state speeds
    seen = set()
    for _ in range(40):
        seen.add(page.locator("#on-air").inner_text().strip())
        page.keyboard.press(".")
    assert any(seen) and not any("km/h" in t for t in seen), seen
    assert not errors


@pytest.fixture(scope="module")
def ground_site(browser, tmp_path_factory):
    # The tracked clip with its pass marked along the ground by vision (`lofted` false), and that mark
    # taken as measured, as it will be (factcheck.LOFTED_FLAG_MEASURED): the one speed vision's measured
    # error covers, so the bundle's manifest.speed opens.
    from ninety.agents import factcheck

    with pytest.MonkeyPatch.context() as patch:
        patch.setattr(factcheck, "LOFTED_FLAG_MEASURED", True)
        yield from serve_site(browser, tmp_path_factory,
                              events=[{**e, "lofted": False} if e["type"] == "pass" else e for e in TRACKED])


def test_a_measured_ball_speed_airs_with_its_band_and_never_above_p3(browser, ground_site):
    # Once measured (manifest.speed), a speed shows with its error band; 147 km/h is above P3's
    # 40 m/s (144 km/h), so no ball went that fast and it never airs (the demo's 4-1 graphic).
    import json

    from ninety.agents import factcheck

    ctx = browser.new_context(viewport={"width": 1280, "height": 900})

    def fast(route):
        cues = [json.loads(line) for line in route.fetch().text().splitlines() if line.strip()]
        first = next(c for c in cues if "48" in c["text"] and "km/h" in c["text"])
        fast_text = first["text"].replace("48.0 km/h", "147 km/h")
        cues.append({**first, "id": first["id"] + "-fast", "text": fast_text})
        route.fulfill(body="".join(json.dumps(c) + "\n" for c in cues), content_type="application/x-ndjson")

    ctx.route("**/bundle/cues.jsonl", fast)
    page = ctx.new_page()
    errors: list[str] = []
    page.on("pageerror", lambda e: errors.append(str(e)))
    page.goto(ground_site)
    page.wait_for_selector("body[data-state=ready] #overlay[data-t]")
    speeds = aired_speeds(page)
    band = f" ± {factcheck.SPEED_ERROR_KMH} km/h"
    assert speeds and all(s.endswith(band) for s in speeds), speeds  # 48 km/h, with its band
    assert not any(s.startswith("147") for s in speeds), speeds
    assert not any(s.startswith("101") for s in speeds), speeds  # the shot's speed is not measured
    assert not errors


def test_every_way_a_speed_is_written_or_said_is_gated(browser, site):
    """Merge-queue review of #378: the gate fails closed on any number with a speed unit, written or
    spoken, and `measured: false` airs nothing even with an error given."""
    page, errors = open_viewer(browser, site)

    def say(text, gate=None):
        return page.evaluate("([t, g]) => window.ninetySpeed(t, g)", [text, gate])

    held = [
        ("a pass (incomplete), 19 m, 146 km/h", "a pass (incomplete), 19 m"),
        ("h-t1 plays a 19 m pass at 49 km/h, but it doesn't arrive.",
         "h-t1 plays a 19 m pass, but it doesn't arrive."),
        ("A player plays it 13 metres to another player, at 49 kilometres an hour.",
         "A player plays it 13 metres to another player."),
        ("a 101.4 km/h strike", "a strike"),
        ("scores, 147 km/h", "scores"),
    ]
    for text, want in held:
        assert say(text) == want
        assert say(text, {"measured": False, "error_kmh": 3.5}) == want
    measured = {"measured": True, "error_kmh": 3.5}
    assert say("a 19 m pass at 49 km/h.", measured) == "a 19 m pass at 49 ± 4 km/h."
    assert say("at 49 kilometres an hour.", measured) == "at 49 kilometres an hour, give or take 4."
    assert say("scores, 147 km/h", measured) == "scores"  # above P3: no ball goes that fast
    assert not errors
