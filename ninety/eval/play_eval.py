"""Where play happens, measured over full matches: volume and outcomes, possession and passes by
third, final-third spells, and the shot estimate against what the engine then does.

    uv run python -m ninety.eval.play_eval --seeds 0-11 --out docs/eval/play.md

Every number in GROUNDING O6, P16 and R3 about where play happens comes from this report. It
reads the engine's own events and, for the shot check, the shooter's estimate at the moment he
chose to shoot; it changes nothing in play (the choice is wrapped, never altered)."""

from __future__ import annotations

import argparse
from collections import Counter
from concurrent.futures import ProcessPoolExecutor

from ninety.sim import decisions as D
from ninety.sim.engine import FPS, Engine

THIRD_M = 35.0  # a third of the pitch's length
BOX_M = 16.5  # Law 1: the penalty area's depth
PENALTY_HALF_WIDTH_M = D.PENALTY_HALF_WIDTH  # Law 1: the penalty area's half width
BLOCK_WINDOW_S = 0.6  # a shot counts as blocked if an outfield opponent touches it this soon


def toward_goal(team: str, x: float) -> float:
    """Metres from the team's own goal line."""
    return x if team == "home" else 105.0 - x


def third(u: float) -> str:
    return "own" if u < THIRD_M else "middle" if u < 2 * THIRD_M else "final"


def one(seed: int) -> Counter:
    e = Engine(seed)
    e.kickoff("home")
    c: Counter = Counter()
    pending = {}
    orig = D.choose

    def choose(scene, rng):
        o = orig(scene, rng)
        if o.kind == "shoot":
            wait = 0.0 if scene.header else D.strike_turn(
                scene.heading, scene.goal_x - scene.x, 34.0 - scene.y, scene.throw, scene.dead)[1]
            blockers = sum(D.in_cone(scene.x, scene.y, scene.goal_x, ox, oy) for ox, oy in
                           (D.at_strike(scene)[0] if hasattr(D, "at_strike") else scene.opponents)
                           if (ox, oy) != scene.keeper)
            pending["shot"] = (wait > 0, abs(scene.goal_x - scene.x) < BOX_M,
                               1 - D.BLOCKER_FACTOR ** blockers, D.shot_chance(scene))
        return o

    D.choose = choose
    shots = []
    seen = 0
    spell = None
    try:
        for _ in range(90 * 60 * FPS):
            e.step()
            for ev in e.match.events[seen:]:
                if ev["type"] == "shot" and "shot" in pending:
                    shots.append((pending.pop("shot"), ev))
            seen = len(e.match.events)
            if not e.restart:
                c["live_frames"] += 1
            if not e.possessor or e.restart:
                continue
            p = e.by_id[e.possessor]
            t = third(toward_goal(p.team, p.x))
            c[f"possession_{t}"] += 1
            if t == "final" and spell is None:
                spell = p.team
                c["final_entries"] += 1
            elif spell is not None and (p.team != spell or t != "final"):
                c["spell_lost" if p.team != spell else "spell_back_out"] += 1
                spell = None
    finally:
        D.choose = orig
    ev = e.match.events
    for x in ev:
        c[f"event_{x['type']}"] += 1
        if x["type"] == "out_of_play" and x["x"] in (0.0, 105.0):
            # Law 17: over the defending team's own goal line, last touched by them
            defending = "home" if x["x"] == 0.0 else "away"
            c["corners"] += x["team"] == defending
        if x["type"] != "pass" or x.get("end_x") is None:
            continue
        u0, u1 = toward_goal(x["team"], x["x"]), toward_goal(x["team"], x["end_x"])
        c[f"pass_start_{third(u0)}"] += 1
        c[f"pass_end_{third(u1)}"] += 1
        c[f"pass_forward_{third(u0)}"] += u1 - u0 > 5.0
        c["passes_done"] += x["outcome"] == "success"
        if (third(u0) == "final" and abs(x["y"] - 34.0) > PENALTY_HALF_WIDTH_M
                and u1 >= 105.0 - BOX_M and abs(x["end_y"] - 34.0) <= PENALTY_HALF_WIDTH_M):
            c["crosses"] += 1  # from wider than the box in the final third, into the box
            c["crosses_done"] += x["outcome"] == "success"
    c["passes"] = c["event_pass"]
    for (turned, box, predicted, estimate), shot in shots:
        k = f"shot_{'turned' if turned else 'facing'}_{'box' if box else 'outside'}"
        i = ev.index(shot)
        nxt = ev[i + 1:i + 6]
        goal = any(x["type"] == "goal" for x in nxt[:3])
        blocked = not goal and any(
            x["type"] in ("deflection", "interception", "possession_change")
            and x.get("team") != shot["team"] and x["t"] - shot["t"] < BLOCK_WINDOW_S for x in nxt)
        c[k] += 1
        c[k + "_goals"] += goal
        c[k + "_blocked"] += blocked
        c[k + "_predicted_blocked_x1000"] += round(1000 * predicted)
        c[k + "_estimate_x1000"] += round(1000 * estimate)
    c[f"passes_seed_{seed}"] = c["passes"]
    return c


def report(seeds: list[int], label: str) -> str:
    with ProcessPoolExecutor() as pool:
        rows = list(pool.map(one, seeds))
    t: Counter = Counter()
    for r in rows:
        t.update(r)
    n = len(rows)
    poss = sum(t[f"possession_{k}"] for k in ("own", "middle", "final"))
    starts = sum(t[f"pass_start_{k}"] for k in ("own", "middle", "final"))
    per_seed = ", ".join(str(t[f"passes_seed_{s}"]) for s in seeds)
    lines = [
        f"## {label}", "",
        f"{n} full matches, seeds {seeds[0]} to {seeds[-1]}.", "",
        "| Measure | Per match | Real |", "|---|---|---|",
        f"| Passes | {t['passes'] / n:.0f} (by seed: {per_seed}) | about 900 to 1,000 |",
        f"| Pass completion | {t['passes_done'] / max(1, t['passes']):.3f} | about 0.75 to 0.88 |",
        f"| Shots | {t['event_shot'] / n:.1f} | about 20 to 30 |",
        f"| Goals | {t['event_goal'] / n:.2f} | about 2.5 to 3 |",
        f"| Corners | {t['corners'] / n:.1f} | about 9 to 10 |",
        f"| Crosses into the box (completed) | {t['crosses'] / n:.1f} "
        f"({t['crosses_done'] / max(1, t['crosses']):.0%}) | |",
        f"| Offsides | {t['event_offside'] / n:.1f} | |",
        f"| Ball in play (min) | {t['live_frames'] / FPS / 60 / n:.1f} | about 55 |",
        f"| Final-third entries | {t['final_entries'] / n:.0f} | |",
        f"| Final-third spells ending in a loss / back out of it | {t['spell_lost'] / n:.0f} / "
        f"{t['spell_back_out'] / n:.0f} | |",
        "",
        "| Third | Possession (time on the ball) | Passes starting | Passes ending "
        "| Forward share of passes starting |",
        "|---|---|---|---|---|",
    ]
    for k in ("own", "middle", "final"):
        lines.append(f"| {k} | {t[f'possession_{k}'] / poss:.1%} | {t[f'pass_start_{k}'] / starts:.1%} | "
                     f"{t[f'pass_end_{k}'] / starts:.1%} | "
                     f"{t[f'pass_forward_{k}'] / max(1, t[f'pass_start_{k}']):.0%} |")
    lines += ["",
              "Real: 28.7 percent of Premier League passes ended in the final third in 2019/20 (Opta).", "",
              "| Shots | Count | Shooter's estimate | Scored | Estimated blocked | Blocked |",
              "|---|---|---|---|---|---|"]
    for turned in ("facing", "turned"):
        for where in ("box", "outside"):
            k = f"shot_{turned}_{where}"
            m = t[k]
            if not m:
                continue
            place = "in" if where == "box" else "outside"
            lines.append(f"| {turned}, {place} the box | {m} | {t[k + '_estimate_x1000'] / 1000 / m:.3f} | "
                         f"{t[k + '_goals'] / m:.3f} | {t[k + '_predicted_blocked_x1000'] / 1000 / m:.2f} | "
                         f"{t[k + '_blocked'] / m:.2f} |")
    return "\n".join(lines) + "\n"


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--seeds", default="0-11", help="a range, e.g. 0-11")
    ap.add_argument("--label", default="This engine")
    ap.add_argument("--out", help="write the report here (markdown); otherwise print it")
    a = ap.parse_args()
    lo, hi = (int(v) for v in a.seeds.split("-"))
    text = report(list(range(lo, hi + 1)), a.label)
    if a.out:
        with open(a.out, "w") as f:
            f.write(text)
    print(text)


if __name__ == "__main__":
    main()
