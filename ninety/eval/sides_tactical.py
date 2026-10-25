"""Team sides as the live path decides them, scored against the truth by pitch position
(docs/eval/sides-tactical/PLAN.md).

    uv run python -m ninety.eval.sides_tactical --clips <dir> --obs <variant dir> --seeds ... --out <json>

Grading data, read offline: each clip's frames.jsonl (players' true places, teams and roles). The
observations (one variant's `seed<N>.jsonl`) are tracked and sided by the live path's own code
(track.track_players, track.assign_teams). Each detected player is paired with the nearest true
player within 1.0 m in its frame, one to one, nearest first; a track's true team is that of most
of its paired frames. A test seed is refused.
"""

from __future__ import annotations

import argparse
import json
import math
from pathlib import Path

import numpy as np

from ninety.eval.attribution_derive import refused
from ninety.eval.detector_derive import ordering
from ninety.eval.event_score import STRICT_M, wilson
from ninety.vision import track as tr
from ninety.vision.tracked_frames import MIN_TRACK_FRAMES

SOUND_SHARE = 0.80  # #200's: a clip is sound when this share of its outfield track-frames is right
BINS = ((0.0, 0.5), (0.5, 0.8), (0.8, 0.9), (0.9, 0.96), (0.96, 1.0 + 1e-9))


def _truth(clip: Path) -> dict[int, list[dict]]:
    out = {}
    for line in (clip / "frames.jsonl").read_text().splitlines():
        fr = json.loads(line)
        out[int(fr["frame"])] = [p for p in fr["players"] if p.get("x") is not None]
    return out


def _pair(dets: list[tuple[int, float, float]], truth: list[dict]) -> dict[int, dict]:
    """Detection index -> its true player: one to one, nearest first, within STRICT_M."""
    cands = sorted((math.hypot(x - p["x"], y - p["y"]), i, j)
                   for i, x, y in dets for j, p in enumerate(truth))
    used_d, used_t, out = set(), set(), {}
    for d, i, j in cands:
        if d > STRICT_M or i in used_d or j in used_t:
            continue
        used_d.add(i)
        used_t.add(j)
        out[i] = truth[j]
    return out


def inherit(tactical: list[tr.Track], broadcast: list[tr.Track]) -> None:
    """Plan variant TB: each tactical track takes the side (and its confidence) of the broadcast
    track it overlaps most. Overlap: frames where both are tracked and their places are within
    STRICT_M, paired one to one per frame, nearest first. A tactical track with no overlap has no
    side (None). Keepers keep their own side (the half they stand in)."""
    count: dict[tuple[int, int], int] = {}
    frames = {f for t in tactical for f in t.frames}
    for f in sorted(frames):
        a = [(i, *t.at(f)) for i, t in enumerate(tactical) if t.at(f) is not None]
        b = [(j, *u.at(f)) for j, u in enumerate(broadcast) if u.at(f) is not None and u.team is not None]
        cands = sorted((math.hypot(x - x2, y - y2), i, j) for i, x, y in a for j, x2, y2 in b)
        used_a, used_b = set(), set()
        for d, i, j in cands:
            if d > STRICT_M or i in used_a or j in used_b:
                continue
            used_a.add(i)
            used_b.add(j)
            count[(i, j)] = count.get((i, j), 0) + 1
    for i, t in enumerate(tactical):
        if t.keeper:
            continue
        best = max(((n, j) for (k, j), n in count.items() if k == i), default=None)
        t.team = broadcast[best[1]].team if best else None
        t.side_confidence = broadcast[best[1]].side_confidence if best else None


def clip_tracks(rows: list[dict], truth: dict[int, list[dict]],
                broadcast_rows: list[dict] | None = None) -> tuple[list[dict], dict]:
    """Every track the events stage would use, with its side, confidence, keeper flag, frames,
    paired frames and true team (None when under half its frames pair). With `broadcast_rows`,
    the sides are inherited from the broadcast's tracks (variant TB)."""
    tracks = tr.track_players(rows)
    info = tr.assign_teams(tracks)
    if broadcast_rows is not None:
        btracks = tr.track_players(broadcast_rows)
        tr.assign_teams(btracks)
        inherit(tracks, btracks)
    by_frame: dict[int, list[tuple[int, float, float]]] = {}
    for k, t in enumerate(tracks):
        for f, (x, y) in zip(t.frames, t.xy, strict=True):
            by_frame.setdefault(f, []).append((k, x, y))
    votes: dict[int, dict[str, int]] = {}
    for f, dets in by_frame.items():
        for k, p in _pair(dets, truth.get(f, [])).items():
            votes.setdefault(k, {}).setdefault(p["team"], 0)
            votes[k][p["team"]] += 1
    out = []
    for k, t in enumerate(tracks):
        if len(t.frames) < MIN_TRACK_FRAMES:
            continue
        v = votes.get(k, {})
        paired = sum(v.values())
        true_team = max(v, key=v.get) if v and paired * 2 >= len(t.frames) else None
        out.append({"id": t.id, "team": t.team, "keeper": t.keeper, "confidence": t.side_confidence,
                    "frames": len(t.frames), "paired": paired, "true_team": true_team})
    return out, info


def summarise(clips: dict[int, list[dict]]) -> dict:
    out: dict = {"clips": len(clips)}
    for kind, keep in (("outfield", lambda t: not t["keeper"]), ("keeper", lambda t: t["keeper"])):
        right = total = 0
        unmatched = 0
        for ts in clips.values():
            for t in ts:
                if not keep(t):
                    continue
                if t["true_team"] is None:
                    unmatched += 1
                    continue
                total += t["frames"]
                right += t["frames"] if t["team"] == t["true_team"] else 0
        out[kind] = {"track_frames": total, "right": right,
                     "accuracy": round(right / total, 4) if total else None,
                     "wilson95": wilson(right, total), "unmatched_tracks": unmatched}
    sound = flipped = 0
    for ts in clips.values():
        o = [t for t in ts if not t["keeper"] and t["true_team"] is not None]
        n = sum(t["frames"] for t in o)
        r = sum(t["frames"] for t in o if t["team"] == t["true_team"])
        if n and r / n >= SOUND_SHARE:
            sound += 1
        if n and r / n < 0.5:
            flipped += 1
    out["sound_clips"], out["flipped_clips"] = sound, flipped
    conf = [(t["confidence"], t["team"] == t["true_team"]) for ts in clips.values() for t in ts
            if not t["keeper"] and t["true_team"] is not None and t["confidence"] is not None]
    wrong = [c for c, ok in conf if not ok]
    rightc = [c for c, ok in conf if ok]

    def dist(v):
        qs = (("min", 0), ("p10", 10), ("p50", 50), ("p90", 90), ("max", 100))
        return None if not v else {q: round(float(np.percentile(v, p)), 3) for q, p in qs}

    top_wrong = max(wrong) if wrong else None
    out["confidence"] = {
        "right": dist(rightc), "wrong": dist(wrong), "n_right": len(rightc), "n_wrong": len(wrong),
        # #200's ordering_95 adds the interval; on main the ordering itself (detector_derive)
        "ordering": None if (o := ordering(conf)) is None else round(o, 4),
        "largest_wrong": top_wrong,
        "right_above_0.96": round(sum(c > 0.96 for c in rightc) / len(rightc), 4) if rightc else None,
        "right_above_largest_wrong": (round(sum(c > top_wrong for c in rightc) / len(rightc), 4)
                                      if rightc and top_wrong is not None else None),
        "bins": [{"from": lo, "to": min(hi, 1.0), "n": len(b := [ok for c, ok in conf if lo <= c < hi]),
                  "accuracy": round(sum(b) / len(b), 4) if b else None} for lo, hi in BINS],
    }
    return out


def main(argv: list[str] | None = None) -> None:
    ap = argparse.ArgumentParser(description="Score the live path's team sides by pitch position.")
    ap.add_argument("--clips", type=Path, required=True)
    ap.add_argument("--obs", type=Path, required=True, help="a folder of seed<N>.jsonl observations")
    ap.add_argument("--seeds", type=int, nargs="+", required=True)
    ap.add_argument("--inherit-from", type=Path, default=None,
                    help="variant TB: a folder of broadcast observations whose tracks give the sides")
    ap.add_argument("--out", type=Path, required=True)
    a = ap.parse_args(argv)
    clips = {}
    for seed in a.seeds:
        if refused(seed):
            raise SystemExit(f"test seed {seed}: sides are measured on validation clips here")
        rows = tr.read_observations(a.obs / f"seed{seed}.jsonl")
        bro = (tr.read_observations(a.inherit_from / f"seed{seed}.jsonl")
               if a.inherit_from is not None else None)
        clips[seed], _ = clip_tracks(rows, _truth(a.clips / f"seed{seed}"), bro)
    report = {"seeds": a.seeds, "obs": a.obs.name, **summarise(clips),
              "per_clip": {s: [t for t in ts] for s, ts in clips.items()}}
    a.out.write_text(json.dumps(report, indent=1) + "\n")
    print(json.dumps({k: v for k, v in report.items() if k not in ("per_clip", "seeds")}))


if __name__ == "__main__":
    main()
