"""The final-render QA step (infra/pod/qa.py): which clips a human looks at is fixed, not chosen."""

import importlib.util
import json
from pathlib import Path

from PIL import Image

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("pod_qa", ROOT / "infra/pod/qa.py")
qa = importlib.util.module_from_spec(spec)
spec.loader.exec_module(qa)
PLAN = json.loads((ROOT / "docs/eval/dataset-v2-freeze.json").read_text())


def _report(ok=True):
    return {"passed": {"player_feet_in_boxes": ok, "data_contract": True},
            "projection": {"ball_px": {"max": 0.2}, "keypoint_px": {"max": 0.001},
                           "player_foot_outside_box": 0 if ok else 2, "player_foot_checked": 100},
            "labels": {"ok": True}, "data_contract": {}}


def _found(flag=(), test_flag=()):
    found = {("train", s): _report(s not in flag) for s, _ in qa.pod.expand(PLAN, "train")}
    found |= {("test", s): _report(s not in test_flag) for s, _ in qa.pod.expand(PLAN, "test")}
    return found


def test_the_sample_is_fixed_by_the_seed_and_flagged_clips_are_always_shown():
    sample, flagged = qa.chosen(PLAN, _found(flag=(7, 4001)))
    assert len(sample) == 20 and not {7, 4001} & set(sample)
    assert flagged == [7, 4001]
    assert qa.chosen(PLAN, _found(flag=(7, 4001)))[0] == sample  # the same every time


def test_test_clips_are_never_shown(tmp_path):
    found = _found(test_flag=(900003,))
    sample, flagged = qa.chosen(PLAN, found)
    assert all(s < 900000 for s in sample + flagged)
    for (split, seed), r in found.items():
        rp = qa.pod.report_path(tmp_path, split, seed)
        rp.parent.mkdir(parents=True, exist_ok=True)
        rp.write_text(json.dumps(r))
    for seed in sample:
        d = qa.pod.clip_dir(tmp_path, PLAN["run"], seed, "train") / "images"
        d.mkdir(parents=True)
        for i in range(10):
            Image.new("RGB", (64, 36), "green").save(d / f"{i:05d}.jpg")
    qa.main(["--plan", str(ROOT / "docs/eval/dataset-v2-freeze.json"), "--out", str(tmp_path)])
    sheets = sorted(p.name for p in (tmp_path / "qa" / "sheets").iterdir())
    assert len(sheets) == 20 and all(n.startswith("train-") for n in sheets)
    summary = json.loads((tmp_path / "qa" / "summary.json").read_text())
    assert summary["excluded"] == [{"split": "test", "seed": 900003, "failed": ["player_feet_in_boxes"]}]
    assert summary["render_check"]["test"]["player_feet_outside_box"] == 2
    assert summary["manifest_verified"] is False  # no manifest was written
