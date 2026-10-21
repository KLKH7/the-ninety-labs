"""Bodies inside each other while a goal is celebrated (docs/eval/restarts.md, "The huddle").

    uv run python scripts/defect_sweep/huddle.py 1 4 6 8 9 10 12 13 14 15 16 17

For each seed: a minute of play, then a planted goal (h9 scores from 100, 30, as in
tests/test_restarts.py), then every frame to the end of the celebration. A frame counts when two
bodies, of either team, are more than 5 cm into each other (`shape.between`; bodies touch under
`shape.CHEST_DEPTH_M`). Counted over the whole celebration, and over the frames when all of the
scorer's team-mates stand at their places (within half a place's spacing, settled: one frame of
braking would stop them) until the first of them leaves. Then the same count over a minute of
open play from the same seed, for comparison. Prints one JSON line a seed, then a summary line.
"""

import json
import math
import statistics as st
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from ninety.sim import shape  # noqa: E402
from ninety.sim.engine import DT, HUDDLE_SPACING_M, THROW_SETTLED_MPS, Engine  # noqa: E402

DEEP_M = 0.05  # a body this far into another counts (the audit's measure)


def overlapping(e: Engine) -> bool:
    ps = e.players
    for i, a in enumerate(ps):
        for b in ps[i + 1:]:
            if abs(a.x - b.x) > shape.SHOULDER_BREADTH_M or abs(a.y - b.y) > shape.SHOULDER_BREADTH_M:
                continue
            if shape.CHEST_DEPTH_M - shape.between(a.x, a.y, a.heading, b.x, b.y, b.heading)[0] > DEEP_M:
                return True
    return False


def planted_goal(seed: int) -> Engine:
    e = Engine(seed)
    e.run(1)
    e.possessor, e.restart, e.set_by, e.throw_by, e.dribbler = None, None, None, None, None
    scorer = e.by_id["h9"]
    scorer.x, scorer.y = 100.0, 30.0
    e.ball = (106.0, 33.0, 0.5, 2.0, 0.0, 0.0)  # in the net
    e.kicked = e.emit("shot", "home", 95.0, 33.0, player=scorer.id)
    e.shot_was_on_target = True
    e.scored("home", e.kicked, 105.0, 33.0)
    return e


def measure(seed: int) -> dict:
    e = planted_goal(seed)
    c = e.celebration
    first_leaves = min(c.leave.values())
    frames = bad = gathered = bad_gathered = 0
    while e.t < c.until:
        e.step()
        frames += 1
        hit = overlapping(e)
        bad += hit
        ring = [e.by_id[pid] for pid in c.ring]
        if e.t < first_leaves and all(math.dist((p.x, p.y), c.places[p.id]) < HUDDLE_SPACING_M / 2
                                      and math.hypot(p.vx, p.vy) <= THROW_SETTLED_MPS for p in ring):
            gathered += 1
            bad_gathered += hit
    o = Engine(seed)
    o.run(1)
    open_frames = int(60 / DT)
    open_bad = 0
    for _ in range(open_frames):
        o.step()
        open_bad += overlapping(o)
    return {"seed": seed, "celebration_frames": frames, "overlap_frames": bad,
            "overlap_share": round(bad / frames, 4), "overlap_s": round(bad * DT, 2),
            "gathered_frames": gathered, "gathered_overlap_frames": bad_gathered,
            "open_play_overlap_share": round(open_bad / open_frames, 4)}


def main(seeds: list[int]) -> None:
    rows = [measure(s) for s in seeds]
    for r in rows:
        print(json.dumps(r))
    share = [r["overlap_share"] for r in rows]
    open_play = [r["open_play_overlap_share"] for r in rows]
    print(json.dumps({"seeds": len(rows), "overlap_share_mean": round(st.mean(share), 4),
                      "overlap_share_max": max(share), "overlap_s_max": max(r["overlap_s"] for r in rows),
                      "gathered_frames": sum(r["gathered_frames"] for r in rows),
                      "gathered_overlap_frames": sum(r["gathered_overlap_frames"] for r in rows),
                      "open_play_overlap_share_mean": round(st.mean(open_play), 4)}))


if __name__ == "__main__":
    main([int(a) for a in sys.argv[1:]] or [1, 4, 6, 8, 9, 10, 12, 13, 14, 15, 16, 17])
