"""The training clips of a render made on a rented machine (infra/pod/render.py), checked against
its manifest, for a fine-tune that runs on the same machine against the clips in place.

    uv run python -m ninety.vision.pod_clips <render out> --run v2freeze --commit <render commit> \
        --config ninety/vision/finetune-v2freeze.json --work <dir>

`<render out>` is the render's `--out`: `manifest.json` and `<run>/train/seed<N>/`. This writes into
`<dir>`:
- `clips.txt`: the passing training clips' folders, one per line (coco_export's input);
- `config.json`: the training config, less any validation seed whose clip failed the render checks
  (removed, not replaced, as seed 111 left dataset v1's validation; the notes say which);
- `dataset-list.json`: run, render commit, the manifest's sha256, the seeds trained and validated
  on, the clips the checks excluded and the validation seeds removed (train.py --dataset-list).

It refuses a render of another run or commit, and a render that is not finished (a training seed
with no report). Only the manifest's `train` clips are read: no test clip is listed (coco_export
refuses one anyway), and nothing of the test split is opened. Every file of every listed clip is
checked against the manifest's sha256 and size before anything is written.
"""

from __future__ import annotations

import argparse
import copy
import hashlib
import json
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from ninety.render.splits import split_of


def sha256(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for block in iter(lambda: f.read(1 << 20), b""):
            h.update(block)
    return h.hexdigest()


def read_manifest(out: Path, run: str, commit: str, crashed: frozenset[int] = frozenset()) -> dict:
    """The render's manifest. A training seed with no report means an unfinished render, unless the
    render's owner named it as crashed at the hand-over (`crashed`, recorded): exactly those, no others."""
    m = json.loads((out / "manifest.json").read_text())
    if m["run"] != run:
        raise ValueError(f"the render is run {m['run']!r}, not {run!r}")
    if m["render_commit"] != commit:
        raise ValueError(f"the render is at {m['render_commit']}, not the pre-registered {commit}")
    missing = {c["seed"] for c in m["missing"] if c["split"] == "train"}
    if missing != set(crashed):
        unnamed, absent = sorted(missing - set(crashed)), sorted(set(crashed) - missing)
        if unnamed:
            raise ValueError(f"the render is not finished: training seeds {unnamed} have no report")
        raise ValueError(f"seeds {absent} were named as crashed but are not missing")
    return m


def train_clips(out: Path, m: dict) -> dict[int, tuple[Path, dict]]:
    """seed -> (clip folder, its files in the manifest), training split only."""
    clips = {}
    for c in m["clips_list"]:
        if c["split"] != "train":
            continue
        if split_of(c["seed"]) != "train":
            raise ValueError(f"seed {c['seed']} is listed as training but is not a training seed")
        clips[c["seed"]] = (out / m["run"] / "train" / f"seed{c['seed']}", c["files"])
    return clips


def differing(clips: dict[int, tuple[Path, dict]], workers: int = 16) -> list[str]:
    """Files whose size or sha256 differs from the manifest, or that are missing (empty when all match)."""
    todo = [(d / rel, want) for d, files in clips.values() for rel, want in files.items()]

    def bad(item: tuple[Path, dict]) -> str | None:
        f, want = item
        if not f.is_file() or f.stat().st_size != want["bytes"] or sha256(f) != want["sha256"]:
            return str(f)
        return None

    with ThreadPoolExecutor(workers) as pool:
        return sorted(b for b in pool.map(bad, todo) if b)


def run_config(cfg: dict, seeds: set[int]) -> tuple[dict, list[int]]:
    """The config with validation seeds that have no passing clip removed (not replaced)."""
    removed = [s for s in cfg["val_seeds"] if s not in seeds]
    kept = [s for s in cfg["val_seeds"] if s in seeds]
    if not kept:
        raise ValueError("no validation seed has a passing clip")
    out = copy.deepcopy(cfg)
    out["val_seeds"] = kept
    if removed:
        out["notes"]["val_seeds_removed"] = (
            f"{removed}: failed the render checks, so removed from validation, not replaced "
            "(the rule in the val_seeds note)"
        )
    return out, removed


def prepare(out: Path, run: str, commit: str, cfg: dict, cfg_path: Path, work: Path,
            crashed: frozenset[int] = frozenset()) -> dict:
    m = read_manifest(out, run, commit, crashed)
    clips = train_clips(out, m)
    bad = differing(clips)
    if bad:
        raise ValueError(f"{len(bad)} files differ from the manifest, first: {bad[0]}")
    config, removed = run_config(cfg, set(clips))
    val = set(config["val_seeds"])
    listing = {
        "run": run,
        "render_commit": commit,
        "render_manifest_sha256": sha256(out / "manifest.json"),
        "config": str(cfg_path),
        "config_sha256": sha256(cfg_path),
        "train_seeds": sorted(s for s in clips if s not in val),
        "val_seeds": sorted(val),
        "val_seeds_removed": removed,
        "excluded_by_checks": [f for f in m["failed"] if f["split"] == "train"],
        "excluded_crashed": sorted(crashed),
        "files_checked": sum(len(f) for _, f in clips.values()),
    }
    work.mkdir(parents=True, exist_ok=True)
    (work / "clips.txt").write_text("".join(f"{d}\n" for d, _ in sorted(clips.values())))
    (work / "config.json").write_text(json.dumps(config, indent=2) + "\n")
    (work / "dataset-list.json").write_text(json.dumps(listing, indent=2) + "\n")
    return listing


def main(argv: list[str] | None = None) -> None:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("out", type=Path, help="the render's --out (manifest.json, <run>/train/seed<N>/)")
    ap.add_argument("--run", required=True)
    ap.add_argument("--commit", required=True, help="the pre-registered render commit (full sha)")
    ap.add_argument("--config", type=Path, required=True)
    ap.add_argument("--work", type=Path, required=True)
    ap.add_argument("--crashed", default="", help="comma-separated training seeds the render's owner "
                    "reported as crashed with no report; excluded, not replaced")
    a = ap.parse_args(argv)
    crashed = frozenset(int(x) for x in a.crashed.split(",") if x.strip())
    listing = prepare(a.out, a.run, a.commit, json.loads(a.config.read_text()), a.config, a.work, crashed)
    print(json.dumps({k: v if not isinstance(v, list) or k.endswith("removed") else len(v)
                      for k, v in listing.items()}, indent=2))


if __name__ == "__main__":
    main()
