"""Interceptions, pressure and tackles on validation: development numbers on stand-in observations.

    uv run python -m ninety.eval.turnover_standin --matches <dir of seed920101 ...> \\
        [--rendered <rendered clip> ...] [--set docs/eval/possession-set.json] --out docs/eval/turnovers-dev

The plans (docs/eval/interception-plan.md, pressure-plan.md, tackle-plan.md) were committed before
this ran. It reads the answer key, so it is an evaluation; nothing on the live path imports it.

- M0: the interception stand-in against the truth, on every true pass an opponent controlled in
  the validation matches, with the detector's own speed and direction code on the true ball path.
- M1: the possession set's validation windows, cut from the same matches, as observations: every
  player at his true place plus noise (sigma NOISE_M), his kit one colour per side, the ball too.
- M2: rendered validation clips, the same, with only what the broadcast shows (visibility above 0).

The detector runs unchanged on these rows and event_score grades it. These are not vision numbers:
no detector checkpoint is on the machine this was written for.
"""

from __future__ import annotations

import argparse
import json
import math
from pathlib import Path

from ninety.eval import event_score
from ninety.eval.event_score import wilson
from ninety.sim import fmath
from ninety.vision import events as ev
from ninety.vision import track as tr
from ninety.vision.track import BallPoint
from ninety.vision.tracked_frames import player_id

FPS = tr.FPS

ROOT = Path(__file__).resolve().parents[2]
SET = ROOT / "docs" / "eval" / "possession-set.json"  # written by #299 (ninety/eval/possession_set.py)
# The players' measured median position error on ours-v2's validation clips (0.221 m,
# docs/eval/attribution-derive.json) over a 2-D Gaussian's median radius, sqrt(2 ln 2) sigma.
NOISE_M = round(0.221 / math.sqrt(2 * fmath.log(2)), 3)
assert NOISE_M == 0.188
KIT = {"home": [200.0, 30.0, 40.0], "away": [40.0, 60.0, 190.0]}
SCORE = 0.9  # every stand-in box: above the detector's 0.5 floor, so the gate is not what is measured
NOISE_SEED = 1
KINDS = ("interception", "pressure", "tackle", "possession_change", "pass")
# Amendment 1 (docs/eval/interception-plan.md): the error's shares of variance that are one offset per
# clip, one shift per frame shared by every object in it, and each object's own. M1 is all object.
SHARES = {"m1": (0.0, 0.0, 1.0), "m3": (1.0, 0.0, 0.0), "m4": (1 / 3, 1 / 3, 1 / 3)}
DECIDES = "m4"  # the run each plan's bar is read on, from amendment 1


def read_jsonl(path: Path) -> list[dict]:
    return [json.loads(x) for x in path.read_text().splitlines() if x.strip()]


def _ball_points(frames: list[dict]) -> list[BallPoint]:
    return [BallPoint(f["frame"], f["ball"]["x"], f["ball"]["y"], 1.0) for f in frames]


def m0(matches: list[Path]) -> dict:
    """Each stand-in's verdict on every true pass an opponent controlled, against the engine's."""
    rows = []
    for m in matches:
        events = read_jsonl(m / "events.jsonl")
        frames = read_jsonl(m / "frames.jsonl")
        first = frames[0]["frame"]
        path = _ball_points(frames)
        caught = {(e["frame"], e["player"]) for e in events if e["type"] == "interception"}
        for e in events:
            if e["type"] != "pass" or not e.get("interceptor"):
                continue
            i = e["frame"] - first
            speed, u = ev._speed_kmh(path, i), ev._direction(path, i)
            # The interception is written where and when he controls it: at the pass's end, the
            # first interception of his after the kick.
            later = [f for f, p in caught if p == e["interceptor"] and f >= e["frame"]]
            truth = bool(later) and any(
                x["type"] == "interception" and x["frame"] == min(later) and x["x"] == e["end_x"]
                and x["y"] == e["end_y"] for x in events)
            row = {"seed": m.name, "frame": e["frame"], "truth": truth,
                   "speed_mps": None if speed is None else round(speed / 3.6, 2)}
            for name, pace in ev.STAND_INS.items():
                row[name] = None if speed is None or u is None else ev.in_the_lane(
                    (path[i].x, path[i].y), u, speed / 3.6, (e["end_x"], e["end_y"]), pace)
            rows.append(row)
    known = [r for r in rows if r["pace6"] is not None]
    out = {"passes": len(rows), "judged": len(known), "unjudged": len(rows) - len(known),
           "true_interceptions": sum(r["truth"] for r in known), "rules": {}}
    rules = {**{n: (lambda r, n=n: r[n]) for n in ev.STAND_INS},
             "all_interceptions": lambda r: True, "none": lambda r: False}
    for name, f in rules.items():
        called_rec = sum(1 for r in known if r["truth"] and not f(r))
        called_int = sum(1 for r in known if not r["truth"] and f(r))
        k = called_rec + called_int
        out["rules"][name] = {"disagree": k, "of": len(known),
                              "rate": round(k / len(known), 3) if known else None,
                              "wilson95": wilson(k, len(known)), "interception_called_recovery": called_rec,
                              "recovery_called_interception": called_int}
    cands = list(ev.STAND_INS)
    best = min(cands, key=lambda n: (out["rules"][n]["disagree"], cands.index(n)))
    floor = min(out["rules"][n]["disagree"] for n in ("all_interceptions", "none"))
    out["chosen"] = best
    out["beats_constant_rules"] = out["rules"][best]["disagree"] < floor
    return out


def observations(frames: list[dict], sigma: float, broadcast: bool, seed: int = NOISE_SEED,
                 shares: tuple[float, float, float] = SHARES["m1"], ids: list | None = None) -> list[dict]:
    """Observation rows (ninety.vision.observe's shape) from answer-key frames: each player and the
    ball at its true place plus Gaussian noise, a kit colour per side, the camera ok. With
    `broadcast`, only what the picture shows (visibility above 0), with the drawn boxes. The noise's
    per-axis variance sigma² is split by `shares` into one offset for the clip, one shift per frame
    shared by every object, and each object's own (amendment 1). The shared parts come from their
    own generator, so the objects' draws, and M1's rows, are the same whatever the shares. `ids`, if
    given, gets each row's player ids in order: for grading only, never in the rows the detector reads."""
    rng = fmath.Random(seed)  # portable draws: the report is the same on every machine (lesson 46)
    shared = fmath.Random(f"{seed}-shared")
    clip_sd, frame_sd, own_sd = (sigma * math.sqrt(s) for s in shares)
    bx, by = shared.gauss(0, clip_sd), shared.gauss(0, clip_sd)
    rows = []
    for f in frames:
        fx, fy = bx + shared.gauss(0, frame_sd), by + shared.gauss(0, frame_sd)
        players, who = [], []
        for k, p in enumerate(f["players"]):
            if broadcast and not (p.get("bbox") and p.get("visibility", 0) > 0):
                continue
            box = p["bbox"] if broadcast else [20 * k, 0, 20 * k + 10, 30]
            players.append({"bbox": box, "score": SCORE, "x": p["x"] + fx + rng.gauss(0, own_sd),
                            "y": p["y"] + fy + rng.gauss(0, own_sd), "rgb": KIT[p["team"]]})
            who.append(p["id"])
        if ids is not None:
            ids.append(who)
        b, ball = f["ball"], []
        if not broadcast or (b.get("bbox") and b.get("visibility", 0) > 0):
            box = b["bbox"] if broadcast else [0, 500, 8, 508]
            ball.append({"bbox": box, "score": SCORE, "x": b["x"] + fx + rng.gauss(0, own_sd),
                         "y": b["y"] + fy + rng.gauss(0, own_sd)})
        rows.append({"frame": f["frame"], "t": f["t"], "camera": {"ok": True}, "players": players,
                     "ball": ball})
    return rows


def window(match: Path, start: float, seconds: float) -> tuple[list[dict], list[dict]]:
    """The window's frames and events from a simulated match, as a clip cut from it holds them
    (whole frames from the start, as the possession set's windows). Only the window's lines of the
    match's frames.jsonl are parsed: each starts with its frame number, written in order."""
    lo, hi = round(start * FPS), round((start + seconds) * FPS) - 1
    frames = []
    with open(match / "frames.jsonl") as fh:
        for line in fh:
            k = int(line[len('{"frame": '):line.index(",")])
            if k > hi:
                break
            if k >= lo:
                frames.append(json.loads(line))
    events = [e for e in read_jsonl(match / "events.jsonl") if lo <= e["frame"] <= hi]
    return frames, events


def diagnostics(truth: list[dict], detected: list[dict], report: dict, frames: list[dict],
                history: list[dict]) -> dict:
    """What the plans ask for beyond the counts."""
    pairs = report["strict"]["pairs"]
    matched = {p["detected_id"]: p["truth_id"] for p in pairs}
    by_id = {e["id"]: e for e in truth}
    pc = [e for e in truth if e["type"] == "possession_change"]
    ints = {(e["frame"], e["team"]) for e in truth if e["type"] == "interception"}
    recoveries = [e for e in pc if (e["frame"], e["team"]) not in ints]
    det_int = [d for d in detected if d["type"] == "interception"]
    on_recovery = sum(1 for d in det_int if d["id"] not in matched and any(
        r["team"] == d["team"] and abs(r["t"] - d["t"]) <= event_score.WINDOW_S for r in recoveries))
    found = {matched[d["id"]] for d in det_int if d["id"] in matched}
    det_pc = [d for d in detected if d["type"] == "possession_change"]
    only_pc = sum(1 for e in truth if e["type"] == "interception" and e["id"] not in found and any(
        d["team"] == e["team"] and abs(d["t"] - e["t"]) <= event_score.WINDOW_S for d in det_pc))
    tk = [d for d in detected if d["type"] == "tackle"]
    out_right = [d["outcome"] == by_id[matched[d["id"]]]["outcome"] for d in tk
                 if d["id"] in matched and by_id[matched[d["id"]]]["outcome"] is not None]
    kept = [d for d in tk if d["confidence"] > ev.HELD]
    passes_at_tackle = sum(1 for d in tk
                           if any(p["type"] == "pass" and p["frame"] == d["frame"] for p in detected))
    true_tk = [e for e in truth if e["type"] == "tackle"]
    found_tk = {matched[d["id"]] for d in tk if d["id"] in matched}
    # poke() knocks the ball off the holder: the engine writes his deflection at the tackle's frame.
    poke = {(e["frame"], e["player"]) for e in truth if e["type"] == "deflection"}
    missed_kind = {"knocked_loose": 0, "taken_off_a_dribble": 0}
    for e in true_tk:
        if e["id"] not in found_tk:
            kind = "knocked_loose" if (e["frame"], e["receiver"]) in poke else "taken_off_a_dribble"
            missed_kind[kind] += 1
    # A false pressure in the clip's first 8 s whose side the engine had written one for in the 8 s
    # before the window: the memory the clip cannot see.
    t0 = frames[0]["t"]
    pre = [e for e in history if e["type"] == "pressure" and t0 - ev.PRESSURE_REPEAT_S <= e["t"] < t0]
    false_pr = [d for d in detected if d["type"] == "pressure" and d["id"] not in matched]
    memory = sum(1 for d in false_pr
                 if d["t"] - t0 <= ev.PRESSURE_REPEAT_S and any(e["team"] == d["team"] for e in pre))
    # Amendment 2's risk: a pass played on by a passer running its way reads slow relative to him.
    true_passes = [e for e in truth if e["type"] == "pass"]
    on_pass = sum(1 for d in tk if d["id"] not in matched and any(
        e["team"] != d["team"] and abs(e["t"] - d["t"]) <= event_score.WINDOW_S for e in true_passes))
    return {"interceptions_on_a_true_recovery": on_recovery,
            "false_tackles_on_a_true_pass": on_pass,
            "true_interceptions_detected_only_as_possession_change": only_pc,
            "tackle_outcome": {"right": sum(out_right), "of": len(out_right)},
            "tackles_kept_through_contact": len(kept), "tackles_held": len(tk) - len(kept),
            "tackles_kept_matched": sum(1 for d in kept if d["id"] in matched),
            "tackles_held_matched": sum(1 for d in tk if d not in kept and d["id"] in matched),
            "detected_passes_at_a_detected_tackle": passes_at_tackle,
            "tackles_missed_by_kind": missed_kind,
            "false_pressures_from_unseen_memory": memory, "false_pressures": len(false_pr)}


def fast_at_feet(rows: list[dict], frames: list[dict], ids: list[list[str]]) -> dict:
    """Of the frames where a player truly has the ball at his feet and the ball is seen, how many the
    tackle rule reads as a strike: its speed relative to him (`events.relative_speed`, tackle plan
    amendment 2) at ARRIVE_MPS or faster. He is a track of his own stand-in places, by his true id."""
    path = tr.ball_path(rows)
    index = {p.frame: i for i, p in enumerate(path)}
    tracks: dict[str, tr.Track] = {}
    for r, who in zip(rows, ids, strict=True):
        for d, pid in zip(r["players"], who, strict=True):
            t = tracks.setdefault(pid, tr.Track(0))
            t.frames.append(r["frame"])
            t.xy.append((d["x"], d["y"]))
    speeds = [ev.relative_speed(path, index[f["frame"]], tracks[f["possessor"]]) for f in frames
              if f.get("possessor") in tracks and f["frame"] in index]
    return {"fast": sum(1 for v in speeds if v is not None and v >= ev.ARRIVE_MPS),
            "of": sum(1 for v in speeds if v is not None)}


def score_clip(name: str, frames: list[dict], truth: list[dict], sigma: float, broadcast: bool,
               history: list[dict] | None = None, shares: tuple[float, float, float] = SHARES["m1"]) -> dict:
    ids: list[list[str]] = []
    rows = observations(frames, sigma, broadcast, shares=shares, ids=ids)
    detected, _ = ev.detect(rows, kinds=ev.TURNOVERS)
    report = event_score.score(truth, detected, frames)
    clip = {"clip": name, "events": {}}
    if shares != SHARES["m1"]:
        clip["fast_at_feet"] = fast_at_feet(rows, frames, ids)
    clip["diagnostics"] = diagnostics(truth, detected, report, frames, history or [])
    for rule in ("strict", "lenient", "time_only"):
        clip["events"][rule] = {k: {m: v[m] for m in ("true", "detected", "tp", "fp", "fn")}
                                for k, v in report[rule]["per_type"].items() if k in KINDS}
    # The side is read once per clip (lesson 172): a clip read the wrong way round fails every event.
    tracks = tr.track_players(rows)
    tr.assign_teams(tracks)
    sided = [t for t in tracks if t.team]
    clip["sides_right"] = sum(1 for t in sided if KIT[t.team] == list(t.rgb[0]))
    clip["sides_of"] = len(sided)
    clip["names"] = names(detected, report, truth, frames, tracks)
    return clip


def names(detected: list[dict], report: dict, truth: list[dict], frames: list[dict], tracks) -> dict:
    """The new kinds' named players on matched events, against the answer key: each named track is
    the true player nearest to it in that frame (lesson 146)."""
    by_id = {e["id"]: e for e in truth}
    matched = {p["detected_id"]: by_id[p["truth_id"]] for p in report["strict"]["pairs"]}
    of_id = {player_id(t): t for t in tracks if t.team}
    at = {f["frame"]: f for f in frames}
    out = {"right": 0, "wrong": 0, "null": 0}
    for d in detected:
        if d["type"] not in ev.TURNOVERS or d["id"] not in matched:
            continue
        for k in ("player", "receiver"):
            want = matched[d["id"]].get(k)
            if not want:
                continue
            t = of_id.get(d.get(k) or "")
            q = t.at(d["frame"]) if t else None
            if q is None:
                out["null"] += 1
                continue
            near = min(at[d["frame"]]["players"], key=lambda p: math.hypot(p["x"] - q[0], p["y"] - q[1]))
            out["right" if near["id"] == want else "wrong"] += 1
    return out


def pooled(clips: list[dict], rule: str) -> dict:
    out = {}
    for k in KINDS:
        rows = [c["events"][rule][k] for c in clips if k in c["events"][rule]]
        tp, fp, fn = (sum(r[x] for r in rows) for x in ("tp", "fp", "fn"))
        out[k] = {"true": tp + fn, "detected": tp + fp, "tp": tp,
                  "precision": round(tp / (tp + fp), 3) if tp + fp else None,
                  "recall": round(tp / (tp + fn), 3) if tp + fn else None,
                  "precision_wilson95": wilson(tp, tp + fp), "recall_wilson95": wilson(tp, tp + fn)}
    return out


def pooled_diagnostics(clips: list[dict]) -> dict:
    out: dict = {}
    for c in clips:
        for k, v in c["diagnostics"].items():
            if isinstance(v, dict):
                out.setdefault(k, {})
                for kk, vv in v.items():
                    out[k][kk] = out[k].get(kk, 0) + vv
            else:
                out[k] = out.get(k, 0) + v
    return out


def main(argv: list[str] | None = None) -> None:
    ap = argparse.ArgumentParser(description="Turnover events on validation stand-in observations.")
    ap.add_argument("--matches", type=Path, required=True, help="folder of simulated validation matches")
    ap.add_argument("--rendered", type=Path, nargs="*", default=[], help="rendered validation clips")
    ap.add_argument("--out", type=Path, required=True)
    ap.add_argument("--set", type=Path, default=SET, help="the possession set's manifest")
    ap.add_argument("--m0-only", action="store_true")
    a = ap.parse_args(argv)
    manifest = json.loads(a.set.read_text())
    clips = [c for c in manifest["clips"] if c["split"] == "validation"]
    matches = sorted(a.matches / f"seed{s}" for s in sorted({c["seed"] for c in clips}))
    report = {"plans": [f"docs/eval/{k}-plan.md" for k in ("interception", "pressure", "tackle")],
              "label": "development numbers on stand-in observations (validation only), not vision results",
              "commit": event_score.git_commit(), "noise_m": NOISE_M, "m0": m0(matches)}
    if not a.m0_only:
        runs = [(NOISE_M, SHARES["m1"], "m1_", "m2_", "_noise"), (0.0, SHARES["m1"], "m1_", "m2_", "_exact"),
                *((NOISE_M, SHARES[k], f"{k}_windows", f"{k}_rendered", "") for k in ("m3", "m4"))]
        for sigma, shares, win, ren, tag in runs:
            m1 = []
            for c in clips:
                m = a.matches / f"seed{c['seed']}"
                frames, truth = window(m, c["start"], c["seconds"])
                history = read_jsonl(m / "events.jsonl")
                name = f"seed{c['seed']}-{round(c['start'] * 25)}"
                m1.append(score_clip(name, frames, truth, sigma, False, history, shares))
            m2 = []
            for d in a.rendered:
                frames, truth = read_jsonl(d / "frames.jsonl"), read_jsonl(d / "events.jsonl")
                seed = int(d.name.split("-")[0].removeprefix("seed"))
                history = read_jsonl(a.matches / f"seed{seed}" / "events.jsonl")
                m2.append(score_clip(d.name, frames, truth, sigma, True, history, shares))
            for name, cl in ((win.rstrip("_"), m1), (ren.rstrip("_"), m2)):
                report[f"{name}{tag}"] = {
                    "clips": len(cl),
                    **{rule: pooled(cl, rule) for rule in ("strict", "lenient", "time_only")},
                    "diagnostics": pooled_diagnostics(cl),
                    "names": {k: sum(c["names"][k] for c in cl) for k in ("right", "wrong", "null")},
                    "sides_right": [sum(c["sides_right"] for c in cl), sum(c["sides_of"] for c in cl)],
                    "per_clip": [{k: v for k, v in c.items() if k != "detected"} for c in cl]}
                if shares != SHARES["m1"]:
                    report[f"{name}{tag}"]["shares"] = list(shares)
                    report[f"{name}{tag}"]["fast_at_feet"] = {
                        k: sum(c["fast_at_feet"][k] for c in cl) for k in ("fast", "of")}
    a.out.parent.mkdir(parents=True, exist_ok=True)
    a.out.with_suffix(".json").write_text(json.dumps(report, indent=2, allow_nan=False) + "\n")
    print(json.dumps({"m0": {k: v for k, v in report["m0"].items() if k != "rules"}
                      | {"rules": {k: v["disagree"] for k, v in report["m0"]["rules"].items()}}}, indent=1))


if __name__ == "__main__":
    main()
