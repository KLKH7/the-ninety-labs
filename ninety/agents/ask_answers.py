"""Code's answer to each row of the intent table (ninety/agents/ask_intents.py).

Every number is computed here from the insights' facts timed at or before the question (never a
fact from after it), and each sentence is checked by the insight fact-check against the facts it
cites. A derived fact (a count, a share, a comparison) carries the ids of the facts it was
computed from, so the answer's evidence leads back to them. A comparison always states both clubs
and who leads; a figure about what vision saw says it is "in the footage we've seen" (the clips
show part of the match). When a row's facts are missing, its honest fallback says so and gives the
closest measured fact instead; an answer whose lead sentence does not carry the row's metric is not
shown (the relevance gate).
"""

from __future__ import annotations

import re

from ninety.agents.ask_intents import BY_ID, HALF_MIN, Read, Window, played
from ninety.agents.contracts import Answer, Question
from ninety.agents.factcheck import Claim

SEEN = "in the footage we've seen"
SCORE_POINTER = "The broadcast's scorebug shows the score; vision does not keep one."
# Fixed text, stating no fact: possession is unknown before a minute of either side on the ball was seen.
POSSESSION_UNKNOWN = (
    "Possession can't be split between the clubs for those minutes: it is measured "
    "from kick-off and from each half's start, once a minute of either side on the ball "
    "has been seen."
)
# What vision's event detection misses, said after a count it gives (fixed words, no number): on the
# demo match it spots fewer shots and restarts than were played, and its pass count is not exact.
MISSES = {
    "shots": "Vision doesn't catch every shot, so the true count may be higher.",
    "restarts": "Vision doesn't catch every restart, so the true count may be higher.",
    "passes": "Vision's pass count isn't exact: it misses some passes and counts some that weren't.",
}
FEED_NOTE = "The scorer's name comes from the Player ID feed."
PITCH_X = 105.0  # the pitch's length (ninety/intel/ball_share.PITCH_X); home attacks towards x = 105
BUILD_UP_S = 60.0  # design, as match_insights.BUILD_UP_S: a goal's build-up is the minute before it
SHOT_BEFORE_GOAL_S = 6.0  # design: a shot this close before a goal of its side is the goal's shot
MIN_PASSES = 15  # design (as companion_match.MIN_SHARE_PASSES): a completion rate needs this many passes
UNMEASURED = {
    "offside": "Vision doesn't call offside, so it can't say whether anyone was: it reads the offside "
    "line at each completed pass it sees.",
    "fouls": "Vision doesn't detect fouls, so it can't count them.",
    "cards": "Vision doesn't see cards or bookings, so it can't count them.",
    "saves": "Vision can't yet tell a save from other shots reliably, so it doesn't count saves.",
    "tackles": "Vision doesn't detect tackles, so it can't count them.",
    "referee": "Vision doesn't judge the referee's calls.",
}
NOT_MATCH = {
    "inject": (
        "I only answer questions about this match, from what the cameras tracked, and I can't "
        "change how I answer. Try one of these:"
    ),
    "future": "I can't predict what will happen: I only know what has happened so far. Try one of these:",
    "outside": (
        "The match tracking can't tell that: it sees where the players and the ball are, not "
        "names, money, the crowd or the weather. Try one of these:"
    ),
}


def possessive(club: str) -> str:
    """ "Lisbon Esportes'", "London Athletic's"."""
    return f"{club}'" if club.endswith("s") else f"{club}'s"


def _plural(n: int, one: str, many: str | None = None, zero: bool = False) -> str:
    """ "1 shot", "3 shots"; "no shots" for a zero when `zero` (a total, never one club's figure)."""
    if zero and n == 0:
        return f"no {many or one + 's'}"
    return f"{n} {one if n == 1 else (many or one + 's')}"


class Ctx:
    """What a builder reads: the insights, the question's time, the read, and the derived facts it
    makes (added to the fact-check's known facts)."""

    def __init__(self, insights, read: Read, t: float):
        self.mi, self.read, self.t = insights, read, float(t)
        self.clubs = insights.fixture.clubs
        self.team_of = {name: team for team, name in self.clubs.items()}
        self.derived: dict[str, dict] = {}
        self.sources: list[dict] = []  # the last restarts read, for a derived count's evidence
        self.known = {**insights.known()}
        for f in self.known.values():
            f.setdefault("clubs", self.clubs)

    def other(self, team: str) -> str:
        return "away" if team == "home" else "home"

    def events(self, kind: str, w: Window | None = None) -> list[dict]:
        """The facts of a kind timed at or before now, inside the window's minutes (to now when the
        window runs to the last minute played)."""
        w = w or self.read.window
        hi_t = self.t if w.hi >= played(self.t) else 60.0 * w.hi
        lo_t = 60.0 * (w.lo - 1)
        return sorted(
            (
                f
                for f in self.mi.facts.get(kind, ())
                if f.get("t") is not None and lo_t <= float(f["t"]) <= hi_t
            ),
            key=lambda f: float(f["t"]),
        )

    def footage_s(self, w: Window) -> float | None:
        """Seconds of footage seen in the window's minutes (the territory rows sample every second of
        it, once per club); None when the insights carry no such rows to tell."""
        rows = [
            r
            for r in self.mi.facts.get("territory", ())
            if r.get("kind") == "territory_minute" and r.get("team") == "home"
        ]
        if not rows:
            return None
        return sum(float(r.get("seconds") or 0) for r in rows if w.lo <= r["minute"] <= w.hi)

    def fact(
        self,
        key: str,
        metric: str,
        value,
        unit: str | None,
        team: str | None = None,
        also=(),
        sources=(),
        w: Window | None = None,
        **extra,
    ) -> dict:
        w = w or self.read.window
        f = {
            "id": f"ask:{key}:m{w.lo}-{w.hi}",
            "kind": "ask",
            "metric": metric,
            "team": team,
            "club": self.clubs.get(team) if team else None,
            "clubs": self.clubs,
            "minute_from": w.lo,
            "minute_to": w.hi,
            "value": value,
            "unit": unit,
            "also": [list(a) for a in also],
            "confident": True,
            "evidence": [s["id"] if isinstance(s, dict) else s for s in sources],
            **extra,
        }
        self.derived[f["id"]] = f
        self.known[f["id"]] = f
        return f

    def ok(self, text: str, cited: list[dict]) -> bool:
        from ninety.agents import insight_check

        for f in cited:  # a tool's summary (players, territory) is known by the tool that made it
            self.known.setdefault(f["id"], {**f, "clubs": f.get("clubs") or self.clubs})
        claim = Claim(text, [f["id"] for f in cited])
        return insight_check.verify(claim, self.known, self.clubs, self.mi.people, self.mi.sheet_names()).ok


class Reply:
    """An answer being built: sentences with the facts each cites. The first is the lead."""

    def __init__(self):
        self.lines: list[tuple[str, list[dict]]] = []
        self.notes: list[str] = []  # said after the answer: a stretch that isn't played yet, a gap
        self.uncited: list[dict] = []  # facts a sentence of fixed words is about (evidence only)
        self.head: str | None = None
        self.status = "verified"

    def say(self, text: str, *cited: dict) -> Reply:
        self.lines.append((text, [c for c in cited if c]))
        return self


def _short(ctx: Ctx, team: str) -> str:
    from ninety.intel.teamsheet import short_name

    fx = ctx.mi.fixture
    return short_name(fx.home_code if team == "home" else fx.away_code)


def _when(w: Window) -> str:
    return w.said


# -- score, scorers, winning --------------------------------------------------------------------


def _scorebug(ctx: Ctx) -> dict | None:
    """The scorebug's latest reading at or before now, each number bound to its club (as
    match_insights.score gives it, lesson 221)."""
    rows = [
        r for r in ctx.mi.facts.get("scorebug", ()) if r.get("confident") and float(r.get("t") or 0) <= ctx.t
    ]
    if not rows:
        return None
    cl = ctx.clubs
    bug = {
        **rows[-1],
        "value": rows[-1]["home"],
        "unit": "goals",
        "clubs": cl,
        "club": None,
        "also": [[rows[-1]["away"], "goals", rf"\b{cl['away']}\b[^.\d]*$"]],
    }
    ctx.known[bug["id"]] = bug
    return bug


def _score_line(ctx: Ctx, bug: dict) -> str:
    cl = ctx.clubs
    return (
        f"{cl['home']} {_plural(bug['home'], 'goal')}, {cl['away']} {_plural(bug['away'], 'goal')}, "
        "read from the broadcast's scorebug."
    )


def _goals(ctx: Ctx, team: str | None = None) -> list[dict]:
    return [
        g
        for g in ctx.events("goal", Window(1, 90, "so far", False))
        if g.get("side_known", True) and g.get("team") and (team is None or g["team"] == team)
    ]


def _no_scorebug(ctx: Ctx) -> Reply:
    """No scorebug reading yet: never a scoreline from vision (option B, Kian, Oct 26), which finds
    some goals and misses others; the pointer, then each goal vision spotted."""
    r = scorers(ctx)
    r.lines.insert(0, (SCORE_POINTER, []))
    r.head = "Goals spotted by vision" if _goals(ctx) else "See the scorebug"
    return r


def score(ctx: Ctx) -> Reply:
    r, bug = Reply(), _scorebug(ctx)
    if bug is None:
        return _no_scorebug(ctx)
    r.say(_score_line(ctx, bug), bug)
    r.head = f"{_short(ctx, 'home')} {bug['home']}, {_short(ctx, 'away')} {bug['away']}"
    return r


def winning(ctx: Ctx) -> Reply:
    r, bug = Reply(), _scorebug(ctx)
    if bug is None:
        return _no_scorebug(ctx)
    h, a = bug["home"], bug["away"]
    lead = None if h == a else ("home" if h > a else "away")
    asked = ctx.read.club
    if lead is None:
        r.say("It's level." if h else "It's level: no goals yet.", bug)
    elif asked and ctx.team_of[asked] != lead:
        r.say(f"No, {asked} are behind: {ctx.clubs[lead]} are winning.", bug)
    else:
        r.say(f"{ctx.clubs[lead]} are winning.", bug)
    r.say(_score_line(ctx, bug), bug)
    r.head = f"{_short(ctx, 'home')} {h}, {_short(ctx, 'away')} {a}"
    return r


def _goal_sentence(g: dict) -> str:
    if g.get("scorer_is") and g.get("scorer_source") == "id_feed":
        return f"{g['scorer_is']} scored for {g['club']} in minute {g['minute']}."
    return f"{g['club']} scored in minute {g['minute']}."


def scorers(ctx: Ctx) -> Reply:
    """The scorebug's reading first (Kian, Oct 26), then each goal vision spotted and can vouch for
    (its detection over the fact-check's floor), by minute, by name when the Player ID feed gives one."""
    from ninety.agents.factcheck import MIN_CONFIDENCE

    r = Reply()
    asked = ctx.read.club
    bug = _scorebug(ctx)
    seen = [
        g
        for g in ctx.events("goal", Window(1, 90, "so far", False))
        if (g.get("event_confidence") is None or g["event_confidence"] >= MIN_CONFIDENCE)
    ]
    goals = [
        g
        for g in seen
        if g.get("side_known", True) and g.get("team") and (asked is None or g["team"] == ctx.team_of[asked])
    ]
    unplaced = [g for g in seen if not (g.get("side_known", True) and g.get("team"))] if asked is None else []
    if bug is not None:
        r.say(_score_line(ctx, bug), bug)
        r.head = f"{_short(ctx, 'home')} {bug['home']}, {_short(ctx, 'away')} {bug['away']}"
    if not goals and not unplaced:
        r.say(
            f"{asked} haven't scored yet."
            if asked and bug is not None and bug[ctx.team_of[asked]] == 0
            else "Vision has spotted no goal it can vouch for so far."
        )
        r.head = r.head or "No goal yet"
        return r
    for g in goals:
        r.say(_goal_sentence(g), g)
    for g in unplaced:
        # Fixed words around its minute: a goal of no known side names no club (code_texts says none).
        r.say(f"It spotted a goal in minute {g['minute']} too, without telling whose it was.")
        r.uncited.append(g)
    if any(g.get("scorer_source") == "id_feed" for g in goals):
        r.say(FEED_NOTE)
    if bug is not None and asked is None and bug["home"] + bug["away"] > len(goals) + len(unplaced):
        r.say("The scorebug shows more goals than vision spotted.", bug)
    r.head = r.head or ", ".join(f"{_short(ctx, g['team'])} {g['minute']}′" for g in goals)[:48] or None
    return r


# -- comparisons of the two clubs -------------------------------------------------------------------


def _order(ctx: Ctx, lead: str | None) -> tuple[str, str]:
    """The club said first: the one asked about, else the leader, else the home club."""
    asked = ctx.read.club
    first = ctx.team_of[asked] if asked else (lead or "home")
    return first, ctx.other(first)


def _no_footage(ctx: Ctx, w: Window) -> str | None:
    if ctx.footage_s(w) != 0:
        return None
    return f"We haven't seen any footage {w.said}."


def _so_far(ctx: Ctx) -> Window:
    done = max(1, played(ctx.t))
    return Window(1, done, "so far", False)


def possession(ctx: Ctx) -> Reply:
    r, w = Reply(), ctx.read.window
    note = None
    if w.empty:
        r.notes.append(w.empty)
        w = _so_far(ctx)
    elif w.lo not in (1, HALF_MIN + 1):
        # Measured only from kick-off and from each half's start (ball_share.MEASURED_FROM, lesson 290):
        # over the stretch asked, the closest measured fact is where the ball was in it.
        terr = on_top(ctx)
        if terr.status == "verified" and terr.lines:
            terr.notes.append(
                f"Possession itself is measured from kick-off and from each half's start, not {w.said}."
            )
            terr.head = None
            return terr
        note = f"Possession is measured from kick-off and from each half's start, not {w.said}."
        r.notes.append(note)
        r.status = "unanswerable"
        r.say(note)
        r.notes.clear()
        return r
    got = {f["team"]: f for f in ctx.mi.possession(w.lo, w.hi)["summary"]}
    if len(got) < 2 or not all(f.get("confident") and f.get("value") is not None for f in got.values()):
        # The fallback: why it isn't known, and the longest run of passing, which needs no side told.
        r.say(POSSESSION_UNKNOWN)
        spell = max((f for f in ctx.events("spell", w)), key=lambda f: f.get("value") or 0, default=None)
        if spell is not None:
            whose = f"{possessive(spell['club'])} longest" if spell.get("club") else "The longest"
            r.say(
                f"{whose} run of passing was {spell['value']} passes in a row, in minute {spell['minute']}.",
                spell,
            )
        r.head = "Not known yet"
        return r
    from ninety.intel.ball_share import ERROR_POINTS

    h, a = got["home"]["value"], got["away"]["value"]
    lead = None if h == a else ("home" if h > a else "away")
    first, second = _order(ctx, lead)
    v1, v2 = got[first]["value"], got[second]["value"]
    f = ctx.fact(
        f"possession:{first}",
        "ask_possession_compare",
        v1,
        "%",
        first,
        also=[(v2, "%"), (ERROR_POINTS, "points")],
        sources=list(got.values()),
        w=w,
    )
    c1, c2 = ctx.clubs[first], ctx.clubs[second]
    if note:
        r.notes.append(note)
    if lead is None:
        r.say(
            f"It's even: {c1} and {c2} have had {v1}% of the ball each {w.said}, by time on the ball {SEEN}.",
            f,
        )
    elif lead == first:
        r.say(
            f"{c1} have had more of the ball: {v1}% to {possessive(c2)} {v2}% {w.said}, by time on the "
            f"ball {SEEN}.",
            f,
        )
    else:
        r.say(
            f"{c1} have had less of the ball: {v1}% to {possessive(c2)} {v2}% {w.said}, by time on the "
            f"ball {SEEN}.",
            f,
        )
    r.say(f"That's give or take {ERROR_POINTS} points.", f)
    r.head = f"{_short(ctx, lead or first)} {got[lead or first]['value']}%"
    return r


def _share(f: dict) -> str:
    """A territory share as its least (the ball near a third's line could be either side of it; the
    Stats tab says it the same way: "at least")."""
    return f"{f['lo']}%" if f["lo"] == f["hi"] else f"at least {f['lo']}%"


def on_top(ctx: Ctx) -> Reply:
    r, w = Reply(), ctx.read.window
    if w.empty:
        r.notes.append(w.empty)
        w = _so_far(ctx)
    gap = _no_footage(ctx, w)
    if gap:
        r.notes.append(gap + " Here it is so far.")
        w = _so_far(ctx)
    got = ctx.mi.on_top(w.lo, w.hi)["summary"]
    top, terr = got[0], {f["team"]: f for f in got[1:]}
    if len(terr) < 2 or not top.get("confident"):
        r.status = "unanswerable"
        r.say(f"It's too early to say who has been on top {w.said}: the ball hasn't been seen enough yet.")
        return r
    lead = top.get("team")
    first, second = _order(ctx, lead)
    t1, t2 = terr[first], terr[second]
    f = ctx.fact(
        f"on_top:{lead or 'none'}",
        "ask_on_top_compare",
        t1["lo"],
        "%",
        lead,
        also=[(t1["hi"], "%"), (t2["lo"], "%"), (t2["hi"], "%")],
        sources=[top, t1, t2],
        w=w,
    )
    c1, c2 = ctx.clubs[first], ctx.clubs[second]
    where = (
        f"the ball was in {possessive(c1)} attacking third {_share(t1)} of the time {SEEN}, against "
        f"{_share(t2)} in {possessive(c2)}"
    )
    if lead is None:
        r.say(f"It's been even {w.said}, with neither side on top: {where}.", f)
        r.head = "Even"
    elif lead == first:
        r.say(f"{c1} have been on top {w.said}: {where}.", f)
        r.head = _short(ctx, lead)
    else:
        r.say(f"{c2} have been on top {w.said}: {where}.", f)
        r.head = _short(ctx, lead)
    return r


def territory(ctx: Ctx) -> Reply:
    r = on_top(ctx)
    if r.status != "verified":
        return r
    text, cited = r.lines[-1]
    f = cited[0]
    # Where the ball has been, said as where it was, then who that favours.
    lead = f["team"]
    verdict = text.split(":", 1)[1].strip()
    verdict = verdict[0].upper() + verdict[1:]
    tail = (
        f" so {ctx.clubs[lead]} have had the better of the territory."
        if lead
        else " so neither side has had clearly more of the territory."
    )
    r.lines[-1] = (verdict[:-1] + "," + tail, cited)
    return r


# -- counts ------------------------------------------------------------------------------------------


def _by_team(rows: list[dict], key=lambda f: True) -> dict[str, int]:
    out = {"home": 0, "away": 0, None: 0}
    for f in rows:
        if key(f):
            out[f["team"] if f.get("team") in ("home", "away") and f.get("side_known", True) else None] += 1
    return out


def _gap_or(ctx: Ctx, r: Reply) -> Window | None:
    w = ctx.read.window
    if w.empty:
        r.notes.append(w.empty)
        return _so_far(ctx)
    gap = _no_footage(ctx, w)
    if gap:
        r.status = "unanswerable"
        r.say(gap + " Ask about the match so far.")
        return None
    return w


def passes(ctx: Ctx) -> Reply:
    r = Reply()
    w = _gap_or(ctx, r)
    if w is None:
        return r
    rows = ctx.events("pass", w)
    n = _by_team(rows)
    first, second = _order(ctx, None if n["home"] == n["away"] else max(("home", "away"), key=n.get))
    f1 = ctx.fact(
        f"passes:{first}",
        "ask_passes",
        n[first],
        "passes",
        first,
        sources=[p for p in rows if p.get("team") == first],
    )
    f2 = ctx.fact(
        f"passes:{second}",
        "ask_passes",
        n[second],
        "passes",
        second,
        sources=[p for p in rows if p.get("team") == second],
    )
    c1, c2 = ctx.clubs[first], ctx.clubs[second]
    if ctx.read.club:
        r.say(
            f"{c1} have made {_plural(n[first], 'pass', 'passes')} {w.said} {SEEN}, against "
            f"{possessive(c2)} {_plural(n[second], 'pass', 'passes')}.",
            f1,
            f2,
        )
    else:
        total = n[first] + n[second]
        ft = ctx.fact("passes:all", "ask_passes_all", total, "passes", None, sources=[])
        r.say(
            f"Vision has counted {_plural(total, 'pass', 'passes')} {w.said} {SEEN}: "
            f"{c1} {_plural(n[first], 'pass', 'passes')}, {c2} {_plural(n[second], 'pass', 'passes')}.",
            ft,
            f1,
            f2,
        )
    r.notes.append(MISSES["passes"])
    r.head = f"{_short(ctx, first)} {n[first]}, {_short(ctx, second)} {n[second]}"
    return r


def completion(ctx: Ctx) -> Reply:
    r = Reply()
    w = _gap_or(ctx, r)
    if w is None:
        return r
    rows = ctx.events("pass", w)
    tot = _by_team(rows)
    won = _by_team(rows, lambda f: f.get("outcome") == "success")
    if min(tot["home"], tot["away"]) < MIN_PASSES:
        r.status = "unanswerable"
        r.say(f"It's too early to rate the passing {w.said}: vision has counted too few passes {SEEN} yet.")
        return r
    pct = {t: round(100 * won[t] / tot[t]) for t in ("home", "away")}
    lead = None if pct["home"] == pct["away"] else max(("home", "away"), key=pct.get)
    first, second = _order(ctx, lead)
    f = ctx.fact(
        f"completion:{first}",
        "ask_completion_compare",
        pct[first],
        "%",
        first,
        also=[(pct[second], "%")],
        sources=rows,
    )
    c1, c2 = ctx.clubs[first], ctx.clubs[second]
    r.say(
        f"{c1} have found a teammate with {pct[first]}% of their passes {w.said} {SEEN}, against "
        f"{possessive(c2)} {pct[second]}%.",
        f,
    )
    if lead:
        r.say(f"So {ctx.clubs[lead]} have been passing better.", f)
    r.head = f"{_short(ctx, first)} {pct[first]}%"
    return r


def shots(ctx: Ctx) -> Reply:
    r = Reply()
    w = _gap_or(ctx, r)
    if w is None:
        return r
    rows = ctx.events("shot", w)
    n = _by_team(rows)
    lead = None if n["home"] == n["away"] else max(("home", "away"), key=n.get)
    first, second = _order(ctx, lead)
    total = len(rows)
    ft = ctx.fact(
        "shots:all", "ask_shots_total", total, "shots", None, also=[(n[None], "shots")], sources=rows
    )
    f1 = ctx.fact(f"shots:{first}", "ask_shots_club", n[first], "shots", first, sources=[])
    f2 = ctx.fact(f"shots:{second}", "ask_shots_club", n[second], "shots", second, sources=[])
    r.notes.append(MISSES["shots"])
    c1, c2 = ctx.clubs[first], ctx.clubs[second]
    unplaced = f", and {_plural(n[None], 'shot')} it didn't place on a side" if n[None] else ""
    if ctx.read.club:
        r.say(
            f"{c1} have had {_plural(n[first], 'shot')} {w.said} {SEEN}, against {possessive(c2)} "
            f"{_plural(n[second], 'shot')}{unplaced}.",
            f1,
            f2,
            ft,
        )
    elif total == 0:
        r.say(f"There have been no shots {w.said} {SEEN}.", ft)
    else:
        r.say(
            f"Vision has spotted {_plural(total, 'shot')} {w.said} {SEEN}: {c1} {_plural(n[first], 'shot')}, "
            f"{c2} {_plural(n[second], 'shot')}{unplaced}.",
            ft,
            f1,
            f2,
        )
    r.head = f"{_short(ctx, first)} {n[first]}, {_short(ctx, second)} {n[second]}"
    return r


def on_target(ctx: Ctx) -> Reply:
    r = Reply()
    w = _gap_or(ctx, r)
    if w is None:
        return r
    rows = ctx.events("shot", w)
    goals = [g for g in ctx.events("goal", w) if g.get("side_known", True)]
    saves = [s for s in rows if s.get("outcome") == "on_target"]
    on = _by_team(goals)
    for t, k in _by_team(saves).items():
        on[t] += k
    wide = sum(1 for s in rows if s.get("outcome") in ("off_target", "blocked"))
    unknown = sum(1 for s in rows if s.get("outcome") is None)
    lead = None if on["home"] == on["away"] else max(("home", "away"), key=on.get)
    first, second = _order(ctx, lead)
    unit = "shots on target"
    f = ctx.fact(
        f"on_target:{first}",
        "ask_on_target",
        on[first],
        unit,
        first,
        also=[(on[second], unit), (on[None], unit), (wide, "shots"), (unknown, "shots")],
        sources=[*goals, *saves],
    )
    c1, c2 = ctx.clubs[first], ctx.clubs[second]
    one = lambda k: _plural(k, "shot on target", "shots on target")  # noqa: E731
    r.say(
        f"{c1} have had {one(on[first])} {w.said} {SEEN}, against {possessive(c2)} {one(on[second])}, "
        "counting goals and saves.",
        f,
    )
    rest = []
    if wide:
        rest.append(f"saw {_plural(wide, 'shot')} miss or get blocked")
    if unknown:
        rest.append(f"didn't see how {_plural(unknown, 'shot')} ended")
    if rest:
        r.say("It " + " and ".join(rest) + ".", f)
    r.head = f"{_short(ctx, first)} {on[first]}, {_short(ctx, second)} {on[second]}"
    return r


RESTART_UNITS = {
    "corner": ("corner", "corners"),
    "throw_in": ("throw-in", "throw-ins"),
    "goal_kick": ("goal kick", "goal kicks"),
    "free_kick": ("free kick", "free kicks"),
    "penalty_kick": ("penalty", "penalties"),
}


def _restarts(ctx: Ctx, w: Window, kinds: tuple[str, ...]) -> dict[str, dict]:
    rows = ctx.events("restart", w)
    ctx.sources = rows
    return {k: _by_team([x for x in rows if x["restart"] == k]) for k in kinds}


def corners(ctx: Ctx) -> Reply:
    r = Reply()
    r.notes.append(MISSES["restarts"])
    w = _gap_or(ctx, r)
    if w is None:
        return r
    if re.search(r"\bset[- ]pieces?\b", ctx.read.text, re.I) and not re.search(
        r"\bcorners?\b", ctx.read.text, re.I
    ):
        got = _restarts(ctx, w, tuple(RESTART_UNITS))
        total = sum(sum(v.values()) for v in got.values())
        parts = [_plural(sum(v.values()), *RESTART_UNITS[k]) for k, v in got.items() if sum(v.values())]
        f = ctx.fact(
            "set_pieces:all",
            "ask_set_pieces_all",
            total,
            "set pieces",
            also=[(sum(v.values()), RESTART_UNITS[k][1]) for k, v in got.items()],
            sources=ctx.sources,
        )
        lead = f"Vision has spotted {_plural(total, 'set piece')} {w.said} {SEEN}"
        r.say(lead + (": " + ", ".join(parts) + "." if parts else "."), f)
        r.head = _plural(total, "set piece")
        return r
    n = _restarts(ctx, w, ("corner",))["corner"]
    lead = None if n["home"] == n["away"] else max(("home", "away"), key=n.get)
    first, second = _order(ctx, lead)
    f = ctx.fact(
        f"corners:{first}",
        "ask_corners",
        n[first],
        "corners",
        first,
        also=[(n[second], "corners"), (n[None], "corners"), (sum(n.values()), "corners")],
        sources=ctx.sources,
    )
    c1, c2 = ctx.clubs[first], ctx.clubs[second]
    total = sum(n.values())
    if total == 0:
        r.say(f"There have been no corners {w.said} {SEEN}.", f)
        r.head = "No corners"
        return r
    r.say(
        f"{c1} have had {_plural(n[first], 'corner')} {w.said} {SEEN}, and {c2} "
        f"{_plural(n[second], 'corner')}.",
        f,
    )
    r.head = f"{_short(ctx, first)} {n[first]}, {_short(ctx, second)} {n[second]}"
    return r


def out_of_play(ctx: Ctx) -> Reply:
    r = Reply()
    r.notes.append(MISSES["restarts"])
    w = _gap_or(ctx, r)
    if w is None:
        return r
    kinds = ("throw_in", "goal_kick", "corner")
    got = _restarts(ctx, w, kinds)
    asked = next(
        (
            k
            for k, p in (("throw_in", r"throw[- ]?ins?"), ("goal_kick", r"goal[- ]kicks?"))
            if re.search(rf"\b{p}\b", ctx.read.text, re.I)
        ),
        None,
    )
    total = sum(sum(v.values()) for v in got.values())
    parts = [_plural(sum(got[k].values()), *RESTART_UNITS[k], zero=True) for k in kinds]
    f = ctx.fact(
        "out_of_play:all",
        "ask_out_of_play",
        total,
        "times",
        also=[(sum(got[k].values()), RESTART_UNITS[k][1]) for k in kinds],
        sources=ctx.sources,
    )
    # One lead for every paraphrase (the total, by kind); a club's count of the kind asked after it.
    if total:
        r.say(
            f"Vision has seen the ball go out of play {_plural(total, 'time')} {w.said} {SEEN}: "
            f"{parts[0]}, {parts[1]} and {parts[2]}.",
            f,
        )
    else:
        r.say(f"The ball hasn't gone out of play {w.said} {SEEN}: {parts[0]}, {parts[1]} and {parts[2]}.", f)
    if asked and ctx.read.club:
        n, (one, many) = got[asked], RESTART_UNITS[asked]
        t = ctx.team_of[ctx.read.club]
        fc = ctx.fact(f"{asked}:{t}", f"ask_{asked}", n[t], many, t, sources=ctx.sources)
        r.say(
            f"{ctx.read.club} have had {_plural(n[t], one, many)} of them."
            if n[t]
            else f"None of them were {possessive(ctx.read.club)}.",
            fc,
        )
    r.head = _plural(total, "time")
    return r


# -- players --------------------------------------------------------------------------------------


def _team_km(ctx: Ctx) -> Reply:
    """The closest measured fact to a player's running: each club's distance, from the footage."""
    r = Reply()
    dist = (ctx.mi.team_stats or {}).get("distance") or {}
    done = played(ctx.t)
    km = {
        t: round(sum(b["km"] for b in (dist.get(t) or {}).get("bins", ()) if b["minute_to"] <= done), 1)
        for t in ("home", "away")
    }
    if not dist or not any(km.values()):
        return r
    pct = ctx.mi.team_stats.get("within_pct")
    f = ctx.fact(
        "team_km",
        "ask_team_km",
        km["home"],
        "km",
        "home",
        also=[(km["away"], "km"), (pct, "%")],
        sources=[],
        w=_so_far(ctx),
    )
    c = ctx.clubs
    r.say(
        f"What the tracking does measure is each side's running: {c['home']} have covered {km['home']} km "
        f"and {c['away']} {km['away']} km so far {SEEN}, give or take {pct}%.",
        f,
    )
    return r


def _cant(ctx: Ctx, why: str, closest: Reply, answers: bool = False) -> Reply:
    """What vision can't say, then the closest thing it measured. `answers`: the closest thing answers
    the question in part (a best player: who scored), so the reply is "verified"; else it is told as
    "unanswerable" with the closest fact beside it (a player's top speed is not a team's distance)."""
    r = Reply()
    r.status = "verified" if answers and closest.lines else "unanswerable"
    r.say(why)
    r.lines += closest.lines
    return r


def best(ctx: Ctx) -> Reply:
    # The players tool's leader, when its least beats every other player's most and the name gate let
    # him be said (by name or position, never "a London Athletic player").
    w = _so_far(ctx)
    asked = ctx.read.club
    top = next((f for f in ctx.mi.players(w.lo, w.hi, asked)["facts"] if f.get("rank") == 1 or asked), None)
    who = (top or {}).get("player_is") or ""
    if (
        top is not None
        and top.get("leads")
        and top.get("confident")
        and not who.lower().startswith(("a ", "an "))
    ):
        r = Reply()
        passes = top["also"][0][0]
        r.say(
            f"{who} has taken the most opponents out of the game with passes "
            f"so far: {top['value']} opponents "
            f"in {_plural(passes, 'pass', 'passes')} {SEEN}.",
            top,
        )
        r.head = who[:48]
        return r
    closest = Reply()
    named = [
        g
        for g in _goals(ctx, ctx.team_of[asked] if asked else None)
        if g.get("scorer_is") and g.get("scorer_source") == "id_feed"
    ]
    for g in named[-2:]:  # the scorers the Player ID feed names: the most decisive thing measured of anyone
        closest.say(_goal_sentence(g), g)
    if named:
        closest.lines[0] = ("Here's what it can say: " + closest.lines[0][0], closest.lines[0][1])
        closest.say(FEED_NOTE)
    else:
        closest = _bypassed(ctx)
    return _cant(
        ctx,
        "Vision can't name players on these pictures well enough to pick a best player yet.",
        closest,
        answers=True,
    )


def _bypassed(ctx: Ctx) -> Reply:
    """Closest to a best player: each club's opponents taken out by passes."""
    r = Reply()
    w = _so_far(ctx)
    tot = {
        f["team"]: f
        for f in ctx.mi.line_breaks(w.lo, w.hi)["summary"]
        if f.get("metric") == "opponents_bypassed_total"
    }
    if len(tot) < 2:
        return r
    asked = ctx.read.club
    first = ctx.team_of[asked] if asked else max(tot, key=lambda t: tot[t]["value"])
    second = ctx.other(first)
    f = ctx.fact(
        f"bypassed:{first}",
        "ask_bypassed_compare",
        tot[first]["value"],
        "opponents",
        first,
        also=[(tot[second]["value"], "opponents")],
        sources=list(tot.values()),
        w=w,
    )
    r.say(
        f"Here's what it does measure: {possessive(ctx.clubs[first])} passes have taken "
        f"{tot[first]['value']} opponents out of the game so far {SEEN}, against "
        f"{tot[second]['value']} opponents for {ctx.clubs[second]}.",
        f,
    )
    return r


def _ranked(ctx: Ctx, metric: str) -> tuple[dict | None, str | None]:
    """The leader of a per-player ranking (ninety/intel/player_stats.py, through the insights'
    player_rank tool), or why there is none: no Player ID feed, or the ranking is withheld."""
    rank = getattr(ctx.mi, "player_rank", None)
    if rank is None or not getattr(ctx.mi, "per_player", None):
        return None, None
    try:
        got = rank(ctx.read.club, metric, ctx.t / 60.0)
    except ValueError:
        return None, None
    if got.get("withheld") or not got.get("facts"):
        return None, got.get("withheld")
    top = got["facts"][0]
    return (top if top.get("leads") else None), None


def fastest(ctx: Ctx) -> Reply:
    top, _ = _ranked(ctx, "fastest")
    if top is not None:
        r = Reply()
        f = ctx.fact(
            f"fastest:{top['player']}",
            "ask_top_speed",
            top["value"],
            "km/h",
            top["team"],
            sources=[],
            w=_so_far(ctx),
            player_name=top["name"],
            name_source="id_feed",
        )
        r.say(f"{top['name']} has been the fastest so far, at {top['value']} km/h {SEEN}.", f)
        r.say("Names come from the Player ID feed; speeds are measured while the video tracked each player.")
        r.head = top["name"][:48]
        return r
    return _cant(
        ctx, "Vision can't measure each player's top speed well enough to rank them yet.", _team_km(ctx)
    )


def distance(ctx: Ctx) -> Reply:
    return _cant(
        ctx, "Vision can't yet say how far each player has run well enough to rank them.", _team_km(ctx)
    )


# -- a goal's story, the key moments ---------------------------------------------------------------


def _goal_asked(ctx: Ctx) -> dict | str | None:
    asked = ctx.read.club
    goals = _goals(ctx, ctx.team_of[asked] if asked else None)
    every = _goals(ctx)
    k = ctx.read.goal
    if k == "equaliser":
        n, picked = {"home": 0, "away": 0}, None
        for g in every:
            n[g["team"]] += 1
            if n["home"] == n["away"]:
                picked = g
        return picked or "none"
    if k == "winner":
        n = {"home": 0, "away": 0}
        for g in every:
            n[g["team"]] += 1
        if n["home"] == n["away"]:
            return "none"
        lead = max(n, key=n.get)
        return [g for g in every if g["team"] == lead][n[ctx.other(lead)]]
    if isinstance(k, int):
        return goals[k] if -len(goals) <= k < len(goals) else "none"
    return goals[-1] if goals else None


def _third(x: float, team: str) -> str:
    depth = x if team == "home" else PITCH_X - x
    return ("own", "middle", "final")[min(int(depth // (PITCH_X / 3)), 2)]


def why_goal(ctx: Ctx) -> Reply:
    r = Reply()
    g = _goal_asked(ctx)
    asked = ctx.read.club
    if not isinstance(g, dict) and re.search(r"\bassist\w*", ctx.read.text, re.I):
        r.say(
            f"{asked} haven't scored yet, so there's no assist to name."
            if asked and g != "none"
            else "That goal hasn't been scored yet, so there's no assist to name."
        )
        r.head = "No goal yet"
        return r
    if not isinstance(g, dict):
        if g == "none":
            r.say("That goal hasn't been scored yet, so there's no build-up to talk through.")
        else:
            r.say(
                f"{asked} haven't scored yet, so there's no build-up to a goal to talk through."
                if asked
                else "No goals yet, so there's no build-up to a goal to talk through."
            )
        r.head = "No goal yet"
        return r
    team, gt = g["team"], float(g["t"])
    club = ctx.clubs[team]
    if re.search(
        r"\bassist\w*|\bset (?:it|the goal) up\b|\bwho (?:made|gave) the pass\b", ctx.read.text, re.I
    ):
        # Who assisted: the pass's maker when vision named him, else that it didn't; then the story.
        if g.get("assister_is"):
            r.say(f"{g['assister_is']} made the pass for {possessive(club)} goal in minute {g['minute']}.", g)
        else:
            r.say(
                f"Vision didn't name who made the last pass for {possessive(club)} goal in minute "
                f"{g['minute']}.",
                g,
            )
    # The move: the scoring side's passes in the minute before the goal, after the last time the other
    # side had the ball or a pass of its own was lost; only what happened before the goal, in order.
    before = [p for p in ctx.mi.facts.get("pass", ()) if gt - BUILD_UP_S <= float(p["t"]) < gt]
    before.sort(key=lambda p: float(p["t"]))
    chain: list[dict] = []
    for p in before:
        if p.get("team") != team or p.get("outcome") != "success":
            chain = []
        else:
            chain.append(p)
    if chain:
        start = _third(float(chain[0]["x"]), team)
        f = ctx.fact(
            f"build_up:{g['id']}",
            "ask_build_up_passes",
            len(chain),
            "passes",
            team,
            sources=chain,
            w=Window(g["minute"], g["minute"], f"in minute {g['minute']}", True),
        )
        if len(chain) == 1:
            r.say(
                f"{club} scored in minute {g['minute']} straight from a single pass, "
                f"played from their {start} "
                "third.",
                g,
                f,
            )
        else:
            r.say(
                f"{club} scored in minute {g['minute']} at the end of a move of {len(chain)} passes in a "
                f"row that started in their {start} third.",
                g,
                f,
            )
        named = [
            (
                ctx.mi.people.get(p.get("player") or "", {}).get("name"),
                ctx.mi.people.get(p.get("receiver") or "", {}).get("name"),
                p,
            )
            for p in chain
        ]
        links = [(f"{a} to {b}", p) for a, b, p in named if a and b and a != b]
        if links:
            r.say("It went " + ", then ".join(x for x, _ in links) + ".", *(p for _, p in links))
        breaks = [
            b
            for b in ctx.mi.facts.get("line_break", ())
            if b.get("event") in {p["id"] for p in chain} and b.get("value", 0) > 0 and b.get("confident")
        ]
        if breaks:
            b = max(breaks, key=lambda b: b["value"])
            opp = ctx.clubs[ctx.other(team)]
            r.say(
                f"The pass that broke the lines took {b['value']} {opp} "
                f"{'player' if b['value'] == 1 else 'players'} out of the game.",
                b,
            )
    else:
        # No pass of theirs followed: the strongest line break of theirs in the minute before, if any.
        breaks = [
            b
            for b in ctx.mi.facts.get("line_break", ())
            if b.get("team") == team
            and gt - BUILD_UP_S <= float(b.get("t") or -1) < gt
            and b.get("value", 0) > 0
            and b.get("confident")
        ]
        if breaks:
            b = max(breaks, key=lambda b: b["value"])
            r.say(f"{club} scored in minute {g['minute']}.", g)
            r.say(
                f"Just before it, a {club} pass took {b['value']} {ctx.clubs[ctx.other(team)]} "
                f"{'player' if b['value'] == 1 else 'players'} out of the game.",
                b,
            )
        else:
            r.say(
                f"{club} scored in minute {g['minute']}; vision saw no completed {club} pass in the minute "
                "before it, so it didn't follow the move.",
                g,
            )
    shot = next(
        (
            s
            for s in reversed(ctx.mi.facts.get("shot", ()))
            if gt - SHOT_BEFORE_GOAL_S <= float(s["t"]) <= gt and s.get("team") in (team, None)
        ),
        None,
    )
    if shot is not None and shot.get("value") is not None:
        shooter = ctx.clubs.get(shot.get("team")) if shot.get("side_known") else None
        r.say(
            f"Then {shooter} shot from {shot['value']} m out."
            if shooter
            else f"Then a shot came from {shot['value']} m out.",
            shot,
        )
    else:
        r.say("Vision didn't see the shot itself: it spotted the goal, not the strike.")
    r.head = f"Goal: {_short(ctx, team)}, minute {g['minute']}"
    return r


def key_moments(ctx: Ctx) -> Reply:
    r = Reply()
    w = ctx.read.window
    goals = [g for g in ctx.events("goal", w) if g.get("side_known", True) and g.get("team")]
    if goals:
        for g in goals:
            r.say(_goal_sentence(g), g)
    else:
        r.say(f"No goals {w.said}.")
    sh = shots(ctx)
    if sh.status == "verified" and sh.lines:
        text, cited = sh.lines[0]
        r.say(text, *cited)
    r.head = f"{len(goals)} goal{'s' if len(goals) != 1 else ''}" if goals else "No goals"
    return r


# -- what vision does not measure -----------------------------------------------------------------


def _offside_reads(ctx: Ctx) -> Reply:
    r = Reply()
    rows = ctx.events("offside", _so_far(ctx))
    goal = _goal_asked(ctx) if re.search(r"\bgoal\b", ctx.read.text, re.I) else None
    span = "so far"
    near = [
        x
        for x in rows
        if isinstance(goal, dict)
        and float(goal["t"]) - BUILD_UP_S <= float(x["t"]) <= float(goal["t"])
        and x.get("verdict") in ("offside", "onside")
    ]
    if near:
        rows, span = near, f"in the minute before {possessive(goal['club'])} goal"
    rows = [x for x in rows if x.get("verdict") in ("offside", "onside")]
    off = sum(1 for x in rows if x["verdict"] == "offside")
    f = ctx.fact(
        "offside_reads", "ask_offside_reads", len(rows), "passes", also=[(off, "passes")], sources=rows
    )
    if rows:
        r.say(
            f"Here's what it read {span} {SEEN}: {_plural(len(rows), 'pass', 'passes')} where it could call "
            + (
                f"the line, with {_plural(off, 'pass', 'passes')} to a player beyond it."
                if off
                else "the line, and none to a player beyond it."
            ),
            f,
        )
    return r


def unmeasured(ctx: Ctx) -> Reply:
    topic = ctx.read.topic or "referee"
    if topic == "offside":
        closest = _offside_reads(ctx)
    elif topic == "saves":
        closest = on_target(ctx)
    elif topic in ("cards", "referee"):
        closest = Reply()
        bug = _scorebug(ctx)
        if bug is not None:
            closest.say(
                "Here's the score instead: " + _score_line(ctx, bug)[0].lower() + _score_line(ctx, bug)[1:],
                bug,
            )
    else:
        closest = possession(ctx)
        if closest.status == "verified" and closest.lines:
            text, cited = closest.lines[0]
            closest.lines = [("Here's what it does measure: " + text, cited)]
    if closest.status != "verified":
        closest = Reply()
    r = Reply()
    r.status = "verified"  # a plain, true reply: what vision cannot say, then what it can
    r.say(UNMEASURED[topic])
    r.lines += [ln for ln in closest.lines if ln[1]][:1]
    r.head = "Not measured"
    return r


BUILDERS = {
    "score": score,
    "scorers": scorers,
    "winning": winning,
    "on_top": on_top,
    "momentum": on_top,
    "possession": possession,
    "passes": passes,
    "completion": completion,
    "shots": shots,
    "on_target": on_target,
    "territory": territory,
    "corners": corners,
    "out_of_play": out_of_play,
    "best": best,
    "fastest": fastest,
    "distance": distance,
    "why_goal": why_goal,
    "key_moments": key_moments,
    "unmeasured": unmeasured,
}


def build(question: Question, insights, read: Read) -> tuple[Answer, list[dict]] | None:
    """Code's answer for a row of the table, or None for a row it leaves to the tools' routing
    (tactics, a player, small talk). Each sentence is fact-checked; a sentence that fails is left out,
    and a lead that fails, or that does not carry the row's metric, gives the row's honest fallback."""
    fn = BUILDERS.get(read.intent)
    if fn is None:
        return None
    if read.window.empty and read.intent not in ("score", "scorers", "winning", "why_goal", "unmeasured"):
        # "How many shots in the second half?" at minute 5: no stretch to count, and no other stat.
        text = f"{read.window.empty} Ask me about the match so far."
        return Answer("unanswerable", text, None, None, None, (), None, None, spoken=text), []
    ctx = Ctx(insights, read, question.t)
    r = fn(ctx)
    kept: list[tuple[str, list[dict]]] = []
    for k, (text, cited) in enumerate(r.lines):
        if cited and not ctx.ok(text, cited):
            if k == 0 and r.status == "verified":
                break  # the lead failed its check: the fallback below
            continue
        kept.append((text, cited))
    lead_ok = bool(kept) and kept[0] == r.lines[0]
    row = BY_ID[read.intent]
    if r.status == "verified" and not (lead_ok and re.search(row.lead, kept[0][0], re.I)):
        kept = [
            (
                f"I can't answer that from what vision has seen yet; it gives {row.fallback} instead "
                "when it has them.",
                [],
            )
        ]
        r.status, r.head = "unanswerable", None
    text = " ".join([*(t for t, _ in kept), *r.notes])
    cited = [f for _, c in kept for f in c] + r.uncited
    ids = [i for f in cited for i in (f["id"], *f.get("evidence", ()))]
    ts = [float(f["t"]) for f in cited if f.get("t") is not None]
    ts += [60.0 * (f["minute_from"] - 1) for f in cited if f.get("minute_from")]
    ts += [min(60.0 * f["minute_to"], float(question.t)) for f in cited if f.get("minute_to")]
    lead = next(
        (
            f
            for f in cited
            if f.get("value") is not None and f.get("unit") and f.get("metric") not in ("score", "scorebug")
        ),
        None,
    )
    answer = Answer(
        r.status if text else "unanswerable",
        text or "I can't answer that from what vision has seen yet.",
        lead["metric"] if lead else None,
        float(lead["value"]) if lead else None,
        lead["unit"] if lead else None,
        tuple(dict.fromkeys(ids)),
        min(ts) if ts else None,
        min(max(ts), float(question.t)) if ts else None,
        spoken=text or None,
        headline=r.head if r.head and all(n in text for n in re.findall(r"\d+", r.head)) else None,
    )
    return answer, [
        {
            "name": n,
            "club": read.club,
            "minute_from": read.window.lo,
            "minute_to": read.window.hi,
            "intent": read.intent,
        }
        for n in row.tools
    ]
