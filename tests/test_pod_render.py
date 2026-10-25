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


def test_the_test_set_is_the_thirty_reserved_test_seeds_with_no_overrides():
    jobs = pod.expand(PLAN, "test")
    assert [s for s, _ in jobs] == list(range(900001, 900031))
    assert all(o == {} for _, o in jobs)


class FakeContainer:
    def __init__(self, log, name):
        self.log, self.name = log, name

    def upload_blob(self, path, data, overwrite):
        self.log.append((self.name, path))


def _clip(tmp_path, split, seed):
    d = pod.clip_dir(tmp_path, "v2freeze", seed, split)
    (d / "images").mkdir(parents=True)
    for name in ("clip.json", "meta.json", "frames.jsonl", "events.jsonl", "images/00000.jpg"):
        (d / name).write_text(name)
    return d


@pytest.mark.parametrize("split,truth,key", [
    ("train", "truth", {"frames.jsonl", "events.jsonl"}),
    ("test", "truth-test", {"frames.jsonl", "events.jsonl", "meta.json"}),
])
def test_the_answer_key_goes_only_to_its_sealed_container_and_clip_json_last(tmp_path, split, truth, key):
    log = []
    containers = {n: FakeContainer(log, n) for n in ("renders", "truth", "truth-test")}
    seed = 900001 if split == "test" else 3
    d = _clip(tmp_path, split, seed)
    assert pod.upload_clip(containers, "v2freeze", split, seed, d) == 5
    sealed = {p.rsplit("/", 1)[1] for n, p in log if n == truth}
    assert sealed == key
    assert not any(n not in ("renders", truth) for n, _ in log)  # a test key never reaches `truth`
    assert log[-1] == ("renders", pod.blob_path("v2freeze", split, seed, "clip.json"))
    assert all(p.startswith(f"v2freeze/{split}/seed") for _, p in log)


def test_verify_finds_a_file_that_changed_after_the_manifest(tmp_path):
    d = _clip(tmp_path, "train", 3)
    files = {f.relative_to(d).as_posix(): {"sha256": pod.sha256(f), "bytes": f.stat().st_size}
             for f in d.rglob("*") if f.is_file()}
    (tmp_path / "manifest.json").write_text(json.dumps(
        {"run": "v2freeze", "clips_list": [{"split": "train", "seed": 3, "files": files}]}))
    assert pod.verify(tmp_path) == []
    (d / "frames.jsonl").write_text("frames.jsonX")  # same size, different bytes
    assert pod.verify(tmp_path) == ["train/seed3/frames.jsonl"]


@pytest.mark.parametrize("renderer, hardware", [
    ("ANGLE (NVIDIA, Vulkan 1.3.277 (NVIDIA GeForce RTX 4090 (0x00002684)), NVIDIA-550.54.15)", True),
    ("ANGLE (NVIDIA Corporation, NVIDIA GeForce RTX 4090/PCIe/SSE2, OpenGL ES 3.2)", True),
    ("ANGLE (Apple, ANGLE Metal Renderer: Apple M3 Pro, Unspecified Version)", True),
    ("ANGLE (Google, Vulkan 1.3.0 (SwiftShader Device (Subzero) (0x0000C0DE)), SwiftShader driver)", False),
    ("ANGLE (Mesa, llvmpipe (LLVM 15.0.7, 256 bits), OpenGL 4.5)", False),
    ("Google SwiftShader", False),
    ("", False),
])
def test_the_gpu_path_refuses_a_software_renderer(renderer, hardware):
    """A pod run that asked for the GPU must be on it: SwiftShader or llvmpipe (software GL) is
    refused, never silently used, and an empty renderer string counts as unknown, not hardware."""
    assert pod.is_hardware(renderer) is hardware


def test_determinism_names_every_file_that_differs(tmp_path):
    a, b = tmp_path / "a", tmp_path / "b"
    for d in (a, b):
        (d / "images").mkdir(parents=True)
        (d / "frames.jsonl").write_text('{"frame": 0}\n')
        (d / "images" / "00000.jpg").write_bytes(b"\xff\xd8same")
    assert pod.differences(a, b) == []
    (b / "images" / "00000.jpg").write_bytes(b"\xff\xd8diff")
    (b / "events.jsonl").write_text("")
    assert pod.differences(a, b) == ["events.jsonl", "images/00000.jpg"]


def test_a_views_answer_key_is_sealed_with_the_clips(tmp_path):
    # A clip rendered with views holds frames.jsonl and events.jsonl under views/<name>/ too: the
    # answer key as much as the clip's own (lesson 192). Fails on a seal of the top level only.
    for split, truth in (("train", "truth"), ("test", "truth-test")):
        log = []
        containers = {n: FakeContainer(log, n) for n in ("renders", "truth", "truth-test")}
        seed = 900001 if split == "test" else 3
        d = _clip(tmp_path / split, split, seed)
        for name in ("tac-l", "tac-r"):
            (d / "views" / name / "images").mkdir(parents=True)
            for f in ("clip.json", "meta.json", "frames.jsonl", "events.jsonl", "images/00000.jpg"):
                (d / "views" / name / f).write_text(f)
        pod.upload_clip(containers, "run", split, seed, d)
        leaked = [p for n, p in log if n == "renders" and p.endswith(("frames.jsonl", "events.jsonl"))]
        assert leaked == []
        assert ("truth" if split == "train" else "truth-test", pod.blob_path(
            "run", split, seed, "views/tac-l/frames.jsonl")) in log
        assert (truth, pod.blob_path("run", split, seed, "views/tac-r/events.jsonl")) in log


def test_a_failed_clips_report_is_sealed_with_its_splits_answer_key(tmp_path):
    # A report's contract messages quote true events and positions; a test seed's goes to
    # truth-test, never to renders, where the detector and trainers read (lesson 192).
    log = []
    containers = {n: FakeContainer(log, n) for n in ("renders", "truth", "truth-test")}
    failed = [{"split": "test", "seed": 900002}, {"split": "train", "seed": 7}]
    for f in failed:
        rp = pod.report_path(tmp_path, f["split"], f["seed"])
        rp.parent.mkdir(parents=True, exist_ok=True)
        rp.write_text('{"data_contract": ["e00054 shot: ball never reaches (36.79, 53.5)"]}')
    assert pod.upload_failed(containers, "run", failed, tmp_path) == 2
    assert log == [("truth-test", "run/failed/test/seed900002.json"),
                   ("truth", "run/failed/train/seed7.json")]


def test_a_clip_with_a_cut_or_cuts_switched_on_fails_the_dataset(tmp_path):
    ok = {"passed": {"data_contract": True}}
    assert pod.judge({"cuts": [], "params": {"dead_ball_cut": False}}, ok)["no_cuts"] is True
    assert pod.judge({"cuts": [{"from": 1}], "params": {}}, ok)["no_cuts"] is False
    assert pod.judge({"cuts": [], "params": {"dead_ball_cut": True}}, ok)["no_cuts"] is False


def test_the_worker_passes_the_plans_views_and_judges_every_clip(tmp_path, monkeypatch):
    import contextlib

    import ninety.render.checks as checks
    import ninety.render.clip as clip

    calls = []

    def fake_render(seed, d, seconds, overrides, gpu, page, views=None):
        calls.append((seed, overrides, views))
        Path(d).mkdir(parents=True)
        return {"cuts": [{"from": 1}] if seed == 4 else [], "params": {}, "frames": 250}

    @contextlib.contextmanager
    def fake_page(gl):
        yield "page", "v", "renderer"

    monkeypatch.setattr(clip, "render_clip", fake_render)
    monkeypatch.setattr(checks, "check_clip", lambda d: {"passed": {"data_contract": True}})
    monkeypatch.setattr(pod, "open_page", fake_page)
    (tmp_path / "reports" / "train").mkdir(parents=True)  # render() makes it before the workers start
    pod._worker(0, [(3, {}), (4, {"occlusion": "crowded"})], str(tmp_path), "run", 10.0, "train",
                views="tactical")
    assert calls == [(3, {}, "tactical"), (4, {"occlusion": "crowded"}, "tactical")]
    reports = {s: json.loads(pod.report_path(tmp_path, "train", s).read_text())["passed"] for s in (3, 4)}
    assert reports[3]["no_cuts"] is True and reports[4]["no_cuts"] is False


def test_a_driver_copied_outside_a_checkout_is_recorded_by_its_hash(tmp_path, monkeypatch):
    # On the pod the driver is a plain copy (no repository round it): git fails there, so the
    # manifest records the file's sha256 instead of failing (found rendering dataset tactical).
    def no_git(repo):
        raise pod.subprocess.CalledProcessError(128, ["git"])

    monkeypatch.setattr(pod, "git_head", no_git)
    assert pod.driver_id() == {"driver_sha256": pod.sha256(Path(pod.__file__))}
