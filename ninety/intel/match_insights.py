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

from ninety.intel import counter_press, line_breaks, overloads, pass_options, roles, shape
from ninety.intel.scene import TEAMS, Frames
from ninety.intel.teamsheet import Fixture

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
                    "also": [[abs(r["change"]), r["unit"]]] if r.get("change") else [],
                    "visual": {"kind": "shape", "minute": r["minute"]},
                }
                for r in shape.shape_rows(f.frames)
            ],
        }
        clubs = fixture.clubs
        for rows in facts.values():
            for r in rows:
                r["club"] = clubs[r["team"]]
                for k in ("passer", "receiver"):
                    if r.get(k) in people:
                        r[f"{k}_is"] = people[r[k]]["say"]
        last = max((float(fr["t"]) for fr in f.frames), default=0.0)
        return cls(clip, fixture, facts, people, int(last // 60) + 1, gate)

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
            for r in self.facts[kind]
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
        )


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
