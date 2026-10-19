"""Pack the Replay bundle the deployed viewer plays, the same bytes on every machine.

Replay mode serves one clip that has already been through the whole chain (ninety-e2e), so a view
costs no model call and no compute beyond serving files. The bundle is synthetic and public, so it
is published as a GitHub release asset; the Dockerfile downloads it by URL and refuses it unless its
SHA-256 matches the one pinned there (REPLAY_SHA256). The image never needs Azure Storage, so the
API's identity holds no role on the storage account that keeps the answer key
(infra/check_truth_sealed.py).

    uv run ninety-e2e <clip> --out runs/replay                # the bundle (docs: infra/README.md)
    python3 infra/replay.py pack runs/replay runs/replay.tar.gz   # prints the sha256 to pin
    python3 infra/replay.py unpack runs/replay.tar.gz <dir> <sha256>   # what the Dockerfile runs

`pack` refuses a bundle that holds a file the viewer does not read, so the answer key of a clip
(frames.jsonl, clip.json, meta.json) can never ride along into the public image.
"""

from __future__ import annotations

import gzip
import hashlib
import io
import json
import sys
import tarfile
from pathlib import Path

# Everything a format-1 bundle may hold (ninety/e2e.py): the viewer reads these and nothing else.
FILES = {"manifest.json", "cues.jsonl", "trace.json", "detections.jsonl", "events.jsonl", "facts.json",
         "video.webm"}
FRAMES = "frames/"  # JPEG footage, when the bundle was made with --frames


def members(bundle: Path) -> list[Path]:
    files = sorted(p for p in bundle.rglob("*") if p.is_file())
    bad = [p.relative_to(bundle).as_posix() for p in files
           if p.relative_to(bundle).as_posix() not in FILES
           and not (p.relative_to(bundle).as_posix().startswith(FRAMES) and p.suffix == ".jpg")]
    if bad:
        raise SystemExit(f"not a viewer file, refusing to publish: {', '.join(bad)}")
    manifest = json.loads((bundle / "manifest.json").read_text())
    if manifest.get("format") != 1:
        raise SystemExit(f"bundle format {manifest.get('format')}, expected 1")
    return files


def pack(bundle: Path, out: Path) -> str:
    raw = io.BytesIO()
    with tarfile.open(fileobj=raw, mode="w", format=tarfile.PAX_FORMAT) as tar:
        for f in members(bundle):
            info = tarfile.TarInfo(f.relative_to(bundle).as_posix())
            info.size, info.mode, info.mtime = f.stat().st_size, 0o644, 0
            with f.open("rb") as fh:
                tar.addfile(info, fh)
    out.write_bytes(gzip.compress(raw.getvalue(), compresslevel=9, mtime=0))
    return hashlib.sha256(out.read_bytes()).hexdigest()


def unpack(archive: Path, dest: Path, sha256: str) -> None:
    data = archive.read_bytes()
    got = hashlib.sha256(data).hexdigest()
    if got != sha256:
        raise SystemExit(f"{archive}: sha256 {got}, expected {sha256}")
    dest.mkdir(parents=True, exist_ok=True)
    with tarfile.open(fileobj=io.BytesIO(data)) as tar:
        tar.extractall(dest, filter="data")
    members(dest)  # the same rule on the way in


def main() -> None:
    args = sys.argv[1:]
    if len(args) == 3 and args[0] == "pack":
        print(pack(Path(args[1]), Path(args[2])))
    elif len(args) == 4 and args[0] == "unpack":
        unpack(Path(args[1]), Path(args[2]), args[3])
    else:
        raise SystemExit(__doc__)


if __name__ == "__main__":
    main()
