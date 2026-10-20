"""Free-kick walls (docs/eval/restarts.md, "The wall").

    uv run python scripts/defect_sweep/wall.py runs/new/seed7 runs/new/seed11 ...
    uv run python scripts/defect_sweep/wall.py --planted 2 3 5 7

With run folders: for each direct free kick within shooting range (a foul, then its kick, less than
offball.SHOT_RANGE_M from the goal's centre, straight-line; not a penalty), the wall the engine plans for it
(Engine.wall_spots) and how many of its places have a defender on them, within a ball's radius,
when the kick is struck.

With --planted and seeds: a minute of play, then a direct free kick to home 22 m out straight on,
18 m out at y = 24 and 27 m out at y = 44, its taker over the ball (as tests/test_restarts.py plants
them), run to the kick: when every wall player first stands on his place (within a ball's radius),
how far each is from it at the kick, the gaps between neighbours' bodies then, and the frames in
which two of them are more than 5 cm into each other while the wall forms.
"""

import json
import math
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from ninety.sim import ball, offball, shape  # noqa: E402
from ninety.sim.engine import PENALTY_MARK_M, PITCH_X, PITCH_Y, Engine, Restart  # noqa: E402

DEEP_M = 0.05  # a body this far into another counts (as scripts/defect_sweep/huddle.py)
PLANTED = [(PITCH_X - 22.0, 34.0), (PITCH_X - 18.0, 24.0), (PITCH_X - 27.0, 44.0)]


def natural(runs: list[str]) -> None:
    e = Engine(1)
    for run in map(Path, runs):
        ev = [json.loads(line) for line in open(run / "events.jsonl")]
        frames = {}
        for line in open(run / "frames.jsonl"):
            f = json.loads(line)
            frames[f["frame"]] = f
        stopped = None
        for i, x in enumerate(ev):
            if x["type"] in ("out_of_play", "foul", "offside"):
                stopped = x
            if x["type"] != "set_piece" or stopped is None or stopped["type"] != "foul":
                continue
            stopped, goal = None, (PITCH_X if x["team"] == "home" else 0.0)
            if math.hypot(goal - x["x"], PITCH_Y / 2 - x["y"]) >= offball.SHOT_RANGE_M:
                continue
            if math.hypot(abs(goal - x["x"]) - PENALTY_MARK_M, PITCH_Y / 2 - x["y"]) < 0.5:
                continue  # a penalty kick (Law 14): no wall
            spots = e.wall_spots(Restart("free_kick", x["team"], x["x"], x["y"], x["player"], 0.0))
            kick = next((k for k in ev[i + 1:] if k["type"] in ("pass", "shot")), None)
            f = frames.get(kick["frame"]) if kick else None
            defenders = [p for p in f["players"] if p["team"] != x["team"]] if f else []
            on = sum(any(math.hypot(p["x"] - sx, p["y"] - sy) < ball.RADIUS for p in defenders)
                     for sx, sy in spots)
            print(json.dumps({"run": run.name, "t": round(x["t"], 1), "x": round(x["x"], 1),
                              "y": round(x["y"], 1), "wall": len(spots), "on_their_places": on,
                              "kick": kick["type"] if kick else None}))


def planted(seeds: list[int]) -> None:
    for seed in seeds:
        for bx, by in PLANTED:
            e = Engine(seed)
            e.run(1)
            e.possessor, e.restart, e.set_by, e.throw_by, e.dribbler = None, None, None, None, None
            e.celebration = None
            # the whistle ends what was in play, as foul() does: the ball in flight, the chase, any lunge
            e.kicked, e.dribble_to, e.windup, e.chase = None, None, None, {}
            e.lunges.clear(), e.lunge_at.clear(), e.evade_at.clear()
            taker = e.by_id["h9"]
            taker.x, taker.y, taker.vx, taker.vy = bx - 0.47, by, 0.0, 0.0
            e.ball = (bx, by, 0.0, 0.0, 0.0, 0.0)
            e.stop("free_kick", "home", (bx, by), taker=taker.id)
            e.restart.carried_by = taker.id
            r, t0 = e.restart, e.t
            wall = dict(r.wall)
            formed, frames, deep = None, 0, 0
            n = len(e.match.events)
            while e.t - t0 < 80 and not any(x["type"] in ("pass", "shot") for x in e.match.events[n:]):
                e.step()
                frames += 1
                ps = [e.by_id[pid] for pid in wall]
                if formed is None and all(math.dist((p.x, p.y), wall[p.id]) < ball.RADIUS for p in ps):
                    formed = round(e.t - t0, 1)
                deep += any(shape.CHEST_DEPTH_M - shape.between(a.x, a.y, a.heading, b.x, b.y, b.heading)[0]
                            > DEEP_M for i, a in enumerate(ps) for b in ps[i + 1:])
            line = sorted((e.by_id[pid] for pid in wall), key=lambda p: (wall[p.id][1], wall[p.id][0]))

            def gap(a, b):  # between two neighbours' bodies (negative: inside each other)
                d = shape.between(a.x, a.y, a.heading, b.x, b.y, b.heading)[0]
                return round(d - shape.CHEST_DEPTH_M, 2)

            print(json.dumps({
                "seed": seed, "kick_at": [bx, by], "wall": len(wall), "stoppage_s": round(r.ready_at - t0, 1),
                "formed_s": formed, "struck_s": round(e.t - t0, 1),
                "off_place_m": [round(math.dist((p.x, p.y), wall[p.id]), 2) for p in line],
                "gaps_m": [gap(a, b) for a, b in zip(line, line[1:], strict=False)],
                "frames": frames, "frames_bodies_in_each_other": deep}))


if __name__ == "__main__":
    if sys.argv[1:2] == ["--planted"]:
        planted([int(a) for a in sys.argv[2:]] or [2, 3, 5, 7])
    else:
        natural(sys.argv[1:])
