"""The commands that render and validate a pre-registered set's clips, one line per clip.

    uv run python -m ninety.eval.set_commands docs/eval/set-piece-set.json --out runs/set-piece-set \\
        [--split test] > clips.sh
    tr '\\n' '\\0' < clips.sh | xargs -0 -n 1 -P 4 sh -c    # 4 at a time; -I would cap a line at 255 bytes

Reads the set's manifest (ninety/eval/set_piece_set.py, possession_set.py and shot_outcome_set.py
write it): each clip is rendered at its start and length with the set's render settings, into
<out>/<split>/seed<N>-<start frame>, then checked against the data contract. Run it at the
manifest's `render_commit`; the line refuses to run anywhere else. A clip already rendered and
valid is skipped, so the list can be re-run after an interruption.

    uv run python -m ninety.eval.set_commands docs/eval/set-piece-set.json --out runs/set-piece-set \\
        --split test --freeze docs/eval/set-piece-set-test-frozen.json

writes the split's frozen manifest: every clip's place, and for each one rendered, the hashes of its
answer key and images (ninety.render.checks.digest), its meta.json's and its renderer; a clip not yet
rendered is listed with a null digest, so the choice is frozen before the pixels are.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import shlex
from pathlib import Path

from ninety.render.checks import digest
from ninety.sim.engine import FPS


def clip_dir(out: Path, clip: dict) -> Path:
    return out / clip["split"] / f"seed{clip['seed']}-{round(clip['start'] * FPS)}"


def commands(manifest: dict, out: Path, split: str | None = None) -> list[str]:
    sets = " ".join(f"--set {shlex.quote(s)}" for s in manifest["render"]["set"])
    views = f" --views {manifest['render']['views']}" if manifest["render"].get("views") else ""
    at = (f'[ "$(git rev-parse HEAD)" = {manifest["render_commit"]} ] '
          '|| { echo "not at the render commit"; exit 1; }')
    lines = []
    for c in manifest["clips"]:
        if split and c["split"] != split:
            continue
        d = shlex.quote(str(clip_dir(out, c)))
        parent = shlex.quote(str(clip_dir(out, c).parent))
        render = (f"uv run ninety-render --seed {c['seed']} --start {c['start']} --seconds {c['seconds']} "
                  f"{sets}{views} --out {d}")
        lines.append(f"{at}; [ -f {d}/meta.json ] && uv run ninety-validate {d} >/dev/null || "
                     f"{{ mkdir -p {parent} && {render} > {d}.log 2>&1 "
                     f"&& uv run ninety-validate {d} >> {d}.log 2>&1 "
                     f"&& echo ok {d} || echo FAILED {d}; }}")
    return lines


def freeze(manifest: dict, out: Path, split: str) -> dict:
    """The split's clips with, for each one rendered, its hashes and renderer (else nulls)."""
    clips = []
    for c in manifest["clips"]:
        if c["split"] != split:
            continue
        d = clip_dir(out, c)
        row = {**c, "dir": str(d.relative_to(out)), "renderer": None, "digest": None}
        row["meta_json_sha256"] = None
        if (d / "meta.json").exists():
            row.update(renderer=json.loads((d / "clip.json").read_text())["renderer"], digest=digest(d),
                       meta_json_sha256=hashlib.sha256((d / "meta.json").read_bytes()).hexdigest())
        clips.append(row)
    return {"name": manifest["name"], "split": split, "render_commit": manifest["render_commit"],
            "render": manifest["render"], "clips": clips,
            "rendered": sum(1 for c in clips if c["digest"]), "count": len(clips)}


def main(argv: list[str] | None = None) -> None:
    ap = argparse.ArgumentParser(description="One render-and-validate command per clip of a set.")
    ap.add_argument("manifest", type=Path)
    ap.add_argument("--out", type=Path, required=True)
    ap.add_argument("--split", choices=("validation", "test"), default=None)
    ap.add_argument("--freeze", type=Path, default=None, help="write the split's frozen manifest here")
    a = ap.parse_args(argv)
    manifest = json.loads(a.manifest.read_text())
    if a.freeze:
        if not a.split:
            ap.error("--freeze needs --split")
        a.freeze.write_text(json.dumps(freeze(manifest, a.out, a.split), indent=1) + "\n")
        return
    for line in commands(manifest, a.out, a.split):
        print(line)


if __name__ == "__main__":
    main()
