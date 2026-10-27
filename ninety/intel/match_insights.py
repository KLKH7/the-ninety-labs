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
    naming,
    offside,
    overloads,
    pass_options,
    passing,
    physical,
    roles,
    scoring,
    set_pieces,
    shape,
    shot_map,
    style,
)
from ninety.intel import identity as identity_mod
from ninety.intel import team_stats as team_stats_mod
from ninety.intel.scene import TEAMS, Frames, minute_of, xy
from ninety.intel.teamsheet import Fixture

BUILD_UP_S = 60.0  # design: a goal's build-up is the minute before it
MAX_FACTS = 12  # design: the most facts a tool returns, the strongest first, so a prompt stays short
HALF_MIN = 45  # Law 7: two halves of 45 minutes (GROUNDING I23)
# The kinds a key moment is drawn from, each already a checked fact (GROUNDING I23, *design*).
MOMENT_KINDS = ("goal", "shot", "counter", "one_two", "line_break")
TOP_LINE_BREAKS = 3  # design: a window's key line breaks are its biggest three
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
    # A joined match's broadcast tracks (the ids its events name) -> what a fan may be told of each,
    # through the camera join (ninety/intel/naming.broadcast_people); empty for a single camera.
    broadcast: dict = field(default_factory=dict)
    # Names from the player-ID feed (ninety/intel/identity.py), tactical and broadcast tracks: the
    # bundle's line-up, and a goal's scorer's name. No statistic or person record reads them.
    identity: dict = field(default_factory=dict)
    identity_broadcast: dict = field(default_factory=dict)
    identity_source: dict = field(default_factory=dict)

    @classmethod
    def build(
        cls,
        clip: str,
        frames: Sequence[Mapping],
        events: Sequence[Mapping],
        fixture: Fixture,
        gate: Mapping | None = None,
        association: Mapping[str, Mapping] | None = None,
        score_reads: Sequence[Mapping] = (),
        feed: identity_mod.Feed | None = None,
        broadcast_frames: Sequence[Mapping] | None = None,
    ) -> MatchInsights:
        bad = sorted({str(fr.get("source")) for fr in frames} - {"tracked"})
        if bad:  # the live path's positions are tracked ones; the simulator's are the answer key
            raise ValueError(f"{clip}: frames must be source 'tracked', got {bad}")
        f = Frames(frames)
        detected_events = list(events)  # as vision detected them, before any person is moved
        broadcast: dict[str, dict] = {}
        if association is not None:
            # A joined match: the players are the tactical camera's tracks and the events name the
            # broadcast's, two id spaces in which one id is two different men. Names come from the
            # whole-pitch tracks (ninety/intel/naming.py), and every person an event names is moved
            # to his tactical track before any fact reads him, or to none (lesson 259).
            gate = dict(naming.gates() if gate is None else gate)
            people = naming.people(f.frames, fixture, gate)
            broadcast = naming.broadcast_people(association, people, fixture, gate)
            events = naming.tactical_events(events, association, gate)
        else:
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
        # Possession share (time in possession) and territory (where the ball was): GROUNDING I17b, I18.
        facts["possession"] = ball_share.possession_rows(f.frames)
        facts["territory"] = ball_share.territory_rows(f.frames)
        facts["shot"] = shot_map.shots(events)  # the shot map (GROUNDING I19)
        facts["pass_type"] = passing.rows(events)  # what the passes did, and to whom (I20, I21)
        facts["running"] = physical.rows(f.frames)  # each track's running, per minute (I22)
        # Goals as vision detected them: what "why did that goal happen?" is asked about.
        facts["goal"] = scoring.goals(events)  # who scored, from whose pass (GROUNDING I24)
        facts["save"] = scoring.saves(events)
        # The score as the broadcast shows it: the changes among the events, and the scorebug file's
        # readings (`score_reads`), whose first holds the score before any change.
        facts["scorebug"] = scoring.scorebug([*events, *score_reads])
        facts["restart"] = set_pieces.rows(events)  # corners, free kicks and the rest (I25)
        facts["spell"] = spell_rows(events)  # runs of passes, receiver to passer (ninety/speech/spells.py)
        for rows in facts.values():
            for r in rows:
                r["club"] = clubs.get(r["team"])  # None for a fact whose side is not known
                for k in ("passer", "receiver", "assister"):
                    if r.get(k) in people:
                        r[f"{k}_is"] = people[r[k]]["say"]
                if r.get("kind") == "goal" and r.get("player") in people:
                    r["scorer_is"] = people[r["player"]]["say"]
        last = max((float(fr["t"]) for fr in f.frames), default=0.0)
        mi = cls(clip, fixture, facts, people, int(last // 60) + 1, gate, team_stats_mod.team_stats(f.frames))
        mi.broadcast = broadcast
        from ninety.intel.stats_table import stats_table

        mi.stats = stats_table(mi)  # the phone's Stats tab, from the same tools the Companion reads
        if feed is not None:
            # Last, after every fact and stat is computed: the feed names tracks and nothing else
            # (an event's side from the feed is set before, in the detected file: identity.sided).
            if not feed.matches(fixture):
                raise ValueError(f"{clip}: the player-ID feed is another fixture's (seed "
                                 f"{feed.meta.get('seed')}, {feed.meta['teams']})")
            mi.identity = identity_mod.tactical(f.frames, feed)
            if association is not None:
                mi.identity_broadcast = identity_mod.named_broadcast(
                    association, mi.identity, feed, detected_events, broadcast_frames)
            mi.identity_source = identity_mod.disclosure(feed)
            # A goal's scorer by name where the feed names the broadcast track vision says scored:
            # a name, never whether, when or for whom (the goal and its side stay vision's).
            by_id = {e["id"]: e for e in detected_events}
            for g in mi.facts.get("goal", ()):
                w = mi.identity_broadcast.get((by_id.get(g["event"]) or {}).get("player") or "")
                if g.get("player") and w and w["team"] == g["team"]:
                    g["scorer_is"], g["scorer_source"] = w["name"], identity_mod.SOURCE
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
        """Each club's share of the time either had the ball over the minutes (time in possession);
        and the longest spells of passes in a row (a run vision followed receiver to passer, which
        needs no side told), longest first."""
        out = self._window_summary(ball_share.possession, "possession", minute_from, minute_to, club)
        spells = [r for r in self.facts.get("spell", ()) if minute_from <= r["minute"] <= minute_to]
        spells.sort(key=lambda r: (-r["value"], r["t"]))
        return {**out, "facts": [*out.get("facts", []), *spells[:1]]}

    def territory(self, minute_from: int, minute_to: int, club: str | None = None) -> dict:
        """Where the ball was over the minutes: each club's share with it in its attacking third."""
        return self._window_summary(ball_share.territory, "territory", minute_from, minute_to, club)

    def on_top(self, minute_from: int, minute_to: int, club: str | None = None) -> dict:
        """Which club has been on top over the minutes, by where the ball was (territory, I18): a club
        leads only when the least share of the footage with the ball in its attacking third is more
        than the other's most; else neither. Both clubs' territory beside it. Possession over an
        arbitrary stretch is not used: it is measured only from kick-off and per half (I17b)."""
        got = self._window_summary(ball_share.territory, "territory", minute_from, minute_to, None)
        terr = {r["team"]: r for r in got["summary"]}
        lead = None
        if len(terr) == 2:
            h, a = terr["home"], terr["away"]
            lead = "home" if h["lo"] > a["hi"] else "away" if a["lo"] > h["hi"] else None
        clubs = self.fixture.clubs
        row = {"id": f"on_top:m{minute_from}-{minute_to}", "kind": "on_top", "metric": "on_top",
               "team": lead, "club": clubs.get(lead), "clubs": clubs, "minute_from": minute_from,
               "minute_to": minute_to, "confident": len(terr) == 2,
               "evidence": [r["id"] for r in terr.values()]}
        return {"facts": [], "summary": [row, *got["summary"]]}

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

    def passing(self, minute_from: int, minute_to: int, club: str | None = None) -> dict:
        """What the passes did over the minutes (progressive, into the final third, long,
        intercepted), each club's count and the total; and the pairs of named players who passed to
        each other most."""
        team = self.team(club)
        rows = self.facts.get("pass_type", ())
        clubs = self.fixture.clubs
        summary = [
            {**r, "club": clubs.get(r["team"])}
            for r in passing.summary(rows, minute_from, minute_to)
            if r["team"] is None or team in (None, r["team"])
        ]
        pairs = [
            {**r, "club": clubs[r["team"]]}
            for r in passing.network(rows, self.people, minute_from, minute_to)
            if team in (None, r["team"])
        ]
        return {"facts": pairs, "summary": summary}

    def physical(self, minute_from: int, minute_to: int, club: str | None = None) -> dict:
        """Each named player's distance (km, from the footage shown, with its measured label), top
        speed, sprints above 25.2 km/h and the zone he was in most, over the minutes."""
        team = self.team(club)
        clubs = self.fixture.clubs
        lb, bar = physical.labels(), team_stats_mod.within_pct()
        # Each figure is said only when the grading of named players (docs/eval/physical.md) is no
        # worse than the bar the phone already accepts for it: team distance's label for distance and
        # sprint counts, the phone card's worst measured top-speed error for top speed (GROUNDING I22).
        held = physical.held(lb, bar)
        facts = []
        for r in physical.players(self.facts.get("running", ()), self.people, minute_from, minute_to):
            if team not in (None, r["team"]):
                continue
            r = {**r, "club": clubs[r["team"]]}
            why = held.get(r["metric"])
            if why:
                r["confident"], r["why_held"] = False, why
            elif r["metric"] == "player_km":
                r["also"], r["within_pct"] = [[lb["distance_pct"], "%"]], lb["distance_pct"]
            facts.append(r)
        return {"facts": facts, "summary": []}

    def set_pieces(self, minute_from: int, minute_to: int, club: str | None = None) -> dict:
        """Each kind of restart over the minutes: the total, and each club's count with bounds."""
        team = self.team(club)
        clubs = self.fixture.clubs
        summary = [
            {**r, "club": clubs.get(r["team"])}
            for r in set_pieces.summary(self.facts.get("restart", ()), minute_from, minute_to)
            if r["team"] is None or team in (None, r["team"])
        ]
        return {"facts": [], "summary": summary}

    def score(self, minute_from: int, minute_to: int, club: str | None = None) -> dict:
        """Each goal up to minute_to with its scorer and assist, oldest first, and each club's saves
        over the minutes; the score's own counts are bookkeeping, never said (option B)."""
        team = self.team(club)
        clubs = self.fixture.clubs
        goals = [g for g in self.facts.get("goal", ()) if g["minute"] <= minute_to]
        shown = [r for r in self.facts.get("scorebug", ()) if r["minute"] <= minute_to]
        # The latest reading, its two numbers each bound to its club (lesson 221), as the score's are.
        summary = [{**shown[-1], "value": shown[-1]["home"], "unit": "goals", "clubs": clubs, "club": None,
                    "also": [[shown[-1]["away"], "goals", rf"\b{clubs['away']}\b[^.\d]*$"]]}] if shown else []
        summary += [{**scoring.score(goals, minute_to, clubs), "clubs": clubs, "club": None}]
        summary += [
            {**r, "club": clubs[t]}
            for t, r in scoring.save_counts(self.facts.get("save", ()), minute_from, minute_to).items()
            if team in (None, t)
        ]
        timeline = sorted((g for g in goals if team in (None, g["team"])), key=lambda g: g["t"])
        return {"facts": timeline[:MAX_FACTS], "summary": summary}

    def halves(self, minute_from: int = 1, minute_to: int | None = None, club: str | None = None) -> dict:
        """The same summaries for each half (Law 7's 45 minutes) up to minute_to (the match so far
        when None): where the ball was, the shots and what the passes did, first half then second, so
        a fan can compare them. minute_from is ignored: a half starts where the Law starts it."""
        now = self.minutes if minute_to is None else min(minute_to, self.minutes)
        spans = [(1, min(HALF_MIN, now))]
        if now > HALF_MIN:
            spans.append((HALF_MIN + 1, now))
        summary = []
        for lo, hi in spans:
            for tool in (self.territory, self.shots, self.passing):
                summary += tool(lo, hi, club)["summary"]
        return {"facts": [], "summary": summary}

    def key_moments(self, minute_from: int, minute_to: int, club: str | None = None) -> dict:
        """The window's key moments, latest first: its goals, shots, regains that led to a shot,
        one-twos and its biggest line breaks, each a fact code can say."""
        moments = []
        for kind in MOMENT_KINDS:
            rows = [r for r in self._rows(kind, minute_from, minute_to, club) if r.get("confident")]
            if kind == "line_break":
                rows = sorted(rows, key=lambda r: (-r["value"], r["t"]))[:TOP_LINE_BREAKS]
            moments += rows
        # Every goal stays, however many other moments there are: a recap never drops a goal. The
        # rest fill the remaining places, latest first.
        goals = [r for r in moments if r["kind"] == "goal"]
        rest = sorted((r for r in moments if r["kind"] != "goal"), key=lambda r: -r["t"])
        kept = goals + rest[: max(0, MAX_FACTS - len(goals))]
        kept.sort(key=lambda r: -r["t"])
        return {"facts": kept, "summary": []}

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
            # The two team sheets (names, shirts, positions): pre-match facts, never a track's.
            "sheets": {t: [{k: s[k] for k in ("number", "name", "position", "line")} for s in rows]
                       for t, rows in self.fixture.as_dict()["sheets"].items()},
            "gates": self.gates,
            "people": self.people,
            "team_stats": self.team_stats,
            "stats": self.stats,
            "facts": self.facts,
            **({"broadcast": self.broadcast, "lineup": naming.lineup(self.broadcast)}
               if self.broadcast else {}),
            # With a player-ID feed, the line-up is the feed's (marked source id_feed), and the
            # tactical tracks' names come with it for the radar and the player card.
            **({"identity": self.identity_source, "identity_tracks": self.identity,
                "identity_broadcast": self.identity_broadcast,
                "lineup_tactical": identity_mod.lineup(self.identity)}
               if self.identity_source else {}),
            **({"lineup": identity_mod.lineup(self.identity_broadcast)} if self.identity_broadcast else {}),
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
            dict(body.get("broadcast") or {}),
            dict(body.get("identity_tracks") or {}),
            dict(body.get("identity_broadcast") or {}),
            dict(body.get("identity") or {}),
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


def spell_rows(events: Sequence[Mapping]) -> list[dict]:
    """Each spell of possession (ninety/speech/spells.py) as an insight fact: its passes, when it ended,
    and its side only when every pass's was told surely."""
    from ninety.agents import factcheck
    from ninety.speech import spells

    rows = []
    for run in spells.spells(list(events)):
        last, team = run[-1], run[-1].get("team")
        sure = team in TEAMS and all(e.get("team") == team and factcheck.side_known(e) for e in run)
        rows.append({"id": f"spell:{last['id']}", "kind": "spell", "metric": "spell_passes",
                     "team": team if sure else None, "minute": minute_of(float(last["t"])),
                     "t": round(float(last["t"]), 2), "value": len(run), "unit": "passes", "confident": True,
                     "events": [e["id"] for e in run]})
    return rows


def score_reads(path: Path) -> list[dict]:
    """A clip's scorebug.jsonl (ninety/vision/scorebug.py): its readings of the score, the vision ones."""
    rows = (json.loads(line) for line in path.read_text().splitlines() if line.strip())
    return [r for r in rows if r.get("type") in scoring.SCORE_TYPES and r.get("source") == "vision"]


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
    ap.add_argument("--association", type=Path,
                    help="a joined match's association.json: names cross the camera join (naming.py)")
    ap.add_argument("--identity-feed", type=Path, default=None,
                    help="the simulated tracking provider's player-ID feed (ninety/sim/identity_feed.py): "
                         "names for the line-up only, never a fact or a stat")
    ap.add_argument("--broadcast-vision", type=Path, default=None,
                    help="with --identity-feed: the segments' vision runs, to name the broadcast's tracks "
                         "directly from the feed too (ninety/intel/identity.py, step 6)")
    ap.add_argument("--scorebug", type=Path, default=None,
                    help="the clip's scorebug.jsonl (ninety/vision/scorebug.py): its readings of the score")
    args = ap.parse_args(argv)
    body = json.loads(args.tracked.read_text())
    frames = [f for f in body["frames"] if f.get("source") == tracking.TRACKED]
    if len(frames) != len(body["frames"]):
        raise SystemExit(f"{args.tracked}: every frame must be source {tracking.TRACKED!r}")
    association = json.loads(args.association.read_text())["tracks"] if args.association else None
    reads = score_reads(args.scorebug) if args.scorebug is not None else []
    feed, b_frames = None, None
    if args.identity_feed:  # the player-ID feed: names (and nothing else) for the line-up
        b_frames = (identity_mod.broadcast_frames(args.broadcast_vision, args.fixture.parent)
                    if args.broadcast_vision else [])
        feed = identity_mod.load_for(args.identity_feed, [*frames, *b_frames], load_fixture(args.fixture))
    mi = MatchInsights.build(args.clip, frames, detected.load(args.detected), load_fixture(args.fixture),
                             association=association, score_reads=reads,
                             feed=feed, broadcast_frames=b_frames)
    args.out.write_text(json.dumps(mi.as_dict(), separators=(",", ":")))
    print(f"{args.out}: " + ", ".join(f"{k} {len(v)}" for k, v in mi.facts.items()))


if __name__ == "__main__":
    main()
