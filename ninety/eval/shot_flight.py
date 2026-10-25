"""How well vision measures a shot's speed, distance, flight time and goal-mouth crossing, graded
against the answer key, and the go/no-go gates of docs/eval/highlights-plan.md.

    uv run python -m ninety.eval.shot_flight --clip <clip dir> --detected <detected.jsonl> \\
        [--clip ... --detected ...] [--crossings <crossings.jsonl>] [--woodwork <woodwork.jsonl>] \\
        [--final-test] --out docs/eval/shot-flight

Each clip directory holds the answer key (events.jsonl, frames.jsonl, meta.json). Detected shots
are matched to true shots by event_score's strict rule. For every matched shot the report gives
vision's speed v, distance d to the goal's centre, position x, y and flight time T = d / v against
the truth's, and T against the true flight time read from the ball's own path. A save is in the
reel when T <= T_DIVE_S; the report counts how often vision and the truth put a true save on the
same side of it, and applies the plan's gates. Optional files add the goal-mouth crossings and the
woodwork hits vision reports (Amendment 1).

Grading only, so it reads the answer key; nothing on the live path imports it. It is run on the
shot-outcome set's validation split only once the plan is merged, and on its test split once: a
clip whose seed is a test seed (900001 to 900030, 910009 to 910016) is refused unless `--final-test`
is given, which is the one scoring of the test split.
"""

from __future__ import annotations

import argparse
import datetime
import json
import math
import re
from pathlib import Path

from ninety.eval.event_score import STRICT_M, check_frames, git_commit, load_events, match, ratio, wilson
from ninety.eval.vision_score import IN_AIR_Z
from ninety.sim import ball
from ninety.sim.engine import CROSSBAR, FPS, GOAL_HALF_WIDTH, POST_RADIUS

PITCH_X, CENTRE_Y = 105.0, 34.0
# docs/eval/highlights-plan.md: a save beats the dive when T <= 0.97 s (Ibrahim et al. 2019).
T_DIVE_S = 0.97
# The plan's gates, fixed before any measurement: the 95th percentile flight-time error on matched
# saves, the share of matched saves on the same side of T_DIVE_S, and the fewest saves to judge them.
GATE_T_P95_S = 0.10
GATE_AGREE = 0.90
MIN_SAVES = 20
# Amendment 1: crossings within this far outside the goal frame are measured too (design), at
# least this many to show a placement label; woodwork needs this many true hits and this precision.
NEAR_FRAME_M = 2.0
MIN_CROSSINGS = 20
MIN_WOODWORK = 10
GATE_WOODWORK_PRECISION = 0.90
# A detected woodwork hit is the true one when within this many frames of it: the detector's own
# window (Amendment 1, how vision finds them, rule 3).
WOODWORK_FRAMES = 3
TOUCHING_M = ball.RADIUS + POST_RADIUS  # the engine's woodwork contact, centre to post or bar


def goal_line(x: float) -> float:
    """The goal line a shot from x attacks: the nearer one. A shot is an option only within 40 m
    of the goal's centre (GROUNDING D3), so it is always struck in the half it attacks."""
    return PITCH_X if x > PITCH_X / 2 else 0.0


def distance_m(x: float, y: float) -> float:
    """d: from where the shot was struck to the centre of the goal it attacks (D3, lesson 138)."""
    return math.hypot(goal_line(x) - x, CENTRE_Y - y)


def flight_time_s(d: float, speed_kmh: float | None) -> float | None:
    """T = d / v, with v in metres a second; None without a speed."""
    if speed_kmh is None or speed_kmh <= 0:
        return None
    return d / (speed_kmh / 3.6)


def percentile(values: list[float], q: float) -> float | None:
    """Linear-interpolated percentile, q in [0, 1] (as ninety/vision/data_stats.py)."""
    if not values:
        return None
    ordered = sorted(values)
    pos = q * (len(ordered) - 1)
    lo, hi = math.floor(pos), math.ceil(pos)
    return ordered[lo] + (ordered[hi] - ordered[lo]) * (pos - lo)


def summary(errors: list[float]) -> dict | None:
    """Median and 95th percentile of the absolute error, and the signed median (the bias)."""
    if not errors:
        return None
    absolute = [abs(e) for e in errors]
    return {"n": len(errors), "median_abs": percentile(absolute, 0.5), "p95_abs": percentile(absolute, 0.95),
            "median_signed": percentile(errors, 0.5)}


def frame_of(event: dict) -> int:
    return event["frame"] if event.get("frame") is not None else round(event["t"] * FPS)


def _after(frames: list[dict], k: int) -> list[dict]:
    return [f for f in frames if f["frame"] >= k]


def true_flight(shot: dict, frames: list[dict], events: list[dict]) -> dict | None:
    """The ball's own flight after a true shot: from its strike to the first time it reaches the
    goal line (between frames, linearly, as the engine does at the line) or the next true event
    after it (anyone touching it, or the ball going out). Also whether it was lifted: its height
    above IN_AIR_Z on any frame of the flight, the scorers' one cut-off. None if nothing ends it."""
    line = goal_line(shot["x"])
    path = _after(frames, frame_of(shot))
    later = [e["t"] for e in events if e["t"] > shot["t"] + 1e-9]
    end = min(later) if later else math.inf
    cross = None
    for a, b in zip(path, path[1:], strict=False):
        if a["t"] > end:
            break
        xa, xb = a["ball"]["x"], b["ball"]["x"]
        if (xa - line) * (xb - line) <= 0 and xa != xb:
            s = (line - xa) / (xb - xa)
            cross = {"t": a["t"] + s * (b["t"] - a["t"]),
                     "y": a["ball"]["y"] + s * (b["ball"]["y"] - a["ball"]["y"]),
                     # the ball's centre: frames give its lowest point (the engine's z)
                     "z": a["ball"].get("z", 0.0) + s * (b["ball"].get("z", 0.0) - a["ball"].get("z", 0.0))
                     + ball.RADIUS}
            break
    t_end = min(end, cross["t"]) if cross else end
    if math.isinf(t_end):
        return None
    flown = [f for f in path if f["t"] <= t_end]
    return {"t_s": t_end - shot["t"],
            "crossing": cross if cross and cross["t"] <= end else None,
            "lifted": any(f["ball"].get("z", 0.0) > IN_AIR_Z for f in flown)}


def woodwork_hits(frames: list[dict]) -> list[dict]:
    """The true woodwork hits, by the engine's own geometry (engine.woodwork). The engine bounces
    the ball inside a step, so a hit never shows the ball over the line: it shows the ball's speed
    along the pitch turning back next to a goal line. Where the ball would have crossed is taken
    from the frame before, carried on one frame at its own velocity, and tested as the engine does:
    within a ball's radius plus a post's of a post (under the bar) or of the bar (between the posts)."""
    hits = []
    for a, b in zip(frames, frames[1:], strict=False):
        p, q = a["ball"], b["ball"]
        vx, vxn = p.get("vx", 0.0), q.get("vx", 0.0)
        if vx == 0 or vx * vxn >= 0:
            continue
        line = PITCH_X if vx > 0 else 0.0
        dt = b["t"] - a["t"]
        x1 = p["x"] + vx * dt
        if (p["x"] - line) * (x1 - line) > 0:
            continue  # it turned back short of the line: a touch, not the woodwork
        s = (line - p["x"]) / (x1 - p["x"])
        y = p["y"] + s * p.get("vy", 0.0) * dt
        zc = p.get("z", 0.0) + s * p.get("vz", 0.0) * dt + ball.RADIUS
        off = abs(y - CENTRE_Y)
        post = abs(off - GOAL_HALF_WIDTH) <= TOUCHING_M and zc <= CROSSBAR
        bar = off <= GOAL_HALF_WIDTH and abs(zc - CROSSBAR) <= TOUCHING_M
        if post or bar:
            hits.append({"frame": a["frame"], "t": a["t"], "what": "bar" if bar else "post",
                         "y": round(y, 3), "z": round(zc, 3)})
    return hits


def near_frame(crossing: dict) -> bool:
    """A crossing measured for placement: within NEAR_FRAME_M of the goal frame, wide or over."""
    return abs(crossing["y"] - CENTRE_Y) <= GOAL_HALF_WIDTH + NEAR_FRAME_M and \
        crossing["z"] <= CROSSBAR + NEAR_FRAME_M


def clip_rows(truth: list[dict], frames: list[dict], detected: list[dict],
              cuts: list[dict] | None = None, clip: str | None = None) -> tuple[list[dict], dict]:
    """One row per matched shot (strict rule), and the counts of unmatched shots. Detected ids count
    from 1 in every clip, so a row names its clip: an id alone is not a shot."""
    true_shots = [e for e in truth if e["type"] == "shot"]
    det_shots = [e for e in detected if e["type"] == "shot"]
    pairs = match(true_shots, det_shots, frames=frames, radius_m=STRICT_M, cuts=cuts)
    by_truth = {e["id"]: e for e in true_shots}
    by_det = {e["id"]: e for e in det_shots}
    rows = []
    for p in pairs:
        t, d = by_truth[p["truth_id"]], by_det[p["detected_id"]]
        d_true, d_vis = distance_m(t["x"], t["y"]), distance_m(d["x"], d["y"])
        T_true = flight_time_s(d_true, t.get("ball_speed_kmh"))
        T_vis = flight_time_s(d_vis, d.get("ball_speed_kmh"))
        flight = true_flight(t, frames, truth)
        rows.append({
            "clip": clip, "truth_id": t["id"], "detected_id": d["id"], "outcome": t.get("outcome"),
            "v_true": t.get("ball_speed_kmh"), "v_vision": d.get("ball_speed_kmh"),
            "d_true": d_true, "d_vision": d_vis,
            "x_error": d["x"] - t["x"], "y_error": d["y"] - t["y"],
            "T_true": T_true, "T_vision": T_vis,
            "T_flown": None if flight is None else flight["t_s"],
            "lifted": None if flight is None else flight["lifted"],
            "crossing": None if flight is None else flight["crossing"],
        })
    counts = {"true_shots": len(true_shots), "detected_shots": len(det_shots), "matched": len(pairs),
              "missed": len(true_shots) - len(pairs), "false": len(det_shots) - len(pairs)}
    return rows, counts


def _errors(rows: list[dict], a: str, b: str) -> list[float]:
    return [r[a] - r[b] for r in rows if r[a] is not None and r[b] is not None]


def error_table(rows: list[dict]) -> dict:
    """Each measured quantity's error, for all matched shots and for saves, ground and lifted apart."""
    def block(rs: list[dict]) -> dict:
        return {"v_kmh": summary(_errors(rs, "v_vision", "v_true")),
                "d_m": summary(_errors(rs, "d_vision", "d_true")),
                "x_m": summary([r["x_error"] for r in rs]),
                "y_m": summary([r["y_error"] for r in rs]),
                "T_vs_d_over_v_s": summary(_errors(rs, "T_vision", "T_true")),
                "T_vs_flown_s": summary(_errors(rs, "T_vision", "T_flown"))}
    groups = {"all": rows, "saves": [r for r in rows if r["outcome"] == "on_target"]}
    out = {}
    for name, rs in groups.items():
        out[name] = {"all": block(rs),
                     "ground": block([r for r in rs if r["lifted"] is False]),
                     "lifted": block([r for r in rs if r["lifted"] is True])}
    return out


def agreement(rows: list[dict]) -> dict:
    """On matched true saves: do vision's T and the truth's T put it on the same side of T_DIVE_S?"""
    saves = [r for r in rows if r["outcome"] == "on_target" and r["T_true"] is not None]
    judged = [r for r in saves if r["T_vision"] is not None]
    same = [r for r in judged if (r["T_vision"] <= T_DIVE_S) == (r["T_true"] <= T_DIVE_S)]
    # A save vision gives no speed cannot be placed by the filter, so it counts against agreement.
    return {"saves": len(saves), "judged": len(judged), "same_side": len(same),
            "share": ratio(len(same), len(saves)), "wilson_95": wilson(len(same), len(saves)),
            "no_vision_speed": len(saves) - len(judged),
            "disagreements": [{"clip": r.get("clip"), "truth_id": r["truth_id"],
                               "T_true": r["T_true"], "T_vision": r["T_vision"],
                               "v_true": r["v_true"], "v_vision": r["v_vision"],
                               "d_true": r["d_true"], "d_vision": r["d_vision"]}
                              for r in judged if r not in same]}


def save_gate(errors: dict, agree: dict) -> dict:
    """The plan's go/no-go for the save filter."""
    n, share = agree["saves"], agree["share"]
    p95 = (errors["saves"]["all"]["T_vs_d_over_v_s"] or {}).get("p95_abs")
    if n < MIN_SAVES:
        return {"live": False, "reason": f"{n} matched saves, fewer than {MIN_SAVES}: not judged",
                "p95_T_s": p95, "agreement": share}
    fails = []
    if p95 is None or p95 > GATE_T_P95_S:
        fails.append(f"95th percentile flight-time error {p95} s over {GATE_T_P95_S} s")
    if share is None or share < GATE_AGREE:
        fails.append(f"agreement {share} under {GATE_AGREE}")
    return {"live": not fails, "reason": "; ".join(fails) or "both gates pass",
            "p95_T_s": p95, "agreement": share}


def crossing_table(rows: list[dict], crossings: dict[tuple, dict]) -> dict:
    """Vision's goal-mouth crossings, keyed by (clip, detected shot id), against the true crossing
    point, for matched shots whose true ball crossed within NEAR_FRAME_M of the goal frame. The key
    has the clip because detected ids repeat from clip to clip."""
    measured = [r for r in rows if r["crossing"] is not None and near_frame(r["crossing"])]
    seen = [r for r in measured if (r.get("clip"), r["detected_id"]) in crossings]
    dy = [crossings[(r.get("clip"), r["detected_id"])]["y"] - r["crossing"]["y"] for r in seen]
    dz = [crossings[(r.get("clip"), r["detected_id"])]["z"] - r["crossing"]["z"] for r in seen]
    return {"true_crossings": len(measured), "with_vision_crossing": len(seen),
            "y_m": summary(dy), "z_m": summary(dz),
            "placement_labels": len(seen) >= MIN_CROSSINGS}


def woodwork_matches(true_hits: list[dict], detected_hits: list[dict]) -> int:
    """Detected woodwork hits in one clip paired with its true ones: one to one, nearest first,
    within WOODWORK_FRAMES frames. Returns how many pair."""
    cands = sorted((abs(d["frame"] - t["frame"]), i, j) for i, t in enumerate(true_hits)
                   for j, d in enumerate(detected_hits) if abs(d["frame"] - t["frame"]) <= WOODWORK_FRAMES)
    used_t, used_d = set(), set()
    for _gap, i, j in cands:
        if i not in used_t and j not in used_d:
            used_t.add(i)
            used_d.add(j)
    return len(used_t)


def woodwork_table(n_true: int, n_detected: int, tp: int) -> dict:
    """The woodwork's precision and recall, pooled over clips, and the plan's gate."""
    precision = ratio(tp, n_detected)
    live = n_true >= MIN_WOODWORK and precision is not None and precision >= GATE_WOODWORK_PRECISION
    return {"true": n_true, "detected": n_detected, "tp": tp,
            "precision": precision, "recall": ratio(tp, n_true), "live": live}


def score(clips: list[dict]) -> dict:
    """clips: dicts of name, truth, frames, detected, cuts, and optionally crossings (this clip's
    detected shot id to {y, z}) and woodwork (detected hits, with frame numbers)."""
    rows, counts, crossings = [], [], {}
    wood = [0, 0, 0]  # true, detected, matched
    for c in clips:
        check_frames(c["frames"], c.get("cuts"))
        r, n = clip_rows(c["truth"], c["frames"], c["detected"], c.get("cuts"), c.get("name"))
        rows += r
        counts.append({"clip": c.get("name"), **n})
        if "woodwork" in c:
            true_hits, det_hits = woodwork_hits(c["frames"]), c["woodwork"] or []
            wood = [wood[0] + len(true_hits), wood[1] + len(det_hits),
                    wood[2] + woodwork_matches(true_hits, det_hits)]
        crossings.update({(c.get("name"), shot): v for shot, v in (c.get("crossings") or {}).items()})
    errors = error_table(rows)
    agree = agreement(rows)
    return {"rules": {"T_dive_s": T_DIVE_S, "gate_T_p95_s": GATE_T_P95_S, "gate_agree": GATE_AGREE,
                      "min_saves": MIN_SAVES, "match": "event_score strict", "lifted_above_m": IN_AIR_Z},
            "counts": counts, "errors": errors, "agreement": agree, "save_filter": save_gate(errors, agree),
            "crossings": crossing_table(rows, crossings) if crossings else None,
            "woodwork": woodwork_table(*wood) if any("woodwork" in c for c in clips) else None,
            "rows": rows}


def sealed_seeds() -> set[int]:
    """The seeds of the test splits: the fixed test set (900001 to 900030) and the shot-outcome
    set's test half (910009 to 910016). Scoring them is the plan's one final look."""
    from ninety.eval.shot_outcome_set import TEST
    from ninety.render.splits import TEST_SEEDS
    return set(TEST_SEEDS) | set(TEST)


def clip_seed(root: Path) -> int | None:
    """A clip's seed: meta.json's, else the digits ending its folder's name."""
    meta = root / "meta.json"
    if meta.exists():
        body = json.loads(meta.read_text())
        if not isinstance(body, dict):
            return None  # a meta.json that is not an object has no seed: unknown, never the name's
        if "seed" in body:  # meta.json wins over the name, and a seed it cannot read is unknown
            seed = body["seed"]
            if isinstance(seed, float) and seed.is_integer():
                seed = int(seed)
            if isinstance(seed, str) and seed.strip().isdigit():
                seed = int(seed)
            return seed if isinstance(seed, int) and not isinstance(seed, bool) else None
    found = re.search(r"(\d+)$", root.name)
    return int(found.group(1)) if found else None


def _jsonl(path: Path) -> list[dict]:
    return [json.loads(line) for line in path.read_text().splitlines() if line.strip()]


def main(argv: list[str] | None = None) -> None:
    ap = argparse.ArgumentParser(description="Grade vision's shot speed, distance and flight time.")
    ap.add_argument("--clip", type=Path, action="append", required=True, help="a clip's answer-key directory")
    ap.add_argument("--detected", type=Path, action="append", required=True, help="its detected events")
    ap.add_argument("--crossings", type=Path,
                    help="vision's goal-mouth crossings: {clip, shot, y, z} a line")
    ap.add_argument("--final-test", action="store_true",
                    help="score the test seeds (900001-900030, 910009-910016): the plan's one look")
    ap.add_argument("--woodwork", type=Path, help="vision's woodwork hits: {clip, frame} a line")
    ap.add_argument("--out", type=Path, required=True, help="report path without suffix")
    args = ap.parse_args(argv)
    if len(args.clip) != len(args.detected):
        raise SystemExit("give one --detected for each --clip")
    sealed = sealed_seeds()
    for root in args.clip:
        seed = clip_seed(root)
        if seed is None and not args.final_test:
            raise SystemExit(f"refused: the seed of {root} is unknown (meta.json's, or ending its name)")
        if seed in sealed and not args.final_test:
            raise SystemExit(f"refused: {root} is test seed {seed}: scored once, with --final-test")
    lines = _jsonl(args.crossings) if args.crossings else None
    if lines is not None and any("clip" not in c for c in lines):
        raise SystemExit("every line of --crossings names its clip: {clip, shot, y, z}")
    hits = _jsonl(args.woodwork) if args.woodwork else None
    clips = []
    for root, det in zip(args.clip, args.detected, strict=True):
        meta = root / "meta.json"
        wood = {"woodwork": [h for h in hits if h.get("clip") == root.name]} if hits is not None else {}
        clips.append({"name": root.name, "truth": load_events(root / "events.jsonl", "truth"),
                      "frames": _jsonl(root / "frames.jsonl"), "detected": load_events(det, "vision"),
                      "cuts": json.loads(meta.read_text()).get("cuts", []) if meta.exists() else [],
                      "crossings": ({c["shot"]: c for c in lines if c["clip"] == root.name}
                                    if lines is not None else None),
                      **wood})
    report = score(clips)
    report["inputs"] = {"clips": [str(c) for c in args.clip], "git_commit": git_commit(),
                        "date": datetime.date.today().isoformat()}
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.with_suffix(".json").write_text(json.dumps(report, indent=2, allow_nan=False) + "\n")
    agree = {k: report["agreement"][k] for k in ("saves", "same_side", "share")}
    print(json.dumps({"counts": report["counts"], "save_filter": report["save_filter"], "agreement": agree},
                     indent=2))


if __name__ == "__main__":
    main()
