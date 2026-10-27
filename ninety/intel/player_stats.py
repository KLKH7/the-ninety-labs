"""Each player's match stats, keyed by the Player ID feed's names: running while tracked, and the
detected events the feed names him in, up to a moment of the match and never after it.

Kian's decision of Oct 26 (AGENTS.md, hard rules): the feed's names may key code-computed
per-player stats for all 22 players, each marked "Player ID feed", never truth. The rules and bars
were fixed before any number was computed (docs/eval/player-stats-plan.md), and the grading against
the truth is docs/eval/player-stats.md.

- **Running** comes from vision's tracked positions. Tracks are stitched into one player only
  through seconds the feed names them his. A gap is never bridged, and a step faster than
  MAX_STEP_MPS is skipped as a track jumping (GROUNDING I16). Each track is read once a second, as
  team distance is. The feed's own positions are never read here: it gives names only.
- **Top speed** is the fastest mean over TOP_WINDOW_S consecutive one-second steps (I22). A value
  above the plausibility cap is withheld.
- **Events** are vision's detected events. One is his when the feed names its track: passes,
  completed passes, shots, goals and involvements.
- **Coverage.** Tracked seconds over elapsed match seconds, and over the footage shown. Running
  figures are withheld under MIN_FOOTAGE_COVERAGE, and "fastest" and "furthest" rank only the
  players at or above it.
- **Measured.** Each stat is said only while its grading met its pre-registered bar
  (CALIBRATION, written by ninety/eval/player_stats_eval.py). An unmeasured or failed stat is
  withheld with its reason. It is never tuned.
"""

from __future__ import annotations

import json
import math
from collections import defaultdict
from collections.abc import Mapping, Sequence
from pathlib import Path

from ninety.intel import identity
from ninety.intel.scene import FPS, minute_of
from ninety.intel.team_stats import MAX_STEP_MPS

STEP_S = 1.0  # one sample a second, team distance's step (GROUNDING I16)
GAP_S = 1.5 * STEP_S  # a later sample than this is a gap, not a step (physical.rows)
TOP_WINDOW_S = (
    3  # design, pre-registered: 3 steps take a 1.26 m position error's speed error from ~6.4 to ~2.1 km/h
)
CAP_KMH = MAX_STEP_MPS * 3.6  # plausibility cap: I16's jump rule, past R6's 8-9 m/s match peaks
MIN_FOOTAGE_COVERAGE = 0.5  # design, pre-registered: tracked a strict majority of the footage shown
# "Best player": a transparent sum, never a model's opinion (docs/eval/player-stats-plan.md).
BEST_WEIGHTS = {"involvements": 1, "passes_completed": 1, "shots": 2, "goals": 5}
BEST_FORMULA = (
    "involvements + completed passes + 2 x shots + 5 x goals, from detected events the Player ID feed names"
)
RUNNING = ("distance_m", "top_kmh", "est_footage_m")
COUNTS = ("passes", "passes_completed", "shots", "goals", "involvements")
METRICS = {
    "best": "best_score",
    "involvement": "involvements",
    "passes": "passes",
    "passes_completed": "passes_completed",
    "shots": "shots",
    "goals": "goals",
    "fastest": "top_kmh",
    "distance": "est_footage_m",
}
# Which stats each ranking needs to be on.
NEEDS = {
    "best": COUNTS,
    "involvement": ("involvements",),
    "passes": ("passes",),
    "passes_completed": ("passes_completed",),
    "shots": ("shots",),
    "goals": ("goals",),
    "fastest": ("top_kmh",),
    "distance": ("est_footage_m",),
}
CALIBRATION = Path(__file__).with_name("player_stats_calibration.json")


def calibration(path: Path = CALIBRATION) -> dict:
    """{stat: {"on": bool, "why": str, ...}} as graded, or {} before any grading."""
    return json.loads(path.read_text()).get("stats", {}) if path.exists() else {}


def roster(feed: identity.Feed) -> list[dict]:
    """The feed's 22 players: id, name, shirt number, side and position."""
    return [
        {
            "player": pid,
            "name": p["name"],
            "number": p["jersey"],
            "team": p["team"],
            "position": p["position"],
        }
        for pid, p in sorted(feed.roster.items())
    ]


def running(frames: Sequence[Mapping], named: Mapping[str, Mapping], trace: list | None = None) -> dict:
    """Per player and match minute: tracked seconds, metres and the fastest sustained window ending in
    it; and the footage seconds of each minute. A step joins two samples of tracks the feed names
    the same player, at most GAP_S apart; nothing else joins them. `trace`, for grading only, gets
    each step and each sustained window counted, by sample times."""
    every = round(STEP_S * FPS)
    footage: dict[int, int] = defaultdict(int)
    by: dict[tuple[str, int], dict] = {}
    last: dict[str, tuple[float, str, float, float]] = {}  # player -> (t, track, x, y)
    steps: dict[str, list[float]] = defaultdict(list)  # player -> the current run of step speeds (m/s)
    times: dict[str, list[float]] = defaultdict(list)  # player -> the current run's sample times
    for fr in frames:
        if int(fr["frame"]) % every:
            continue
        t = float(fr["t"])
        m = minute_of(t)
        footage[m] += 1
        here: dict[str, list[Mapping]] = defaultdict(list)
        for pl in fr["players"]:
            w = named.get(pl["id"])
            if w and w.get("player"):
                here[w["player"]].append(pl)
        for pid, cands in here.items():
            prev = last.get(pid)
            # The track he was on, if it is still here; else the one the feed names him on most surely.
            pl = next((c for c in cands if prev and c["id"] == prev[1]), None) or max(
                cands, key=lambda c: (named[c["id"]].get("share", 0), c["id"])
            )
            x, y = float(pl["x"]), float(pl["y"])
            r = by.setdefault(
                (pid, m), {"player": pid, "minute": m, "tracked_s": 0, "m": 0.0, "top_mps": 0.0}
            )
            r["tracked_s"] += 1
            last[pid] = (t, pl["id"], x, y)
            if prev is None or t - prev[0] > GAP_S:
                steps[pid], times[pid] = [], [t]
                continue
            v = math.hypot(x - prev[2], y - prev[3]) / (t - prev[0])
            if v > MAX_STEP_MPS:  # a track jumping, not a player (I16): the run starts again
                steps[pid], times[pid] = [], [t]
                continue
            r["m"] += v * (t - prev[0])
            run = steps[pid]
            run.append(v)
            times[pid].append(t)
            if trace is not None:
                trace.append(("step", pid, prev[0], t))
            if len(run) >= TOP_WINDOW_S:
                r["top_mps"] = max(r["top_mps"], sum(run[-TOP_WINDOW_S:]) / TOP_WINDOW_S)
                if trace is not None:
                    trace.append(("window", pid, tuple(times[pid][-TOP_WINDOW_S - 1 :])))
    rows = [{**r, "m": round(r["m"], 2), "top_mps": round(r["top_mps"], 3)} for r in by.values()]
    return {
        "rows": sorted(rows, key=lambda r: (r["player"], r["minute"])),
        "footage": dict(sorted(footage.items())),
    }


def event_rows(events: Sequence[Mapping], named_broadcast: Mapping[str, Mapping]) -> list[dict]:
    """Each detected event the feed names a player in: who, what, when, and in which role."""

    def who(track):
        w = named_broadcast.get(track or "")
        return w["player"] if w and w.get("player") else None

    out = []
    for e in events:
        roles = {}
        for k in ("player", "receiver", "interceptor"):
            pid = who(e.get(k))
            if pid:
                roles.setdefault(pid, k)
        kind = e.get("type")
        credited = None
        if kind == "goal":
            strike = identity.strike_of(e, events)
            for src in (strike, e):
                pid = who((src or {}).get("player"))
                w = named_broadcast.get((src or {}).get("player") or "")
                if pid and w.get("team") == e.get("team"):
                    credited = pid
                    break
        for pid, role in roles.items():
            out.append(
                {
                    "event": e["id"],
                    "t": round(float(e["t"]), 2),
                    "type": kind,
                    "player": pid,
                    "role": role,
                    "outcome": e.get("outcome"),
                    "had_shot": bool(kind == "goal" and identity.strike_of(e, events)),
                }
            )
        if credited:
            out.append(
                {
                    "event": e["id"],
                    "t": round(float(e["t"]), 2),
                    "type": "goal_credit",
                    "player": credited,
                    "role": "scorer",
                    "outcome": None,
                    "had_shot": bool(identity.strike_of(e, events)),
                }
            )
    return out


def build(
    frames: Sequence[Mapping],
    events: Sequence[Mapping],
    feed: identity.Feed,
    named_tactical: Mapping[str, Mapping],
    named_broadcast: Mapping[str, Mapping],
) -> dict:
    """What the tools answer from, stored with the match's insights."""
    run = running(frames, named_tactical)
    return {
        "source": identity.SOURCE,
        "label": identity.SOURCE_LABEL,
        "roster": roster(feed),
        "running": run["rows"],
        "footage": {str(k): v for k, v in run["footage"].items()},
        "events": event_rows(events, named_broadcast),
    }


def _counts(evs: Sequence[Mapping]) -> dict:
    c = dict.fromkeys(COUNTS, 0)
    c["involvements"] = len({e["event"] for e in evs if e["type"] != "goal_credit"})
    for e in evs:
        if e["role"] == "player" and e["type"] == "pass":
            c["passes"] += 1
            c["passes_completed"] += e["outcome"] == "success"
        elif e["role"] == "player" and (e["type"] == "shot" or (e["type"] == "goal" and not e["had_shot"])):
            c["shots"] += 1
        elif e["type"] == "goal_credit":
            c["goals"] += 1
    return c


def stats(body: Mapping, t: float, cal: Mapping | None = None, withhold: bool = True) -> list[dict]:
    """Every rostered player's stats at match second t: running over the minutes ended by t, events
    up to t. A withheld figure is None, its reason under `withheld` (grading reads them all:
    withhold=False)."""
    cal = calibration() if cal is None else cal
    done = int(t // 60)  # minutes 1..done have ended by t
    footage_s = sum(v for k, v in body["footage"].items() if int(k) <= done)
    run: dict[str, dict] = defaultdict(lambda: {"tracked_s": 0, "m": 0.0, "top_mps": 0.0})
    for r in body["running"]:
        if r["minute"] <= done:
            a = run[r["player"]]
            a["tracked_s"] += r["tracked_s"]
            a["m"] += r["m"]
            a["top_mps"] = max(a["top_mps"], r["top_mps"])
    evs: dict[str, list[dict]] = defaultdict(list)
    for e in body["events"]:
        if e["t"] <= t:
            evs[e["player"]].append(e)
    out = []
    for p in body["roster"]:
        a = run[p["player"]]
        fc = a["tracked_s"] / footage_s if footage_s else 0.0
        row = {
            **p,
            "source": identity.SOURCE,
            "source_label": identity.SOURCE_LABEL,
            "t": round(t, 2),
            "running_to_minute": done,
            "elapsed_s": round(t, 1),
            "footage_s": footage_s,
            "tracked_s": a["tracked_s"],
            "coverage": round(a["tracked_s"] / t, 3) if t > 0 else 0.0,
            "footage_coverage": round(fc, 3),
            "distance_m": round(a["m"]),
            "top_kmh": round(a["top_mps"] * 3.6, 1),
            "est_footage_m": round(a["m"] * footage_s / a["tracked_s"]) if a["tracked_s"] else None,
            **_counts(evs[p["player"]]),
        }
        row["best_score"] = sum(w * row[k] for k, w in BEST_WEIGHTS.items())
        withheld = {}
        for k in RUNNING:
            if fc < MIN_FOOTAGE_COVERAGE:
                withheld[k] = (
                    f"tracked {a['tracked_s']} s of {footage_s} s of footage shown, under "
                    f"{MIN_FOOTAGE_COVERAGE:.0%}"
                )
            elif k == "top_kmh" and row[k] > CAP_KMH:
                withheld[k] = f"{row[k]} km/h is past the plausibility cap of {CAP_KMH:.1f} km/h"
        for k in (*RUNNING, *COUNTS):
            c = cal.get(k)
            if k not in withheld and not (c and c.get("on")):
                withheld[k] = (c or {}).get("why") or "not yet measured against the truth"
        for k in withheld if withhold else ():
            row[k] = None
        if withhold and any(k in withheld for k in COUNTS):
            row["best_score"] = None
        row["withheld"] = withheld
        out.append(row)
    return out


def find(rows: Sequence[Mapping], player: str) -> list[Mapping]:
    """The rows a fan's name for a player fits: a full name, else a shirt number, else a unique word."""
    q = str(player).strip().lower()
    full = [r for r in rows if r["name"].lower() == q]
    if full:
        return full
    if q.lstrip("#").isdigit():
        return [r for r in rows if r["number"] == int(q.lstrip("#"))]
    return [r for r in rows if q in r["name"].lower().split() or q == r["player"].lower()]


def rank(rows: Sequence[Mapping], metric: str, cal: Mapping | None = None) -> dict:
    """Players ranked by one metric, most first. Fastest and furthest rank only the players at or
    above the coverage rule; a ranking whose stat is not on is withheld."""
    if metric not in METRICS:
        raise ValueError(f"unknown metric {metric!r}; one of {', '.join(METRICS)}")
    cal = calibration() if cal is None else cal
    # Its stats must be on, and the ranking itself graded (top-3 against the truth's) and met.
    off = [k for k in (*NEEDS[metric], f"rank:{metric}") if not (cal.get(k) or {}).get("on")]
    key = METRICS[metric]
    out = {
        "metric": metric,
        "formula": BEST_FORMULA if metric == "best" else None,
        "source": identity.SOURCE,
        "source_label": identity.SOURCE_LABEL,
        "facts": [],
        "withheld": None,
    }
    if off:
        out["withheld"] = "; ".join(
            f"{k}: {(cal.get(k) or {}).get('why') or 'not yet measured against the truth'}" for k in off
        )
        return out
    ranked = sorted(
        (r for r in rows if r.get(key) is not None),
        key=lambda r: (-r[key], -(r.get("involvements") or 0), r["name"]),
    )
    for i, r in enumerate(ranked, 1):
        out["facts"].append(
            {
                "rank": i,
                "player": r["player"],
                "name": r["name"],
                "number": r["number"],
                "team": r["team"],
                "value": r[key],
                "metric": key,
                "tracked_s": r["tracked_s"],
                "footage_coverage": r["footage_coverage"],
            }
        )
    if len(ranked) >= 2:
        out["facts"][0]["leads"] = ranked[0][key] > ranked[1][key]
    elif ranked:
        out["facts"][0]["leads"] = True
    if metric in ("fastest", "distance"):
        out["among"] = f"players tracked at least {MIN_FOOTAGE_COVERAGE:.0%} of the footage shown"
    return out


ORDER_WORDING = "{0}, then {1}, then {2}, in the moves the video picked up"  # the only way it is said:
# no single player is ever "the most involved" (the leader was right in 3 of 4 held-out cases), never "best"


def order(raw_rows: Sequence[Mapping], cal: Mapping | None = None) -> dict:
    """A club's three players most involved in the detected events the feed names them in, as an
    ordered list with no count and no rank (docs/eval/player-involvement-rank-plan.md), said only as
    ORDER_WORDING: "A, then B, then C, in the moves the video picked up". No single player is ever
    called "the most involved". Served only while the held-out grading met its bar. `raw_rows` are
    stats(..., withhold=False); no value leaves here."""
    cal = calibration() if cal is None else cal
    flag = cal.get("rank:involvement_order") or {}
    out = {"metric": "involvement", "order_only": True, "of": "the moves the video picked up",
           "source": identity.SOURCE,
           "source_label": identity.SOURCE_LABEL, "facts": [], "withheld": None}
    if not flag.get("on"):
        out["withheld"] = flag.get("why") or "not yet measured against the truth"
        return out
    ranked = sorted(raw_rows, key=lambda r: (-r["involvements"], r["name"]))
    out["facts"] = [{"player": r["player"], "name": r["name"], "number": r["number"], "team": r["team"]}
                    for r in ranked[:3]]
    if len(out["facts"]) == 3:
        out["say"] = ORDER_WORDING.format(*(f["name"] for f in out["facts"]))
    return out


__all__ = ["BEST_FORMULA", "METRICS", "build", "calibration", "find", "order", "rank", "stats"]
