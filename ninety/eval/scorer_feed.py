"""Shooters named from the ball and the player-ID feed (ninety/intel/identity.py, step 9) against the
answer key, offline.

    uv run python -m ninety.eval.scorer_feed --match 8080 <named.jsonl> <feed> <truth> \\
        --match 8324 <named.jsonl> <feed> <truth> --out docs/eval/scorer-feed

Grading, so it reads the answer key; nothing on the live path imports it. The plan, fixed before
any score: docs/eval/scorer-feed-plan.md. `<named.jsonl>` is the step's output
(`python -m ninety.intel.identity shooters`); `<truth>` is the simulated run's directory or a
footage-hunt compact.npz with its events.jsonl beside it.

The feed names players by the provider's ids (club code and shirt), the answer key by the
engine's: each engine id is mapped to the feed id nearest it, on average over a minute of frames
(the feed is the engine's positions plus the provider's noise, a few centimetres).
"""

from __future__ import annotations

import argparse
import datetime
import json
import math
from collections import defaultdict
from pathlib import Path

from ninety.eval.event_score import git_commit, wilson
from ninety.intel import identity

COMMAND = "uv run python -m ninety.eval.scorer_feed"
GATE = 0.95  # pre-registered (docs/eval/scorer-feed-plan.md)
SHOT_S, GOAL_S = 1.0, 2.0  # pre-registered: how near in time the answer key's shot or goal must be
MAP_FRAMES = range(25 * 60, 25 * 120, 25)  # one frame a second over the second minute


def _truth(truth: Path) -> tuple[dict[int, dict[str, tuple[float, float]]], list[dict]]:
    """Engine positions at MAP_FRAMES, and the answer key's events."""
    want = set(MAP_FRAMES)
    at: dict[int, dict[str, tuple[float, float]]] = {}
    if truth.suffix == ".npz":
        import numpy as np

        z = np.load(truth)
        ids, xy = [str(i) for i in z["ids"]], z["xy"]  # each z[...] decompresses the whole array: once
        for n in want:
            at[n] = {ids[k]: (float(xy[n][k][0]), float(xy[n][k][1])) for k in range(len(ids))}
        ev_path = truth.parent / "events.jsonl"
    else:
        with (truth / "frames.jsonl").open() as fh:
            for line in fh:
                r = json.loads(line)
                if r["frame"] in want:
                    at[r["frame"]] = {p["id"]: (p["x"], p["y"]) for p in r["players"]}
                if r["frame"] > max(want):
                    break
        ev_path = truth / "events.jsonl"
    return at, [json.loads(x) for x in ev_path.read_text().splitlines() if x.strip()]


def engine_to_feed(at: dict, feed: identity.Feed) -> dict[str, str]:
    """Each engine id's feed id: the one nearest it on average over MAP_FRAMES."""
    dist: dict[tuple[str, str], list[float]] = defaultdict(list)
    for n, eng in at.items():
        fd = feed.at.get(n, {})
        for e, (x, y) in eng.items():
            for f, (fx, fy) in fd.items():
                dist[(e, f)].append(math.hypot(x - fx, y - fy))
    out = {}
    for e in {e for e, _ in dist}:
        f = min((f for e2, f in dist if e2 == e), key=lambda f: sum(dist[(e, f)]) / len(dist[(e, f)]))
        out[e] = f
    return out


def grade_match(seed: str, named: Path, feed_path: Path, truth: Path) -> dict:
    at, tev = _truth(truth)
    feed = identity.load(feed_path, [n / 25 for n in MAP_FRAMES])
    to_feed = engine_to_feed(at, feed)
    events = [json.loads(x) for x in named.read_text().splitlines() if x.strip()]
    rows = []
    for e in events:
        w = e.get("player_named")
        if not w:
            continue
        kind, near = ("shot", SHOT_S) if e["type"] == "shot" else ("goal", GOAL_S)
        cands = [t for t in tev if t["type"] == kind and abs(float(t["t"]) - float(e["t"])) <= near]
        t = min(cands, key=lambda t: abs(float(t["t"]) - float(e["t"]))) if cands else None
        true_id = to_feed.get(t["player"]) if t else None
        rows.append({"event": e["id"], "type": e["type"], "t": e["t"], "by": w["by"], "named": w["player_id"],
                     "truth": true_id, "right": true_id is not None and true_id == w["player_id"]})
    by_ball = [r for r in rows if r["by"] == "ball"]
    k = sum(r["right"] for r in rows)
    return {"seed": seed, "named": len(rows), "right": k,
            "precision": round(k / len(rows), 3) if rows else None,
            "wilson95": wilson(k, len(rows)) if rows else None,
            "by_ball": {"named": len(by_ball), "right": sum(r["right"] for r in by_ball)},
            "goals": [r for r in rows if r["type"] == "goal"], "rows": rows}


def main(argv: list[str] | None = None) -> None:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--match", nargs=4, action="append", required=True,
                    metavar=("SEED", "NAMED", "FEED", "TRUTH"))
    ap.add_argument("--out", type=Path, required=True)
    args = ap.parse_args(argv)
    matches = [grade_match(s, Path(n), Path(f), Path(t)) for s, n, f, t in args.match]
    gate_m = matches[0]
    body = {
        "plan": "docs/eval/scorer-feed-plan.md",
        "command": COMMAND,
        "commit": git_commit(),
        "date": datetime.date.today().isoformat(),
        "gate": {"seed": gate_m["seed"], "precision_at_least": GATE, "precision": gate_m["precision"],
                 "wilson95": gate_m["wilson95"], "named": gate_m["named"],
                 "met": gate_m["precision"] is not None and gate_m["precision"] >= GATE},
        "matches": matches,
    }
    args.out.with_suffix(".json").write_text(json.dumps(body, indent=1) + "\n")
    print(json.dumps(body["gate"]))
    for m in matches:
        goals = [(g["event"], g["named"], g["truth"]) for g in m["goals"]]
        print(m["seed"], m["right"], "/", m["named"], goals)


if __name__ == "__main__":
    main()
