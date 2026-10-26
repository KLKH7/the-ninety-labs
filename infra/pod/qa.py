"""Quality check of a rendered dataset before it is uploaded: contact sheets for a human to look at,
and a summary of what the run made.

    uv run python infra/pod/qa.py --plan PLAN --out OUT

Which clips get a sheet is fixed by the plan, not by looking: QA_SAMPLE training clips drawn with
the plan's QA_SEED from the clips that passed, plus every training clip the checks flagged. Test
clips are never drawn or shown (the test set is rendered only); a flagged test clip is listed by
seed and failed check, nothing more.

Writes OUT/qa/summary.json and OUT/qa/sheets/<split>-seed<N>.jpg.
"""

from __future__ import annotations

import argparse
import importlib.util
import json
import random
from pathlib import Path

from PIL import Image, ImageDraw

QA_SAMPLE = 20
QA_SEED = 20261021  # fixed before any clip of the run was rendered (docs/eval/dataset-v2-freeze.json)
FRAMES_PER_SHEET = 8  # evenly spaced through the clip, in two rows of four
TILE = (480, 270)

_spec = importlib.util.spec_from_file_location("pod_render", Path(__file__).with_name("render.py"))
pod = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(pod)


def reports(plan: dict, out: Path) -> dict:
    """Every report the run wrote, by (split, seed)."""
    found = {}
    for split in pod.SPLITS:
        for seed, _ in pod.expand(plan, split):
            rp = pod.report_path(out, split, seed)
            if rp.exists():
                found[(split, seed)] = json.loads(rp.read_text())
    return found


def chosen(plan: dict, found: dict) -> tuple[list[int], list[int]]:
    """The training seeds to look at: a seeded sample of the passing ones, and every flagged one."""
    passed = sorted(s for (sp, s), r in found.items() if sp == "train" and all(r["passed"].values()))
    flagged = sorted(s for (sp, s), r in found.items() if sp == "train" and not all(r["passed"].values()))
    sample = sorted(random.Random(QA_SEED).sample(passed, min(QA_SAMPLE, len(passed))))
    return sample, flagged


def sheet(clip_dir: Path, title: str) -> Image.Image:
    images = sorted((clip_dir / "images").glob("*.jpg"))
    n = len(images)
    k = FRAMES_PER_SHEET - 1
    picks = [images[round(i * (n - 1) / k)] for i in range(FRAMES_PER_SHEET)] if n else []
    w, h = TILE
    out = Image.new("RGB", (4 * w, 2 * h + 28), "black")
    draw = ImageDraw.Draw(out)
    draw.text((8, 8), title, fill="white")
    for i, f in enumerate(picks):
        tile = Image.open(f).convert("RGB").resize(TILE)
        ImageDraw.Draw(tile).text((6, 6), f.name, fill="white")
        out.paste(tile, ((i % 4) * w, 28 + (i // 4) * h))
    return out


def totals(found: dict) -> dict:
    rows = list(found.values())

    def worst(key):
        xs = [r["projection"][key]["max"] for r in rows if r["projection"][key]["max"] is not None]
        return max(xs) if xs else None

    return {
        "clips_checked": len(rows),
        "passed": sum(all(r["passed"].values()) for r in rows),
        "ball_projection_max_px": worst("ball_px"),
        "keypoint_projection_max_px": worst("keypoint_px"),
        "player_feet_outside_box": sum(r["projection"]["player_foot_outside_box"] for r in rows),
        "player_feet_checked": sum(r["projection"]["player_foot_checked"] for r in rows),
        "clips_with_label_problems": sum(not r["labels"]["ok"] for r in rows),
        "clips_failing_the_data_contract": sum(bool(r["data_contract"]) for r in rows),
    }


def main(argv: list[str] | None = None) -> None:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--plan", type=Path, required=True)
    ap.add_argument("--out", type=Path, required=True)
    a = ap.parse_args(argv)
    plan = json.loads(a.plan.read_text())
    found = reports(plan, a.out)
    sample, flagged = chosen(plan, found)
    sheets = a.out / "qa" / "sheets"
    sheets.mkdir(parents=True, exist_ok=True)
    for seed in sample + flagged:
        r = found[("train", seed)]
        bad = sorted(k for k, v in r["passed"].items() if not v)
        label = f"train seed {seed}  " + ("FLAGGED: " + ", ".join(bad) if bad else "sampled, passed")
        d = pod.clip_dir(a.out, plan["run"], seed, "train")
        sheet(d, label).save(sheets / f"train-seed{seed}.jpg", quality=85)
    excluded = [{"split": sp, "seed": s, "failed": sorted(k for k, v in r["passed"].items() if not v)}
                for (sp, s), r in sorted(found.items()) if not all(r["passed"].values())]
    missing = [{"split": sp, "seed": s} for sp in pod.SPLITS for s, _ in pod.expand(plan, sp)
               if (sp, s) not in found]
    manifest_ok = (a.out / "manifest.json").exists() and not pod.verify(a.out)
    summary = {
        "run": plan["run"],
        "sheets": {"sampled": sample, "flagged": flagged, "qa_seed": QA_SEED, "folder": str(sheets)},
        "excluded": excluded,
        "missing": missing,
        "render_check": {sp: totals({k: v for k, v in found.items() if k[0] == sp}) for sp in pod.SPLITS},
        "manifest_verified": manifest_ok,
    }
    (a.out / "qa" / "summary.json").write_text(json.dumps(summary, indent=1))
    print(json.dumps({k: summary[k] for k in ("excluded", "missing", "render_check", "manifest_verified")},
                     indent=1))


if __name__ == "__main__":
    main()
