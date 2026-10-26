"""Variant S of the sides plan: the kit and where a player stands, combined
(docs/eval/sides-tactical/SPATIAL-PLAN.md, fixed before any S number).

    uv run python -m ninety.eval.sides_spatial --clips <dir> --obs <T1-fused dir> --seeds ... --out <json>

Each outfield track's three pieces of evidence that it is home (kit, depth, kick-off) come from the
observations only (`features`, no truth). The weights of their logistic combination are fitted on
validation tracks against their true team (offline, `fit`), leaving each clip out of the fit that
judges it. A test seed is refused.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import numpy as np

from ninety.eval.attribution_derive import refused
from ninety.eval.sides_tactical import _pair, _truth, summarise
from ninety.vision import sides
from ninety.vision import track as tr
from ninety.vision.tracked_frames import MIN_TRACK_FRAMES

RIDGE = 1e-6  # keeps the fit finite when a feature never varies (design)
FEATURES = ("kit", "depth", "kickoff")


def features(rows: list[dict]) -> tuple[list[tr.Track], dict[int, list[float]]]:
    """The clip's tracks (sided by `assign_teams`) and each outfield track's evidence, computed by the
    live path's own code (ninety/vision/sides.py)."""
    tracks = tr.track_players(rows)
    info = tr.assign_teams(tracks)
    return tracks, sides.features(tracks, info, rows)


def true_teams(tracks: list[tr.Track], truth: dict[int, list[dict]]) -> dict[int, str | None]:
    """Each track's true team, as sides_tactical pairs it (the team of most of its paired frames,
    None under half)."""
    by_frame: dict[int, list[tuple[int, float, float]]] = {}
    for k, t in enumerate(tracks):
        for f, (x, y) in zip(t.frames, t.xy, strict=True):
            by_frame.setdefault(f, []).append((k, x, y))
    votes: dict[int, dict[str, int]] = {}
    for f, dets in by_frame.items():
        for k, p in _pair(dets, truth.get(f, [])).items():
            votes.setdefault(k, {}).setdefault(p["team"], 0)
            votes[k][p["team"]] += 1
    out = {}
    for k, t in enumerate(tracks):
        v = votes.get(k, {})
        out[t.id] = max(v, key=v.get) if v and sum(v.values()) * 2 >= len(t.frames) else None
    return out


def fit(X: np.ndarray, y: np.ndarray, w: np.ndarray, iters: int = 50) -> np.ndarray:
    """Weighted logistic regression by Newton's method: [w0, w1, w2, w3]."""
    A = np.c_[np.ones(len(X)), X]
    beta = np.zeros(A.shape[1])
    for _ in range(iters):
        p = 1 / (1 + np.exp(-A @ beta))
        g = A.T @ (w * (y - p)) - RIDGE * beta
        H = (A * (w * p * (1 - p))[:, None]).T @ A + RIDGE * np.eye(len(beta))
        step = np.linalg.solve(H, g)
        beta += step
        if np.abs(step).max() < 1e-9:
            break
    return beta


def predict(beta: np.ndarray, x: list[float]) -> float:
    """The live path's own probability (sides.p_home) with these weights."""
    return sides.p_home(x, tuple(float(b) for b in beta))


def calibration_error(rows: list[dict]) -> float:
    """The frame-weighted mean over the plan's bins of |accuracy - mean confidence|."""
    from ninety.eval.sides_tactical import BINS

    total = err = 0.0
    for lo, hi in BINS:
        b = [r for r in rows if lo <= r["confidence"] < hi]
        n = sum(r["frames"] for r in b)
        if not n:
            continue
        acc = sum(r["frames"] for r in b if r["team"] == r["true_team"]) / n
        conf = sum(r["confidence"] * r["frames"] for r in b) / n
        total += n
        err += n * abs(acc - conf)
    return round(err / total, 4) if total else 0.0


def run(clips: Path, obs: Path, seeds: list[int]) -> dict:
    data = {}
    for seed in seeds:
        if refused(seed):
            raise SystemExit(f"test seed {seed}: sides are measured on validation clips here")
        rows = tr.read_observations(obs / f"seed{seed}.jsonl")
        tracks, feats = features(rows)
        truth = true_teams(tracks, _truth(clips / f"seed{seed}"))
        data[seed] = [(t, feats.get(t.id), truth[t.id]) for t in tracks if len(t.frames) >= MIN_TRACK_FRAMES]
    weights_by_clip = {}
    scored: dict[int, list[dict]] = {}
    for seed in seeds:
        train = [(f, tt, len(t.frames)) for s in seeds if s != seed for t, f, tt in data[s]
                 if f is not None and tt is not None]
        X = np.array([f for f, _, _ in train])
        y = np.array([1.0 if tt == "home" else 0.0 for _, tt, _ in train])
        w = np.array([n for _, _, n in train], dtype=float)
        beta = fit(X, y, w)
        weights_by_clip[seed] = [round(float(b), 4) for b in beta]
        out = []
        for t, f, tt in data[seed]:
            if t.keeper or f is None:
                team, conf = t.team, t.side_confidence
            else:
                p = predict(beta, f)
                team, conf = ("home" if p >= 0.5 else "away"), max(p, 1 - p)
            out.append({"id": t.id, "team": team, "keeper": t.keeper, "confidence": round(conf, 4)
                        if conf is not None else None, "frames": len(t.frames),
                        "paired": None, "true_team": tt})
        scored[seed] = out
    every = [(f, tt, len(t.frames)) for s in seeds for t, f, tt in data[s]
             if f is not None and tt is not None]
    beta_all = fit(np.array([f for f, _, _ in every]),
                   np.array([1.0 if tt == "home" else 0.0 for _, tt, _ in every]),
                   np.array([n for _, _, n in every], dtype=float))
    report = {"seeds": seeds, "obs": obs.name, "features": FEATURES, **summarise(scored)}
    outfield = [r for ts in scored.values() for r in ts if not r["keeper"] and r["true_team"] is not None
                and r["team"] is not None]
    report["calibration_error"] = calibration_error(outfield)
    report["weights_all"] = [round(float(b), 4) for b in beta_all]
    report["weights_leave_one_out"] = weights_by_clip
    report["per_clip"] = scored
    return report


def _loo(data: dict, seeds: list[int], cols: list[int]) -> tuple[dict, dict]:
    """Leave-one-clip-out fit on the chosen feature columns: ({seed: weights}, {seed: [rows]})."""
    weights, scored = {}, {}
    for seed in seeds:
        train = [(f, tt, n) for s in seeds if s != seed for _, f, tt, n in data[s]
                 if f is not None and tt is not None]
        X = np.array([[f[c] for c in cols] for f, _, _ in train])
        beta = fit(X, np.array([1.0 if tt == "home" else 0.0 for _, tt, _ in train]),
                   np.array([n for _, _, n in train], dtype=float))
        weights[seed] = beta
        out = []
        for t, f, tt, n in data[seed]:
            if t.keeper or f is None:
                team, conf = t.team, t.side_confidence
            else:
                p = predict(beta, [f[c] for c in cols])
                team, conf = ("home" if p >= 0.5 else "away"), max(p, 1 - p)
            out.append({"id": t.id, "team": team, "keeper": t.keeper, "confidence": None if conf is None
                        else round(conf, 4), "frames": n, "paired": None, "true_team": tt})
        scored[seed] = out
    return weights, scored


def _report(scored: dict) -> dict:
    rep = summarise(scored)
    rows = [r for ts in scored.values() for r in ts if not r["keeper"] and r["true_team"] is not None
            and r["team"] is not None]
    top = [r for r in rows if r["confidence"] is not None and r["confidence"] >= 0.96]
    return {"outfield": rep["outfield"], "sound_clips": rep["sound_clips"],
            "flipped_clips": rep["flipped_clips"],
            "calibration_error": calibration_error(rows), "confidence": rep["confidence"],
            "at_or_above_0.96": {"tracks": len(top), "right": sum(r["team"] == r["true_team"] for r in top)}}


def run_graph(clips: Path, obs: Path, seeds: list[int]) -> dict:
    """Variant G of the plan: S's features plus the possession-transfer graph, and each source alone."""
    from ninety.vision import events as ev

    data, links = {}, {}
    for seed in seeds:
        if refused(seed):
            raise SystemExit(f"test seed {seed}: sides are measured on validation clips here")
        rows = tr.read_observations(obs / f"seed{seed}.jsonl")
        tracks, feats = features(rows)
        truth = true_teams(tracks, _truth(clips / f"seed{seed}"))
        path = tr.ball_path(rows)
        cuts = [p["frame"] for p, q in zip(rows, rows[1:], strict=False) if q["frame"] != p["frame"] + 1]
        links[seed] = sides.transfers(ev.spells(path, tracks), cuts)
        data[seed] = [(t, feats.get(t.id), truth[t.id], len(t.frames)) for t in tracks
                      if len(t.frames) >= MIN_TRACK_FRAMES]
    s_weights, _ = _loo(data, seeds, [0, 1, 2])
    for seed in seeds:  # the graph from S's own leave-one-out probabilities, never this clip's fit
        p = {t.id: predict(s_weights[seed], f) for t, f, _, _ in data[seed] if f is not None}
        g = sides.graph_evidence(links[seed], p)
        data[seed] = [(t, None if f is None else f + [g.get(t.id, 0.0)], tt, n) for t, f, tt, n in data[seed]]
    out = {"seeds": seeds, "obs": obs.name, "transfers": sum(len(v) for v in links.values())}
    sources = (("kit", [0]), ("spatial", [1, 2]), ("graph", [3]), ("S", [0, 1, 2]), ("G", [0, 1, 2, 3]))
    for name, cols in sources:
        _, scored = _loo(data, seeds, cols)
        out[name] = _report(scored)
    every = [(f, tt, n) for s in seeds for _, f, tt, n in data[s] if f is not None and tt is not None]
    out["G_weights_all"] = [round(float(b), 4) for b in fit(np.array([f for f, _, _ in every]),
                            np.array([1.0 if tt == "home" else 0.0 for _, tt, _ in every]),
                            np.array([n for _, _, n in every], dtype=float))]
    return out


def main(argv: list[str] | None = None) -> None:
    ap = argparse.ArgumentParser(description="Variant S: kit and position combined, leave one clip out.")
    ap.add_argument("--clips", type=Path, required=True)
    ap.add_argument("--obs", type=Path, required=True)
    ap.add_argument("--seeds", type=int, nargs="+", required=True)
    ap.add_argument("--out", type=Path, required=True)
    ap.add_argument("--graph", action="store_true",
                    help="variant G: the possession graph too, and each source alone")
    a = ap.parse_args(argv)
    if a.graph:
        report = run_graph(a.clips, a.obs, a.seeds)
        a.out.write_text(json.dumps(report, indent=1) + "\n")
        print(json.dumps({k: (v["outfield"]["accuracy"], v["calibration_error"], v["at_or_above_0.96"])
                          for k, v in report.items() if isinstance(v, dict) and "outfield" in v}))
        return
    report = run(a.clips, a.obs, a.seeds)
    a.out.write_text(json.dumps(report, indent=1) + "\n")
    print(json.dumps({k: report[k] for k in ("outfield", "sound_clips", "flipped_clips", "calibration_error",
                                             "weights_all")}))


if __name__ == "__main__":
    main()
