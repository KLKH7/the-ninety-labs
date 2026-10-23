"""The goals' nets (docs/eval/restarts.md, "The goal net"; lesson 184).

    uv run python scripts/defect_sweep/nets.py runs/new/seed7 runs/new/seed11 ...

From each run's frames.jsonl and events.jsonl (simulated matches, ground truth). A goal's net, seen
as the renderer draws it: 2 m behind the goal line at the top and the bottom, its back 2 m high, its
roof sloping down to it from the crossbar (Law 1's posts, 7.32 m apart, and crossbar, 2.44 m high).

- After each goal, up to its kick-off: how far behind the goal line the ball's centre goes, and
  where it comes back over the goal line (between the posts, through the mouth, or not).
- Every ball step into or out of a goal other than over its goal line between the posts and under
  the bar, that is through its net, and every player step that passes through a net seen from
  above; each split into after a goal (up to its kick-off) and at any other time.
- Seconds from each goal to its kick-off.

Prints one JSON object of totals with the first few cases of each, as (run, time, player).
"""

import json
import sys
from pathlib import Path

PITCH_X, MID, HALF_WIDTH, BAR = 105.0, 34.0, 3.66, 2.44  # Law 1
DEPTH, BACK_HEIGHT = 2.0, 2.0  # the net as drawn (web/render/render.js, buildNet)
RADIUS = 0.11  # Law 2
SLACK_M = 0.02  # positions are written to the millimetre; this is a ball's touch on the net, not more


def sides() -> list[tuple[tuple[float, float], tuple[float, float]]]:
    """Both nets seen from above: two sides and a back each."""
    out = []
    for line, sign in ((0.0, -1.0), (PITCH_X, 1.0)):
        back = line + sign * DEPTH
        lo, hi = MID - HALF_WIDTH, MID + HALF_WIDTH
        out += [((line, lo), (back, lo)), ((line, hi), (back, hi)), ((back, lo), (back, hi))]
    return out


SIDES = sides()


def through(a, b, c, d) -> bool:
    """The step a -> b meets the stretch c -> d: a + s (b - a) = c + u (d - c), s and u in [0, 1]."""
    rx, ry, qx, qy = b[0] - a[0], b[1] - a[1], d[0] - c[0], d[1] - c[1]
    den = rx * qy - ry * qx
    if den == 0:
        return False
    s = ((c[0] - a[0]) * qy - (c[1] - a[1]) * qx) / den
    u = ((c[0] - a[0]) * ry - (c[1] - a[1]) * rx) / den
    return 0 <= s <= 1 and 0 <= u <= 1


def in_goal(b: dict) -> float | None:
    """The goal line whose goal holds the ball (its lowest point is z), if any."""
    for line, sign in ((0.0, -1.0), (PITCH_X, 1.0)):
        depth = (b["x"] - line) * sign
        if 0 < depth <= DEPTH and abs(b["y"] - MID) <= HALF_WIDTH:
            roof = BAR + (BACK_HEIGHT - BAR) * depth / DEPTH
            if b["z"] + 2 * RADIUS <= roof + SLACK_M:
                return line
    return None


def through_net(a: dict, b: dict) -> str | None:
    """'in' or 'out' if the ball went into or out of a goal other than by its mouth, else None."""
    ia, ib = in_goal(a), in_goal(b)
    if ia == ib:
        return None
    line = ib if ib is not None else ia
    sign = 1.0 if line > 0 else -1.0
    da, db = (a["x"] - line) * sign, (b["x"] - line) * sign
    if (da <= 0) != (db <= 0):  # over the goal line this step: where?
        s = da / (da - db)
        y, z = a["y"] + s * (b["y"] - a["y"]), a["z"] + s * (b["z"] - a["z"])
        if abs(y - MID) < HALF_WIDTH and z + 2 * RADIUS < BAR + SLACK_M:
            return None
    return "in" if ib is not None else "out"


def main() -> None:
    goals, to_kick = [], []
    walked = {"after_goal": [], "other": []}
    balls = {"after_goal": [], "other": []}
    for run in map(Path, sys.argv[1:]):
        events = [json.loads(line) for line in open(run / "events.jsonl")]
        frames = [json.loads(line) for line in open(run / "frames.jsonl")]
        by = {f["frame"]: f for f in frames}
        kicks = [e for e in events if e["type"] == "kickoff"]
        after = set()
        for g in (e for e in events if e["type"] == "goal"):
            k = next((e for e in kicks if e["frame"] > g["frame"]), None)
            end = k["frame"] if k else frames[-1]["frame"]
            after.update(range(g["frame"], end + 1))
            if k:
                to_kick.append(round(k["t"] - g["t"], 1))
            line = PITCH_X if g["x"] > PITCH_X / 2 else 0.0
            sign = 1.0 if line > 0 else -1.0
            deepest, back_over, prev = 0.0, None, None
            for n in range(g["frame"], end + 1):
                b = by[n]["ball"] if n in by else None
                if b is None:
                    continue
                behind = (b["x"] - line) * sign
                deepest = max(deepest, behind)
                if prev is not None and back_over is None and (prev["x"] - line) * sign > 0 >= behind:
                    back_over = abs(b["y"] - MID)
                prev = b
            goals.append({"run": run.name, "t": g["t"], "deepest_m": round(deepest, 3),
                          "back_over_the_line_at_m_from_centre": back_over and round(back_over, 3)})
        for a, b in zip(frames, frames[1:], strict=False):
            if b["frame"] != a["frame"] + 1:
                continue
            when = "after_goal" if b["frame"] in after else "other"
            was = {p["id"]: (p["x"], p["y"]) for p in a["players"]}
            for p in b["players"]:
                q = was.get(p["id"])
                if q is None or (0 < min(q[0], p["x"]) and max(q[0], p["x"]) < PITCH_X):
                    continue
                if any(through(q, (p["x"], p["y"]), c, d) for c, d in SIDES):
                    walked[when].append((run.name, b["t"], p["id"]))
            how = through_net(a["ball"], b["ball"])
            if how:
                balls[when].append((run.name, b["t"], how))
    print(json.dumps({
        "goals": len(goals),
        "deepest_after_a_goal_m": max((g["deepest_m"] for g in goals), default=None),
        "past_the_net_after_a_goal": sum(g["deepest_m"] > DEPTH for g in goals),
        "out_of_the_goal_by_the_mouth": sum(g["back_over_the_line_at_m_from_centre"] is not None
                                            and g["back_over_the_line_at_m_from_centre"] < HALF_WIDTH
                                            for g in goals),
        "goal_to_kickoff_s": [min(to_kick, default=None), max(to_kick, default=None)],
        "players_through_a_net": {k: len(v) for k, v in walked.items()},
        "balls_through_a_net": {k: len(v) for k, v in balls.items()},
        "first_cases": {"players": {k: v[:5] for k, v in walked.items()},
                        "balls": {k: v[:5] for k, v in balls.items()}},
        "goal_list": goals,
    }, indent=1))


if __name__ == "__main__":
    main()
