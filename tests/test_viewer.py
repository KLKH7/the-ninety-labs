"""Smoke test of the viewer (web/viewer) in headless Chromium, on a bundle ninety-e2e wrote.

Needs the built viewer (`npm ci --prefix web/viewer && npm run build --prefix web/viewer`) and
Playwright's Chromium. Skipped without them, unless NINETY_REQUIRE_VIEWER=1 (the CI viewer job sets
it, so the test can never silently stop running there).
"""

import functools
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
            b = p.chromium.launch()
            yield b
            b.close()
    except Exception as e:  # no Chromium installed
        if "Executable doesn't exist" in str(e):
            unavailable(str(e))
        raise


@pytest.fixture(scope="module")
def site(browser, tmp_path_factory):
    """dist/ with a bundle at bundle/, served over HTTP the way a static host would."""
    root = tmp_path_factory.mktemp("site")
    page = browser.new_page(viewport={"width": W, "height": H})
    page.set_content('<body style="margin:0;background:#2e7d32"></body>')
    jpeg = page.screenshot(type="jpeg")
    page.close()
    clip, detections, events = write_clip(tmp_path_factory.mktemp("clip"), jpeg)
    www = root / "www"
    shutil.copytree(DIST, www)
    args = [str(clip), "--out", str(www / "bundle"), "--detections", str(detections), "--frames", "--plant",
            "--events-file", str(events)]
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
    assert "h8 shot, on target, 101 km/h." in claim.inner_text()
    assert claim.locator(".step.reject").count() == 1
    assert "143" in claim.locator(".step.reject").inner_text()
    assert "Events" in page.locator("#pipeline").inner_text()
    assert not errors


def test_graphics_follow_the_clock_and_the_persona(browser, site):
    page, errors = open_viewer(browser, site)
    assert match_t(page) == pytest.approx(T_START, abs=0.05)
    page.get_by_role("button", name="Watch it").click()  # to just before the shot
    page.wait_for_function("document.querySelector('#overlay').dataset.t > 60.6")
    page.keyboard.press("2")  # the verified insight airs for the analyst (ninety/agents/live.py)
    page.keyboard.press(".")  # frame by frame up to the shot at 61.2 s
    for _ in range(25):
        if "insight-e2" in on_air(page):
            break
        page.keyboard.press(".")
    assert page.get_by_role("radio", name="Analyst").get_attribute("aria-checked") == "true"
    assert set(on_air(page)) == {"insight-e2", "cue-e2-analyst"}
    assert "Crowmere 8 shot, on target, 101 km/h" in page.locator("#on-air").inner_text()
    assert page.locator("#claims .claim").get_attribute("aria-current") == "true"

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
    assert page.is_visible("#voice-toggle") and page.is_checked("#voice")
    assert "where the play is" in page.locator("#audio-note").inner_text()
    # With the voice on, the live region is quiet: a screen reader does not say each line twice.
    assert page.get_attribute("#on-air", "aria-live") == "off"
    page.get_by_role("button", name="Watch it").click()  # seeks past the first line, to 60.7 s
    page.keyboard.press("3")
    play_to(page, 62.85)
    # mutation: say every line whose start is behind the clock (no SEEK_S guard) -> ad-e1 is said late
    assert narrator(page)["spoken"] == ["ad-insight-e2"]
    assert "ad-insight-e2" in on_air(page)
    assert "143" not in page.locator("#on-air").inner_text()  # the planted number is never on air
    assert not errors


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
