"""The demo site the API serves: the viewer, the Replay bundle, Live mode's passcode, the headers."""

import json

import pytest
from starlette.testclient import TestClient

from ninety.api import app as api


@pytest.fixture
def site(tmp_path):
    viewer = tmp_path / "viewer"
    (viewer / "assets").mkdir(parents=True)
    (viewer / "index.html").write_text("<!doctype html><title>viewer</title>")
    (viewer / "assets" / "index-abc.js").write_text("console.log(1)")
    replay = tmp_path / "replay"
    replay.mkdir()
    (replay / "manifest.json").write_text(json.dumps({"format": 1}))
    (replay / "video.webm").write_bytes(bytes(range(256)) * 4)
    phone = tmp_path / "phone"
    phone.mkdir()
    (phone / "index.html").write_text("<!doctype html><title>phone</title>")
    (phone / "assets").mkdir()
    (phone / "assets" / "index-def.js").write_text("console.log(2)")
    (tmp_path / "secret.txt").write_text("outside the bundle")
    return TestClient(api.build("k" * 64, passcode="p" * 24, viewer=viewer, replay=replay, phone=phone))


def test_the_viewer_is_served_at_the_root(site):
    r = site.get("/")
    assert r.status_code == 200 and "<title>viewer</title>" in r.text
    assert r.headers["cache-control"] == "no-store"
    assert "immutable" in site.get("/assets/index-abc.js").headers["cache-control"]


def test_the_phone_companion_is_served_beside_the_viewer(site):
    # The viewer's QR code points at phone/ relative to its own page (web/viewer/src/companion.ts).
    for path in ("/phone/", "/phone"):
        r = site.get(path)
        assert r.status_code == 200 and "<title>phone</title>" in r.text, path
    # Framed only by this origin's big screen (its companion panel), never by another site.
    assert "frame-ancestors 'self'" in site.get("/phone/").headers["content-security-policy"]
    assert site.get("/phone/../secret.txt").status_code == 404
    assert "immutable" in site.get("/phone/assets/index-def.js").headers["cache-control"]


def test_the_replay_bundle_is_served_with_byte_ranges(site):
    assert site.get("/bundle/manifest.json").json() == {"format": 1}
    r = site.get("/bundle/video.webm", headers={"range": "bytes=10-19"})
    assert r.status_code == 206 and r.content == bytes(range(10, 20))


def test_nothing_outside_the_bundle_is_served(site):
    for path in ("/bundle/../secret.txt", "/bundle/%2e%2e/secret.txt", "/../secret.txt"):
        assert site.get(path).status_code == 404, path


def test_every_response_carries_the_security_headers(site):
    for path in ("/", "/bundle/manifest.json", "/api/health", "/api/live/status", "/nope"):
        h = site.get(path).headers
        assert "connect-src 'self'" in h["content-security-policy"], path
        assert "frame-ancestors 'none'" in h["content-security-policy"], path
        assert h["x-content-type-options"] == "nosniff", path


def test_unknown_api_routes_are_the_apis_404_not_the_sites(site):
    for method in ("get", "post"):
        r = getattr(site, method)("/api/nope")
        assert r.status_code == 404 and r.json() == {"error": "no such route"}, method


def test_live_mode_needs_the_passcode(site):
    assert site.get("/api/live/status").status_code == 401
    assert site.get("/api/live/status", headers={"x-ninety-passcode": "wrong"}).status_code == 401
    assert site.get("/api/live/status", headers={"x-ninety-passcode": "p" * 24}).json() == {"live": "ok"}


def test_a_websocket_behind_the_gate_needs_the_key_too():
    # The gate checks WebSocket handshakes as it checks HTTP, so a Live route that upgrades never
    # opens without the passcode, and never at all when none is configured.
    async def echo(websocket):
        await websocket.accept()
        await websocket.send_text("open")
        await websocket.close()

    from starlette.applications import Starlette
    from starlette.routing import WebSocketRoute
    from starlette.websockets import WebSocketDisconnect

    inner = Starlette(routes=[WebSocketRoute("/ws", echo)])
    for configured, sent in (("p" * 24, None), ("p" * 24, "wrong"), ("", "")):
        gated = TestClient(api.RequireKey(inner, configured, api.PASSCODE_HEADER))
        headers = {} if sent is None else {"x-ninety-passcode": sent}
        with pytest.raises(WebSocketDisconnect):
            with gated.websocket_connect("/ws", headers=headers) as ws:
                ws.receive_text()
    gated = TestClient(api.RequireKey(inner, "p" * 24, api.PASSCODE_HEADER))
    with gated.websocket_connect("/ws", headers={"x-ninety-passcode": "p" * 24}) as ws:
        assert ws.receive_text() == "open"


def test_live_mode_without_a_configured_passcode_refuses_everyone(tmp_path):
    # Fail closed: a missing Key Vault reference must not open Live mode.
    client = TestClient(api.build("k" * 64, passcode="", viewer=tmp_path / "none", replay=tmp_path / "none"))
    assert client.get("/api/live/status").status_code == 503
    assert client.get("/api/live/status", headers={"x-ninety-passcode": ""}).status_code == 503


def test_without_a_viewer_or_bundle_the_api_still_answers(tmp_path):
    none = tmp_path / "none"
    client = TestClient(api.build("k" * 64, passcode="p" * 24, viewer=none, replay=none, phone=none))
    assert client.get("/api/health").status_code == 200
    assert client.get("/").status_code == 404
    assert client.get("/bundle/manifest.json").status_code == 404
    assert client.get("/phone/").status_code == 404


def test_only_the_phones_pages_may_apply_inline_styles_and_scripts_stay_self_everywhere(site):
    """The phone's Ionic components write <style> elements at run time (web/phone/src/ionic.ts), so
    its pages allow inline styles; nothing else does, and no page allows an inline script."""
    for path in ("/phone/", "/phone", "/phone/assets/index-def.js"):
        csp = site.get(path).headers["content-security-policy"]
        assert "style-src 'self' 'unsafe-inline'" in csp, path
        assert "frame-ancestors 'self'" in csp and "connect-src 'self'" in csp, path
    for path in ("/", "/bundle/manifest.json", "/api/health", "/phoney", "/assets/index-abc.js"):
        assert "style-src" not in site.get(path).headers["content-security-policy"], path
    for path in ("/", "/phone/"):
        # default-src 'self' rules scripts
        assert "script-src" not in site.get(path).headers["content-security-policy"]
