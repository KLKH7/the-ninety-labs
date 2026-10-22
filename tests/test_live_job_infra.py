"""The live detection job's infrastructure (infra/live-job.*) and its staging (ninety/vision/stage_live.py).

The Bicep and the image cannot be built in this test run (no Bicep compiler or Docker here); CI's
infra job compiles main.bicep only. So these read the files: the job's identity holds no storage
role, the image installs no CUDA or NVIDIA package that uv.lock would bring, its CPU torch is the
locked version, and the build context admits no answer-key file.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

import pytest

from ninety.vision import live_job, stage_live
from tests.test_vision_live_path import TRUTH_FILES

ROOT = Path(__file__).resolve().parents[1]
BICEP = (ROOT / "infra" / "live-job.bicep").read_text()
DOCKERFILE = (ROOT / "infra" / "live-job.Dockerfile").read_text()
IGNORE = (ROOT / "infra" / "live-job.Dockerfile.dockerignore").read_text()
LOCK = (ROOT / "uv.lock").read_text()


def _code(text: str) -> str:
    return "\n".join(line.split("//")[0] for line in text.splitlines())


def test_the_job_s_only_role_is_pulling_its_image():
    code = _code(BICEP)
    assignments = re.findall(r"Microsoft\.Authorization/roleAssignments@[^']+' = \{(.*?)\n\}", code, re.S)
    assert len(assignments) == 1
    assert "scope: registry" in assignments[0] and "acrPull" in assignments[0]
    assert "Microsoft.Storage" not in code  # no storage account, container or role: the truth is out of reach


def test_the_job_template_holds_no_secret_or_key():
    code = _code(BICEP).lower()
    assert not [w for w in ("listkeys", "secret", "password", "connectionstring", "accountkey") if w in code]


def _locked(name: str) -> str:
    return re.search(rf'^name = "{re.escape(name)}"\nversion = "([^"]+)"', LOCK, re.M).group(1)


def test_the_image_s_cpu_torch_is_the_locked_version():
    assert f"torch-{_locked('torch')}%2Bcpu-" in DOCKERFILE
    assert f"torchvision-{_locked('torchvision')}%2Bcpu-" in DOCKERFILE
    assert len(re.findall(r"--hash=sha256:[0-9a-f]{64}", DOCKERFILE)) == 2


def test_every_cuda_package_the_lock_holds_is_left_out_of_the_image():
    """A lock update that brings a new NVIDIA or CUDA package must fail here, not ship it."""
    cuda = set(re.findall(r'^name = "((?:nvidia|cuda)-[a-z0-9-]+|triton)"$', LOCK, re.M))
    assert cuda  # the lock does hold them, so the check is not empty
    left_out = set(re.findall(r"--no-emit-package ([a-z0-9-]+)", DOCKERFILE))
    assert cuda <= left_out, sorted(cuda - left_out)


def test_the_image_build_runs_the_job_s_own_checks_on_its_inputs():
    assert "j.check_input(Path('/data/clip'))" in DOCKERFILE
    assert "j.verify_checkpoint(" in DOCKERFILE
    assert "--echo" in DOCKERFILE and "USER app" in DOCKERFILE


def test_the_build_context_admits_no_answer_key_file():
    rules = [line for line in IGNORE.splitlines() if line and not line.startswith("#")]
    allowed = [rule[1:] for rule in rules if rule.startswith("!")]
    assert rules[0] == "*"  # everything is left out unless named
    assert not [p for p in allowed for f in TRUTH_FILES if f in p]
    assert not [p for p in allowed if p.startswith(("runs/", "docs", "tests")) and "live-input" not in p]


def rendered_clip(tmp_path: Path, frames: int = 10) -> Path:
    """A rendered clip as the renderer lays it out: images, clip.json and frames.jsonl, at 2 fps."""
    clip = tmp_path / "seed8001"
    (clip / "images").mkdir(parents=True)
    (clip / "clip.json").write_text(json.dumps({"clip_id": "seed8001"}))
    rows = []
    for k in range(frames):
        (clip / "images" / f"{k:05d}.jpg").write_bytes(b"jpg %d" % k)
        rows.append({"frame": k, "t": k / 2, "image": f"images/{k:05d}.jpg", "players": ["answer key"]})
    (clip / "frames.jsonl").write_text("".join(json.dumps(r) + "\n" for r in rows))
    (clip / "events.jsonl").write_text("{}\n")
    return clip


def test_staging_keeps_the_window_with_its_frame_numbers_and_no_labels(tmp_path):
    out = tmp_path / "live-input" / "clip"
    assert stage_live.stage_clip(rendered_clip(tmp_path), 1.0, 2.5, out) == 4
    rows = [json.loads(line) for line in (out / "index.jsonl").read_text().splitlines()]
    assert [r["frame"] for r in rows] == [2, 3, 4, 5] and rows[0]["t"] == 1.0
    assert all(set(r) == {"clip", "frame", "t", "image"} and r["clip"] == "seed8001" for r in rows)
    assert sorted(p.name for p in out.iterdir()) == ["images", "index.jsonl"]
    assert live_job.check_input(out)  # the job takes what staging writes


def test_staging_refuses_an_empty_or_backwards_window(tmp_path):
    clip = rendered_clip(tmp_path)
    with pytest.raises(SystemExit, match="no frame"):
        stage_live.stage_clip(clip, 100.0, 160.0, tmp_path / "a")
    with pytest.raises(SystemExit, match="after"):
        stage_live.stage_clip(clip, 3.0, 1.0, tmp_path / "b")


def test_staging_a_checkpoint_needs_its_record(tmp_path):
    src = tmp_path / "ours-v4"
    src.mkdir()
    (src / "checkpoint_best_total.pth").write_bytes(b"w")
    with pytest.raises(SystemExit, match="train-manifest.json"):
        stage_live.stage_checkpoint(src, tmp_path / "out")


def test_echo_puts_the_run_and_each_detected_event_in_the_log(tmp_path, monkeypatch, capsys):
    from ninety.vision import pitch
    from tests.test_vision_live_job import FakeModel, checkpoint, clean_clip

    clip, _ = clean_clip(tmp_path)
    weights = checkpoint(tmp_path)
    monkeypatch.setattr(live_job, "load", lambda w, **kw: FakeModel())
    monkeypatch.setattr(pitch, "find_gantry", lambda anchors, w, h: (58.0, -37.0, 16.0))
    out = tmp_path / "out"
    live_job.main([str(clip), "--checkpoint", "ours-v4", "--weights", str(weights), "--out", str(out),
                   "--echo"])
    lines = [json.loads(line) for line in capsys.readouterr().out.splitlines()]
    runs = [x["run"] for x in lines if "run" in x]
    assert len(runs) == 1 and runs[0]["weights_sha256"] == live_job.sha256(weights)
    assert sum("detected" in x for x in lines) == len((out / "detected.jsonl").read_text().splitlines())
