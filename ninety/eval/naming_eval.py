"""How often a name said on air is the right man: ninety/intel/naming.py graded on a joined match.

    uv run python -m ninety.eval.naming_eval --clip runs/demo-8080-match \\
        --vision runs/demo-8080-vision-v2 --truth <the seed's simulated run> --out docs/eval/naming.json

Grading reads the answer key, which only an evaluation may (AGENTS.md). The live path's own files
are named exactly as the live path names them (naming.people over tracked.json, then
naming.broadcast_people over association.json); then every tracked player of each camera is given
his true player, the one nearest the track on average over its frames, teams ignored
(ninety/eval/association.true_players). A name is right when that true player is the starter the
team sheet gives the named slot: the same side and the same role in the simulator's roster.

The segments are split before anything is graded (docs/eval/roles.md, pre-registered): the even
segments of the edit are development and set the gates, the odd ones are held out and scored once
with them. Two units are graded: tactical tracks (each track one), and detected events by their
actor (each event one, through its broadcast track), since an event's actor is the name a fan hears.
"""

from __future__ import annotations

import argparse
import json
from itertools import product
from pathlib import Path

from ninety.eval.association import true_players
from ninety.eval.event_score import git_commit, wilson
from ninety.intel import naming, roles
from ninety.intel.match_insights import load_fixture
from ninety.vision.match_join import renumber

# Pre-registered (docs/eval/roles.md, before any grading): the target, the floor, and the grid.
TARGET = 0.95  # design: a name on air is right at least 19 times in 20, the roles.md name target
MIN_NAMED = 30  # design: a setting counts only when it names at least this many of each unit
SHARES = (0.5, 0.6, 0.7, 0.8, 0.9)
SECONDS = (2.0, 5.0, 10.0)
ASSOCIATIONS = (0.75, 0.9, 1.0)


def _jsonl(path: Path) -> list[dict]:
    return [json.loads(x) for x in path.read_text().splitlines() if x.strip()]


def load_truth(run: Path, frames: set[int]) -> tuple[dict[int, dict], dict[str, str]]:
    meta = json.loads((run / "meta.json").read_text())
    role = {r["id"]: r["role"] for r in meta["roster"]}
    truth = {}
    with (run / "frames.jsonl").open() as fh:
        for line in fh:
            f = json.loads(line)
            if f["frame"] in frames:
                truth[f["frame"]] = {"frame": f["frame"], "players": [
                    {k: p[k] for k in ("id", "team", "x", "y")} for p in f["players"]]}
    return truth, role


def broadcast_frames(vision: Path, segments: list[str]) -> list[dict]:
    """Every segment's broadcast tracked frames, ids renumbered as the join renumbered them."""
    out = []
    for k, name in enumerate(segments):
        body = json.loads((vision / name / "broadcast" / "tracked.json").read_text())
        out += [renumber(f, k) for f in body["frames"]]
    return out


def right(w: dict, owner: dict[str, tuple[str, float]], role: dict[str, str], track: str) -> bool:
    true = owner[track][0]
    return true[0] == w["team"][0] and role.get(true) == w["role"]


def score(named: list[bool]) -> dict:
    n, k = len(named), sum(named)
    return {"named": n, "right": k, "precision": round(k / n, 3) if n else None,
            "ci": wilson(k, n) if n else None}


def grade(tactical, broadcast, events, owner_v, owner_b, role, split) -> dict:
    tracks = [t for t, w in tactical.items() if split(t)]
    named_t = [right(w, owner_v, role, t) for t, w in tactical.items() if split(t) and w["name"]]
    actors = [e["player"] for e in events if e.get("player") in broadcast and split(e["player"])]
    named_e = [right(broadcast[a], owner_b, role, a) for a in actors if broadcast[a]["name"]]
    return {
        "tracks": len(tracks), "track_names": score(named_t),
        "track_coverage": round(len(named_t) / len(tracks), 3) if tracks else None,
        "events": len(actors), "event_names": score(named_e),
        "event_coverage": round(len(named_e) / len(actors), 3) if actors else None,
    }


def main(argv: list[str] | None = None) -> None:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--clip", type=Path, required=True)
    ap.add_argument("--vision", type=Path, required=True)
    ap.add_argument("--truth", type=Path, required=True)
    ap.add_argument("--out", type=Path, default=Path("docs/eval/naming.json"))
    ap.add_argument("--calibration", type=Path, default=naming.CALIBRATION)
    args = ap.parse_args(argv)
    clip = args.clip
    frames = json.loads((clip / "tracked.json").read_text())["frames"]
    association = json.loads((clip / "association.json").read_text())["tracks"]
    events = _jsonl(clip / "detected.jsonl")
    fixture = load_fixture(clip / "clip.json")
    segments = sorted(p.name for p in args.vision.iterdir() if (p / "broadcast" / "tracked.json").exists())
    b_frames = broadcast_frames(args.vision, segments)
    truth, role = load_truth(args.truth, {f["frame"] for f in frames} | {f["frame"] for f in b_frames})
    owner_v = true_players([f for f in frames if f["frame"] in truth], truth)
    owner_b = true_players([f for f in b_frames if f["frame"] in truth], truth)
    dev = lambda t: naming.segment(t) % 2 == 0  # noqa: E731
    held = lambda t: naming.segment(t) % 2 == 1  # noqa: E731

    assigned = {team: naming.assign(frames, team) for team in ("home", "away")}
    rows = []
    for share, secs, assoc in product(SHARES, SECONDS, ASSOCIATIONS):
        gate = {"share": share, "seconds": secs, "association": assoc}
        tv = naming.people(frames, fixture, gate, assigned=assigned)
        bp = naming.broadcast_people(association, tv, fixture, gate)
        rows.append({"gate": gate, "dev": grade(tv, bp, events, owner_v, owner_b, role, dev)})

    def passes(r):
        d = r["dev"]
        return all(d[u]["named"] >= MIN_NAMED and d[u]["precision"] >= TARGET
                   for u in ("track_names", "event_names"))

    ok = [r for r in rows if passes(r)]
    # The most events named on development; ties go to the stricter gate.
    chosen = max(ok, key=lambda r: (r["dev"]["event_names"]["named"], r["gate"]["share"],
                                    r["gate"]["seconds"], r["gate"]["association"])) if ok else None
    out = {"commit": git_commit(), "clip": str(clip), "truth": str(args.truth), "target": TARGET,
           "min_named": MIN_NAMED, "grid": rows, "chosen": chosen and chosen["gate"]}
    if chosen:
        gate = chosen["gate"]
        tv = naming.people(frames, fixture, gate, assigned=assigned)
        bp = naming.broadcast_people(association, tv, fixture, gate)
        out["held_out"] = grade(tv, bp, events, owner_v, owner_b, role, held)
        out["all"] = grade(tv, bp, events, owner_v, owner_b, role, lambda t: True)
    # Today's naming (roles.assign over the clip, its calibrated gate), for comparison only.
    old = {}
    for team in ("home", "away"):
        got = roles.assign(frames, team)
        for t in {p["id"] for f in frames for p in f["players"] if p["team"] == team}:
            old[t] = roles.who(t, team, got, fixture, roles.gates())
    spans = {}
    for f in frames:
        for p in f["players"]:
            a, b = spans.get(p["id"], (f["t"], f["t"]))
            spans[p["id"]] = (min(a, f["t"]), max(b, f["t"]))
    old = roles.one_track_per_name(old, spans)
    for w in old.values():
        w.setdefault("role", None)
    old_b = naming.broadcast_people(association, old, fixture, {"association": 0.0})
    out["before"] = {s: grade(old, old_b, events, owner_v, owner_b, role, f)
                     for s, f in (("dev", dev), ("held_out", held), ("all", lambda t: True))}
    args.out.write_text(json.dumps(out, indent=1) + "\n")
    if chosen:
        args.calibration.write_text(json.dumps({**chosen["gate"], "target": TARGET,
                                                "source": "docs/eval/naming.json"}, indent=1) + "\n")
    print(json.dumps({k: out.get(k) for k in ("chosen", "held_out", "all", "before")}, indent=1))


if __name__ == "__main__":
    main()
