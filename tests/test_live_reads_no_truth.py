"""M1 guard: nothing on the live path reads the ground truth (AGENTS.md, "Ground truth is the
answer key").

The live path (detected events -> stats -> agents -> cues, and the MCP server the Analyst reads
the clip through) is run in a fresh interpreter with an audit hook on every file it opens. It
fails if that run opens a clip's events.jsonl or frames.jsonl or anything under a truth folder,
or loads any of our code that writes the answer key (the simulator, the renderer), reads it (the
scoring, the validator) or fetches it from the truth containers (the vision dataset tools).

The Azure storage client itself is not banned: the Foundry SDK imports it. That the API's identity
cannot reach the truth containers is checked on the template (infra/check_truth_sealed.py); this
checks that no code of ours on the live path tries. A static check could be fooled by a computed
path; this watches what the code actually does.
"""

import json
import subprocess
import sys
import textwrap
from pathlib import Path

from ninety.match import tracking

ROOT = Path(__file__).resolve().parents[1]
TRUTH_FILES = {"events.jsonl", "frames.jsonl"}
TRUTH_DIRS = {"truth", "truth-test"}
# Our modules that write, read or fetch the answer key: none may load on the live path.
FORBIDDEN = (
    "ninety.sim", "ninety.render", "ninety.eval", "ninety.validate",
    "ninety.vision.fetch_clips", "ninety.vision.coco_export", "ninety.vision.data_stats",
    "ninety.vision.train",
)

LIVE_PATH = """
import asyncio, json
import httpx
from ninety.agents import live
from ninety.personalizer import translate
from ninety.personalizer.client import RemotePersonalizer
from ninety.personalizer.core import verified_text
from ninety.personalizer.server import create_app
from ninety.agents.factcheck import Claim, Verdict
from ninety.match import detected
from ninety.mcp import match_server

events = detected.load(detected.FIXTURES / "detected-standin-seed900001.jsonl")
sure = next(e for e in events if e["type"] == "pass" and e.get("receiver") and e["confidence"] >= 0.8)

async def ask(prompt):
    return json.dumps({"text": f"{sure['player']} finds {sure['receiver']}.", "evidence": [sure["id"]]})

async def judge(claim, evidence):
    return Verdict(ok=True)

# The Personalizer runs as it does live: over A2A to its own server (here in process), Spanish
# through the translator path.
spanish = translate.translated(verified_text, translate.mock)
app = create_app(spanish, "http://personalizer/")
http = httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://personalizer/")
personalize = RemotePersonalizer("http://personalizer/", http=http, fallback=spanish)
result = asyncio.run(live.run(events, ask=ask, judge=judge, minute=int(sure["t"] // 60) + 1,
                              personalize=personalize))
assert result.outcome.accepted and result.cues
assert personalize.last_route == "remote"
assert {c["lang"] for c in result.cues if c["kind"] == "insight"} == {"en", "es"}
assert match_server.list_events(detected.M1_CLIP, 1, 99, None)
match_server.match_info(detected.M1_CLIP)

# The phone companion as deployed (NINETY_COMPANION unset is `on`): the M1 clip from tracked
# positions only, and every stand-in, whose positions are the simulator's, refused before any is read.
from starlette.applications import Starlette
from starlette.testclient import TestClient
from ninety.api import companion as companion_api

phone = TestClient(Starlette(routes=companion_api.from_env({}).routes()))
for clip in match_server.MATCHES:
    assert phone.post("/api/pair", json={"clip": clip}).status_code == 503
    assert phone.get(f"/api/minimap/{clip}").status_code == 503
    assert phone.get(f"/api/card/{clip}/h7?t_to=10").status_code == 503
    assert phone.get(f"/api/flow/{clip}/home?t_to=10").status_code == 503
m1 = phone.post("/api/pair", json={"clip": detected.M1_CLIP})
assert m1.status_code in (201, 503), m1.text  # 503 until its tracked frames file is committed
if m1.status_code == 201:
    assert phone.get(f"/api/minimap/{detected.M1_CLIP}").json()["source"] == "tracked"
"""


def run_live_path(extra: str = "") -> dict:
    """Runs the live path in a fresh interpreter; returns what it opened and which modules loaded."""
    script = textwrap.dedent("""
        import os, sys, json
        opened = []
        def hook(event, args):
            if event == "open" and args and isinstance(args[0], (str, bytes, os.PathLike)):
                opened.append(os.fsdecode(args[0]))
        sys.addaudithook(hook)
    """) + LIVE_PATH + extra + textwrap.dedent("""
        print("RESULT " + json.dumps({"opened": opened, "modules": sorted(sys.modules)}))
    """)
    done = subprocess.run(
        [sys.executable, "-c", script], cwd=ROOT, capture_output=True, text=True, timeout=300
    )
    assert done.returncode == 0, done.stderr[-3000:]
    line = next(x for x in done.stdout.splitlines() if x.startswith("RESULT "))
    return json.loads(line.removeprefix("RESULT "))


def truth_reads(run: dict) -> list[str]:
    reads = [
        p for p in run["opened"]
        if Path(p).name in TRUTH_FILES or TRUTH_DIRS & set(Path(p).parts) or _precomputed_frames(p)
    ]
    loaded = [m for m in run["modules"] if any(m == f or m.startswith(f + ".") for f in FORBIDDEN)]
    return reads + loaded


def _precomputed_frames(path: str) -> bool:
    """A served stand-in's simulator frames, as the image precomputes them: <match dir>/frames/<clip>.json."""
    p = Path(path)
    return p.suffix == ".json" and p.parent.name == tracking.FRAMES_DIR


def test_the_live_path_reads_no_ground_truth():
    assert truth_reads(run_live_path()) == []


def test_the_guard_catches_a_truth_read(tmp_path):
    """The guard must be able to fail: a live path that opens a clip's events.jsonl, or imports
    the simulator, is caught (docs/LESSONS.md: a check that cannot fail checks nothing)."""
    clip = tmp_path / "seed900001"
    clip.mkdir()
    (clip / "events.jsonl").write_text("")
    frames = tmp_path / "matches" / "frames"
    frames.mkdir(parents=True)
    (frames / "seed7.json").write_text("{}")
    planted = (f"\nopen({str(clip / 'events.jsonl')!r}).read()\nimport ninety.sim.engine\n"
               f"open({str(frames / 'seed7.json')!r}).read()\n")
    found = truth_reads(run_live_path(planted))
    assert any(p.endswith("events.jsonl") for p in found)
    assert "ninety.sim.engine" in found
    assert any(p.endswith("frames/seed7.json") for p in found)  # the companion's stand-in frames
