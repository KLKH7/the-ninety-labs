"""Fetch a render run's clips from Blob Storage, only what training reads, onto a training machine.

    RENDERS_SAS_URL=<container SAS URL> uv run python -m ninety.vision.fetch_clips v2 --out data/clips
    RENDERS_SAS_URL=... TRUTH_SAS_URL=... uv run python -m ninety.vision.fetch_clips \
        --list docs/eval/dataset-v1.json --out data/clips

Downloads, per clip, `clip.json`, `frames.jsonl` and the images of every `--stride`-th frame:
exactly the frames coco_export keeps (same stride, from frame 0). The render checks already ran on
every clip before it was uploaded (ninety/render/job.py), so they are not repeated here.

Several runs go into one folder in order: a seed already fetched from an earlier run is skipped in
a later one, so `v2los` then `v2` takes the re-rendered crowded clips from v2los and the rest from v2.

`--list` fetches a dataset definition (docs/eval/dataset-v1.json) exactly: each listed seed from
the run it names, and nothing else. Runs rendered since the ground truth was sealed keep images and
clip.json in the `renders` container and frames.jsonl in the `truth` container (ninety/render/job.py),
so a list fetch reads both. The list's sha256 is written to <out>/dataset-list.json, so the training
manifest can say which definition it trained on.

The SAS URLs come only from the environment, are read-only, and are never printed or written to
disk. Only training seeds are fetched; a test or reserved seed in the run is refused. The truth
link must never reach the test set's answer key: it goes to a rented machine and covers its whole
container, so the frozen test set's ground truth lives in a container training never links.

A list fetch refuses an `--out` that already holds a clip: coco_export trains on every `seed*`
folder there, so a clip left from an earlier fetch would be trained on without being listed.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import sys
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from ninety.render.splits import split_of

KEEP_FILES = ("clip.json", "frames.jsonl")
NAME = re.compile(r"^(?P<run>[^/]+)/train/seed(?P<seed>\d+)/(?P<rel>.+)$")
IMAGE = re.compile(r"^images/(?P<idx>\d+)\.jpg$")


def wanted(blob_name: str, run: str, stride: int) -> tuple[int, str] | None:
    """(seed, path inside the clip) when training needs this blob, else None."""
    m = NAME.match(blob_name)
    if not m or m["run"] != run:
        return None
    rel = m["rel"]
    if rel in KEEP_FILES:
        return int(m["seed"]), rel
    im = IMAGE.match(rel)
    if im and int(im["idx"]) % stride == 0:
        return int(m["seed"]), rel
    return None


def plan(
    names: list[str], run: str, stride: int, skip_seeds: frozenset[int] = frozenset()
) -> list[tuple[str, int, str]]:
    out = []
    for name in names:
        w = wanted(name, run, stride)
        if w is None:
            continue
        seed, rel = w
        if seed in skip_seeds:
            continue
        if split_of(seed) != "train":
            raise ValueError(f"seed {seed} in {run} is not a training seed; refusing to fetch it")
        out.append((name, seed, rel))
    return out


def read_list(path: Path) -> dict[int, str]:
    """seed -> run from a dataset definition; refuses a seed listed twice or one that is not training."""
    picks: dict[int, str] = {}
    for clip in json.loads(path.read_text())["clips_list"]:
        seed, run = int(clip["seed"]), clip["run"]
        if seed in picks:
            raise ValueError(f"seed {seed} is listed twice in {path}")
        if split_of(seed) != "train":
            raise ValueError(f"seed {seed} in {path} is not a training seed; refusing to fetch it")
        picks[seed] = run
    return picks


def plan_list(
    names_by_run: dict[str, list[str]], picks: dict[int, str], stride: int
) -> tuple[list[tuple[str, int, str]], list[tuple[str, int, str]]]:
    """(renders blobs, truth blobs) for exactly the listed seeds, each from the run the list names.

    Images and clip.json come from `renders`; frames.jsonl from `truth`. A listed seed whose clip.json
    is not in its run is an error, never a silent gap.
    """
    media = []
    for run in sorted(set(picks.values())):
        for name, seed, rel in plan(names_by_run.get(run, []), run, stride):
            if picks.get(seed) == run and rel != "frames.jsonl":
                media.append((name, seed, rel))
    found = {seed for _, seed, rel in media if rel == "clip.json"}
    missing = sorted(set(picks) - found)
    if missing:
        raise ValueError(f"listed seeds with no clip.json in their run: {missing}")
    truth = [
        (f"{run}/train/seed{seed}/frames.jsonl", seed, "frames.jsonl") for seed, run in sorted(picks.items())
    ]
    return media, truth


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _download(container, out: Path, workers: int, todo: list[tuple[str, int, str]]) -> int:
    def fetch(item: tuple[str, int, str]) -> int:
        name, seed, rel = item
        dest = out / f"seed{seed}" / rel
        dest.parent.mkdir(parents=True, exist_ok=True)
        data = container.download_blob(name).readall()
        dest.write_bytes(data)
        return len(data)

    with ThreadPoolExecutor(workers) as pool:
        return sum(pool.map(fetch, todo))


def _env_container(var: str, what: str):
    from azure.storage.blob import ContainerClient

    url = os.environ.get(var)
    if not url:
        sys.exit(f"set {var} to a read-only SAS URL of the {what} container")
    return ContainerClient.from_container_url(url)


def check_empty(out: Path) -> None:
    """A list fetch starts from no clips: anything already in `out` would be trained on unlisted."""
    leftover = sorted(d.name for d in out.glob("seed*")) if out.exists() else []
    if leftover:
        raise ValueError(
            f"{out} already holds {len(leftover)} clips ({', '.join(leftover[:3])}...): "
            "a list fetch needs an empty --out, so only the listed clips are trained on"
        )


def fetch_list(path: Path, out: Path, stride: int, workers: int) -> None:
    check_empty(out)
    picks = read_list(path)
    renders = _env_container("RENDERS_SAS_URL", "renders")
    truth = _env_container("TRUTH_SAS_URL", "truth")
    t = time.time()
    names = {
        run: [b.name for b in renders.list_blobs(name_starts_with=f"{run}/train/")]
        for run in sorted(set(picks.values()))
    }
    media, labels = plan_list(names, picks, stride)
    # clip.json last: its presence means the clip's other files arrived
    first = [m for m in media if m[2] != "clip.json"]
    total = _download(truth, out, workers, labels) + _download(renders, out, workers, first)
    total += _download(renders, out, workers, [m for m in media if m[2] == "clip.json"])
    out.mkdir(parents=True, exist_ok=True)
    (out / "dataset-list.json").write_text(
        json.dumps({"path": str(path), "sha256": sha256(path), "clips": len(picks)}, indent=2)
    )
    print(f"{path}: fetched {len(media) + len(labels)} files, {total / 1e9:.2f} GB, "
          f"{len(picks)} clips in {time.time() - t:.0f}s")


def main(argv: list[str] | None = None) -> None:
    ap = argparse.ArgumentParser(description="Fetch a render run's training frames from Blob Storage.")
    ap.add_argument("run", nargs="?", help="render run name, e.g. v2 (or use --list)")
    ap.add_argument("--list", type=Path, help="a dataset definition, e.g. docs/eval/dataset-v1.json")
    ap.add_argument("--out", type=Path, required=True, help="clip directories land in <out>/seed<N>/")
    ap.add_argument("--stride", type=int, default=5)
    ap.add_argument("--workers", type=int, default=32)
    a = ap.parse_args(argv)
    if (a.run is None) == (a.list is None):
        ap.error("give a run or --list, not both")
    if a.list:
        fetch_list(a.list, a.out, a.stride, a.workers)
        return
    container = _env_container("RENDERS_SAS_URL", "renders")
    t = time.time()
    names = [b.name for b in container.list_blobs(name_starts_with=f"{a.run}/train/")]
    # seeds an earlier run already supplied (their clip.json arrived) are not taken again
    have = frozenset(int(d.name[4:]) for d in a.out.glob("seed*") if (d / "clip.json").exists())
    todo = plan(names, a.run, a.stride, have)

    total = _download(container, a.out, a.workers, todo)
    seeds = {s for _, s, _ in todo}
    took = time.time() - t
    print(f"{a.run}: fetched {len(todo)} files, {total / 1e9:.2f} GB, {len(seeds)} clips in {took:.0f}s")
    print(f"{a.run}: {len(have)} seeds were already present from an earlier run and were skipped")


if __name__ == "__main__":
    main()
