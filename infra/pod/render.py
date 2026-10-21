"""Render a pre-registered dataset on a rented CPU machine, check every clip, write its manifest and
upload it to the same Blob layout as the Azure render job (ninety/render/job.py).

It runs against a checkout of the render commit (`--repo`): the renderer, the checks and the upload
are that commit's own code, so the clips are what the commit makes; this file only schedules them.

    python render.py render   --plan PLAN --repo REPO --out OUT --split test|train --workers N [--seeds 3,4]
    python render.py manifest --plan PLAN --repo REPO --out OUT
    python render.py verify   --out OUT
    python render.py upload   --out OUT --account ACCOUNT

No credential goes to the render machine. Copy `--out` back over SSH, then on the maintainer's
machine run `verify` (every sha256 against the manifest) and `upload --account <name>`, which uses
the local az login. The test split's answer key goes to `truth-test`, never `truth`.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import multiprocessing as mp
import subprocess
import sys
import time
from pathlib import Path


def expand(plan: dict, split: str = "train") -> list[tuple[int, dict]]:
    """Every (seed, overrides) of a split of the plan, in order; refuses a seed of another split."""
    from ninety.render.splits import check_seed

    if split == "test":
        first, last = plan["test_set"]["seeds"]
        seeds = list(range(first, last + 1))
        for s in seeds:
            check_seed(s, "test")
        if len(seeds) != plan["test_set"]["clips"]:
            raise ValueError(f"the test set lists {len(seeds)} seeds, not {plan['test_set']['clips']}")
        return [(s, {}) for s in seeds]
    out = []
    for g in plan["seeds"]["groups"]:
        for s in range(g["first"], g["last"] + 1):
            check_seed(s, "train")
            out.append((s, dict(g["overrides"])))
    if len(out) != plan["seeds"]["clips"] or len({s for s, _ in out}) != len(out):
        raise ValueError(f"the plan lists {len(out)} seeds, not {plan['seeds']['clips']} distinct ones")
    return out


SPLITS = ("test", "train")  # the test set renders first


def clip_dir(out: Path, run: str, seed: int, split: str = "train") -> Path:
    return out / run / split / f"seed{seed}"


def report_path(out: Path, split: str, seed: int) -> Path:
    return out / "reports" / split / f"seed{seed}.json"


def _worker(index: int, jobs: list[tuple[int, dict]], out: str, run: str, seconds: float, split: str) -> None:
    from ninety.render.checks import check_clip
    from ninety.render.clip import browser_page, render_clip

    out_p = Path(out)
    log = out_p / f"results-{split}-w{index}.jsonl"
    with browser_page() as (page, _):
        for seed, overrides in jobs:
            rp = report_path(out_p, split, seed)
            if rp.exists():
                continue  # finished in an earlier run: resume
            d = clip_dir(out_p, run, seed, split)
            t = time.time()
            clip = render_clip(seed, d, seconds=seconds, overrides=overrides, page=page)
            report = check_clip(d)
            # A training clip shows every frame: no dead-ball cut (docs/DATA_CONTRACT.md, lesson 156).
            report["passed"]["no_cuts"] = not clip.get("cuts") and not clip["params"].get("dead_ball_cut")
            rp.write_text(json.dumps(report))
            line = {"seed": seed, "passed": all(report["passed"].values()), "frames": clip["frames"],
                    "seconds_taken": round(time.time() - t, 1), "worker": index}
            with log.open("a") as f:
                f.write(json.dumps(line) + "\n")
            print(json.dumps(line), flush=True)


def render(plan: dict, out: Path, workers: int, only: set[int] | None, split: str = "train") -> None:
    jobs = [j for j in expand(plan, split) if only is None or j[0] in only]
    (out / "reports" / split).mkdir(parents=True, exist_ok=True)
    chunks = [jobs[i::workers] for i in range(workers)]  # round-robin, so slow groups spread out
    t = time.time()
    ctx = mp.get_context("spawn")
    seconds = plan["render"]["seconds"]
    procs = [ctx.Process(target=_worker, args=(i, c, str(out), plan["run"], seconds, split))
             for i, c in enumerate(chunks) if c]
    for p in procs:
        p.start()
    for p in procs:
        p.join()
    hours = (time.time() - t) / 3600
    print(json.dumps({"split": split, "clips": len(jobs), "workers": workers, "hours": round(hours, 3),
                      "clips_per_hour": round(len(jobs) / hours, 1) if hours else None,
                      "worker_exit_codes": [p.exitcode for p in procs]}), flush=True)


def sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for block in iter(lambda: f.read(1 << 20), b""):
            h.update(block)
    return h.hexdigest()


def git_head(repo: Path) -> str:
    return subprocess.run(["git", "-C", str(repo), "rev-parse", "HEAD"], capture_output=True,
                          text=True, check=True).stdout.strip()


KNOBS = ("lighting", "kit_contrast", "occlusion", "weather")


def manifest(plan: dict, repo: Path, out: Path) -> dict:
    from ninety.render import RENDERER_VERSION

    clips, failed, missing = [], [], []
    for split in SPLITS:
        for seed, overrides in expand(plan, split):
            rp = report_path(out, split, seed)
            if not rp.exists():
                missing.append({"split": split, "seed": seed})
                continue
            report = json.loads(rp.read_text())
            if not all(report["passed"].values()):
                bad = sorted(k for k, v in report["passed"].items() if not v)
                failed.append({"split": split, "seed": seed, "failed": bad})
                continue
            d = clip_dir(out, plan["run"], seed, split)
            clip = json.loads((d / "clip.json").read_text())
            files = {f.relative_to(d).as_posix(): {"sha256": sha256(f), "bytes": f.stat().st_size}
                     for f in sorted(d.rglob("*")) if f.is_file()}
            clips.append({"split": split, "seed": seed, "overrides": overrides, "frames": clip["frames"],
                          "params": {k: clip["params"].get(k) for k in KNOBS}, "files": files})
    m = {"name": plan["name"], "run": plan["run"], "render_commit": git_head(repo),
         "renderer": RENDERER_VERSION, "plan_commit": plan.get("commit"),
         "driver": "infra/pod/render.py", "clips": len(clips),
         "bytes": sum(f["bytes"] for c in clips for f in c["files"].values()),
         "failed": failed, "missing": missing, "clips_list": clips}
    (out / "manifest.json").write_text(json.dumps(m, indent=1))
    return m


def verify(out: Path) -> list[str]:
    """Every file the manifest lists, with its sha256 and size: what differs (empty when all match)."""
    m = json.loads((out / "manifest.json").read_text())
    bad = []
    for c in m["clips_list"]:
        d = clip_dir(out, m["run"], c["seed"], c["split"])
        on_disk = {f.relative_to(d).as_posix() for f in d.rglob("*") if f.is_file()}
        if on_disk != set(c["files"]):
            bad.append(f"{c['split']}/seed{c['seed']}: files differ from the manifest")
        for rel, want in c["files"].items():
            f = d / rel
            if not f.is_file() or f.stat().st_size != want["bytes"] or sha256(f) != want["sha256"]:
                bad.append(f"{c['split']}/seed{c['seed']}/{rel}")
    return bad


# The answer key goes to the sealed container: frames and events for training (ninety/render/job.py),
# and meta.json too for the test set, as the 91d1e3b test set was uploaded.
TRUTH = {"train": ("events.jsonl", "frames.jsonl"), "test": ("events.jsonl", "frames.jsonl", "meta.json")}
TRUTH_CONTAINER = {"train": "truth", "test": "truth-test"}


def blob_path(run: str, split: str, seed: int, rel: str) -> str:
    return f"{run}/{split}/seed{seed}/{rel}"


def upload_clip(containers: dict, run: str, split: str, seed: int, d: Path) -> int:
    """The answer key first, then the media, clip.json last, so its presence means the whole clip."""
    files = sorted(f for f in d.rglob("*") if f.is_file() and f.name != "clip.json")
    truth = [f for f in files if f.parent == d and f.name in TRUTH[split]]
    media = [f for f in files if f not in truth] + [d / "clip.json"]
    n = 0
    for name, group in ((TRUTH_CONTAINER[split], truth), ("renders", media)):
        for f in group:
            with open(f, "rb") as data:
                containers[name].upload_blob(blob_path(run, split, seed, f.relative_to(d).as_posix()),
                                             data, overwrite=True)
            n += 1
    return n


def upload(out: Path, account: str) -> dict:
    """Upload from the maintainer's machine with its az login, after `verify` passes."""
    from azure.identity import AzureCliCredential
    from azure.storage.blob import BlobServiceClient

    bad = verify(out)
    if bad:
        raise SystemExit(f"{len(bad)} files differ from the manifest, first: {bad[0]}")
    service = BlobServiceClient(f"https://{account}.blob.core.windows.net", credential=AzureCliCredential())
    containers = {n: service.get_container_client(n) for n in ("renders", "truth", "truth-test")}
    m = json.loads((out / "manifest.json").read_text())
    run = m["run"]
    done = {"uploaded": 0, "skipped": 0, "files": 0}
    for c in m["clips_list"]:
        split, s = c["split"], c["seed"]
        if containers["renders"].get_blob_client(blob_path(run, split, s, "clip.json")).exists():
            done["skipped"] += 1
            continue
        done["files"] += upload_clip(containers, run, split, s, clip_dir(out, run, s, split))
        done["uploaded"] += 1
    for f in m["failed"]:
        rp = report_path(out, f["split"], f["seed"])
        name = f"{run}/failed/{f['split']}/seed{f['seed']}.json"
        containers["renders"].upload_blob(name, rp.read_bytes(), overwrite=True)
    manifest_bytes = (out / "manifest.json").read_bytes()
    containers["renders"].upload_blob(f"{run}/manifest.json", manifest_bytes, overwrite=True)
    print(json.dumps(done), flush=True)
    return done


def main(argv: list[str] | None = None) -> None:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("command", choices=("render", "manifest", "verify", "upload"))
    ap.add_argument("--plan", type=Path)
    ap.add_argument("--repo", type=Path, help="checkout of the render commit")
    ap.add_argument("--out", type=Path, required=True)
    ap.add_argument("--split", choices=SPLITS, default="train")
    ap.add_argument("--workers", type=int, default=8)
    ap.add_argument("--seeds", default="", help="comma-separated subset, for the throughput test")
    ap.add_argument("--account", help="storage account, for upload")
    a = ap.parse_args(argv)
    if a.command == "verify":
        bad = verify(a.out)
        print(json.dumps({"files_differing": len(bad), "first": bad[:5]}))
        sys.exit(1 if bad else 0)
    if a.command == "upload":
        upload(a.out, a.account)
        return
    sys.path.insert(0, str(a.repo))
    plan = json.loads(a.plan.read_text())
    if a.command == "render":
        only = {int(s) for s in a.seeds.split(",") if s} or None
        render(plan, a.out, a.workers, only, a.split)
    else:
        m = manifest(plan, a.repo, a.out)
        keys = ("clips", "bytes", "failed", "missing", "render_commit", "renderer")
        print(json.dumps({k: m[k] for k in keys}))


if __name__ == "__main__":
    main()
