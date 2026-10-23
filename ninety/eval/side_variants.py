"""Step A's side-naming variants, compared on validation clips (docs/eval/detector-plan.md, Outcome).

    uv run python -m ninety.eval.side_variants --clips <render run v1>/train --observations <dir>

Each variant is a kit clustering swapped into ninety/vision/track.py for the run, then measured the
same way: side accuracy per track (frames), its coverage, and teams right on matched passes.
Development only: it refuses test seeds (ninety/eval/detector_derive.py, `read`).
"""

from __future__ import annotations

import argparse
import math
from pathlib import Path

from ninety.eval import attribution_score as at
from ninety.eval import detector_derive as dd
from ninety.vision import track as tr

SEEDS = (108, 109, 114, 115, 116, 120, 121, 122, 2041, 2042, 2043, 2045, 3041, 3042, 3045)


def farthest(pts):
    """Today's start: the two tracks whose kits are farthest apart."""
    a, b = max(((p, q) for p in pts for q in pts), key=lambda pq: tr._dist(pq[0][0], pq[1][0]))
    return a[0], b[0]


def axis_split(trim: bool):
    """A start from the cut along the main axis that leaves the least weighted spread on each side,
    optionally after trimming points beyond OUTLIER_FACTOR median deviations (for the start only)."""
    def start(pts):
        m = tr._mean(pts)
        dim = len(m)
        cov = [[sum(w * (c[i] - m[i]) * (c[j] - m[j]) for c, w in pts) for j in range(dim)]
               for i in range(dim)]
        axis = [1.0] * dim
        for _ in range(50):
            nxt = [sum(cov[i][j] * axis[j] for j in range(dim)) for i in range(dim)]
            norm = math.sqrt(sum(v * v for v in nxt))
            if norm == 0:
                break
            axis = [v / norm for v in nxt]
        proj = sorted((sum((c[k] - m[k]) * axis[k] for k in range(dim)), w, c) for c, w in pts)
        if trim:
            total = sum(w for _, w, _ in proj)

            def wmedian(vals):
                acc = 0.0
                for v, w in sorted(vals):
                    acc += w
                    if acc >= total / 2:
                        return v
            med = wmedian([(v, w) for v, w, _ in proj])
            mad = wmedian([(abs(v - med), w) for v, w, _ in proj])
            proj = [x for x in proj if abs(x[0] - med) <= tr.OUTLIER_FACTOR * max(mad, 1e-9)] or proj

        def spread(g):
            total = sum(w for _, w, _ in g)
            mu = sum(v * w for v, w, _ in g) / total
            return sum(w * (v - mu) * (v - mu) for v, w, _ in g)
        k = min(range(1, len(proj)), key=lambda k: spread(proj[:k]) + spread(proj[k:]))
        return tr._mean([(c, w) for _, w, c in proj[:k]]), tr._mean([(c, w) for _, w, c in proj[k:]])
    return start


def clustering(start, features):
    """track.two_colours with this start and these features (the rest as in track.py)."""
    def two_colours(tracks):
        best = None
        for feature in features:
            pts = [(c, len(t.frames)) for t in tracks if len(t.frames) >= tr.MIN_COLOUR_FRAMES
                   and (c := tr.kit(t, feature)) is not None]
            if len(pts) < 2:
                return None
            ca, cb = start(pts)
            for _ in range(20):
                ga = [(c, w) for c, w in pts if tr._dist(c, ca) <= tr._dist(c, cb)]
                gb = [(c, w) for c, w in pts if tr._dist(c, ca) > tr._dist(c, cb)]
                if not ga or not gb:
                    break
                na, nb = tr._mean(ga), tr._mean(gb)
                if (na, nb) == (ca, cb):
                    break
                ca, cb = na, nb
            spread = sorted(min(tr._dist(c, ca), tr._dist(c, cb)) for c, _ in pts)
            typical = max(spread[len(spread) // 2], tr.NOISE[feature])
            core = [(c, w) for c, w in pts
                    if min(tr._dist(c, ca), tr._dist(c, cb)) <= tr.OUTLIER_FACTOR * typical]
            ga = [(c, w) for c, w in core if tr._dist(c, ca) <= tr._dist(c, cb)]
            gb = [(c, w) for c, w in core if tr._dist(c, ca) > tr._dist(c, cb)]
            if ga and gb:
                ca, cb = tr._mean(ga), tr._mean(gb)
            score = tr.separation(core or pts, ca, cb, tr.NOISE[feature])
            if best is None or score > best[0]:
                best = (score, feature, ca, cb)
        return best[1:]
    return two_colours


VARIANTS = {
    "v0 main: chromaticity, farthest start": clustering(farthest, ("chromaticity",)),
    "v1 adopted: feature choice, farthest start": clustering(farthest, tr.FEATURES),
    "v2 feature choice, trimmed axis start": clustering(axis_split(True), tr.FEATURES),
    "v3 chromaticity, trimmed axis start": clustering(axis_split(True), ("chromaticity",)),
    "v4 chromaticity, axis start": clustering(axis_split(False), ("chromaticity",)),
    "v5 feature choice, axis start": clustering(axis_split(False), tr.FEATURES),
}


def measure(clips: Path, observations: Path) -> dict:
    right = frames = every = passes = passes_right = 0
    per = {}
    for seed in SEEDS:
        got = dd.read(seed, clips, observations)
        if got is None:
            continue
        a = dd.sides(got[0], got[1])
        right, frames, every = right + a["right_frames"], frames + a["frames"], every + a["all_frames"]
        m = [p for p in at.clip(seed, clips, [observations])["pairs"] if p["type"] == "pass"]
        passes += len(m)
        passes_right += sum(p["team"]["truth"] == p["team"]["detected"] for p in m)
        if a["all_frames"]:
            acc = round(a["accuracy"], 3) if a["accuracy"] is not None else None
            per[seed] = (a["naming"].get("feature"), acc, a["naming"].get("vote_margin"))
    return {"accuracy": right / frames, "coverage": frames / every, "passes": f"{passes_right}/{passes}",
            "per_clip": per}


def main(argv: list[str] | None = None) -> None:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--clips", type=Path, required=True)
    ap.add_argument("--observations", type=Path, required=True)
    a = ap.parse_args(argv)
    original = tr.two_colours
    try:
        for name, fn in VARIANTS.items():
            tr.two_colours = fn
            r = measure(a.clips, a.observations)
            print(f"{name}: accuracy {r['accuracy']:.3f}, coverage {r['coverage']:.3f}, "
                  f"passes {r['passes']}; "
                  + " ".join(f"{s}:{f}:{acc}:vote {v}" for s, (f, acc, v) in r["per_clip"].items()))
    finally:
        tr.two_colours = original


if __name__ == "__main__":
    main()
