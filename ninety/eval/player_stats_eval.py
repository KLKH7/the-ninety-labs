"""Grade ninety/intel/player_stats.py against the truth: each pre-registered stat and ranking, at full
time on one joined match, against its bar (docs/eval/player-stats-plan.md).

    uv run python -m ninety.eval.player_stats_eval --clip runs/demo-8324-final \\
        --vision runs/demo-8324-final-work/vision --truth-clips runs/demo-8324-final-work/clips \\
        --feed runs/demo-8324-final/final-work/identity_feed.jsonl

The truth is the engine's positions and events in the clip windows the condensed footage is cut
from, read only here. Feed ids map to engine ids by side and position, as identity_eval does. Each
stat's verdict is written to player_stats_calibration.json: a stat that misses its bar is off. Nothing
is tuned; no constant is read back from the grading.
"""

from __future__ import annotations

import argparse
import json
import math
from collections import Counter, defaultdict
from pathlib import Path

from ninety.eval.event_score import git_commit
from ninety.intel import identity, player_stats
from ninety.intel.match_insights import load_fixture
from ninety.intel.teamsheet import LABEL
from ninety.match import detected

PCT_BAR = 21  # team distance's measured label, ±21% (GROUNDING I16, I22)
TOP_BAR_KMH = 7.7  # the phone card's worst measured top-speed error (I22; physical.TOP_SPEED_BAR_KMH)
COUNT_SHARE = 0.8  # ≥ 80% of players within max(1, 21%) of the truth (design, pre-registered)
TOP3_BAR = 2.0  # mean top-3 overlap ≥ 2 of 3 over the two clubs (design, pre-registered)
DETECTED_TYPES = {"pass", "shot", "goal", "possession_change", "out_of_play", "set_piece", "kickoff"}
RANKINGS = ("best", "involvement", "passes", "fastest", "distance")


def _jsonl(path: Path) -> list[dict]:
    return [json.loads(line) for line in path.read_text().splitlines() if line.strip()]


def load_truth(clips: Path) -> tuple[dict[int, dict[str, tuple[float, float]]], list[dict], dict[tuple, str]]:
    """Every clip frame's true positions by engine id, every clip event, and (team, position) -> engine id."""
    pos: dict[int, dict[str, tuple[float, float]]] = {}
    events: list[dict] = []
    roster: dict[tuple, str] = {}
    for d in sorted(p for p in clips.iterdir() if (p / "frames.jsonl").is_file()):
        for fr in _jsonl(d / "frames.jsonl"):
            pos[int(fr["frame"])] = {p["id"]: (float(p["x"]), float(p["y"])) for p in fr["players"]}
        events += _jsonl(d / "events.jsonl")
        for r in json.loads((d / "meta.json").read_text())["roster"]:
            roster[(r["team"], LABEL[r["role"]])] = r["id"]
    seen, uniq = set(), []
    for e in sorted(events, key=lambda e: float(e["t"])):
        if e["id"] not in seen:
            seen.add(e["id"])
            uniq.append(e)
    return pos, uniq, roster


def _at(pos, t: float, eid: str):
    return (pos.get(round(t * 25)) or {}).get(eid)


def _dist(a, b) -> float:
    return math.hypot(a[0] - b[0], a[1] - b[1])


def truth_counts(events: list[dict], eid_to_pid: dict[str, str]) -> dict[str, Counter]:
    """The same counts as player_stats._counts, on the truth's events of the types vision detects."""
    c: dict[str, Counter] = defaultdict(Counter)
    for e in events:
        if e["type"] not in DETECTED_TYPES:
            continue
        involved = {eid_to_pid.get(e.get(k)) for k in ("player", "receiver", "interceptor")} - {None}
        for pid in involved:
            c[pid]["involvements"] += 1
        pid = eid_to_pid.get(e.get("player"))
        if not pid:
            continue
        if e["type"] == "pass":
            c[pid]["passes"] += 1
            c[pid]["passes_completed"] += e.get("outcome") == "success"
        elif e["type"] == "shot":
            c[pid]["shots"] += 1
        elif e["type"] == "goal":
            c[pid]["goals"] += 1
            if not identity.strike_of(e, events):
                c[pid]["shots"] += 1
    return c


def _pct(a: float, b: float) -> float | None:
    return round(100 * (a - b) / b, 1) if b else None


def _q(xs: list[float], q: float) -> float | None:
    xs = sorted(abs(x) for x in xs if x is not None)
    if not xs:
        return None
    return round(xs[min(len(xs) - 1, math.ceil(q * len(xs)) - 1)], 1)


def overlap(ours: list[str], truth: list[str]) -> int:
    return len(set(ours[:3]) & set(truth[:3]))


def truth_rank(values: dict[str, float], names: dict[str, str]) -> list[str]:
    return [p for p, _ in sorted(values.items(), key=lambda kv: (-kv[1], names[kv[0]]))]


def main(argv: list[str] | None = None) -> None:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--clip", type=Path, required=True)
    ap.add_argument("--vision", type=Path, required=True)
    ap.add_argument("--truth-clips", type=Path, required=True)
    ap.add_argument("--feed", type=Path, required=True)
    ap.add_argument("--out", type=Path, default=Path("docs/eval/player-stats.json"))
    ap.add_argument("--calibration", type=Path, default=player_stats.CALIBRATION)
    args = ap.parse_args(argv)
    clip = args.clip
    frames = json.loads((clip / "tracked.json").read_text())["frames"]
    association = json.loads((clip / "association.json").read_text())["tracks"]
    events = detected.load(clip / "detected.jsonl")
    b_frames = identity.broadcast_frames(args.vision, clip)
    feed = identity.load_for(args.feed, [*frames, *b_frames], load_fixture(clip / "clip.json"))
    tactical = identity.tactical(frames, feed)
    named_b = identity.named_broadcast(association, tactical, feed, events, b_frames)
    sided = identity.sided(events, named_b)
    trace: list = []
    player_stats.running(frames, tactical, trace)
    body = player_stats.build(frames, sided, feed, tactical, named_b)
    t_end = max(float(f["t"]) for f in frames)
    t_ft = 60.0 * math.ceil(t_end / 60)
    everything_on = {
        k: {"on": True}
        for k in (*player_stats.RUNNING, *player_stats.COUNTS, *(f"rank:{m}" for m in player_stats.METRICS))
    }
    ours = {r["player"]: r for r in player_stats.stats(body, t_ft, everything_on, withhold=False)}

    pos, t_events, roster = load_truth(args.truth_clips)
    pid_to_eid = {pid: roster[(p["team"], p["position"])] for pid, p in feed.roster.items()}
    eid_to_pid = {e: p for p, e in pid_to_eid.items()}
    names = {pid: p["name"] for pid, p in feed.roster.items()}

    # Truth over the same steps and windows the live path counted.
    t_dist: dict[str, float] = defaultdict(float)
    t_top: dict[str, float] = defaultdict(float)
    for kind, pid, *rest in trace:
        eid = pid_to_eid[pid]
        if kind == "step":
            a, b = _at(pos, rest[0], eid), _at(pos, rest[1], eid)
            if a and b:
                t_dist[pid] += _dist(a, b)
        else:
            ts = rest[0]
            pts = [_at(pos, t, eid) for t in ts]
            if all(pts):
                v = sum(_dist(pts[i], pts[i + 1]) for i in range(len(ts) - 1)) / (ts[-1] - ts[0])
                t_top[pid] = max(t_top[pid], v * 3.6)
    # Truth over every footage second shown (what "furthest" ranks), one-second steps as the live path.
    seconds = sorted({float(f["t"]) for f in frames if int(f["frame"]) % 25 == 0})
    t_footage: dict[str, float] = defaultdict(float)
    for a, b in zip(seconds, seconds[1:], strict=False):
        if b - a > player_stats.GAP_S:
            continue
        for pid, eid in pid_to_eid.items():
            pa, pb = _at(pos, a, eid), _at(pos, b, eid)
            if pa and pb:
                t_footage[pid] += _dist(pa, pb)
    # The truth's events only in the footage windows shown.
    shown = [e for e in t_events if round(float(e["t"]) * 25) in pos]
    t_counts = truth_counts(shown, eid_to_pid)

    players = []
    for pid, r in sorted(ours.items()):
        ok = r["footage_coverage"] >= player_stats.MIN_FOOTAGE_COVERAGE
        row = {
            "player": pid,
            "name": r["name"],
            "team": r["team"],
            "tracked_s": r["tracked_s"],
            "footage_s": r["footage_s"],
            "footage_coverage": r["footage_coverage"],
            "covered": ok,
            "distance_m": r["distance_m"],
            "truth_distance_m": round(t_dist[pid]),
            "distance_err_pct": _pct(r["distance_m"], t_dist[pid]),
            "top_kmh": r["top_kmh"],
            "truth_top_kmh": round(t_top[pid], 1),
            "top_err_kmh": round(r["top_kmh"] - t_top[pid], 1) if pid in t_top else None,
            "est_footage_m": r["est_footage_m"],
            "truth_footage_m": round(t_footage[pid]),
            "est_err_pct": _pct(r["est_footage_m"] or 0, t_footage[pid]) if r["est_footage_m"] else None,
        }
        for k in player_stats.COUNTS:
            row[k], row[f"truth_{k}"] = r[k], t_counts[pid][k]
        players.append(row)

    covered = [p for p in players if p["covered"]]
    verdict: dict[str, dict] = {}

    def put(stat, met, measured, n, bar):
        said = ", ".join(f"{k.replace('_', ' ')} {v}" for k, v in measured.items())
        why = None if met else f"missed its bar ({bar}) on {n} players: {said} (docs/eval/player-stats.md)"
        verdict[stat] = {"on": bool(met), "measured": measured, "players": n, "bar": bar, "why": why}

    d = [p["distance_err_pct"] for p in covered if p["distance_err_pct"] is not None]
    put(
        "distance_m",
        d and _q(d, 0.5) <= PCT_BAR and _q(d, 0.9) <= PCT_BAR,
        {"median_abs_pct": _q(d, 0.5), "p90_abs_pct": _q(d, 0.9)},
        len(d),
        f"median and p90 ≤ {PCT_BAR}%",
    )
    s = [p["top_err_kmh"] for p in covered if p["top_err_kmh"] is not None]
    put(
        "top_kmh",
        s and _q(s, 0.9) <= TOP_BAR_KMH,
        {"median_abs_kmh": _q(s, 0.5), "p90_abs_kmh": _q(s, 0.9)},
        len(s),
        f"p90 ≤ {TOP_BAR_KMH} km/h",
    )
    e = [p["est_err_pct"] for p in covered if p["est_err_pct"] is not None]
    put(
        "est_footage_m",
        e and _q(e, 0.9) <= PCT_BAR,
        {"median_abs_pct": _q(e, 0.5), "p90_abs_pct": _q(e, 0.9)},
        len(e),
        f"p90 ≤ {PCT_BAR}%",
    )
    for k in player_stats.COUNTS:
        within = [abs(p[k] - p[f"truth_{k}"]) <= max(1, PCT_BAR / 100 * p[f"truth_{k}"]) for p in players]
        share = round(sum(within) / len(within), 2)
        errs = [p[k] - p[f"truth_{k}"] for p in players]
        ours_t, truth_t = sum(p[k] for p in players), sum(p[f"truth_{k}"] for p in players)
        # Added after looking, and it can only turn a stat off (lesson 298): for a rare event the ±1
        # floor holds for every player who never scored, so 1 goal of 4 met the per-player bar. The
        # match total must be within the same 21% too.
        total_ok = truth_t > 0 and abs(ours_t - truth_t) <= PCT_BAR / 100 * truth_t
        put(
            k,
            share >= COUNT_SHARE and total_ok,
            {
                "share_within": share,
                "mean_err": round(sum(errs) / len(errs), 2),
                "ours_total": ours_t,
                "truth_total": truth_t,
            },
            len(players),
            f"≥ {COUNT_SHARE:.0%} of players within max(1, {PCT_BAR}%), and the total within {PCT_BAR}%",
        )

    # Rankings: top-3 per club, ours against the same formula on the truth.
    rank_out = {}
    for metric in RANKINGS:
        per_club = {}
        for team in ("home", "away"):
            rows = [r for r in ours.values() if r["team"] == team]
            got = [f["player"] for f in player_stats.rank(rows, metric, everything_on)["facts"]]
            if metric in ("fastest", "distance"):
                pool = [p["player"] for p in covered if p["team"] == team]
                tv = {p: (t_top[p] if metric == "fastest" else t_footage[p]) for p in pool}
            else:
                pool = [p for p in ours if ours[p]["team"] == team]
                if metric == "best":
                    tv = {
                        p: sum(w * t_counts[p][k] for k, w in player_stats.BEST_WEIGHTS.items()) for p in pool
                    }
                else:
                    tv = {p: t_counts[p][player_stats.METRICS[metric]] for p in pool}
            truth = truth_rank(tv, names)
            per_club[team] = {
                "ours": [names[p] for p in got[:3]],
                "truth": [names[p] for p in truth[:3]],
                "overlap": overlap(got, truth),
                "pool": len(pool),
            }
        mean = sum(c["overlap"] for c in per_club.values()) / 2
        rank_out[metric] = {"clubs": per_club, "mean_overlap": mean, "met": mean >= TOP3_BAR}

    out = {
        "commit": git_commit(),
        "plan": "docs/eval/player-stats-plan.md",
        "clip": str(clip),
        "t": t_ft,
        "footage_s": ours[next(iter(ours))]["footage_s"],
        "players_covered": len(covered),
        "players": players,
        "stats": verdict,
        "rankings": rank_out,
        "truth_events_shown": len(shown),
    }
    args.out.write_text(json.dumps(out, indent=1) + "\n")
    cal = {k: {"on": v["on"], "why": v["why"]} for k, v in verdict.items()}
    for m, r in rank_out.items():
        cal[f"rank:{m}"] = {
            "on": r["met"],
            "why": None
            if r["met"]
            else (
                f"its top three agreed with the truth's {r['mean_overlap']} of 3 per club, under {TOP3_BAR}"
                " (docs/eval/player-stats.md)"
            ),
        }
    args.calibration.write_text(
        json.dumps({"stats": cal, "source": "docs/eval/player-stats.json"}, indent=1) + "\n"
    )
    print(
        json.dumps(
            {
                "stats": verdict,
                "rankings": {m: (r["mean_overlap"], r["met"]) for m, r in rank_out.items()},
                "covered": len(covered),
            },
            indent=1,
        )
    )


if __name__ == "__main__":
    main()
