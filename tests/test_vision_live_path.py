"""The live path of event detection never reads ground truth (AGENTS.md, hard rule; lesson 17).

Two checks. Statically: the live modules import nothing from the engine, the renderer or the
evaluation, and no string in their code (docstrings aside) names a truth or settings file.
At run time: the image stage runs on a clip whose frames.jsonl, events.jsonl, clip.json and
meta.json are traps that fail the test when opened (needs an image library, so it runs where the
vision group is installed).
"""

from __future__ import annotations

import ast
import builtins
import io
import json
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
LIVE = ["ninety/vision/pitch.py", "ninety/vision/observe.py", "ninety/vision/track.py",
        "ninety/vision/events.py"]
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


def test_the_image_stage_opens_no_truth_file(tmp_path, monkeypatch):
    np = pytest.importorskip("numpy")
    Image = pytest.importorskip("PIL.Image")
    from ninety.vision import observe, pitch

    clip = tmp_path / "clip"
    (clip / "images").mkdir(parents=True)
    for name in TRUTH_FILES:
        (clip / name).write_text("{}\n")
    v = pitch.View(58.0, -37.0, 16.0, 0.29, 0.14, 3600.0, 320, 180)
    img = np.zeros((180, 320, 3), dtype=np.uint8)
    img[...] = (60, 120, 10)
    uv = []
    for pl in pitch.pitch_polylines():
        for (x0, y0), (x1, y1) in zip(pl[:-1], pl[1:], strict=True):
            for k in range(40):
                uv.append((x0 + (x1 - x0) * k / 40, y0 + (y1 - y0) * k / 40, 0.0))
    px, depth = v.project(np.array(uv))
    for (u, w), d in zip(px, depth, strict=True):
        if d > 0 and 0 <= u < 320 and 0 <= w < 180:
            img[int(w), int(u)] = (240, 240, 235)
    rows = []
    for k in range(2):
        Image.fromarray(img).save(clip / "images" / f"{k:05d}.jpg", quality=95)
        rows.append({"clip": "c", "frame": k, "t": k / 25, "detections": [],
                     "model": {"name": "rf-detr", "size": "small", "version": "x", "checkpoint": "ours-v2"}})
    dets = tmp_path / "detections.jsonl"
    dets.write_text("".join(json.dumps(r) + "\n" for r in rows))

    opened: list[str] = []
    real_open = builtins.open

    def guarded(file, *a, **kw):
        opened.append(str(file))
        if Path(str(file)).name in TRUTH_FILES:
            raise AssertionError(f"the live path opened {file}")
        return real_open(file, *a, **kw)

    monkeypatch.setattr(builtins, "open", guarded)
    monkeypatch.setattr(io, "open", guarded)
    monkeypatch.setattr(pitch, "find_gantry", lambda anchors, w, h: (58.0, -37.0, 16.0))
    try:
        observe.main([str(clip), "--detections", str(dets), "--out", str(tmp_path / "obs.jsonl")])
    except ValueError:
        pass  # a tiny synthetic frame may not fit; what matters is which files were opened
    assert any(o.endswith(".jpg") for o in opened)  # the images were read, through the guard
    assert not [o for o in opened if Path(o).name in TRUTH_FILES]
