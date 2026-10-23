"""Render training clips in an Azure Container Apps job and upload them to Blob Storage.

One job execution renders one range of training seeds; start several executions with different
ranges to render in parallel (infra/render-job.sh). Configuration comes from the environment:

    NINETY_RUN          run name, the blob prefix: <run>/train/seed<N>/...      (required)
    NINETY_FIRST_SEED   first training seed                                       (required)
    NINETY_COUNT        number of consecutive seeds                               (required)
    NINETY_SECONDS      clip length in seconds                                    (default 10)
    NINETY_SET          render overrides, ';'-separated key=value, e.g. "occlusion=crowded"
    AZURE_STORAGE_BLOB_URL   https://<account>.blob.core.windows.net             (required)
    AZURE_STORAGE_CONTAINER  container for images and clip.json                   (default renders)
    AZURE_STORAGE_TRUTH_CONTAINER  container for the ground truth                     (default truth)
    AZURE_CLIENT_ID     the job's user-assigned managed identity (set by the job definition)

Ground truth is sealed: events.jsonl and frames.jsonl (true events, positions, camera, boxes), the
clip's own and every view's under views/<name>/, go to the `truth` container, which only the render
job, training and scoring may read; images and clip.json go to `renders`. Nothing on the live path
is granted the truth container (infra/main.bicep, checked by infra/check_truth_sealed.py).

Queue mode (the event-driven job): with NINETY_QUEUE set, the execution takes one render request
from that Storage Queue instead of reading the seed range from the environment. A request is JSON
{"run", "first_seed", "count", "set", "seconds", "commit", "reason"} (ninety/agents/data_agent.py
writes them), and must name the commit this execution runs: a request for another engine version
is refused, so every clip of a round comes from the same engine. A request that fails is retried
once, then moved to NINETY_QUEUE + "-failed" with the error.

Only training seeds: the fixed test set is rendered once, locally, with software GL, so its pixels
never depend on which machine drew them. Each clip runs the render checks before upload. A clip
that fails them is not uploaded as data; its check report goes to <run>/failed/ in `truth` (its
contract messages quote true events and positions, lesson 192) so it is counted,
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
from collections.abc import Callable
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
        "truth_container": env.get("AZURE_STORAGE_TRUTH_CONTAINER") or "truth",
    }


TRUTH_FILES = ("events.jsonl", "frames.jsonl")  # the answer key: true events, positions, camera, boxes


def blob_name(run: str, seed: int, rel: Path) -> str:
    return f"{run}/train/seed{seed}/{rel.as_posix()}"


def upload_dir(container, truth, run: str, seed: int, clip_dir: Path, last: str = "clip.json") -> int:
    """Upload a clip: ground truth to the sealed `truth` container first, then images, and `last`
    after everything else, so its presence means the whole clip, truth included, arrived."""
    files = [f for f in sorted(clip_dir.rglob("*")) if f.is_file() and f.name != last]
    # At any depth: a clip's views (views/<name>/, clip.py) carry their own answer key (lesson 192).
    truth_files = [f for f in files if f.name in TRUTH_FILES]
    media = [f for f in files if f not in truth_files]
    n = 0
    for target, group in ((truth, truth_files), (container, [*media, clip_dir / last])):
        for f in group:
            with open(f, "rb") as data:
                target.upload_blob(blob_name(run, seed, f.relative_to(clip_dir)), data, overwrite=True)
            n += 1
    return n


def _credential():
    from azure.identity import ManagedIdentityCredential

    return ManagedIdentityCredential(client_id=os.environ.get("AZURE_CLIENT_ID"))


def _containers(cfg: dict):
    from azure.storage.blob import BlobServiceClient

    service = BlobServiceClient(cfg["blob_url"], credential=_credential())
    clips, truth = cfg["container"], cfg["truth_container"]
    return service.get_container_client(clips), service.get_container_client(truth)


def run_job(cfg: dict, container, render_clip, browser_page, work: Path, truth) -> dict:
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
                files = upload_dir(container, truth, cfg["run"], s, d)
                done["uploaded"].append(s)
            else:
                # The report quotes the answer key (a contract message names a true event and where
                # it was), so it is sealed with it, never beside vision's input (lesson 192).
                truth.upload_blob(
                    f"{cfg['run']}/failed/seed{s}.json", json.dumps(report).encode(), overwrite=True
                )
                files = 0
                done["failed"].append(s)
            print(json.dumps({"seed": s, "passed": ok, "files": files,
                              "seconds_taken": round(time.time() - t, 1)}), flush=True)
            shutil.rmtree(d)
    return done


MAX_ATTEMPTS = 2  # a request that fails twice goes to the failed queue instead of looping
VISIBILITY_SECONDS = 5 * 3600  # longer than the job's 4 h replica timeout, so no one else takes it


def request_env(request: dict, env: dict) -> dict:
    """A queued request as the environment job_config validates, refusing one for another commit."""
    commit = env.get("NINETY_COMMIT", "")
    if request.get("commit") != commit:
        raise ValueError(f"request is for commit {request.get('commit')!r}, this execution runs {commit!r}")
    return env | {
        "NINETY_RUN": str(request["run"]),
        "NINETY_FIRST_SEED": str(request["first_seed"]),
        "NINETY_COUNT": str(request["count"]),
        "NINETY_SET": str(request.get("set") or ""),
        "NINETY_SECONDS": str(request.get("seconds") or ""),
    }


def take_request(queue, failed_queue, env: dict, run: Callable[[dict], object]) -> str:
    """Take one request from the queue and run it. Returns what happened, for the log."""
    message = next(iter(queue.receive_messages(max_messages=1, visibility_timeout=VISIBILITY_SECONDS)), None)
    if message is None:
        return "queue empty"
    try:
        cfg = job_config(request_env(json.loads(message.content), env))
        run(cfg)
    except Exception as e:  # noqa: BLE001 - every failure is recorded, then retried or set aside
        # A bad request fails the same way every time, so it is set aside at once; anything else
        # (a network error, a crashed browser) gets one more attempt.
        permanent = isinstance(e, (ValueError, KeyError, json.JSONDecodeError))
        if permanent or message.dequeue_count >= MAX_ATTEMPTS:
            failed_queue.send_message(json.dumps({"request": message.content, "error": repr(e)}))
            queue.delete_message(message)
            return f"failed for good: {e!r}"
        return f"failed, will retry: {e!r}"
    queue.delete_message(message)
    return "done"


def _queues(env: dict):
    from azure.storage.queue import QueueClient

    url, name = env["AZURE_STORAGE_QUEUE_URL"], env["NINETY_QUEUE"]
    credential = _credential()
    failed = QueueClient(url, name + "-failed", credential=credential)
    return QueueClient(url, name, credential=credential), failed


def _render(cfg: dict) -> dict:
    from ninety.render.clip import browser_page, render_clip

    container, truth = _containers(cfg)
    with tempfile.TemporaryDirectory() as work:
        done = run_job(cfg, container, render_clip, browser_page, Path(work), truth)
    # A clip that fails its checks fails again on retry (same seed, same pixels), so it is reported
    # in <run>/failed/ rather than failing the execution into a pointless retry.
    print(json.dumps({k: len(v) for k, v in done.items()} | {"failed_seeds": done["failed"]}), flush=True)
    return done


def main() -> None:
    env = dict(os.environ)
    if env.get("NINETY_QUEUE"):
        queue, failed = _queues(env)
        print(json.dumps({"queue": env["NINETY_QUEUE"], "commit": env.get("NINETY_COMMIT"),
                          "result": take_request(queue, failed, env, _render)}), flush=True)
        return
    try:
        cfg = job_config(env)
    except ValueError as e:
        sys.exit(str(e))
    start = {k: v for k, v in cfg.items() if k != "blob_url"} | {
        "seeds": [cfg["seeds"][0], cfg["seeds"][-1]],
        "commit": os.environ.get("NINETY_COMMIT"),
    }
    print(json.dumps(start), flush=True)
    _render(cfg)


if __name__ == "__main__":
    main()
