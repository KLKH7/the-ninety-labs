"""Pack the match package the deployed API serves Ask, the wind map and the player card from.

A served clip (ninety/match/tracking.py, `served_clips`) is a folder under NINETY_SERVED_DIR named
for the clip, holding what the e2e run made: tracked.json (positions from tracking the video),
detected.jsonl (detected events), clip.json (the clip's seed, timeline and club codes) and
scorebug.jsonl when the scorebug was read, and insights.json: the clip's MatchInsights, built offline
by ninety.intel.match_insights with the Player ID feed and the camera join, which the API cannot
rebuild at runtime (it has neither), so per-player stats and the feed's names reach Ask. The
Dockerfile copies it to NINETY_MATCH_DIR/insights/<clip>.json, which match_server.insights_of reads
first. Like the Replay bundle (infra/replay.py) it is synthetic
and public, published as a release asset, and pinned by SHA-256 in the Dockerfile.

    python3 infra/served.py pack <package> <clip id> runs/served.tar.gz [events] [insights]  # sha256
    python3 infra/served.py unpack runs/served.tar.gz <served dir> <sha256>   # what the Dockerfile runs

Nothing of the answer key can ride along. Only the four files are taken. tracked.json must hold
tracked frames only (no simulator positions). detected.jsonl must hold detected events only
(source vision). clip.json is cut to the keys a served clip reads. scorebug.jsonl must hold readings
only. insights.json must be this clip's. `unpack` checks the same.
"""

from __future__ import annotations

import gzip
import hashlib
import io
import json
import re
import sys
import tarfile
from pathlib import Path

FILES = ("tracked.json", "detected.jsonl", "clip.json", "scorebug.jsonl", "insights.json")
REQUIRED = ("tracked.json", "detected.jsonl", "clip.json")
# What a served clip reads from clip.json: its id, seed (the team sheets), timeline and club codes.
CLIP_KEYS = ("clip_id", "seed", "fps", "frames", "t_start", "t_end", "segments", "params", "source")
PARAM_KEYS = ("width", "height", "fps", "home_code", "away_code")
CLIP_ID = re.compile(r"[A-Za-z0-9_-]+")


def check(folder: Path) -> None:
    """The rules above, on a package folder; SystemExit names the first broken one."""
    names = sorted(p.name for p in folder.iterdir())
    extra = [n for n in names if n not in FILES]
    missing = [n for n in REQUIRED if n not in names]
    if extra or missing:
        raise SystemExit(f"{folder}: not a served package (extra {extra}, missing {missing})")
    frames = json.loads((folder / "tracked.json").read_text())["frames"]
    if not frames or any(f.get("source") != "tracked" for f in frames):
        raise SystemExit(f"{folder}/tracked.json: every frame must be tracked, none the simulator's")
    for n, line in enumerate((folder / "detected.jsonl").read_text().splitlines(), 1):
        if line.strip() and json.loads(line).get("source") != "vision":
            raise SystemExit(f"{folder}/detected.jsonl line {n}: not a detected event (source vision)")
    clip = json.loads((folder / "clip.json").read_text())
    if set(clip) - set(CLIP_KEYS) or set(clip.get("params", {})) - set(PARAM_KEYS):
        raise SystemExit(f"{folder}/clip.json: keys beyond what a served clip reads")
    if (folder / "scorebug.jsonl").exists():
        for n, line in enumerate((folder / "scorebug.jsonl").read_text().splitlines(), 1):
            if line.strip() and json.loads(line).get("type") not in ("score_read", "score_change"):
                raise SystemExit(f"{folder}/scorebug.jsonl line {n}: not a scorebug reading")
    if (folder / "insights.json").exists():
        insights = json.loads((folder / "insights.json").read_text())
        if not isinstance(insights, dict) or insights.get("clip") != folder.name:
            raise SystemExit(f"{folder}/insights.json: not this clip's MatchInsights")


def pack(package: Path, clip: str, out: Path, events: Path | None = None,
         insights: Path | None = None) -> str:
    """The package's served files as <clip>/... in a repeatable tar.gz; returns its sha256.
    `events` replaces the package's detected.jsonl (e.g. the events the ID feed sided); `insights`
    adds the clip's offline-built insights.json."""
    if not CLIP_ID.fullmatch(clip) or re.fullmatch(r"seed\d+", clip):
        raise SystemExit(f"{clip!r}: a served clip is a plain folder name, not a simulator match's")
    meta = json.loads((package / "clip.json").read_text())
    body = {"clip.json": json.dumps({k: meta[k] for k in CLIP_KEYS if k in meta}
                                    | {"params": {k: v for k, v in meta.get("params", {}).items()
                                                  if k in PARAM_KEYS}}).encode()}
    for name in ("tracked.json", "scorebug.jsonl"):
        if (package / name).exists():
            body[name] = (package / name).read_bytes()
    body["detected.jsonl"] = (events or package / "detected.jsonl").read_bytes()
    if insights is not None:
        body["insights.json"] = insights.read_bytes()
    staging = out.parent / f".{out.name}.check" / clip
    staging.mkdir(parents=True, exist_ok=True)
    for name, data in body.items():
        (staging / name).write_bytes(data)
    check(staging)
    raw = io.BytesIO()
    with tarfile.open(fileobj=raw, mode="w", format=tarfile.PAX_FORMAT) as tar:
        for name in sorted(body):
            info = tarfile.TarInfo(f"{clip}/{name}")
            info.size, info.mode, info.mtime = len(body[name]), 0o644, 0
            tar.addfile(info, io.BytesIO(body[name]))
    out.write_bytes(gzip.compress(raw.getvalue(), compresslevel=9, mtime=0))
    for name in body:
        (staging / name).unlink()
    staging.rmdir()
    staging.parent.rmdir()
    return hashlib.sha256(out.read_bytes()).hexdigest()


def unpack(archive: Path, dest: Path, sha256: str) -> None:
    data = archive.read_bytes()
    got = hashlib.sha256(data).hexdigest()
    if got != sha256:
        raise SystemExit(f"{archive}: sha256 {got}, expected {sha256}")
    dest.mkdir(parents=True, exist_ok=True)
    with tarfile.open(fileobj=io.BytesIO(gzip.decompress(data))) as tar:
        tar.extractall(dest, filter="data")
    for folder in dest.iterdir():
        if not folder.is_dir() or not CLIP_ID.fullmatch(folder.name):
            raise SystemExit(f"{folder}: not a served clip folder")
        check(folder)


def main() -> None:
    args = sys.argv[1:]
    if len(args) in (4, 5, 6) and args[0] == "pack":
        extra = [Path(a) if a else None for a in args[4:]] + [None, None]
        print(pack(Path(args[1]), args[2], Path(args[3]), extra[0], extra[1]))
    elif len(args) == 4 and args[0] == "unpack":
        unpack(Path(args[1]), Path(args[2]), args[3])
    else:
        raise SystemExit(__doc__)


if __name__ == "__main__":
    main()
