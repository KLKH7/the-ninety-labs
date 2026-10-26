"""The phone's words and dots for a shot (web/phone/src/shots.ts): only what its outcome says.

The live path writes a detected save as a shot with no outcome (lesson 258), so a null outcome must
read as a plain shot, never as a miss: "shoots wide" for every former save would be a new false
claim. Built with the phone's own esbuild and run under node, as tests/test_speech.py builds voice.ts.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
from pathlib import Path

import pytest

PHONE = Path(__file__).resolve().parents[1] / "web" / "phone"


def unavailable(reason: str):
    """A skip locally; a failure in CI's phone job, which installs everything (as tests/test_phone.py)."""
    if os.environ.get("NINETY_REQUIRE_PHONE") == "1":
        pytest.fail(reason)
    pytest.skip(reason)


@pytest.fixture(scope="module")
def shots(tmp_path_factory):
    esbuild = PHONE / "node_modules" / ".bin" / "esbuild"
    node = shutil.which("node")
    if not esbuild.exists() or node is None:
        unavailable("web/phone is not installed (npm ci --prefix web/phone), or node is missing")
    out = tmp_path_factory.mktemp("shots") / "shots.mjs"
    subprocess.run([str(esbuild), str(PHONE / "src" / "shots.ts"), "--format=esm", f"--outfile={out}"],
                   check=True, capture_output=True)

    def call(outcomes: list) -> list[list[str]]:
        script = (f"import {{ kind, said }} from {json.dumps(out.as_uri())};"
                  f"console.log(JSON.stringify({json.dumps(outcomes)}.map(o => [kind(o), said(o, 'Ben')])));")
        done = subprocess.run([node, "--input-type=module", "-e", script], check=True, capture_output=True,
                              text=True)
        return json.loads(done.stdout)
    return call


def test_a_shot_with_no_outcome_is_a_plain_shot_never_a_miss(shots):
    assert shots([None]) == [["plain", "Ben shoots."]]


def test_each_known_outcome_says_what_it_is(shots):
    assert shots(["goal", "on_target", "blocked", "off_target"]) == [
        ["goal", "Ben scores."], ["on", "Shot saved, from Ben."], ["off", "Ben's shot is blocked."],
        ["off", "Ben shoots wide."]]
