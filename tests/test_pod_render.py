"""The pre-registered look-freeze dataset (docs/eval/dataset-v2-freeze.json) and its pod driver."""

import importlib.util
import json
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
PLAN = json.loads((ROOT / "docs/eval/dataset-v2-freeze.json").read_text())
spec = importlib.util.spec_from_file_location("pod_render", ROOT / "infra/pod/render.py")
pod = importlib.util.module_from_spec(spec)
spec.loader.exec_module(pod)


def test_the_plan_is_v3_s_seeds_and_overrides_all_training_seeds():
    jobs = pod.expand(PLAN)
    assert len(jobs) == 280 == len({s for s, _ in jobs})
    v1 = json.loads((ROOT / "docs/eval/dataset-v1.json").read_text())
    runs = ("v3", "v3boards", "v3boards-set")
    v3 = {c["seed"]: c["overrides"] for c in v1["clips_list"] if c["run"] in runs}
    # v1 dropped 82 and 111 for its own defects; every other v3 seed is here with its overrides.
    assert {s: o for s, o in jobs if s not in (82, 111)} == v3
    assert all(s < 900000 for s, _ in jobs)


def test_a_plan_with_a_test_seed_or_a_wrong_count_is_refused():
    bad = json.loads(json.dumps(PLAN))
    bad["seeds"]["groups"].append({"first": 900001, "last": 900001, "overrides": {}})
    bad["seeds"]["clips"] = 281
    with pytest.raises(ValueError):
        pod.expand(bad)
    short = json.loads(json.dumps(PLAN))
    short["seeds"]["clips"] = 279
    with pytest.raises(ValueError):
        pod.expand(short)


def test_training_clips_show_every_frame():
    assert PLAN["render"]["dead_ball_cut"] is False
    assert PLAN["render"]["seconds"] == 10
