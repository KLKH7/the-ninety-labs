"""Render a pre-registered dataset on a rented CPU machine, check every clip, write its manifest and
upload it to the same Blob layout as the Azure render job (ninety/render/job.py).

It runs against a checkout of the render commit (`--repo`): the renderer, the checks and the upload
are that commit's own code, so the clips are what the commit makes; this file only schedules them.

    python render.py render   --plan PLAN --repo REPO --out OUT --workers N [--seeds 3,4,5]
    python render.py manifest --plan PLAN --repo REPO --out OUT
    python render.py upload   --plan PLAN --repo REPO --out OUT

`upload` reads two container SAS URLs from the environment, NINETY_RENDERS_SAS_URL and
NINETY_TRUTH_SAS_URL. They are never written to disk or printed.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import multiprocessing as mp
import os
import subprocess
import sys
import time
from pathlib import Path


def expand(plan: dict) -> list[tuple[int, dict]]:
    """Every (seed, overrides) of the plan, in order; refuses a seed that is not a training seed."""
    from ninety.render.splits import check_seed

    out = []
    for g in plan["seeds"]["groups"]:
        for s in range(g["first"], g["last"] + 1):
            check_seed(s, "train")
            out.append((s, dict(g["overrides"])))
    if len(out) != plan["seeds"]["clips"] or len({s for s, _ in out}) != len(out):
        raise ValueError(f"the plan lists {len(out)} seeds, not {plan['seeds']['clips']} distinct ones")
    return out


def clip_dir(out: Path, run: str, seed: int) -> Path:
    return out / run / "train" / f"seed{seed}"


def _worker(index: int, jobs: list[tuple[int, dict]], out: str, run: str, seconds: float) -> None:
    from ninety.render.checks import check_clip
    from ninety.render.clip import browser_page, render_clip

    out_p = Path(out)
    reports = out_p / "reports"
    log = out_p / f"results-w{index}.jsonl"
    with browser_page() as (page, _):
        for seed, overrides in jobs:
            if (reports / f"seed{seed}.json").exists():
                continue  # finished in an earlier run: resume
            d = clip_dir(out_p, run, seed)
            t = time.time()
            clip = render_clip(seed, d, seconds=seconds, overrides=overrides, page=page)
            report = check_clip(d)
            # A training clip shows every frame: no dead-ball cut (docs/DATA_CONTRACT.md, lesson 156).
            report["passed"]["no_cuts"] = not clip.get("cuts") and not clip["params"].get("dead_ball_cut")
            (reports / f"seed{seed}.json").write_text(json.dumps(report))
            line = {"seed": seed, "passed": all(report["passed"].values()), "frames": clip["frames"],
                    "seconds_taken": round(time.time() - t, 1), "worker": index}
            with log.open("a") as f:
                f.write(json.dumps(line) + "\n")
            print(json.dumps(line), flush=True)


def render(plan: dict, out: Path, workers: int, only: set[int] | None) -> None:
    jobs = [j for j in expand(plan) if only is None or j[0] in only]
    (out / "reports").mkdir(parents=True, exist_ok=True)
    chunks = [jobs[i::workers] for i in range(workers)]  # round-robin, so slow groups spread out
    t = time.time()
    ctx = mp.get_context("spawn")
    procs = [ctx.Process(target=_worker, args=(i, c, str(out), plan["run"], plan["render"]["seconds"]))
             for i, c in enumerate(chunks) if c]
    for p in procs:
        p.start()
    for p in procs:
        p.join()
    hours = (time.time() - t) / 3600
    print(json.dumps({"clips": len(jobs), "workers": workers, "hours": round(hours, 3),
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
    for seed, overrides in expand(plan):
        rp = out / "reports" / f"seed{seed}.json"
        if not rp.exists():
            missing.append(seed)
            continue
        report = json.loads(rp.read_text())
        if not all(report["passed"].values()):
            failed.append({"seed": seed, "failed": sorted(k for k, v in report["passed"].items() if not v)})
            continue
        d = clip_dir(out, plan["run"], seed)
        clip = json.loads((d / "clip.json").read_text())
        files = {f.relative_to(d).as_posix(): {"sha256": sha256(f), "bytes": f.stat().st_size}
                 for f in sorted(d.rglob("*")) if f.is_file()}
        clips.append({"seed": seed, "overrides": overrides, "frames": clip["frames"],
                      "params": {k: clip["params"].get(k) for k in KNOBS},
                      "files": files})
    m = {"name": plan["name"], "run": plan["run"], "render_commit": git_head(repo),
         "renderer": RENDERER_VERSION, "plan_commit": plan.get("commit"),
         "driver": "infra/pod/render.py", "clips": len(clips), "failed": failed, "missing": missing,
         "clips_list": clips}
    (out / "manifest.json").write_text(json.dumps(m, indent=1))
    return m


def upload(plan: dict, out: Path) -> dict:
    from azure.storage.blob import ContainerClient

    from ninety.render.job import blob_name, upload_dir

    container = ContainerClient.from_container_url(os.environ["NINETY_RENDERS_SAS_URL"])
    truth = ContainerClient.from_container_url(os.environ["NINETY_TRUTH_SAS_URL"])
    m = json.loads((out / "manifest.json").read_text())
    done = {"uploaded": 0, "skipped": 0, "files": 0}
    for c in m["clips_list"]:
        s = c["seed"]
        if container.get_blob_client(blob_name(plan["run"], s, Path("clip.json"))).exists():
            done["skipped"] += 1  # clip.json goes last, so its presence means the whole clip arrived
            continue
        done["files"] += upload_dir(container, truth, plan["run"], s, clip_dir(out, plan["run"], s))
        done["uploaded"] += 1
    for f in m["failed"]:
        rp = out / "reports" / f"seed{f['seed']}.json"
        name = f"{plan['run']}/failed/seed{f['seed']}.json"
        container.upload_blob(name, rp.read_bytes(), overwrite=True)
    manifest_bytes = (out / "manifest.json").read_bytes()
    container.upload_blob(f"{plan['run']}/manifest.json", manifest_bytes, overwrite=True)
    print(json.dumps(done), flush=True)
    return done


def main(argv: list[str] | None = None) -> None:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("command", choices=("render", "manifest", "upload"))
    ap.add_argument("--plan", type=Path, required=True)
    ap.add_argument("--repo", type=Path, required=True, help="checkout of the render commit")
    ap.add_argument("--out", type=Path, required=True)
    ap.add_argument("--workers", type=int, default=8)
    ap.add_argument("--seeds", default="", help="comma-separated subset, for the throughput test")
    a = ap.parse_args(argv)
    sys.path.insert(0, str(a.repo))
    plan = json.loads(a.plan.read_text())
    if a.command == "render":
        only = {int(s) for s in a.seeds.split(",") if s} or None
        render(plan, a.out, a.workers, only)
    elif a.command == "manifest":
        m = manifest(plan, a.repo, a.out)
        print(json.dumps({k: m[k] for k in ("clips", "failed", "missing", "render_commit", "renderer")}))
    else:
        upload(plan, a.out)


if __name__ == "__main__":
    main()
