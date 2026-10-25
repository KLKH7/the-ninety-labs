"""The live path of event detection never reads ground truth (AGENTS.md, hard rule; lesson 17).

Two checks. Statically: the live modules import nothing from the engine, the renderer or the
evaluation, and no string in their code (docstrings aside) names a truth or settings file.
At run time, under an audit hook in a fresh interpreter (as tests/test_live_reads_no_truth.py):
tracks and events on the committed observations, and the image stage on a synthetic clip whose
frames.jsonl, events.jsonl, clip.json and meta.json are traps. Each run must show it did the work,
so it cannot pass on nothing. The image stage needs numpy and pillow, which the dev group installs,
so it runs in CI and never skips.
"""

from __future__ import annotations

import ast
import json
import subprocess
import sys
import textwrap
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
LIVE = ["ninety/vision/flight.py",
        "ninety/vision/pitch.py", "ninety/vision/observe.py", "ninety/vision/track.py",
        "ninety/vision/events.py", "ninety/vision/tracked_frames.py", "ninety/vision/live_job.py",
        "ninety/vision/tiles.py", "ninety/vision/fuse.py", "ninety/vision/join.py",
        "ninety/vision/sides.py"]
TRUTH_FILES = ("frames.jsonl", "events.jsonl", "clip.json", "meta.json")
FORBIDDEN_IMPORTS = ("ninety.sim", "ninety.render", "ninety.eval")


def _code_strings(tree: ast.AST) -> list[str]:
    docs = set()
    for node in ast.walk(tree):
        if isinstance(node, (ast.Module, ast.FunctionDef, ast.ClassDef, ast.AsyncFunctionDef)):
            body = getattr(node, "body", [])
            if body and isinstance(body[0], ast.Expr) and isinstance(body[0].value, ast.Constant):
                docs.add(id(body[0].value))
    return [n.value for n in ast.walk(tree)
            if isinstance(n, ast.Constant) and isinstance(n.value, str) and id(n) not in docs]


@pytest.mark.parametrize("path", LIVE)
def test_a_live_module_imports_no_engine_renderer_or_evaluation(path):
    tree = ast.parse((ROOT / path).read_text())
    names = [a.name for n in ast.walk(tree) if isinstance(n, ast.Import) for a in n.names]
    names += [n.module or "" for n in ast.walk(tree) if isinstance(n, ast.ImportFrom)]
    assert not [m for m in names if m.startswith(FORBIDDEN_IMPORTS)], names


@pytest.mark.parametrize("path", LIVE)
def test_a_live_module_names_no_truth_file_in_its_code(path):
    strings = _code_strings(ast.parse((ROOT / path).read_text()))
    assert not [s for s in strings if any(f in s for f in TRUTH_FILES) or "truth" in s.lower()]


def test_the_static_check_catches_a_module_that_opens_frames_jsonl():
    planted = 'def f(clip):\n    """Reads nothing."""\n    return open(clip / "frames.jsonl")\n'
    assert any("frames.jsonl" in s for s in _code_strings(ast.parse(planted)))


# The runtime check, as tests/test_live_reads_no_truth.py does it for the agents: each stage runs
# in a fresh interpreter with an audit hook recording every file it opens and, at the end, every
# module it loaded. A static check can be fooled by a computed path; this watches the run.
AUDIT = textwrap.dedent("""
    import os, sys, json
    opened = []
    def hook(event, args):
        if event == "open" and args and isinstance(args[0], (str, bytes, os.PathLike)):
            opened.append(os.fsdecode(args[0]))
    sys.addaudithook(hook)
""")
TRUTH_DIRS = {"truth", "truth-test"}


def run_audited(body: str) -> dict:
    script = AUDIT + textwrap.dedent(body) + textwrap.dedent("""
        print("RESULT " + json.dumps({"opened": opened, "modules": sorted(sys.modules), "out": OUT}))
    """)
    done = subprocess.run([sys.executable, "-c", script], cwd=ROOT, capture_output=True, text=True,
                          timeout=600)
    assert done.returncode == 0, done.stderr[-3000:]
    line = next(x for x in done.stdout.splitlines() if x.startswith("RESULT "))
    return json.loads(line.removeprefix("RESULT "))


def truth_reads(run: dict) -> list[str]:
    reads = [o for o in run["opened"] if Path(o).name in TRUTH_FILES or TRUTH_DIRS & set(Path(o).parts)]
    loaded = [m for m in run["modules"] if m.startswith(FORBIDDEN_IMPORTS)]
    return reads + loaded


EVENT_STAGE = """
    from ninety.vision import events, track
    rows = track.read_observations("tests/fixtures/observations-seed900001.jsonl")
    found, _ = events.detect(rows)
    OUT = {"events": len(found), "types": sorted({e["type"] for e in found}),
           "named": sum(1 for e in found for k in ("player", "receiver", "interceptor") if e.get(k))}
"""


def test_tracks_and_events_from_the_committed_observations_open_no_truth():
    run = run_audited(EVENT_STAGE)
    assert run["out"]["events"] > 0  # it did the work, so the guard is not passing on nothing
    assert run["out"]["named"] > 0  # and named players (h-t12) from the tracks alone
    assert any(o.endswith("observations-seed900001.jsonl") for o in run["opened"])
    assert truth_reads(run) == []


def test_the_runtime_guard_catches_a_planted_truth_read(tmp_path):
    trap = tmp_path / "frames.jsonl"
    trap.write_text("{}\n")
    run = run_audited(textwrap.dedent(EVENT_STAGE) + f"open({str(trap)!r}).read()\n")
    assert truth_reads(run) == [str(trap)]


def synthetic_clip(clip: Path) -> Path:
    """Two frames of grass with Law 1's markings as a known camera sees them, a detections file
    that found nothing, and the answer key's and the settings' file names as traps. Built here,
    outside the audited run, so writing the traps is not counted as opening them."""
    # Imported, not skipped: numpy and pillow are in the dev group so CI runs this guard; without
    # them it fails rather than passing quietly.
    import numpy as np
    from PIL import Image

    from ninety.vision import pitch

    (clip / "images").mkdir(parents=True)
    for name in TRUTH_FILES:
        (clip / name).write_text("{}\n")
    v = pitch.View(58.0, -37.0, 16.0, 0.29, 0.14, 3600.0, 640, 360)
    img = np.zeros((360, 640, 3), dtype=np.uint8)
    img[...] = (60, 120, 10)
    pts = []
    for pl in pitch.pitch_polylines():
        for (x0, y0), (x1, y1) in zip(pl[:-1], pl[1:], strict=True):
            n = max(1, int(np.hypot(x1 - x0, y1 - y0) / 0.05))
            pts += [(x0 + (x1 - x0) * k / n, y0 + (y1 - y0) * k / n, 0.0) for k in range(n)]
    uv, depth = v.project(np.array(pts))
    for (u, w), d in zip(uv, depth, strict=True):
        if d > 0 and 0 <= u < 640 and 0 <= w < 360:
            img[int(w), int(u)] = (240, 240, 235)
    model = {"name": "rf-detr", "size": "small", "version": "x", "checkpoint": "ours-v2"}
    rows = []
    for k in range(2):
        Image.fromarray(img).save(clip / "images" / f"{k:05d}.jpg", quality=95)
        rows.append({"clip": "c", "frame": k, "t": k / 25, "detections": [], "model": model})
    dets = clip.parent / "detections.jsonl"
    dets.write_text("".join(json.dumps(r) + "\n" for r in rows))
    return dets


def test_the_image_stage_opens_no_truth_file(tmp_path):
    clip = tmp_path / "clip"
    dets = synthetic_clip(clip)
    out = tmp_path / "obs.jsonl"
    run = run_audited(f"""
        from ninety.vision import events, observe, pitch, track
        pitch.find_gantry = lambda anchors, w, h: (58.0, -37.0, 16.0)  # the search is tested elsewhere
        observe.main([{str(clip)!r}, "--detections", {str(dets)!r}, "--out", {str(out)!r}])
        obs = track.read_observations({str(out)!r})
        events.detect(obs)
        OUT = {{"rows": len(obs), "camera_ok": sum(r["camera"]["ok"] for r in obs)}}
    """)
    assert run["out"]["rows"] == 2 and run["out"]["camera_ok"] == 2  # it ran the whole stage
    assert any(o.endswith(".jpg") for o in run["opened"])
    assert truth_reads(run) == []
