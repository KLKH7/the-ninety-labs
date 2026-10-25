"""The phone's Stats tab: every team stat the tools compute, grouped, "so far" at each 5 minutes.

Built once per match from the same tool summaries the Companion reads (ninety/intel/match_insights.py),
so the Stats tab and the conversation can never disagree. Each row is one metric for both teams;
its series gives the value from minute 1 to the end of each BIN_MIN-minute bin, so the phone shows
"so far" at its clock without reading ahead. A value that is not confident (its bounds disagree, or
a shape median over no confident minute) says so; the phone shows it as unsure.
"""

from __future__ import annotations

import statistics
from collections.abc import Callable

from ninety.intel.scene import TEAMS
from ninety.intel.team_stats import BIN_MIN, within_pct


def _distance_label() -> str:
    """The row says how far it may be off, as measured (docs/eval/team-distance.md)."""
    pct = within_pct()
    return f"Distance covered (tracked, ±{pct}%)" if pct is not None else "Distance covered (tracked)"


SHAPE_ROWS = (
    ("width", "Width", "m"),
    ("length", "Length, back to front", "m"),
    ("line_height", "Back line from own goal", "m"),
    ("area", "Area covered by the outfield", "m²"),
    ("behind_ball", "Players behind the ball", "players"),
    ("ahead_of_ball", "Players ahead of the ball", "players"),
)


def _summary(get: Callable[[int, int], dict], metric: str, field: str = "value") -> Callable[[int], dict]:
    def at(m: int, lo: int = 1) -> dict:
        rows = {r["team"]: r for r in get(lo, m)["summary"] if r.get("metric") == metric}
        out = {t: (rows[t].get(field) if t in rows else None) for t in TEAMS}
        out["confident"] = all(rows.get(t, {}).get("confident", False) for t in TEAMS)
        out["evidence"] = [rows[t]["id"] for t in TEAMS if t in rows]
        return out

    return at


def _also(get, metric: str, unit: str, context: str | None = None) -> Callable[[int], dict]:
    """A summary's own `also` number (turnovers, a channel's share), by unit and context."""

    def at(m: int, lo: int = 1) -> dict:
        rows = {r["team"]: r for r in get(lo, m)["summary"] if r.get("metric") == metric}
        out = {}
        for t in TEAMS:
            hit = [
                a[0]
                for a in rows.get(t, {}).get("also", [])
                if a[1] == unit and (context is None or context in (a[2:] or [""])[0])
            ]
            out[t] = hit[0] if hit else None
        out["confident"] = all(rows.get(t, {}).get("confident", False) for t in TEAMS)
        out["evidence"] = [rows[t]["id"] for t in TEAMS if t in rows]
        return out

    return at


def _inside(mi) -> Callable[[int], dict]:
    """Shots from inside the penalty area: sure only when no shot was within the error of its line
    (the merge queue's review of #318), as well as every shot's side known."""
    base = _summary(mi.shots, "shots", "inside_box")

    def at(m: int, lo: int = 1) -> dict:
        out = base(m, lo)
        rows = [r for r in mi.shots(lo, m)["summary"] if r.get("metric") == "shots"]
        out["confident"] = out["confident"] and all(r.get("inside_exact", True) for r in rows)
        return out

    return at


def _territory(mi) -> Callable[[int], dict]:
    return _summary(mi.territory, "final_third_share", "lo")


def _count(mi, kind: str) -> Callable[[int], dict]:
    def at(m: int, lo: int = 1) -> dict:
        rows = [f for f in mi.facts.get(kind, ()) if lo <= f["minute"] <= m]
        return {
            **{t: sum(f["team"] == t for f in rows) for t in TEAMS},
            "confident": True,
            "evidence": [f["id"] for f in rows][-6:],
        }

    return at


def _shape(mi, metric: str) -> Callable[[int], dict]:
    def at(m: int, lo: int = 1) -> dict:
        out = {}
        for t in TEAMS:
            vals = [
                r["value"]
                for r in mi.facts.get("shape", ())
                if r["metric"] == metric and r["team"] == t and r["confident"] and lo <= r["minute"] <= m
            ]
            out[t] = int(statistics.median(vals) + 0.5) if vals else None
        out["confident"] = all(out[t] is not None for t in TEAMS)
        out["evidence"] = []
        return out

    return at


def _distance(mi) -> Callable[[int], dict]:
    def at(m: int, lo: int = 1) -> dict:
        bins = {
            t: [
                b
                for b in mi.team_stats.get("distance", {}).get(t, {}).get("bins", [])
                if b["minute_to"] <= m and b["minute_from"] >= lo
            ]
            for t in TEAMS
        }
        out = {t: round(sum(b["km"] for b in bins[t]), 1) if bins[t] else None for t in TEAMS}
        out["coverage"] = {
            t: (round(statistics.fmean([b["coverage"] for b in bins[t]]), 2) if bins[t] else None)
            for t in TEAMS
        }
        out["confident"] = all(out[t] is not None for t in TEAMS)
        out["evidence"] = []
        return out

    return at


def _rows(mi) -> list:
    """The Stats tab's rows: group, key, label, unit, and the function giving its value over minutes."""
    return [
        (
            "Attack",
            "possession",
            "Possession (share of passes)",
            "%",
            _summary(mi.possession, "possession_share"),
        ),
        # The lower bound: the seconds with the ball near a third's line may add to it (GROUNDING I18).
        ("Attack", "territory", "Ball in the attacking third, at least", "%", _territory(mi)),
        *[
            ("Passing", key, label, "passes", _summary(mi.passing, key))
            for key, label in (
                ("progressive", "Progressive passes"),
                ("final_third_entry", "Passes into the final third"),
                ("long", "Long passes (32 m or more)"),
                ("intercepted", "Passes intercepted"),
            )
        ],
        *[
            # Under Attack: the phone draws the groups it knows (web/phone, Attack to Physical).
            ("Attack", key, label, unit, _summary(mi.set_pieces, key))
            for key, label, unit in (
                ("corner", "Corners", "corners"),
                ("free_kick", "Free kicks", "free kicks"),
                ("throw_in", "Throw-ins", "throw-ins"),
                ("goal_kick", "Goal kicks", "goal kicks"),
                ("penalty_kick", "Penalties", "penalties"),
            )
        ],
        (
            "Attack",
            "shots_inside",
            "Shots from inside the penalty area",
            "shots",
            _inside(mi),
        ),
        ("Attack", "counters", "Regains that led to a shot", "regains", _count(mi, "counter")),
        ("Attack", "one_twos", "One-twos", "one-twos", _count(mi, "one_two")),
        ("Attack", "crosses", "Crosses", "crosses", _summary(mi.style, "crosses")),
        *[
            (
                "Attack",
                f"channel_{c}",
                f"Passes from the {c}",
                "%",
                _also(mi.style, "pass_share_by_channel", "%", c),
            )
            for c in ("left", "centre", "right")
        ],
        (
            "Passing",
            "opponents_bypassed_total",
            "Opponents taken out by passes",
            "opponents",
            _summary(mi.line_breaks, "opponents_bypassed_total"),
        ),
        (
            "Passing",
            "passes_with_no_open_teammate_ahead",
            "Passes with no teammate free further forward",
            "passes",
            _summary(mi.pass_options, "passes_with_no_open_teammate_ahead"),
        ),
        (
            "Passing",
            "keeper_long_balls",
            "Keeper going long",
            "times",
            _summary(mi.style, "keeper_long_balls"),
        ),
        (
            "Pressing",
            "turnovers",
            "Turnovers in open play",
            "turnovers",
            _also(mi.counter_press, "regains_within_5s", "turnovers"),
        ),
        (
            "Pressing",
            "regains_within_5s",
            "Won back within 5 seconds",
            "regains",
            _summary(mi.counter_press, "regains_within_5s"),
        ),
        (
            "Pressing",
            "overload_moments",
            "Overloads around the ball",
            "overloads",
            _summary(mi.overloads, "overload_moments"),
        ),
        *[("Shape", key, label, unit, _shape(mi, key)) for key, label, unit in SHAPE_ROWS],
        ("Physical", "distance_km", _distance_label(), "km", _distance(mi)),
    ]


def stats_table(mi) -> dict:
    """The Stats tab's rows, each with a series of "so far" values per BIN_MIN minutes; the same rows
    for each half (Law 7's 45 minutes); and the pass network of named players."""
    from ninety.intel.match_insights import HALF_MIN  # Law 7 (imported here: match_insights imports us)

    rows = _rows(mi)
    ends = list(range(BIN_MIN, mi.minutes + BIN_MIN, BIN_MIN))
    out = []
    for group, key, label, unit, at in rows:
        series = [{"minute_to": min(m, mi.minutes), **at(min(m, mi.minutes))} for m in ends]
        out.append({"group": group, "key": key, "label": label, "unit": unit, "series": series})
    halves = {}
    for name, lo, hi in (("first", 1, min(HALF_MIN, mi.minutes)), ("second", HALF_MIN + 1, mi.minutes)):
        if hi < lo:
            continue
        halves[name] = {
            "minute_from": lo,
            "minute_to": hi,
            "rows": [
                {"group": g, "key": k, "label": lb, "unit": u, **at(hi, lo)} for g, k, lb, u, at in rows
            ],
        }
    return {
        "bin_min": BIN_MIN,
        "from_footage": True,
        "rows": out,
        "halves": halves,
        "pass_network": pass_network(mi, 1, mi.minutes),
    }


def pass_network(mi, minute_from: int, minute_to: int) -> dict:
    """Each club's named players at their average position, and the completed passes between them:
    only the passes the video could name both players of (GROUNDING I21)."""
    from ninety.intel import passing

    pos: dict[tuple, list[float]] = {}
    for r in mi.facts.get("running", ()):
        who = mi.people.get(r["track"], {})
        if not who.get("name") or not minute_from <= r["minute"] <= minute_to or not r.get("n"):
            continue
        p = pos.setdefault((who["team"], who["name"]), [0.0, 0.0, 0])
        p[0], p[1], p[2] = p[0] + r["sx"], p[1] + r["sy"], p[2] + r["n"]
    made: dict[tuple, int] = {}
    for r in mi.facts.get("pass_type", ()):
        who = mi.people.get(r.get("passer"), {})
        if r.get("receiver") and who.get("name") and minute_from <= r["minute"] <= minute_to:
            made[(who["team"], who["name"])] = made.get((who["team"], who["name"]), 0) + 1
    links = passing.network(mi.facts.get("pass_type", ()), mi.people, minute_from, minute_to, top=10_000)
    out = {}
    for team in TEAMS:
        nodes = [
            {
                "id": name,
                "x": round(p[0] / p[2], 1),
                "y": round(p[1] / p[2], 1),
                "passes": made.get((t, name), 0),
            }
            for (t, name), p in sorted(pos.items())
            if t == team
        ]
        edges = [
            {"a": r["passer_is"], "b": r["receiver_is"], "n": r["value"]} for r in links if r["team"] == team
        ]
        out[team] = {"nodes": nodes, "links": edges, "named_passes_only": True}
    return out


__all__ = ["pass_network", "stats_table"]
