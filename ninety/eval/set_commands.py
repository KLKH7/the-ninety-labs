"""The commands that render and validate a pre-registered set's clips, one line per clip.

    uv run python -m ninety.eval.set_commands docs/eval/set-piece-set.json --out runs/set-piece-set \\
        [--split test] > clips.sh
    tr '\\n' '\\0' < clips.sh | xargs -0 -n 1 -P 4 sh -c    # 4 at a time; -I would cap a line at 255 bytes

Reads the set's manifest (ninety/eval/set_piece_set.py, possession_set.py and shot_outcome_set.py
write it): each clip is rendered at its start and length with the set's render settings, into
<out>/<split>/seed<N>-<start frame>, then checked against the data contract. Run it at the
manifest's `render_commit`; the line refuses to run anywhere else. A clip already rendered and
valid is skipped, so the list can be re-run after an interruption.
"""

from __future__ import annotations

import argparse
import json
import shlex
from pathlib import Path

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


def main(argv: list[str] | None = None) -> None:
    ap = argparse.ArgumentParser(description="One render-and-validate command per clip of a set.")
    ap.add_argument("manifest", type=Path)
    ap.add_argument("--out", type=Path, required=True)
    ap.add_argument("--split", choices=("validation", "test"), default=None)
    a = ap.parse_args(argv)
    for line in commands(json.loads(a.manifest.read_text()), a.out, a.split):
        print(line)


if __name__ == "__main__":
    main()
