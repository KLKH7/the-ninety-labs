"""Fetch a render run's clips from Blob Storage, only what training reads, onto a training machine.

    RENDERS_SAS_URL=<container SAS URL> uv run python -m ninety.vision.fetch_clips v2 --out data/clips

Downloads, per clip, `clip.json`, `frames.jsonl` and the images of every `--stride`-th frame:
exactly the frames coco_export keeps (same stride, from frame 0). The render checks already ran on
every clip before it was uploaded (ninety/render/job.py), so they are not repeated here.

The SAS URL comes only from the environment, is read-only, and is never printed or written to
disk. Only training seeds are fetched; a test or reserved seed in the run is refused.
"""

from __future__ import annotations

import argparse
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


def plan(names: list[str], run: str, stride: int) -> list[tuple[str, int, str]]:
    out = []
    for name in names:
        w = wanted(name, run, stride)
        if w is None:
            continue
        seed, rel = w
        if split_of(seed) != "train":
            raise ValueError(f"seed {seed} in {run} is not a training seed; refusing to fetch it")
        out.append((name, seed, rel))
    return out


def main(argv: list[str] | None = None) -> None:
    from azure.storage.blob import ContainerClient

    ap = argparse.ArgumentParser(description="Fetch a render run's training frames from Blob Storage.")
    ap.add_argument("run", help="render run name, e.g. v2")
    ap.add_argument("--out", type=Path, required=True, help="clip directories land in <out>/seed<N>/")
    ap.add_argument("--stride", type=int, default=5)
    ap.add_argument("--workers", type=int, default=32)
    a = ap.parse_args(argv)
    url = os.environ.get("RENDERS_SAS_URL")
    if not url:
        sys.exit("set RENDERS_SAS_URL to a read-only SAS URL of the renders container")
    container = ContainerClient.from_container_url(url)
    t = time.time()
    names = [b.name for b in container.list_blobs(name_starts_with=f"{a.run}/train/")]
    todo = plan(names, a.run, a.stride)

    def fetch(item: tuple[str, int, str]) -> int:
        name, seed, rel = item
        dest = a.out / f"seed{seed}" / rel
        dest.parent.mkdir(parents=True, exist_ok=True)
        data = container.download_blob(name).readall()
        dest.write_bytes(data)
        return len(data)

    with ThreadPoolExecutor(a.workers) as pool:
        total = sum(pool.map(fetch, todo))
    seeds = {s for _, s, _ in todo}
    print(f"fetched {len(todo)} files, {total / 1e9:.2f} GB, {len(seeds)} clips in {time.time() - t:.0f}s")


if __name__ == "__main__":
    main()
