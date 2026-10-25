"""Re-derive the camera trust test's height band on current renders, per camera kind
(docs/eval/ball-three-cams/PLAN.md, Deviations; the rule is docs/eval/detector-plan.md's step B).

    uv run python -m ninety.eval.band_derive --clips <dir> --obs <dir> --seeds ... --out <json>

Grading data, read offline: each clip's frames.jsonl (the broadcast's true camera) and each view's
(`views/<name>/frames.jsonl`). Observations, made by the live path with any band (the band does not
change the fit or the ratio), are read from `<obs>/broadcast/seed<N>.jsonl` and
`<obs>/view-<name>-<detector>/seed<N>.jsonl`.

For each camera kind, `detector_derive.gates`: every frame's ground mapping error through its
estimated camera against the true one, its height ratio, and the band: the 1st to 99th percentile of
the ratio on frames whose error is within 1.0 m. The same function and rule that set today's band,
run on today's renders. A test seed is refused. A band carries the look it was measured on (lesson
230): the clips' renderer versions (clip.json) are recorded, and clips of two looks are refused.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from ninety.eval.attribution_derive import refused
from ninety.eval.detector_derive import gates
from ninety.eval.vision_score import load_jsonl


def _frames(path: Path) -> dict[int, dict]:
    return {int(r["frame"]): r for r in load_jsonl(path)}


def derive(clips: Path, obs: Path, seeds: list[int]) -> dict:
    kinds: dict[str, list] = {"broadcast": [], "fixed": []}
    looks = set()
    for seed in seeds:
        if refused(seed):
            raise SystemExit(f"test seed {seed}: the band is derived on validation clips only")
        clip = clips / f"seed{seed}"
        looks.add(_renderer(clip))
        if len(looks - {None}) > 1:
            raise SystemExit(f"seed {seed}: clips of renderers {sorted(looks - {None})}: one band per look")
        if (obs / "broadcast" / f"seed{seed}.jsonl").exists():  # each kind may be run on its own
            kinds["broadcast"].append((seed, load_jsonl(obs / "broadcast" / f"seed{seed}.jsonl"),
                                       _frames(clip / "frames.jsonl")))
        for d in sorted(obs.glob("view-*")):
            view = _view(d.name, clip)
            if (d / f"seed{seed}.jsonl").exists():
                kinds["fixed"].append((seed, load_jsonl(d / f"seed{seed}.jsonl"),
                                       _frames(clip / "views" / view / "frames.jsonl")))
    look = sorted(looks - {None})
    return {"seeds": seeds, "renderer": look[0] if look else None} | {
        k: gates(v) for k, v in kinds.items() if v}


def _renderer(clip: Path) -> str | None:
    """The renderer version the clip was drawn with (clip.json), read offline; None without one."""
    meta = clip / "clip.json"
    return json.loads(meta.read_text()).get("renderer", {}).get("version") if meta.exists() else None


def _view(folder: str, clip: Path) -> str:
    """The view a `view-<name>-<detector>` folder holds: the longest of the clip's view names it
    starts with (view and detector names both hold dashes)."""
    names = [p.name for p in (clip / "views").iterdir() if p.is_dir()]
    rest = folder.removeprefix("view-")
    found = sorted((n for n in names if rest.startswith(n + "-")), key=len)
    if not found:
        raise SystemExit(f"{folder}: names no view of {clip}")
    return found[-1]


def main(argv: list[str] | None = None) -> None:
    ap = argparse.ArgumentParser(description="Re-derive the height band per camera kind.")
    ap.add_argument("--clips", type=Path, required=True)
    ap.add_argument("--obs", type=Path, required=True)
    ap.add_argument("--seeds", type=int, nargs="+", required=True)
    ap.add_argument("--out", type=Path, required=True)
    a = ap.parse_args(argv)
    report = derive(a.clips, a.obs, a.seeds)
    a.out.write_text(json.dumps(report, indent=2) + "\n")
    print(json.dumps({k: v["band"] for k, v in report.items() if k not in ("seeds", "renderer")}))


if __name__ == "__main__":
    main()
