"""Measure the views' position error, then grade the broadcast -> tactical association, on validation.

    uv run python -m ninety.eval.association error --runs <dir> --clips <dir> --seeds 108,109 --out F
    uv run python -m ninety.eval.association grade --runs <dir> --clips <dir> --seeds 108,109 --out F

`--runs` holds `seed<N>/broadcast/` and `seed<N>/views/`, the two live_job runs of each clip;
`--clips` the rendered clips, `seed<N>/frames.jsonl` and `seed<N>/views/<name>/frames.jsonl`.
Grading only (AGENTS.md: the answer key is for training labels and grading); a test seed is
refused. Two steps, in this order, fixed before either was run (docs/eval/association.md):

- **error**: the views' players' pitch-position error, by the rule that set RIVAL_M for the
  broadcast (ninety/eval/pitch_score.py: each placed detection paired with the true player whose
  box in that view it overlaps, IoU 0.5), pooled over both views of every clip; its 90th
  percentile becomes ninety/vision/join.py's VIEWS_ERROR_M.
- **grade**: join each clip (ninety.vision.join, with the MATCH_M in the code), then give every
  tracked player of each camera his true player: the one nearest the track on average over the
  frames it was seen, teams ignored (each camera's team read is its own). A broadcast track's
  association is right when its tactical track has the same true player. Reported: how many
  broadcast tracks, and how many of their tracked frames, were associated (the rate), and how
  many associations were wrong (the error), each with a Wilson 95% interval.
"""

from __future__ import annotations

import argparse
import json
import math
import statistics
from pathlib import Path

from ninety.eval.attribution_derive import refused
from ninety.eval.event_score import git_commit, wilson
from ninety.eval.pitch_score import _summary, errors
from ninety.vision import join as jn
from ninety.vision import track as tr


def _frames(path: Path) -> list[dict]:
    return [json.loads(x) for x in path.read_text().splitlines() if x.strip()]


def views_error(runs: Path, clips: Path, seeds: list[int]) -> dict:
    pooled, by = [], {}
    for s in seeds:
        mine = []
        for v in json.loads((runs / f"seed{s}" / "views" / "run.json").read_text())["views"]:
            obs = tr.read_observations(runs / f"seed{s}" / "views" / "views" / v / "observations.jsonl")
            players, _, _, _ = errors(_frames(clips / f"seed{s}" / "views" / v / "frames.jsonl"), obs)
            mine += players
        by[s] = _summary(mine)
        pooled += mine
    return {"pooled": _summary(pooled), "by_seed": by}


def true_players(tracked: list[dict], truth: dict[int, dict]) -> dict[str, tuple[str, float]]:
    """Each track -> (the true player nearest it on average over its frames, that mean in m)."""
    sums: dict[str, dict[str, list[float]]] = {}
    for f in tracked:
        for p in f["players"]:
            for q in truth[f["frame"]]["players"]:
                sums.setdefault(p["id"], {}).setdefault(q["id"], []).append(
                    math.dist((p["x"], p["y"]), (q["x"], q["y"])))
    out = {}
    for pid, by in sums.items():
        full = max(map(len, by.values()))  # true players on the pitch in every frame of the track
        out[pid] = min(((q, statistics.fmean(d)) for q, d in by.items() if len(d) == full),
                       key=lambda x: (x[1], x[0]))
    return out


def grade_one(seed: int, runs: Path, clips: Path) -> dict:
    out = runs / f"seed{seed}" / "joined"
    jn.join(runs / f"seed{seed}" / "broadcast", runs / f"seed{seed}" / "views", out)
    assoc = json.loads((out / "association.json").read_text())["tracks"]
    b = jn.read_run(runs / f"seed{seed}" / "broadcast")["tracked"]["frames"]
    v = json.loads((out / "tracked.json").read_text())["frames"]  # the joined: the ids association.json names
    truth = {f["frame"]: f for f in _frames(clips / f"seed{seed}" / "frames.jsonl")}
    tb, tv = true_players(b, truth), true_players(v, truth)
    rows = []
    for pid, a in sorted(assoc.items()):
        row = {"broadcast": pid, "frames": a["frames"], "track": a["track"],
               "confidence": a["confidence"], "true": tb[pid][0], "offset_m": round(tb[pid][1], 3)}
        if a["track"]:
            row["track_true"] = tv[a["track"]][0]
            row["right"] = row["track_true"] == row["true"]
        rows.append(row)
    return {"seed": seed, "tracks": rows}


def summary(clips: list[dict]) -> dict:
    rows = [r for c in clips for r in c["tracks"]]
    n, frames = len(rows), sum(r["frames"] for r in rows)
    done = [r for r in rows if r["track"]]
    wrong = [r for r in done if not r["right"]]
    done_frames = sum(r["frames"] for r in done)
    return {
        "broadcast_tracks": n,
        "associated": len(done), "rate": round(len(done) / n, 3) if n else None,
        "rate_ci": wilson(len(done), n),
        "frames": frames, "associated_frames": done_frames,
        "frame_rate": round(done_frames / frames, 3) if frames else None,
        "wrong": len(wrong), "error": round(len(wrong) / len(done), 3) if done else None,
        "error_ci": wilson(len(wrong), len(done)),
        "wrong_frames": sum(r["frames"] for r in wrong),
    }


def main(argv: list[str] | None = None) -> None:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("step", choices=["error", "grade"])
    ap.add_argument("--runs", type=Path, required=True)
    ap.add_argument("--clips", type=Path, required=True)
    ap.add_argument("--seeds", required=True, help="comma-separated validation seeds")
    ap.add_argument("--out", type=Path, required=True)
    a = ap.parse_args(argv)
    seeds = [int(s) for s in a.seeds.split(",")]
    if any(refused(s) for s in seeds):
        raise SystemExit(f"refused: {[s for s in seeds if refused(s)]} are test or reserved seeds")
    # A clip whose live run failed (the camera could not be placed on any frame) is reported, not
    # used: the error step needs the views' run of it, grading both cameras'.
    needs = ("views",) if a.step == "error" else ("broadcast", "views")  # the error is the views' own
    ran = [s for s in seeds if all((a.runs / f"seed{s}" / c / "run.json").is_file() for c in needs)]
    body = {"step": a.step, "seeds": ran, "not_run": [s for s in seeds if s not in ran],
            "commit": git_commit()}
    seeds = ran
    if a.step == "error":
        body |= views_error(a.runs, a.clips, seeds)
    else:
        per = [grade_one(s, a.runs, a.clips) for s in seeds]
        body |= {"match_m": round(jn.MATCH_M, 3), "broadcast_error_m": jn.BROADCAST_ERROR_M,
                 "views_error_m": jn.VIEWS_ERROR_M, "pooled": summary(per),
                 "by_seed": {c["seed"]: summary([c]) for c in per}, "clips": per}
    a.out.write_text(json.dumps(body, indent=1) + "\n")
    print(json.dumps(body.get("pooled"), indent=1))


if __name__ == "__main__":
    main()
