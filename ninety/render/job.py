"""Render training clips in an Azure Container Apps job and upload them to Blob Storage.

One job execution renders one range of training seeds; start several executions with different
ranges to render in parallel (infra/render-job.sh). Configuration comes from the environment:

    NINETY_RUN          run name, the blob prefix: <run>/train/seed<N>/...      (required)
    NINETY_FIRST_SEED   first training seed                                       (required)
    NINETY_COUNT        number of consecutive seeds                               (required)
    NINETY_SECONDS      clip length in seconds                                    (default 10)
    NINETY_SET          render overrides, ';'-separated key=value, e.g. "occlusion=crowded"
    AZURE_STORAGE_BLOB_URL   https://<account>.blob.core.windows.net             (required)
    AZURE_STORAGE_CONTAINER  container name                                       (default renders)
    AZURE_CLIENT_ID     the job's user-assigned managed identity (set by the job definition)

Only training seeds: the fixed test set is rendered once, locally, with software GL, so its pixels
never depend on which machine drew them. Each clip runs the render checks before upload. A clip
that fails them is not uploaded as data; its check report goes to <run>/failed/ so it is counted,
never silently dropped. A seed whose clip.json is already in the container is skipped, so a
retried execution resumes instead of redoing finished clips.
"""

from __future__ import annotations

import json
import os
import shutil
import sys
import tempfile
import time
from pathlib import Path

from ninety.render.checks import check_clip
from ninety.render.params import parse_override
from ninety.render.splits import check_seed


def parse_overrides(text: str) -> dict:
    return dict(parse_override(s.strip()) for s in text.split(";") if s.strip())


def job_config(env: dict) -> dict:
    missing = [k for k in ("NINETY_RUN", "NINETY_FIRST_SEED", "NINETY_COUNT", "AZURE_STORAGE_BLOB_URL")
               if not env.get(k)]
    if missing:
        raise ValueError(f"missing environment variables: {', '.join(missing)}")
    run = env["NINETY_RUN"]
    if not run.replace("-", "").replace("_", "").isalnum():
        raise ValueError(f"NINETY_RUN must be letters, digits, '-' or '_', not {run!r}")
    first, count = int(env["NINETY_FIRST_SEED"]), int(env["NINETY_COUNT"])
    if count < 1:
        raise ValueError(f"NINETY_COUNT must be at least 1, got {count}")
    seeds = list(range(first, first + count))
    for s in seeds:
        check_seed(s, "train")
    return {
        "run": run,
        "seeds": seeds,
        "seconds": float(env.get("NINETY_SECONDS") or 10.0),
        "overrides": parse_overrides(env.get("NINETY_SET", "")),
        "blob_url": env["AZURE_STORAGE_BLOB_URL"],
        "container": env.get("AZURE_STORAGE_CONTAINER") or "renders",
    }


def blob_name(run: str, seed: int, rel: Path) -> str:
    return f"{run}/train/seed{seed}/{rel.as_posix()}"


def upload_dir(container, run: str, seed: int, clip_dir: Path, last: str = "clip.json") -> int:
    """Upload a clip, `last` after everything else, so its presence means the whole clip arrived."""
    files = [f for f in sorted(clip_dir.rglob("*")) if f.is_file() and f.name != last]
    files.append(clip_dir / last)
    n = 0
    for f in files:
        with open(f, "rb") as data:
            container.upload_blob(blob_name(run, seed, f.relative_to(clip_dir)), data, overwrite=True)
        n += 1
    return n


def _container(cfg: dict):
    from azure.identity import ManagedIdentityCredential
    from azure.storage.blob import BlobServiceClient

    cred = ManagedIdentityCredential(client_id=os.environ.get("AZURE_CLIENT_ID"))
    return BlobServiceClient(cfg["blob_url"], credential=cred).get_container_client(cfg["container"])


def run_job(cfg: dict, container, render_clip, browser_page, work: Path) -> dict:
    """Render, check and upload every seed in cfg; returns counts. Rendering is injected for tests."""
    done = {"uploaded": [], "skipped": [], "failed": []}
    with browser_page() as (page, _):
        for s in cfg["seeds"]:
            if container.get_blob_client(blob_name(cfg["run"], s, Path("clip.json"))).exists():
                done["skipped"].append(s)
                continue
            t = time.time()
            d = work / f"seed{s}"
            render_clip(s, d, seconds=cfg["seconds"], overrides=cfg["overrides"], page=page)
            report = check_clip(d)
            ok = all(report["passed"].values())
            if ok:
                files = upload_dir(container, cfg["run"], s, d)
                done["uploaded"].append(s)
            else:
                container.upload_blob(
                    f"{cfg['run']}/failed/seed{s}.json", json.dumps(report).encode(), overwrite=True
                )
                files = 0
                done["failed"].append(s)
            print(json.dumps({"seed": s, "passed": ok, "files": files,
                              "seconds_taken": round(time.time() - t, 1)}), flush=True)
            shutil.rmtree(d)
    return done


def main() -> None:
    from ninety.render.clip import browser_page, render_clip

    try:
        cfg = job_config(dict(os.environ))
    except ValueError as e:
        sys.exit(str(e))
    start = {k: v for k, v in cfg.items() if k != "blob_url"} | {
        "seeds": [cfg["seeds"][0], cfg["seeds"][-1]],
        "commit": os.environ.get("NINETY_COMMIT"),
    }
    print(json.dumps(start), flush=True)
    with tempfile.TemporaryDirectory() as work:
        done = run_job(cfg, _container(cfg), render_clip, browser_page, Path(work))
    # A clip that fails its checks fails again on retry (same seed, same pixels), so it is reported
    # in <run>/failed/ rather than failing the execution into a pointless retry.
    print(json.dumps({k: len(v) for k, v in done.items()} | {"failed_seeds": done["failed"]}), flush=True)


if __name__ == "__main__":
    main()
