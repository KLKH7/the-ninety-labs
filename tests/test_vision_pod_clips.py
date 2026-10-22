"""The training clips of a pod render, read against its manifest (ninety/vision/pod_clips.py), and the
look-freeze fine-tune's config (ninety/vision/finetune-v2freeze.json)."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from ninety.vision import pod_clips

VISION = Path(pod_clips.__file__).parent
COMMIT = "a" * 40


def render(tmp_path, seeds=(3, 4, 108), failed=(), missing=(), test=(900001,)):
    """A finished render's --out as infra/pod/render.py leaves it: clips, reports and the manifest."""
    out = tmp_path / "out"
    clips = []
    for split, group in (("train", seeds), ("test", test)):
        for s in group:
            d = out / "v2freeze" / split / f"seed{s}"
            (d / "images").mkdir(parents=True)
            (d / "images" / "00000.jpg").write_bytes(f"jpg{s}".encode())
            (d / "frames.jsonl").write_text(json.dumps({"seed": s}) + "\n")
            files = {f.relative_to(d).as_posix(): {"sha256": pod_clips.sha256(f), "bytes": f.stat().st_size}
                     for f in sorted(d.rglob("*")) if f.is_file()}
            clips.append({"split": split, "seed": s, "files": files})
    m = {"run": "v2freeze", "render_commit": COMMIT, "clips_list": clips,
         "failed": [{"split": "train", "seed": s, "failed": ["feet_in_box"]} for s in failed],
         "missing": [{"split": "train", "seed": s} for s in missing]}
    (out / "manifest.json").write_text(json.dumps(m))
    return out


CFG = {"notes": {}, "val_seeds": [108, 109], "stride": 5}


def test_lists_only_passing_training_clips_and_removes_a_failed_validation_seed(tmp_path):
    out = render(tmp_path, failed=(109,))
    work = tmp_path / "work"
    cfg_path = tmp_path / "cfg.json"
    cfg_path.write_text(json.dumps(CFG))
    listing = pod_clips.prepare(out, "v2freeze", COMMIT, CFG, cfg_path, work)
    listed = work.joinpath("clips.txt").read_text().split()
    assert sorted(listed) == sorted(str(out / "v2freeze" / "train" / f"seed{s}") for s in (3, 4, 108))
    cfg = json.loads(work.joinpath("config.json").read_text())
    assert cfg["val_seeds"] == [108] and "109" in cfg["notes"]["val_seeds_removed"]
    assert listing["train_seeds"] == [3, 4] and listing["val_seeds"] == [108]
    assert listing["val_seeds_removed"] == [109] and listing["excluded_by_checks"][0]["seed"] == 109
    assert listing["render_manifest_sha256"] == pod_clips.sha256(out / "manifest.json")
    assert CFG["val_seeds"] == [108, 109]  # the committed config is not changed


def test_refuses_an_unfinished_render_another_run_or_another_commit(tmp_path):
    out = render(tmp_path, missing=(5,))
    with pytest.raises(ValueError, match="not finished"):
        pod_clips.read_manifest(out, "v2freeze", COMMIT)
    out = render(tmp_path / "b")
    with pytest.raises(ValueError, match="not the pre-registered"):
        pod_clips.read_manifest(out, "v2freeze", "b" * 40)
    with pytest.raises(ValueError, match="not 'v2'"):
        pod_clips.read_manifest(out, "v2", COMMIT)


def test_refuses_a_file_that_changed_after_the_manifest(tmp_path):
    out = render(tmp_path)
    (out / "v2freeze" / "train" / "seed4" / "images" / "00000.jpg").write_bytes(b"jpg5")
    with pytest.raises(ValueError, match="differ from the manifest"):
        pod_clips.prepare(out, "v2freeze", COMMIT, CFG, tmp_path / "cfg.json", tmp_path / "work")
    assert not (tmp_path / "work").exists()


def test_refuses_when_no_validation_seed_passed(tmp_path):
    with pytest.raises(ValueError, match="no validation seed"):
        pod_clips.run_config(CFG, {3, 4})


def test_the_freeze_config_differs_from_round_2_only_in_its_validation_seeds_and_time_cap():
    freeze = json.loads((VISION / "finetune-v2freeze.json").read_text())
    round2 = json.loads((VISION / "finetune-round2.json").read_text())
    v1 = json.loads((VISION / "finetune.json").read_text())
    assert freeze["train"] == round2["train"]
    assert {k for k in freeze if freeze.get(k) != round2.get(k)} == {"notes", "val_seeds", "time_cap_minutes"}
    assert freeze["val_seeds"] == v1["val_seeds"]  # dataset v1's validation seeds, re-rendered
    assert freeze["time_cap_minutes"] == 110


def test_a_seed_with_no_report_is_accepted_only_when_named_as_crashed(tmp_path):
    out = render(tmp_path, missing=(5,))
    m = pod_clips.read_manifest(out, "v2freeze", COMMIT, crashed=frozenset({5}))
    assert m["run"] == "v2freeze"
    with pytest.raises(ValueError, match=r"\[6\] were named as crashed"):
        pod_clips.read_manifest(out, "v2freeze", COMMIT, crashed=frozenset({5, 6}))
    out = render(tmp_path / "b", missing=(5, 7))
    with pytest.raises(ValueError, match=r"\[7\] have no report"):
        pod_clips.read_manifest(out, "v2freeze", COMMIT, crashed=frozenset({5}))
