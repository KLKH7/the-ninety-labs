"""How far a track's role share can be trusted: role assignment graded on simulated matches.

Grading reads the answer key, which only an evaluation may (AGENTS.md): the simulator's frames give
every player's true position and its roster his role. Tracked data is made from them the way the
tracker spoils it, then given to `ninety.intel.roles.assign` exactly as the live path would:

- every player is split into tracks: a track ends after a draw from an exponential with mean
  FRAGMENT_S seconds, and a new track id starts (the tracker loses a player and finds him again);
- each track's position is off by an error that persists, a random walk pulled back to zero,
  scaled so its 90th-percentile size is the tracker's measured 1.26 m (ninety/intel/scene.
  POSITION_ERROR_M): a misjudgement held, not a fresh draw each frame (docs/LESSONS.md, lesson 135);
- in each frame each player is missing with probability MISSING (occluded, out of shot);
- when two team-mates come within SWAP_M of each other, their tracks swap with probability SWAP_P
  (the tracker's identity switch), so a track can follow one player and then another. A track is
  graded against the player it followed most.

Each track's assigned role is graded against its player's roster role, and its line (goalkeeper,
defender, midfielder, forward) against his line. The gates are the least share at which the
precision of the tracks at or above it reaches its target, over at least MIN_TRACKS tracks, on the
development matches; the held-out match is scored once with those gates (docs/eval/roles.md).

    uv run python -m ninety.eval.roles_eval --dev runs/u7 runs/seed11 --held-out runs/c21
"""

from __future__ import annotations

import argparse
import json
import math
import random
from collections import Counter, defaultdict
from pathlib import Path

from ninety.intel import roles
from ninety.intel.scene import POSITION_ERROR_M
from ninety.intel.teamsheet import LINE
from ninety.sim import fmath

# Design, fixed before any run was graded: the targets a name, a position and a line must reach.
# A name is the strongest claim a fan hears, so it asks the most of the share.
TARGETS = {"name": 0.95, "role": 0.90, "line": 0.95}
MIN_TRACKS = 50  # design: a gate opens only on at least this many tracks at or above it
FRAGMENT_S = (30.0, 10.0, 120.0)  # design: the first sets the gates; the others are reported
MISSING = 0.05  # design: one player in twenty unseen in a frame
SIGMA_M = POSITION_ERROR_M / math.sqrt(2 * fmath.log(10))  # 2-D error whose 90th percentile is 1.26 m
PULL = 0.02  # design: the error's pull back to zero per sampled frame (a few seconds' memory)
# Design: two team-mates within this of each other may be confused by the tracker (about the
# strict match radius, docs/GROUNDING.md S3), and are, at that moment, with this chance.
SWAP_M = 1.5
SWAP_P = 0.5
WINDOW_MIN = 15  # design: roles are assigned over each 15-minute window, the stats' window (S4)
STEP = roles.STEP_FRAMES


def load(run: Path, step: int = STEP) -> tuple[list[dict], dict[str, str]]:
    meta = json.loads((run / "meta.json").read_text())
    if "roster" in meta:
        role = {r["id"]: r["role"] for r in meta["roster"]}
    else:  # an older run's meta has no roster: ids follow the engine's formation order (h1 is its GK)
        from ninety.sim.engine import FORMATION

        role = {f"{t}{i}": r for t in "ha" for i, (r, _, _) in enumerate(FORMATION, 1)}
    frames = []
    with (run / "frames.jsonl").open() as fh:
        for line in fh:
            f = json.loads(line)
            if f["frame"] % step == 0:
                frames.append(
                    {
                        "frame": f["frame"],
                        "t": f["t"],
                        "ball": f["ball"],
                        "players": [{k: p[k] for k in ("id", "team", "x", "y")} for p in f["players"]],
                    }
                )
    return frames, role


def spoil(frames: list[dict], seed: int, fragment_s: float) -> tuple[list[dict], dict[str, str]]:
    """Tracked-like frames, and which true player each track is."""
    rng = fmath.Random(seed)  # portable draws: the report is the same on every machine (lesson 46)
    state: dict[str, dict] = {}
    seen: dict[str, Counter] = defaultdict(Counter)
    close: set[frozenset] = set()
    n = 0
    out = []
    prev_t = frames[0]["t"] if frames else 0.0
    for f in frames:
        dt = max(f["t"] - prev_t, 0.0)
        prev_t = f["t"]
        pull = 1 - fmath.exp(dt / (STEP / 25) * fmath.log(1 - PULL)) if dt else 0.0  # PULL is per 0.2 s
        k = math.sqrt(pull * (2 - pull))  # keeps the walk's spread at SIGMA_M per axis
        players = []
        _swap(f["players"], state, close, rng)
        for p in f["players"]:
            s = state.get(p["id"])
            if s is None or s["left"] <= 0:
                n += 1
                s = {
                    "track": f"{p['team'][0]}-t{n}",
                    "left": -fragment_s * fmath.log(1.0 - rng.random()),  # exponential, mean fragment_s
                    "ex": rng.gauss(0, SIGMA_M),
                    "ey": rng.gauss(0, SIGMA_M),
                }
                state[p["id"]] = s
            seen[s["track"]][p["id"]] += 1  # the track's owner is whom it followed most
            s["left"] -= dt
            s["ex"] = (1 - pull) * s["ex"] + k * rng.gauss(0, SIGMA_M)
            s["ey"] = (1 - pull) * s["ey"] + k * rng.gauss(0, SIGMA_M)
            if rng.random() < MISSING:
                continue
            players.append(
                {
                    "id": s["track"],
                    "team": p["team"],
                    "x": min(105.0, max(0.0, p["x"] + s["ex"])),
                    "y": min(68.0, max(0.0, p["y"] + s["ey"])),
                }
            )
        out.append({**f, "players": players})
    owner = {track: c.most_common(1)[0][0] for track, c in seen.items()}
    return out, owner


def _swap(players: list[dict], state: dict, close: set, rng: random.Random) -> None:
    """The tracker's identity switch: when two team-mates come within SWAP_M, at the moment they do,
    their tracks swap with probability SWAP_P, each track going on with the other player."""
    now = set()
    for i, a in enumerate(players):
        for b in players[i + 1 :]:
            if a["team"] == b["team"] and math.hypot(a["x"] - b["x"], a["y"] - b["y"]) < SWAP_M:
                pair = frozenset((a["id"], b["id"]))
                now.add(pair)
                if pair not in close and a["id"] in state and b["id"] in state and rng.random() < SWAP_P:
                    state[a["id"]], state[b["id"]] = state[b["id"]], state[a["id"]]
    close.clear()
    close.update(now)


def graded(frames: list[dict], truth_role: dict[str, str], seed: int, fragment_s: float) -> list[dict]:
    spoilt, owner = spoil(frames, seed, fragment_s)
    rows = []
    t_end = frames[-1]["t"] if frames else 0
    for w0 in range(0, int(t_end // 60) + 1, WINDOW_MIN):
        window = [f for f in spoilt if w0 * 60 <= f["t"] < (w0 + WINDOW_MIN) * 60]
        for team in ("home", "away"):
            for track, r in roles.assign(window, team).items():
                true = truth_role[owner[track]]
                rows.append(
                    {
                        "share": r["share"],
                        "frames": r["frames"],
                        "role_ok": r["role"] == true,
                        "line_ok": LINE[r["role"]] == LINE[true],
                        "role": r["role"],
                        "true": true,
                    }
                )
    return rows


def gate(rows: list[dict], key: str, target: float) -> float | None:
    """The least share s with precision at or above `target` over the tracks with share >= s."""
    ok = "line_ok" if key == "line" else "role_ok"
    for s in sorted({r["share"] for r in rows}):
        above = [r for r in rows if r["share"] >= s]
        if len(above) < MIN_TRACKS:
            return None
        if sum(r[ok] for r in above) / len(above) >= target:
            return s
    return None


def summary(rows: list[dict], gates: dict) -> dict:
    out = {
        "tracks": len(rows),
        "role_ok": sum(r["role_ok"] for r in rows),
        "line_ok": sum(r["line_ok"] for r in rows),
    }
    for key, s in gates.items():
        ok = "line_ok" if key == "line" else "role_ok"
        above = [r for r in rows if s is not None and r["share"] >= s]
        out[key] = {
            "gate": s,
            "said": len(above),
            "right": sum(r[ok] for r in above),
            "precision": round(sum(r[ok] for r in above) / len(above), 3) if above else None,
        }
    out["confusions"] = Counter(f"{r['true']}->{r['role']}" for r in rows if not r["role_ok"]).most_common(6)
    return out


def main(argv: list[str] | None = None) -> None:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--dev", type=Path, nargs="+", required=True)
    ap.add_argument("--held-out", type=Path, nargs="+", required=True)
    ap.add_argument("--out", type=Path, default=Path("docs/eval/roles.json"))
    ap.add_argument("--calibration", type=Path, default=roles.CALIBRATION)
    args = ap.parse_args(argv)
    loaded = {run: load(run) for run in [*args.dev, *args.held_out]}
    report: dict = {
        "targets": TARGETS,
        "min_tracks": MIN_TRACKS,
        "missing": MISSING,
        "sigma_m": round(SIGMA_M, 3),
        "window_min": WINDOW_MIN,
        "dev": [str(r) for r in args.dev],
        "held_out": [str(r) for r in args.held_out],
        "by_fragment": {},
    }
    gates = None
    for fs in FRAGMENT_S:
        dev = [row for k, run in enumerate(args.dev) for row in graded(*loaded[run], 1000 + k, fs)]
        if gates is None:  # the first fragment length sets the gates, on the development matches only
            gates = {key: gate(dev, key, target) for key, target in TARGETS.items()}
        held = [row for k, run in enumerate(args.held_out) for row in graded(*loaded[run], 2000 + k, fs)]
        report["by_fragment"][str(fs)] = {"dev": summary(dev, gates), "held_out": summary(held, gates)}
        print(fs, json.dumps(report["by_fragment"][str(fs)]["held_out"]))
    report["gates"] = gates
    args.out.write_text(json.dumps(report, indent=1) + "\n")
    args.calibration.write_text(
        json.dumps({**gates, "fragment_s": FRAGMENT_S[0], "source": str(args.out)}, indent=1) + "\n"
    )
    args.out.with_suffix(".md").write_text(markdown(report))
    print("gates", gates)


MD_HEAD = """# Who a tracked player is: role assignment graded on simulated matches

Generated by `uv run python -m ninety.eval.roles_eval --dev runs/u7 runs/seed11 --held-out runs/c21`
(seeds 7 and 11 set the gates, 21 is held out). The engine's frames are spoiled as the tracker spoils
them: tracks broken after an exponential time, a persistent position error ({sigma} m a side), {missing}
of players missing a frame, and team-mates within 1.5 m swapping tracks half the time. Roles are
assigned over each {window}-minute window. Targets, fixed before the run: name {t_name}, position
{t_role}, line {t_line}, over at least {min_tracks} tracks.

Gates (the share at or above which each may be said): {gates}.

| Fragment mean | Split | Tracks | Role right | Line right | Named (precision) | Confusions |
|---|---|---|---|---|---|---|
"""
MD_TAIL = """
Reading: on the engine's football almost every track is given its right role, so the gates sit at
the lowest share seen. That says the engine's players hold their formation places (they rarely swap
or cross), not that role inference is this good on football with fluid positions. Before the demo,
the same grading runs on the demo match's own tracked output against its ground truth.
"""


def markdown(r: dict) -> str:
    rows = []
    for fs, both in r["by_fragment"].items():
        for split in ("dev", "held_out"):
            m = both[split]
            confusions = ", ".join(f"{a} {n}" for a, n in m["confusions"])
            named = f"{m['name']['said']} ({m['name']['precision']})"
            rows.append(
                f"| {float(fs):g} s | {split} | {m['tracks']} | {m['role_ok']} | {m['line_ok']} | {named} "
                f"| {confusions} |"
            )
    head = MD_HEAD.format(
        sigma=r["sigma_m"],
        missing=f"{r['missing']:.0%}",
        window=r["window_min"],
        t_name=r["targets"]["name"],
        t_role=r["targets"]["role"],
        t_line=r["targets"]["line"],
        min_tracks=r["min_tracks"],
        gates=r["gates"],
    )
    return head + "\n".join(rows) + "\n" + MD_TAIL


if __name__ == "__main__":
    main()
