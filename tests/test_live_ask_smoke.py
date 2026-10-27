"""The deployed Live Ask reaches Foundry: a match question asked with the demo passcode is answered by
the published agents (source "model"), not by code's fallback.

The deployed API once answered every Live question from code without saying so, because its identity
had no Foundry role (docs/LESSONS.md, lesson on provisioned infra drifting behind main.bicep): the
viewer saw a good answer either way, so only this test tells the two apart.

Skipped without NINETY_LIVE_URL and NINETY_DEMO_PASSCODE. The passcode is a secret: the live-smoke
workflow passes it from the repo secret when one is set; by hand, read it from Key Vault into the
environment without printing it (infra/README.md). One question costs about $0.0015 in tokens.
"""

import asyncio
import json
import os
import urllib.error
import urllib.request

import pytest

from ninety.api.companion import PASSCODE_HEADER

URL = os.environ.get("NINETY_LIVE_URL", "").rstrip("/")
PASSCODE = os.environ.get("NINETY_DEMO_PASSCODE", "")
CLIP = os.environ.get("NINETY_LIVE_CLIP", "seed900001")  # the served clip with tracked positions
AT_S = 120.0  # design: two minutes in, enough of the match for a possession question to have an answer
pytestmark = pytest.mark.skipif(not (URL and PASSCODE), reason="no live URL or passcode")


def post(path: str, body: dict, headers: dict | None = None) -> tuple[int, dict]:
    sent = {"content-type": "application/json"} | (headers or {})
    req = urllib.request.Request(URL + path, method="POST", data=json.dumps(body).encode(), headers=sent)
    try:
        with urllib.request.urlopen(req, timeout=100) as r:  # the first call may wake a cold replica
            return r.status, json.loads(r.read())
    except urllib.error.HTTPError as e:
        return e.code, json.loads(e.read() or b"{}")


async def ask_with_the_screen_at(code: str, t: float, text: str) -> tuple[int, dict]:
    """Ask as a phone would, with a laptop on the pairing showing match time t (paused), so the
    question is answered at t, not clamped to a playhead of 0."""
    import websockets

    ws_url = URL.replace("https://", "wss://", 1) + f"/api/pair/{code}?role=laptop"
    async with websockets.connect(ws_url, open_timeout=100) as laptop:
        await laptop.send(json.dumps({"type": "clock", "t": t, "playing": False}))
        await asyncio.sleep(1.0)  # design: the relay stores the clock before the question arrives
        body = {"session": code, "player": None, "text": text, "t": t}
        return await asyncio.to_thread(post, "/api/ask", body, {PASSCODE_HEADER: PASSCODE})


def test_a_live_question_is_answered_by_the_foundry_agents():
    status, paired = post("/api/pair", {"clip": CLIP})
    assert status == 201, paired
    question = "Who has had more of the ball?"
    status, message = asyncio.run(ask_with_the_screen_at(paired["code"], AT_S, question))
    assert status == 200, message
    assert message["type"] == "answer" and message["answer"]["text"]
    assert message["source"] == "model", f"answered by {message['source']}: Live did not reach Foundry"
