"""One match's insight facts, from its tracked frames and detected events: what the tools serve.

Built once per match from the live path's inputs only: the tracked frames (`tracking.tracked`,
which refuses anything not `source: tracked`), vision's detected events (`detected.load`, which
refuses ground truth) and the fixture (the two clubs' codes from the clip's render parameters and
the match's seed, from which each team sheet is drawn). It computes every fact once, assigns each
track a role, and answers the tool calls by filtering, so a call never computes anything heavy.

The same object answers the MCP tools (ninety/mcp/match_server.py), the Companion's tool calls
(ninety/agents/companion.py) and the Insight Scout (ninety/agents/scout.py).

    uv run python -m ninety.intel.match_insights TRACKED DETECTED FIXTURE --out insights.json
"""

from __future__ import annotations

import argparse
import json
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from pathlib import Path

from ninety.intel import (
    ball_share,
    counter_press,
    line_breaks,
    offside,
    overloads,
    pass_options,
    roles,
    shape,
    shot_map,
    style,
)
from ninety.intel import team_stats as team_stats_mod
from ninety.intel.scene import TEAMS, Frames, xy
from ninety.intel.teamsheet import Fixture

BUILD_UP_S = 60.0  # design: a goal's build-up is the minute before it
MAX_FACTS = 12  # design: the most facts a tool returns, the strongest first, so a prompt stays short
KIND_FACTS = ("line_break", "overload", "counter_press", "pass_options")


@dataclass
class MatchInsights:
    clip: str
    fixture: Fixture
    facts: dict[str, list[dict]]  # kind -> facts, oldest first
    people: dict[str, dict]  # track id -> roles.who record
    minutes: int
    gates: dict = field(default_factory=dict)
    team_stats: dict = field(default_factory=dict)  # the phone's match stats (ninety/intel/team_stats.py)
    stats: dict = field(default_factory=dict)  # the Stats tab's grouped rows (ninety/intel/stats_table.py)

    @classmethod
    def build(
        cls,
        clip: str,
        frames: Sequence[Mapping],
        events: Sequence[Mapping],
        fixture: Fixture,
        gate: Mapping | None = None,
    ) -> MatchInsights:
        bad = sorted({str(fr.get("source")) for fr in frames} - {"tracked"})
        if bad:  # the live path's positions are tracked ones; the simulator's are the answer key
            raise ValueError(f"{clip}: frames must be source 'tracked', got {bad}")
        f = Frames(frames)
        gate = dict(roles.gates() if gate is None else gate)
        people = {}
        for team in TEAMS:
            assigned = roles.assign(f.frames, team)
            for track in {p["id"] for fr in f.frames for p in fr["players"] if p["team"] == team}:
                people[track] = roles.who(track, team, assigned, fixture, gate)
        spans: dict[str, tuple[float, float]] = {}
        for fr in f.frames:
            for p in fr["players"]:
                t0, t1 = spans.get(p["id"], (fr["t"], fr["t"]))
                spans[p["id"]] = (min(t0, fr["t"]), max(t1, fr["t"]))
        people = roles.one_track_per_name(people, spans)
        shapes = shape_drawings(f.frames)
        facts = {
            "line_break": line_breaks.line_breaks(events, f),
            "overload": overloads.overloads(f),
            "counter_press": counter_press.counter_press(events, f),
            "pass_options": pass_options.pass_options(events, f),
            # The team-shape facts of #228 (ninety/intel/shape.py), as its team_shape tool serves them.
            "shape": [
                {
                    **r,
                    "kind": "shape",
                    "t": 60.0 * r["minute"] - 1,  # the minute's last second: a shape is known once it is over
                    "also": shape_also(r),
                    "visual": {
                        "kind": "shape",
                        "minute": r["minute"],
                        **shapes.get((r["team"], r["minute"]), {}),
                    },
                }
                for r in shape.shape_rows(f.frames)
            ],
        }
        clubs = fixture.clubs
        facts["offside"] = offside.offsides(events, f)
        # Playing style's atoms: the detected passes, the counter-attacks and the one-twos.
        facts["pass"] = style.passes(events)
        facts["counter"] = style.counters(events)
        facts["one_two"] = style.one_twos(facts["pass"])
        # Possession share (the pass ratio) and territory (where the ball was): GROUNDING I17, I18.
        facts["possession"] = ball_share.possession_rows(events)
        facts["territory"] = ball_share.territory_rows(f.frames)
        facts["shot"] = shot_map.shots(events)  # the shot map (GROUNDING I19)
        # Goals as vision detected them: what "why did that goal happen?" is asked about.
        facts["goal"] = [
            {
                "id": f"goal:{e['id']}",
                "kind": "goal",
                "team": e["team"],
                "minute": int(float(e["t"]) // 60) + 1,
                "t": round(float(e["t"]), 2),
                "event": e["id"],
                "event_confidence": e.get("confidence"),
                "team_confidence": e.get("team_confidence"),
                "player": e.get("player"),
                "confident": True,
            }
            for e in events
            if e.get("type") == "goal"
        ]
        for rows in facts.values():
            for r in rows:
                r["club"] = clubs[r["team"]]
                for k in ("passer", "receiver"):
                    if r.get(k) in people:
                        r[f"{k}_is"] = people[r[k]]["say"]
        last = max((float(fr["t"]) for fr in f.frames), default=0.0)
        mi = cls(clip, fixture, facts, people, int(last // 60) + 1, gate, team_stats_mod.team_stats(f.frames))
        from ninety.intel.stats_table import stats_table

        mi.stats = stats_table(mi)  # the phone's Stats tab, from the same tools the Companion reads
        return mi

    # -- what the tools answer -------------------------------------------------------------

    def team(self, club: str | None) -> str | None:
        """The side a tool argument names: a club's name (any case), or None for both."""
        if club is None or club == "":
            return None
        by_name = {name.lower(): team for team, name in self.fixture.clubs.items()}
        if club.lower() not in by_name:
            raise ValueError(
                f"unknown club {club!r}; this match is {' v '.join(self.fixture.clubs.values())}"
            )
        return by_name[club.lower()]

    def _rows(self, kind: str, minute_from: int, minute_to: int, club: str | None) -> list[dict]:
        team = self.team(club)
        return [
            r
            for r in self.facts.get(kind, ())
            if minute_from <= r["minute"] <= minute_to and (team is None or r["team"] == team)
        ]

    def _summary(self, rows: list[dict], minute_from: int, minute_to: int, fn) -> list[dict]:
        out = fn(rows, minute_from, minute_to)
        for r in out:
            r["club"] = self.fixture.clubs[r["team"]]
        return out

    def line_breaks(self, minute_from: int, minute_to: int, club: str | None = None) -> dict:
        rows = self._rows("line_break", minute_from, minute_to, club)
        top = sorted((r for r in rows if r["value"] > 0), key=lambda r: (-r["value"], r["t"]))[:MAX_FACTS]
        return {"facts": top, "summary": self._summary(rows, minute_from, minute_to, line_breaks.team_totals)}

    def overloads(self, minute_from: int, minute_to: int, club: str | None = None) -> dict:
        rows = self._rows("overload", minute_from, minute_to, club)
        top = sorted(rows, key=lambda r: (-r["value"], -r["duration_s"], r["t"]))[:MAX_FACTS]
        return {"facts": top, "summary": self._summary(rows, minute_from, minute_to, overloads.team_summary)}

    def counter_press(self, minute_from: int, minute_to: int, club: str | None = None) -> dict:
        rows = self._rows("counter_press", minute_from, minute_to, club)
        top = sorted(rows, key=lambda r: (not r["regained"], -r["value"], r["t"]))[:MAX_FACTS]
        return {
            "facts": top,
            "summary": self._summary(rows, minute_from, minute_to, counter_press.team_summary),
        }

    def pass_options(self, minute_from: int, minute_to: int, club: str | None = None) -> dict:
        rows = self._rows("pass_options", minute_from, minute_to, club)
        # The passes a fan asks about: lost ones first, then those that went past an open teammate ahead.
        top = sorted(
            rows,
            key=lambda r: (
                r.get("outcome") != "fail",
                r.get("target_open") is not False,
                -r["value"],
                r["t"],
            ),
        )[:MAX_FACTS]
        summary = []
        for team in TEAMS:
            own = [r for r in rows if r["team"] == team]
            sure = [r for r in own if r["confident"]]
            none_open = sum(1 for r in sure if r["value"] == 0)
            summary.append(
                {
                    "id": f"po:{team}:m{minute_from}-{minute_to}",
                    "kind": "pass_options",
                    "metric": "passes_with_no_open_teammate_ahead",
                    "team": team,
                    "club": self.fixture.clubs[team],
                    "minute_from": minute_from,
                    "minute_to": minute_to,
                    "value": none_open,
                    "unit": "passes",
                    "lo": none_open,
                    "hi": none_open,
                    "confident": True,
                    "passes": len(own),
                    "confident_passes": len(sure),
                    "also": [[len(sure), "passes"]],
                }
            )
        return {"facts": top, "summary": summary}

    def team_shape(self, minute_from: int, minute_to: int, club: str | None = None) -> dict:
        rows = self._rows("shape", minute_from, minute_to, club)
        # The confident facts of the latest minutes first: a fan asks about now.
        top = sorted(rows, key=lambda r: (not r["confident"], -r["minute"], r["metric"]))[: MAX_FACTS * 2]
        return {"facts": top, "summary": []}

    def goal_build_up(self, minute: int, club: str | None = None) -> dict:
        """The goal at or before `minute` (the latest, or one club's), and the insight facts of the
        BUILD_UP_S before it: what led to it, strongest first."""
        team = self.team(club)
        goals = [
            g
            for g in self.facts.get("goal", ())
            if g["minute"] <= minute and (team is None or g["team"] == team)
        ]
        if not goals:
            return {"facts": [], "summary": []}
        goal = goals[-1]
        before = [
            f
            for kind in ("line_break", "overload", "counter_press", "pass_options")
            for f in self.facts.get(kind, ())
            if goal["t"] - BUILD_UP_S <= f["t"] <= goal["t"]
        ]
        before.sort(key=lambda f: (not f["confident"], f["team"] != goal["team"], -f["value"], -f["t"]))
        return {"facts": [goal, *before[:MAX_FACTS]], "summary": []}

    def players(self, minute_from: int, minute_to: int, club: str | None = None) -> dict:
        """Players ranked by the opponents their completed passes took out of the game, each as one
        fact. A player's total is confident when its bounds agree; the leader's fact is confident only
        when, in addition, his lowest possible total beats every other player's highest, so "the most"
        holds whatever the untracked players were doing."""
        team = self.team(club)
        by: dict[str, list[dict]] = {}
        for f in self._rows("line_break", minute_from, minute_to, club):
            if f.get("passer") and f["hi"] > 0:
                # One named player's pieces of track are one row (roles.one_track_per_name); an
                # unnamed track is its own.
                name = self.people.get(f["passer"], {}).get("name")
                by.setdefault(f"{f['team']}:{name}" if name else f["passer"], []).append(f)
        ranked = sorted(by.items(), key=lambda kv: (-sum(f["value"] for f in kv[1]), kv[0]))
        out = []
        for k, (_, rows) in enumerate(ranked[:5], 1):
            track = rows[0]["passer"]
            who = self.people.get(track, {})
            out.append(
                {
                    "id": f"top:{track}:m{minute_from}-{minute_to}",
                    "kind": "players",
                    "metric": "opponents_bypassed_by_player",
                    "team": who.get("team", rows[0]["team"]),
                    "club": self.fixture.clubs[rows[0]["team"]],
                    "minute_from": minute_from,
                    "minute_to": minute_to,
                    "player": track,
                    "tracks": sorted({f["passer"] for f in rows}),
                    "player_is": who.get("say"),
                    "rank": k,
                    "value": sum(f["value"] for f in rows),
                    "unit": "opponents",
                    "lo": sum(f["lo"] for f in rows),
                    "hi": sum(f["hi"] for f in rows),
                    "confident": sum(f["lo"] for f in rows) == sum(f["hi"] for f in rows),
                    "also": [[len(rows), "passes"]],
                }
            )
        # "The most" needs the leader's least to beat everyone else's most.
        if out:
            others_hi = max((sum(f["hi"] for f in rows) for _, rows in ranked[1:]), default=-1)
            out[0]["leads"] = out[0]["lo"] > others_hi
            out[0]["confident"] = out[0]["confident"] and out[0]["leads"]
        if team is not None:
            out = [r for r in out if r["team"] == team]
        return {"facts": out, "summary": []}

    def possession(self, minute_from: int, minute_to: int, club: str | None = None) -> dict:
        """Each club's share of the passes over the minutes, the pass ratio Opta publishes as possession."""
        return self._window_summary(ball_share.possession, "possession", minute_from, minute_to, club)

    def territory(self, minute_from: int, minute_to: int, club: str | None = None) -> dict:
        """Where the ball was over the minutes: each club's share with it in its attacking third."""
        return self._window_summary(ball_share.territory, "territory", minute_from, minute_to, club)

    def shots(self, minute_from: int, minute_to: int, club: str | None = None) -> dict:
        """The shot map over the minutes: each shot's spot, its distance from the goal and the angle
        the posts make there, nearest first; and each club's shots and those from inside the penalty area."""
        team = self.team(club)
        rows = self._rows("shot", minute_from, minute_to, club)
        top = sorted(rows, key=lambda r: (r["value"], r["t"]))[:MAX_FACTS]
        clubs = self.fixture.clubs
        got = shot_map.summary(self.facts.get("shot", ()), minute_from, minute_to)
        summary = [
            {**r, "club": clubs.get(t)} for t, r in got.items() if t == "all" or team in (None, t)
        ]
        return {"facts": top, "summary": summary}

    def _window_summary(self, fn, kind: str, minute_from: int, minute_to: int, club: str | None) -> dict:
        team = self.team(club)
        got = fn(self.facts.get(kind, ()), minute_from, minute_to)
        clubs = self.fixture.clubs
        summary = [{**r, "club": clubs[t], "clubs": clubs} for t, r in got.items() if team in (None, t)]
        return {"facts": [], "summary": summary}

    def style(self, minute_from: int, minute_to: int, club: str | None = None) -> dict:
        """How each club played over the minutes: its passing channels, its width beside the other
        club's, its crosses, its keeper's distribution, and its counter-attacks and one-twos."""
        team = self.team(club)
        teams = [team] if team else list(TEAMS)
        clubs = self.fixture.clubs
        rows = [p for p in self.facts.get("pass", ()) if minute_from <= p["minute"] <= minute_to]
        summary = []
        for t in teams:
            for got in (
                style.channels(rows, t, minute_from, minute_to, clubs[t]),
                style.width(self.facts.get("shape", []), t, minute_from, minute_to, clubs),
                style.crosses(rows, t, minute_from, minute_to, clubs[t]),
                style.keeper(rows, t, minute_from, minute_to, clubs[t], self.people),
            ):
                if got is not None:
                    summary.append(got)
        moments = [
            {**f, "club": clubs[f["team"]]}
            for kind in ("counter", "one_two")
            for f in self.facts.get(kind, ())
            if minute_from <= f["minute"] <= minute_to and f["team"] in teams
        ]
        return {"facts": moments[:MAX_FACTS], "summary": summary}

    def referee(self, minute_from: int, minute_to: int, club: str | None = None) -> dict:
        """The offside readings of the minutes (the attacking club's, or both), latest first, and the
        Law summaries the Referee explains calls from (ninety/agents/referee.py)."""
        from ninety.agents.referee import law_facts

        rows = sorted(self._rows("offside", minute_from, minute_to, club), key=lambda r: -r["t"])
        return {"facts": rows[:MAX_FACTS], "summary": law_facts()}

    def lineup(self, club: str | None = None) -> dict:
        """The team sheets, and who of the tracked players may be named and how."""
        team = self.team(club)
        teams = [team] if team else list(TEAMS)
        return {
            "clubs": self.fixture.clubs,
            "sheets": {t: [s for s in self.fixture.as_dict()["sheets"][t]] for t in teams},
            "gates": self.gates,
            "players": sorted(
                (p for p in self.people.values() if p["team"] in teams and p["role"]),
                key=lambda p: (p["team"], p["role"] or "", p["track"]),
            ),
        }

    def known(self) -> dict[str, dict]:
        """Every fact by id, summaries included for the whole match, as the fact-checker reads them."""
        out = {r["id"]: r for rows in self.facts.values() for r in rows}
        return out

    def sheet_names(self) -> list[str]:
        return [s.name for t in TEAMS for s in self.fixture.sheet(t)]

    def as_dict(self) -> dict:
        return {
            "clip": self.clip,
            "fixture": {
                "seed": self.fixture.seed,
                "home_code": self.fixture.home_code,
                "away_code": self.fixture.away_code,
            },
            "minutes": self.minutes,
            "gates": self.gates,
            "people": self.people,
            "team_stats": self.team_stats,
            "stats": self.stats,
            "facts": self.facts,
        }

    @classmethod
    def from_dict(cls, body: Mapping) -> MatchInsights:
        fx = body["fixture"]
        return cls(
            body["clip"],
            Fixture(int(fx["seed"]), fx["home_code"], fx["away_code"]),
            dict(body["facts"]),
            dict(body["people"]),
            int(body["minutes"]),
            dict(body.get("gates") or {}),
            dict(body.get("team_stats") or {}),
            dict(body.get("stats") or {}),
        )


CHANGE_CONTEXT = r"\b(?:up|back|by|forward|deeper|higher|further)\s+$"


def shape_also(r: Mapping) -> list:
    """A shape fact's other number: its change, said right after the move ("pushed up 6 m"), while
    its value (the line's height) is the one after "to". Both are metres, so each is bound to its own
    role (lesson 221)."""
    return [[abs(r["change"]), r["unit"], CHANGE_CONTEXT]] if r.get("change") else []


def shape_drawings(frames: Sequence[Mapping]) -> dict[tuple[str, int], dict]:
    """What the phone draws for a team's shape in a minute: its players in the frame of that minute
    with most of them tracked (the latest, on a tie), and its outfield players split into back, middle
    and front lines at the two largest gaps in depth, as the shape facts split them (shape.lines), each
    line ordered across the pitch. The keeper is left out as the shape facts leave him out."""
    best: dict[tuple[str, int], Mapping] = {}
    for fr in frames:
        for team in TEAMS:
            key = (team, shape.minute_of(fr["t"]))
            n = sum(p["team"] == team for p in fr["players"])
            old = best.get(key)
            if old is None or n >= sum(p["team"] == team for p in old["players"]):
                best[key] = fr
    out = {}
    for (team, minute), fr in best.items():
        own = [p for p in fr["players"] if p["team"] == team]
        if len(own) < 4:
            continue
        ranked = sorted(own, key=lambda p: shape.depth(team, p["x"]))
        if shape.in_own_penalty_area(shape.depth(team, ranked[0]["x"]), ranked[0]["y"]):
            ranked = ranked[1:]
        depths = [shape.depth(team, p["x"]) for p in ranked]
        gaps = sorted(range(1, len(depths)), key=lambda i: (depths[i] - depths[i - 1], -i), reverse=True)[:2]
        a, b = sorted(gaps)
        lines = [
            sorted(ranked[:a], key=lambda p: p["y"]),
            sorted(ranked[a:b], key=lambda p: p["y"]),
            sorted(ranked[b:], key=lambda p: p["y"]),
        ]
        out[(team, minute)] = {
            "lines": [[xy(p) for p in line] for line in lines],
            "players": [xy(p) for p in own],
        }
    return out


def load_fixture(path: Path) -> Fixture:
    """A clip's fixture: its seed and the two club codes, from its clip.json (`seed` and
    `params.home_code`/`params.away_code`) or a file holding just those three."""
    body = json.loads(Path(path).read_text())
    params = body.get("params", body)
    return Fixture(int(body["seed"]), params["home_code"], params["away_code"])


def main(argv: list[str] | None = None) -> None:
    from ninety.match import detected, tracking

    ap = argparse.ArgumentParser(
        description="A clip's insight facts, from tracked frames and detected events."
    )
    ap.add_argument("tracked", type=Path)
    ap.add_argument("detected", type=Path)
    ap.add_argument("fixture", type=Path, help="the clip's clip.json, or {seed, home_code, away_code}")
    ap.add_argument("--clip", required=True)
    ap.add_argument("--out", type=Path, required=True)
    args = ap.parse_args(argv)
    body = json.loads(args.tracked.read_text())
    frames = [f for f in body["frames"] if f.get("source") == tracking.TRACKED]
    if len(frames) != len(body["frames"]):
        raise SystemExit(f"{args.tracked}: every frame must be source {tracking.TRACKED!r}")
    mi = MatchInsights.build(args.clip, frames, detected.load(args.detected), load_fixture(args.fixture))
    args.out.write_text(json.dumps(mi.as_dict(), separators=(",", ":")))
    print(f"{args.out}: " + ", ".join(f"{k} {len(v)}" for k, v in mi.facts.items()))


if __name__ == "__main__":
    main()
