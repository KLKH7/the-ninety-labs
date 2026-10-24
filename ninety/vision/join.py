"""Join the broadcast's live run and the tactical views' live run of one clip on the shared clock.

    uv run python -m ninety.vision.join <broadcast run> <views run> --out <joined>

Each run is a ninety.vision.live_job output folder (run.json, detected.jsonl, observations.jsonl,
tracked.json): one over the broadcast camera, one over the fixed tactical camera's views of the
same window. Each camera does what it is best at. The broadcast follows the ball, so the ball and
the events come from it. The views see the whole pitch, so the players, their teams and the shape
come from them. The joined folder is what ninety-e2e reads (`--events-file`, `--tracked`,
`--observations`), so the agents and the phone read one bundle:

    detected.jsonl      the broadcast run's events, unchanged
    observations.jsonl  the broadcast run's, unchanged (the radar draws its camera's footprint)
    tracked.json        the views' tracked players and teams on every frame they have, with the
                        broadcast's ball on the frames where the broadcast has one
    association.json    each broadcast player track -> the tactical track of the same man, or none
    join.json           what was joined, and how

**The shared clock.** Both runs number the clip's frames on its own clock (stage_live keeps the
frame numbers and times). The join refuses two runs unless they are of the same clip and observed
exactly the same frames at the same times, so a frame number means the same moment in both. It
never shifts or resamples one camera onto the other.

**Association.** On every frame both tracked files hold, each broadcast player is paired with the
nearest tactical player on the pitch. The pair is taken only when it is unambiguous: the nearest
is within MATCH_M and the next nearest is more than MATCH_M farther than it. MATCH_M is the two
cameras' position errors added in quadrature (two independent errors on one man), each a measured
90th percentile, not a tuned number. Each broadcast track is then given the tactical track most of
its paired frames chose, with the share of its paired frames that chose it as the confidence.
Teams play no part: each camera reads the kits on its own, and the association is how one camera's
read can be lent to the other.

Nothing here reads ground truth: only the four files each run wrote (tests/test_vision_join.py
watches it run). The association's accuracy is graded offline (ninety/eval/association.py).
"""

from __future__ import annotations

import argparse
import json
import math
from collections import Counter
from pathlib import Path

from ninety.vision import events as ev
from ninety.vision import track as tr

RUN_FILES = ("run.json", "detected.jsonl", "observations.jsonl", "tracked.json")
# The players' position errors, each the 90th percentile measured on validation clips. The
# broadcast's is events.RIVAL_M (docs/eval/attribution-derive.md); the views' is measured by the
# same rule on the views' tracked players (docs/eval/association.md).
BROADCAST_ERROR_M = ev.RIVAL_M
VIEWS_ERROR_M = 0.0  # set from docs/eval/association.md before this merges
MATCH_M = math.hypot(BROADCAST_ERROR_M, VIEWS_ERROR_M)
PLACES = 3


def read_run(run: Path) -> dict:
    """The four files of one live run, and nothing else in its folder."""
    missing = [n for n in RUN_FILES if not (run / n).is_file()]
    if missing:
        raise SystemExit(f"{run}: not a live run, missing {missing}")
    return {
        "run": json.loads((run / "run.json").read_text()),
        "events": [json.loads(x) for x in (run / "detected.jsonl").read_text().splitlines() if x.strip()],
        "observations": tr.read_observations(run / "observations.jsonl"),
        "tracked": json.loads((run / "tracked.json").read_text()),
    }


def check_clock(broadcast: dict, views: dict) -> None:
    """Same clip, the broadcast camera alone against two views or more, and the same frames at the
    same times; otherwise frame numbers would not name the same moment in both."""
    b, v = broadcast["run"], views["run"]
    if b["clip"] != v["clip"]:
        raise SystemExit(f"refused: the runs are of two clips, {b['clip']!r} and {v['clip']!r}")
    if b.get("views"):
        raise SystemExit(f"refused: the broadcast run is of views {b['views']}, not the broadcast")
    if len(v.get("views") or []) < 2:
        raise SystemExit("refused: the views run is not of the tactical camera's views")
    clock_b = [(r["frame"], r["t"]) for r in broadcast["observations"]]
    clock_v = [(r["frame"], r["t"]) for r in views["observations"]]
    if clock_b != clock_v:
        raise SystemExit("refused: the runs did not observe the same frames at the same times")
    known = {f for f, _ in clock_b}
    for name, body in (("broadcast", broadcast), ("views", views)):
        stray = [f["frame"] for f in body["tracked"]["frames"] if f["frame"] not in known]
        if stray:
            raise SystemExit(f"refused: the {name} run's tracked frames {stray[:3]} were not observed")


def tracked(broadcast: dict, views: dict) -> tuple[dict, dict]:
    """The views' tracked frames, with the broadcast's ball wherever the broadcast has one."""
    ball = {f["frame"]: f["ball"] for f in broadcast["tracked"]["frames"]}
    frames, swapped = [], 0
    for f in views["tracked"]["frames"]:
        if f["frame"] in ball:
            f = {**f, "ball": ball[f["frame"]]}
            swapped += 1
        frames.append(f)
    body = {"restarts": views["tracked"].get("restarts", []), "frames": frames}
    return body, {"frames": len(frames), "ball_from_broadcast": swapped,
                  "ball_from_views": len(frames) - swapped}


def pair_frame(mine: list[dict], theirs: list[dict], match_m: float) -> dict[str, tuple[str, float]]:
    """Each of `mine` -> (the nearest of `theirs`, its distance), where that pair is unambiguous."""
    out = {}
    for p in mine:
        ds = sorted((math.dist((p["x"], p["y"]), (q["x"], q["y"])), q["id"]) for q in theirs)
        if not ds or ds[0][0] > match_m:
            continue
        if len(ds) > 1 and ds[1][0] - ds[0][0] <= match_m:
            continue  # a second man within the gap: no match rather than a guess
        out[p["id"]] = (ds[0][1], ds[0][0])
    return out


def associate(broadcast: dict, views: dict, match_m: float = MATCH_M) -> dict:
    """broadcast track id -> {track, confidence, frames, paired, agree}, or track None when no
    frame of it was paired."""
    theirs = {f["frame"]: f["players"] for f in views["tracked"]["frames"]}
    seen: Counter[str] = Counter()
    votes: dict[str, Counter[str]] = {}
    dist: dict[tuple[str, str], list[float]] = {}
    for f in broadcast["tracked"]["frames"]:
        if f["frame"] not in theirs:
            continue
        seen.update(p["id"] for p in f["players"])
        for pid, (qid, d) in pair_frame(f["players"], theirs[f["frame"]], match_m).items():
            votes.setdefault(pid, Counter())[qid] += 1
            dist.setdefault((pid, qid), []).append(d)
    out = {}
    for pid in sorted(seen):
        if pid not in votes:
            out[pid] = {"track": None, "confidence": 0.0, "frames": seen[pid], "paired": 0}
            continue
        paired = sum(votes[pid].values())
        # Most votes; a tie goes to the nearer on average, then to the id, so the file is stable.
        qid, n = min(votes[pid].items(),
                     key=lambda kv: (-kv[1], sum(dist[pid, kv[0]]) / kv[1], kv[0]))
        out[pid] = {"track": qid, "confidence": round(n / paired, PLACES), "frames": seen[pid],
                    "paired": paired, "agree": n,
                    "mean_m": round(sum(dist[pid, qid]) / n, PLACES)}
    return out


def join(broadcast_run: Path, views_run: Path, out: Path) -> dict:
    """Write the joined folder and return join.json's contents."""
    b, v = read_run(Path(broadcast_run)), read_run(Path(views_run))
    check_clock(b, v)
    out = Path(out)
    out.mkdir(parents=True, exist_ok=True)
    (out / "detected.jsonl").write_text("".join(json.dumps(e) + "\n" for e in b["events"]), encoding="utf-8")
    (out / "observations.jsonl").write_text(
        "".join(json.dumps(r, separators=(",", ":")) + "\n" for r in b["observations"]), encoding="utf-8")
    body, how = tracked(b, v)
    (out / "tracked.json").write_text(json.dumps(body, separators=(",", ":")) + "\n", encoding="utf-8")
    pairs = associate(b, v)
    (out / "association.json").write_text(json.dumps({
        "match_m": round(MATCH_M, PLACES),
        "broadcast_error_m": BROADCAST_ERROR_M,
        "views_error_m": VIEWS_ERROR_M,
        "tracks": pairs,
    }, indent=1) + "\n", encoding="utf-8")
    matched = sum(1 for a in pairs.values() if a["track"])
    report = {
        "clip": b["run"]["clip"],
        "frames": len(b["observations"]),
        "views": v["run"]["views"],
        "events": len(b["events"]),
        "tracked": how,
        "association": {"broadcast_tracks": len(pairs), "matched": matched,
                        "match_m": round(MATCH_M, PLACES)},
    }
    (out / "join.json").write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    return report


def main(argv: list[str] | None = None) -> None:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("broadcast", type=Path, help="live_job's output folder for the broadcast camera")
    ap.add_argument("views", type=Path, help="live_job's output folder for the tactical views")
    ap.add_argument("--out", type=Path, required=True)
    args = ap.parse_args(argv)
    r = join(args.broadcast, args.views, args.out)
    print(f"{args.out}: {r['frames']} frames, {r['events']} events, "
          f"{r['association']['matched']} of {r['association']['broadcast_tracks']} broadcast tracks paired")


if __name__ == "__main__":
    main()
