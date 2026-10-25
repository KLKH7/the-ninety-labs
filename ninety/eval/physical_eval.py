"""How far each named player's distance, top speed and sprint count from tracked positions are from
the truth, as the phone and the Companion say them.

Grading only (AGENTS.md): this reads the simulator's truth. A simulated match is spoiled as the
tracker spoils it (ninety/eval/roles_eval.spoil: fragments, a persistent position error, players
missing, swaps). The players are then named exactly as the live path names them (roles.assign,
roles.who and roles.one_track_per_name, lesson 241), and ninety/intel/physical.players sums each
named player's tracks, as the tool does: a piece of track the name rule left unnamed is dropped, as
it is live. Each named player is graded against the true player his name belongs to (the starter
of that role on the sheet), over the same minutes.

    uv run python -m ninety.eval.physical_eval runs/f7-65247ba3 runs/f11-65247ba3 runs/f21-65247ba3 \\
        runs/f8076-65247ba3 --minutes 30 --calibrate --out docs/eval/physical.json

With --calibrate it writes the phone's labels (ninety/intel/physical_calibration.json), each the
worst of every case of every match graded, rounded up: distance and sprints in percent, top speed in
km/h.
"""

from __future__ import annotations

import argparse
import json
import math
import statistics
from collections import defaultdict
from pathlib import Path

from ninety.eval import roles_eval
from ninety.intel import physical, roles
from ninety.intel.teamsheet import Fixture

TEAMS = ("home", "away")


def true_players(rows) -> dict[str, dict]:
    def blank() -> dict:
        return {"top_kmh": 0.0, "sprints": 0, "m": 0.0, "zones": defaultdict(float)}

    out: dict[str, dict] = defaultdict(blank)
    for r in rows:
        p = out[r["track"]]
        p["top_kmh"] = max(p["top_kmh"], r["top_kmh"])
        p["sprints"] += r["sprints"]
        p["m"] += r["m"]
        for z, sec in r["zones"].items():
            p["zones"][z] += sec
    for p in out.values():
        p["zone"] = tuple(max(p["zones"], key=p["zones"].get).split("-")) if p["zones"] else None
    return dict(out)


def grade(run: Path, minutes: float, fragment_s: float, seed: int = 1) -> dict:
    """Per named player: distance tracked / true, top speed tracked − true, and the sprints."""
    meta = json.loads((run / "meta.json").read_text())
    fixture = Fixture(int(meta["seed"]), "LON", "LIS")
    frames, _ = roles_eval.load(run, step=25)
    frames = [f for f in frames if f["t"] <= minutes * 60]
    spoilt, _ = roles_eval.spoil(frames, seed, fragment_s)
    spans: dict[str, tuple[float, float]] = {}
    for f in spoilt:
        for p in f["players"]:
            a, b = spans.get(p["id"], (f["t"], f["t"]))
            spans[p["id"]] = (min(a, f["t"]), max(b, f["t"]))
    people = {}
    for team in TEAMS:
        assigned = roles.assign(spoilt, team)
        for track in {p["id"] for f in spoilt for p in f["players"] if p["team"] == team}:
            people[track] = roles.who(track, team, assigned, fixture, roles.gates())
    people = roles.one_track_per_name(people, spans)
    by: dict[tuple, dict] = defaultdict(dict)
    for r in physical.players(physical.rows(spoilt), people, 1, 10_000):
        by[(r["team"], r["player_is"])][r["metric"]] = r
    true = true_players(physical.rows(frames))
    sheet = {(t, s.role): s.name for t in TEAMS for s in fixture.sheet(t)}
    out = []
    for p in meta["roster"]:
        name = sheet.get((p["team"], p["role"]))
        got = by.get((p["team"], name))
        if not got or p["id"] not in true or not true[p["id"]]["m"]:
            continue
        t = true[p["id"]]
        out.append({
            "player": p["id"],
            "name": name,
            "km_ratio": round(got["player_km"]["value"] * 1000 / t["m"], 3),
            "top_error_kmh": round(got["player_top_kmh"]["value"] - t["top_kmh"], 1),
            "sprints": got["player_sprints"]["value"],
            "sprints_true": t["sprints"],
            "zone_right": (got["player_zone"]["third"], got["player_zone"]["channel"]) == t["zone"]
            if "player_zone" in got and t.get("zone") else None,
        })
    km = [r["km_ratio"] for r in out]
    top = [r["top_error_kmh"] for r in out]
    s_seen, s_true = sum(r["sprints"] for r in out), sum(r["sprints_true"] for r in out)
    return {
        "fragment_s": fragment_s,
        "named": len(out),
        "km_ratio": (
            {"median": round(statistics.median(km), 3), "min": min(km), "max": max(km)} if km else None
        ),
        "top_error_kmh": (
            {"median": round(statistics.median(top), 1), "min": min(top), "max": max(top)} if top else None
        ),
        "sprints": {
            "tracked": s_seen, "true": s_true, "ratio": round(s_seen / s_true, 2) if s_true else None
        },
        "zone_right": {"right": sum(r["zone_right"] is True for r in out),
                       "of": sum(r["zone_right"] is not None for r in out)},
        "rows": out,
    }


def labels(cases: list[dict]) -> dict:
    """The phone's labels: the worst of every case of every match, rounded up."""
    km = max(
        max(abs(c["km_ratio"]["min"] - 1), abs(c["km_ratio"]["max"] - 1)) for c in cases if c["km_ratio"]
    )
    top = max(
        max(abs(c["top_error_kmh"]["min"]), abs(c["top_error_kmh"]["max"]))
        for c in cases
        if c["top_error_kmh"]
    )
    sp = max(abs(c["sprints"]["ratio"] - 1) for c in cases if c["sprints"]["ratio"] is not None)
    return {
        "distance_pct": math.ceil(round(km * 100, 6)),
        "top_kmh": math.ceil(round(top, 6)),
        "sprints_pct": math.ceil(round(sp * 100, 6)),
    }


def main(argv: list[str] | None = None) -> None:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("runs", type=Path, nargs="+")
    ap.add_argument("--minutes", type=float, default=30.0)
    ap.add_argument("--out", type=Path, required=True)
    ap.add_argument("--calibrate", action="store_true", help="write the phone's labels: worst of all runs")
    args = ap.parse_args(argv)
    report: dict = {"minutes": args.minutes, "sprint_kmh": physical.SPRINT_KMH, "runs": {}}
    cases = []
    for run in args.runs:
        got = [grade(run, args.minutes, fs) for fs in roles_eval.FRAGMENT_S]
        report["runs"][run.name] = got
        cases += got
        for g in got:
            print(run.name, g["fragment_s"], g["named"], g["km_ratio"], g["top_error_kmh"], g["sprints"])
    report["labels"] = labels(cases)
    args.out.write_text(json.dumps(report, indent=1) + "\n")
    if args.calibrate:
        body = {**report["labels"], "runs": list(report["runs"]), "source": str(args.out)}
        physical.CALIBRATION.write_text(json.dumps(body, indent=1) + "\n")
    lb = report["labels"]
    lines = [
        "# Named players' distance, top speed and sprints, graded against the truth",
        "",
        "Generated by `uv run python -m ninety.eval.physical_eval "
        + " ".join(f"runs/{n}" for n in report["runs"])
        + f" --minutes {args.minutes:g}`: each simulated match spoiled as the tracker spoils it, the "
        "players named as the live path names them (a piece of track left unnamed is dropped, as live), "
        f"a step a second, sprints above {physical.SPRINT_KMH} km/h held for a second, each named "
        "player graded against the true player of his role.",
        "",
        "| Match | Fragment mean | Named | Distance, tracked / true, median (range) "
        "| Top speed, tracked − true (km/h) | Sprints, tracked / true | Main zone right |",
        "|---|---|---|---|---|---|---|",
    ]
    for name, got in report["runs"].items():
        for g in got:
            k, t, s = g["km_ratio"], g["top_error_kmh"], g["sprints"]
            lines.append(
                f"| {name} | {g['fragment_s']:g} s | {g['named']} | {k['median']} ({k['min']} to {k['max']}) "
                f"| {t['median']} ({t['min']} to {t['max']}) | {s['tracked']} / {s['true']} ({s['ratio']}) "
                f"| {g['zone_right']['right']}/{g['zone_right']['of']} |"
            )
    lines += [
        "",
        f"The phone's labels, the worst of every case above, rounded up: distance ±{lb['distance_pct']}%, "
        f"top speed ±{lb['top_kmh']} km/h, sprints ±{lb['sprints_pct']}%.",
    ]
    args.out.with_suffix(".md").write_text("\n".join(lines) + "\n")


if __name__ == "__main__":
    main()
