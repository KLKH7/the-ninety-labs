"""scripts/footage_hunt.py (the demo's editorial scorer, docs/eval/demo-match-hunt.md) on a short
simulated run: it never opens or closes a window while a pass or shot is in flight, and no picked
play window holds a flagged moment."""

import json
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture(scope="module")
def hunt(tmp_path_factory):
    run = tmp_path_factory.mktemp("run")
    out = tmp_path_factory.mktemp("out")
    sim = [sys.executable, "-m", "ninety.sim.cli", "--seed", "7", "--minutes", "6", "--out", str(run)]
    subprocess.run(sim, check=True, cwd=ROOT, capture_output=True)
    subprocess.run([sys.executable, str(ROOT / "scripts" / "footage_hunt.py"), str(run), str(out)],
                   check=True, cwd=ROOT, capture_output=True)
    ev = [json.loads(x) for x in (run / "events.jsonl").read_text().splitlines() if x.strip()]
    return ev, json.loads((out / "picks.json").read_text())


def test_picked_play_windows_hold_no_flagged_moment(hunt):
    _, picks = hunt
    for c in picks["picked"] + picks["reserve"]:
        if c["why"] in ("play", "reserve"):
            assert not c["bad"], c


def test_no_window_edge_falls_inside_a_struck_ball(hunt):
    ev, picks = hunt
    strikes = [e["t"] for e in ev if e["type"] in ("pass", "shot")]
    for c in picks["picked"] + picks["reserve"]:
        if not c["why"].startswith(("play", "reserve", "must")):
            continue
        for edge in (c["start"], c["end"]):
            # a strike within 0.2 s after an edge would be cut mid-swing; the flight itself is checked
            # by the script's in_flight(), this guards the obvious case end to end
            assert not any(0 < t - edge < 0.2 for t in strikes), (c, edge)
