"""The live smoke test: the deployed demo, end to end, in headless Chromium, as a judge would open it.

    NINETY_LIVE_URL=https://<app>.azurecontainerapps.io uv run pytest -q tests/test_live_smoke.py

Skipped without NINETY_LIVE_URL. The deploy workflow sets it with NINETY_REQUIRE_LIVE=1, so there
it can never silently skip, and NINETY_EXPECT_COMMIT, so an old revision still serving is a failure.
Reads only: it calls no route that costs a model call, and sends neither the MCP key nor the passcode.
"""

import json
import os
import time
import urllib.error
import urllib.request

import pytest

URL = os.environ.get("NINETY_LIVE_URL", "").rstrip("/")
pytestmark = pytest.mark.skipif(not URL and os.environ.get("NINETY_REQUIRE_LIVE") != "1",
                                reason="NINETY_LIVE_URL is not set")


def get(path: str, method: str = "GET", body: bytes | None = None) -> tuple[int, dict, bytes]:
    if not URL:
        pytest.fail("NINETY_REQUIRE_LIVE=1 but NINETY_LIVE_URL is not set")
    req = urllib.request.Request(URL + path, method=method, data=body,
                                 headers={"content-type": "application/json"} if body else {})
    try:
        with urllib.request.urlopen(req, timeout=60) as r:  # the first call may wake a cold replica
            return r.status, dict(r.headers), r.read()
    except urllib.error.HTTPError as e:
        return e.code, dict(e.headers), e.read()


def test_health_reports_the_deployed_commit():
    status, _, body = get("/api/health")
    assert status == 200
    expected = os.environ.get("NINETY_EXPECT_COMMIT")
    if expected:
        assert json.loads(body)["commit"] == expected


def test_the_keyed_routes_are_configured_and_closed():
    # 401, not 503: the Key Vault secret reached the app, and nothing passes without it.
    listing = json.dumps({"jsonrpc": "2.0", "id": 1, "method": "tools/list"}).encode()
    status, _, _ = get("/mcp", "POST", listing)
    assert status == 401
    status, _, _ = get("/api/live/status")
    assert status == 401


def test_the_bundle_holds_no_answer_key():
    status, _, body = get("/bundle/manifest.json")
    assert status == 200 and json.loads(body)["format"] == 1
    for name in ("frames.jsonl", "clip.json", "meta.json"):
        assert get(f"/bundle/{name}")[0] == 404, name


def test_the_security_headers_are_sent():
    _, headers, _ = get("/")
    headers = {k.lower(): v for k, v in headers.items()}
    assert "connect-src 'self'" in headers["content-security-policy"]
    assert headers["x-content-type-options"] == "nosniff"


def clock(page) -> float:
    return float(page.get_attribute("#overlay", "data-t"))


def wait_until(check, seconds: float) -> None:
    """Polls from Python: the site's CSP forbids eval, which page.wait_for_function relies on."""
    end = time.monotonic() + seconds
    while not check():
        assert time.monotonic() < end, "timed out"
        time.sleep(0.1)


def test_the_viewer_plays_the_replay_with_its_graphics():
    from playwright.sync_api import sync_playwright

    manifest = json.loads(get("/bundle/manifest.json")[2])
    with sync_playwright() as p:
        browser = p.chromium.launch()
        page = browser.new_page(viewport={"width": 1280, "height": 900})
        problems: list[str] = []
        page.on("pageerror", lambda e: problems.append(f"page error: {e}"))
        page.on("console", lambda m: m.type == "error" and problems.append(f"console: {m.text}"))
        page.on("requestfailed", lambda r: problems.append(f"request failed: {r.url}"))
        page.goto(URL + "/", timeout=90_000)
        page.wait_for_selector("body[data-state=ready] #overlay[data-t]", timeout=60_000)
        assert page.locator("#claims .claim").count() == manifest["agents"]["claims"]

        start = clock(page)
        page.locator("#overlay").focus()
        page.keyboard.press("Space")  # the footage plays and the clock follows it
        wait_until(lambda: clock(page) > start + 0.5, 30)
        page.keyboard.press("Space")

        seen: set[str] = set()  # step through the clip a second at a time: some graphic goes on air
        for _ in range(int(manifest["footage"]["frames"] / manifest["fps"]) + 1):
            seen |= set((page.get_attribute("#overlay", "data-on-air") or "").split())
            page.keyboard.press("ArrowRight")
            page.wait_for_timeout(100)
        assert seen, "no graphic went on air during the whole clip"
        browser.close()
    assert not problems, problems
