"""Code's answer to each row of the intent table (ninety/agents/ask_intents.py).

Every number is computed here from the insights' facts timed at or before the question (never a
fact from after it), and each sentence is checked by the insight fact-check against the facts it
cites. A derived fact (a count, a share, a comparison) carries the ids of the facts it was
computed from, so the answer's evidence leads back to them.

The voice (Kian, Oct 27): lead with the confident true thing the data supports. A count is said as
the club comparison it is reliable for (vision misses events at both ends alike); one short scope
phrase ("in the footage so far") and no caveats, since how vision measures is the phone's "How we
know" tab; never "can't" or "not known" while a related measured fact exists, and only offside,
fouls and cards are "not tracked", each pivoting at once to something real. An answer whose lead
sentence does not carry the row's metric is not shown (the relevance gate).
"""

from __future__ import annotations

import re

from ninety.agents.ask_intents import BY_ID, HALF_MIN, Read, Window, played
from ninety.agents.contracts import Answer, Question
from ninety.agents.factcheck import Claim

# The one scope phrase an answer carries (Kian, Oct 27): the clips show part of the match, so a figure
# is of the footage. How vision measures, and how often it misses, is the phone's "How we know" tab.
SCOPE = "in the footage so far"
FEED = "Player ID feed"  # a name from the feed is said with its source (AGENTS.md)
SCORE_POINTER = "The broadcast's scorebug shows the score; vision does not keep one."
PITCH_X = 105.0  # the pitch's length (ninety/intel/ball_share.PITCH_X); home attacks towards x = 105
BUILD_UP_S = 60.0  # design, as match_insights.BUILD_UP_S: a goal's build-up is the minute before it
SHOT_BEFORE_GOAL_S = 6.0  # design: a shot this close before a goal of its side is the goal's shot
MIN_PASSES = 15  # design (as companion_match.MIN_SHARE_PASSES): a completion rate needs this many passes
# How each row's figures are made, for the answer's How-we-know field and the reply to "how do you
# know?" (Kian, Oct 27: never in the answer's text). Only rates docs/EVALUATION.md measures are said
# (passes: event detection on the frozen test clips; goals: shot outcomes; possession:
# docs/eval/possession-time.json); a rate not measured is said as not measured, and no total is ever
# corrected or estimated.
_GOALS = (
    "Goals are detected in the broadcast video (on the frozen test clips it found 10 of 15 goals, "
    "recall 0.67, 95% interval 0.42 to 0.85) and the score is read from the broadcast's scorebug; "
    "a scorer's name comes from the Player ID feed."
)
_PASSES = (
    "Passes are detected in the broadcast video by following the ball from one player to another, "
    "and said as which club made more of them and its share, never as a count."
)
_RESTARTS = (
    "Restarts (corners, throw-ins, goal kicks, free kicks) are read from where the ball left the "
    "pitch and how play restarted in the broadcast video. Their counts are not said: the detector is "
    "not yet reliable enough for them, so the answer gives where the ball has been instead."
)
_WHERE = (
    "Where the ball was comes from the tracked ball: each club's share of the footage with the ball in "
    "its attacking third. A club is on top only when its smallest possible share beats the other's "
    "largest (the ball near a third's line could be either side)."
)
_PLAYERS = (
    "Players are named by the Player ID feed, as a broadcaster licenses identity from a tracking "
    "provider. Running and speed come from tracked positions while the video followed each player; "
    "who was most involved is an order of the moves the video picked up, with no count."
)
HOW = {
    "score": "The score is read from the broadcast's scorebug.",
    "winning": "The score is read from the broadcast's scorebug.",
    "scorers": _GOALS,
    "key_moments": _GOALS,
    "why_goal": _GOALS + " A goal's build-up is the scoring side's passes in the minute before it, in order.",
    "passes": _PASSES,
    "completion": _PASSES + " Whether a pass found a teammate is read from where the ball went next.",
    "shots": (
        "Shots are detected in the broadcast video from the ball leaving a player towards goal; how many "
        "the detector misses is not measured yet."
    ),
    "on_target": (
        "Shots on target are goals and saves. "
        + _GOALS.split(" and the score")[0]
        + "; saves are not yet detected reliably (2 of 49 on the same clips)."
    ),
    "corners": _RESTARTS,
    "out_of_play": _RESTARTS,
    "possession": (
        "Possession is each club's share of the time one of its players had the ball, in the footage "
        "shown; dead and contested time count for neither. Against the answer key it was within 8.1 "
        "points over six stretches of two matches (mean error 5.75 points), so it is said give or "
        "take 10 points."
    ),
    "on_top": _WHERE,
    "momentum": _WHERE,
    "territory": _WHERE,
    "best": _PLAYERS,
    "fastest": _PLAYERS,
    "distance": _PLAYERS,
    "unmeasured": (
        "Offside, fouls and cards are not detected; the fact said instead is measured as in its own answer."
    ),
}
HOW_DEFAULT = (
    "Every number is computed by code from what the cameras tracked, and checked against those facts "
    "before it is shown."
)


# What vision does not measure, in one plain clause; the answer goes on to something it does.
UNMEASURED = {
    "offside": "Offside is not tracked here",
    "fouls": "Fouls are not tracked here",
    "cards": "Cards are not tracked here",
    "saves": "Saves are not tracked on their own here",
    "tackles": "Tackles are not tracked here",
    "referee": "The referee's calls are not tracked here",
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
    """The club's short name as a fan reads it ("Lisbon"), never its three-letter code."""
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
        return f"{g['scorer_is']} ({FEED}) scored for {g['club']} in minute {g['minute']}."
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
        if bug is None or (bug["home"] + bug["away"] == 0 and not asked):
            r.say("No goals yet.")
        elif asked and bug[ctx.team_of[asked]] == 0:
            r.say(f"{asked} haven't scored yet.")
        r.head = r.head or "No goal yet"
        return r
    for g in goals:
        r.say(_goal_sentence(g), g)
    for g in unplaced:
        # Fixed words around its minute: a goal of no known side names no club (code_texts says none).
        r.say(f"There was also a goal in minute {g['minute']}.")
        r.uncited.append(g)
    r.head = r.head or ", ".join(f"{_short(ctx, g['team'])} {g['minute']}′" for g in goals)[:48] or None
    return r


# -- comparisons of the two clubs -------------------------------------------------------------------


def _order(ctx: Ctx, lead: str | None) -> tuple[str, str]:
    """The club said first: the one asked about, else the leader, else the home club."""
    asked = ctx.read.club
    first = ctx.team_of[asked] if asked else (lead or "home")
    return first, ctx.other(first)


def _no_footage(ctx: Ctx, w: Window) -> bool:
    return ctx.footage_s(w) == 0


def _so_far(ctx: Ctx) -> Window:
    done = max(1, played(ctx.t))
    return Window(1, done, "so far", False)


def _scope(w: Window) -> str:
    """The one scope phrase an answer carries, at the end of its lead (Kian, Oct 27): what was seen."""
    return SCOPE if w.said == "so far" else f"{w.said}, {SCOPE.replace(' so far', '')}"


def _lower(text: str) -> str:
    """A sentence continued after a comma: its first word lower-case unless it is a name."""
    first = text.split(" ", 1)[0]
    return text[0].lower() + text[1:] if first in ("It's", "The", "There", "No", "Neither") else text


def _compare(
    ctx: Ctx,
    w: Window,
    n: dict,
    key: str,
    noun: str,
    one: str,
    verb: str,
    sources=(),
    scope: str | None = None,
) -> Reply:
    """A count said as the comparison it is reliable for (vision misses events at both ends alike):
    who has had more, then both numbers, and the scope once. "Lisbon Esportes have had more shots: 5 to
    London Athletic's 3 in the footage so far." The club asked about is said first."""
    r = Reply()
    h, a = n["home"], n["away"]
    lead = None if h == a else ("home" if h > a else "away")
    first, second = _order(ctx, lead)
    c1, c2 = ctx.clubs[first], ctx.clubs[second]
    n1, n2 = n[first], n[second]
    more = "more" if n1 > n2 else "fewer"
    # Each number bound to its place in the sentence: the first after "more shots:", the other after
    # "to London Athletic's" (a context the fact-check reads), so the two can never be swapped.
    also = [
        (n1, "", rf"\b(?:more|fewer) {re.escape(noun)}:\s*$"),
        (n2, "", rf"\bto {re.escape(possessive(c2))}\s*$"),
        (n1, "", rf"\b{re.escape(verb)}\s*$"),
    ]
    f = ctx.fact(f"{key}:{first}", f"ask_{key}_compare", None, None, first, also=also, sources=sources, w=w)
    if h == a == 0:
        r.say(f"Neither side has {verb} a {one} {scope or _scope(w)}.", f)
        r.head = f"No {noun}"
    elif h == a:
        r.say(
            f"It's level: {c1} and {c2} have {verb} {n1} {one if n1 == 1 else noun} each "
            f"{scope or _scope(w)}.",
            f,
        )
        r.head = f"Level: {n1} each"
    else:
        r.say(f"{c1} have {verb} {more} {noun}: {n1} to {possessive(c2)} {n2} {scope or _scope(w)}.", f)
        r.head = f"{_short(ctx, lead)}: {n[lead]} {noun}"
    return r


def possession(ctx: Ctx) -> Reply:
    """Each club's share of the time on the ball, from kick-off or a half's start (where it is
    measured); over any other stretch, or before it can be split, the closest measured fact: who has
    been on top there."""
    w = ctx.read.window
    if w.empty:
        w = _so_far(ctx)
    measured = w.lo in (1, HALF_MIN + 1)
    got = {f["team"]: f for f in ctx.mi.possession(w.lo, w.hi)["summary"]} if measured else {}
    if len(got) < 2 or not all(f.get("confident") and f.get("value") is not None for f in got.values()):
        # The closest measured fact over the same stretch: who was on top there, else the passes made.
        named = ctx.read.window.named and not ctx.read.window.empty
        r = on_top(ctx, w, broaden=not named)
        if r.status != "verified":
            r = _instead(passes(ctx))
        r.head = None
        return r
    from ninety.intel.ball_share import ERROR_POINTS

    r = Reply()
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
    # Its measured error is part of the figure, in the same sentence (lesson 296).
    err = f"give or take {ERROR_POINTS} points"
    if lead is None:
        r.say(f"It's even: {c1} and {c2} have had {v1}% of the ball each {_scope(w)}, {err}.", f)
    else:
        r.say(
            f"{c1} have had {'more' if lead == first else 'less'} of the ball: {v1}% to {possessive(c2)} "
            f"{v2}% {_scope(w)}, {err}.",
            f,
        )
    r.head = f"{_short(ctx, lead or first)} {got[lead or first]['value']}%"
    return r


def _fraction(f: dict) -> str:
    """A territory share as a fan says it: its plain fraction, else its least ("at least 18%")."""
    from ninety.intel.ball_share import share_words

    words = share_words(f["lo"], f["hi"])
    if words:
        return f"{words} of the time"
    return f"{f['lo']}% of the time" if f["lo"] == f["hi"] else f"at least {f['lo']}% of the time"


def _amount(f: dict) -> str:
    """A territory share as a fan says it: its plain fraction ("about a third"), else its range."""
    from ninety.intel.ball_share import share_words

    words = share_words(f["lo"], f["hi"])
    if words:
        return words
    return f"{f['lo']}%" if f["lo"] == f["hi"] else f"{f['lo']} to {f['hi']}%"


def _pair(a: dict, b: dict, b_owner: str) -> str:
    """One number pair: "about a third of the time, to London Athletic's about a tenth"."""
    sa, sb = _amount(a), _amount(b)
    return f"{sa} of the time, to {b_owner} {sb}"


def _shares(ctx: Ctx, w: Window) -> tuple[dict, dict] | None:
    got = ctx.mi.on_top(w.lo, w.hi)["summary"]
    top, terr = got[0], {f["team"]: f for f in got[1:]}
    if len(terr) < 2 or not top.get("confident"):
        return None
    return top, terr


def on_top(ctx: Ctx, w: Window | None = None, broaden: bool = True) -> Reply:
    """Who has been on top over the stretch: the verdict (a club leads only when its least share of the
    ball in its attacking third beats the other's most) and both shares, in one sentence. A stretch
    with too little of the ball seen is answered over the match so far (unless `broaden` is off)."""
    r, w = Reply(), w or ctx.read.window
    asked = w
    if broaden and (w.empty or _no_footage(ctx, w) or _shares(ctx, w) is None):
        w = _so_far(ctx)
    got = _shares(ctx, w)
    # A stretch the fan named but too little of it seen: said in one clause, then the match so far.
    narrowed = asked.named and not asked.empty and w is not asked
    if got is None:
        # Too little of the ball seen to compare territory: the closest measured fact, who has passed
        # more (Kian, Oct 27: never "too early" while a related fact exists).
        return _instead(passes(ctx))
    top, terr = got
    lead = top.get("team")
    first, second = _order(ctx, lead)
    f = _shares_fact(ctx, w, top, terr, lead or first)
    c1, c2 = ctx.clubs[first], ctx.clubs[second]
    when = "so far" if w.said == "so far" else w.said
    if lead is None:
        sa, sb = _amount(terr[first]), _amount(terr[second])
        where = (
            f"the ball has been in each side's attacking third {sa} of the time"
            if sa == sb
            else f"the ball has been in {possessive(c1)} attacking third {sa} of the time, and in "
            f"{possessive(c2)} {sb}"
        )
        r.say(f"It's been even {when}: {where}, {SCOPE.replace(' so far', '')}.", f)
        r.head = "Even"
    else:
        other = possessive(ctx.clubs[ctx.other(lead)])
        r.say(
            f"{ctx.clubs[lead]} have been on top {when}, with the ball in their attacking third "
            f"{_pair(terr[lead], terr[ctx.other(lead)], other)}, {SCOPE.replace(' so far', '')}.",
            f,
        )
        r.head = _short(ctx, lead)
    del c1
    if narrowed and got is not None:
        r = _clause(r, "Too little of that stretch has been seen yet")
    return r


def _shares_fact(ctx: Ctx, w: Window, top: dict, terr: dict, team: str) -> dict:
    # A share said as "at least N%" carries its least as a number with its unit.
    also = [(terr[t][k], "%") for t in ("home", "away") for k in ("lo", "hi")]
    also += [(terr[t]["lo"], "", r"(?:attacking third|'s?)\s*$") for t in ("home", "away")]
    # "a tenth" ends a clause and reads as the ordinal 10th: its fraction, where its bounds make one.
    from ninety.intel.ball_share import FRACTIONS, share_words

    said = {share_words(terr[t]["lo"], terr[t]["hi"]) for t in ("home", "away")}
    from ninety.agents.factcheck import spelled_as_digits

    for word, _ in FRACTIONS:  # the number the fact-check reads the fraction's word as ("tenth": 10)
        if f"about {word}" in said:
            also += [
                (float(n), "", r"\ba\s*$") for n in re.findall(r"\d+", spelled_as_digits(f"x {word}, y"))
            ]
    return ctx.fact(
        f"on_top:{top.get('team') or 'none'}:{team}",
        "ask_on_top",
        None,
        None,
        team,
        also=also,
        sources=[top, *terr.values()],
        w=w,
    )


def territory(ctx: Ctx) -> Reply:
    """Where the ball has been: which club's attacking third it was in more, with both shares."""
    r, w = Reply(), ctx.read.window
    if w.empty or _no_footage(ctx, w) or _shares(ctx, w) is None:
        w = _so_far(ctx)
    got = _shares(ctx, w)
    if got is None:
        return on_top(ctx)
    top, terr = got
    lead = top.get("team")
    first, second = (lead, ctx.other(lead)) if lead else _order(ctx, None)
    f = _shares_fact(ctx, w, top, terr, first)
    c1, c2 = ctx.clubs[first], ctx.clubs[second]
    s1, s2 = _fraction(terr[first]), _fraction(terr[second])
    place = SCOPE if w.said == "so far" else f"{w.said}, {SCOPE.replace(' so far', '')}"
    if lead:
        r.say(
            f"The ball has been in {possessive(c1)} attacking third more, "
            f"{_pair(terr[first], terr[second], possessive(c2))}, {place}.",
            f,
        )
        r.head = _short(ctx, lead)
    else:
        r.say(
            f"The ball has been in each side's attacking third about as often: in {possessive(c1)} "
            f"{_amount(terr[first])} of the time, and in {possessive(c2)} {_amount(terr[second])}, {place}.",
            f,
        )
        r.head = "Even"
    del s1, s2
    return r


# -- counts: the comparison first ---------------------------------------------------------------


def _by_team(rows: list[dict], key=lambda f: True) -> dict[str, int]:
    out = {"home": 0, "away": 0, None: 0}
    for f in rows:
        if key(f):
            out[f["team"] if f.get("team") in ("home", "away") and f.get("side_known", True) else None] += 1
    return out


def _window(ctx: Ctx) -> Window:
    """The stretch asked about, or the match so far when nothing of it has been seen."""
    w = ctx.read.window
    return _so_far(ctx) if w.empty or _no_footage(ctx, w) else w


# Design, pre-registered before it was run (the Coordinator, Oct 27; measured on 8324's footage,
# in-sample): the pass detector overcounts (recall 0.84, precision 0.68) but the clubs' direction held in
# every 15-minute window, so passes are said as a share rounded to 5 points ("about 55%"), never a count.
PASS_SHARE_STEP = 5
# Shots (recall 0.22 there): a direction is said only when the gap is large, the larger at least twice
# the smaller and at least 3 more; otherwise the answer leads with the goals and where the ball was.
SHOT_RATIO, SHOT_GAP = 2.0, 3
# Restarts (corners, throw-ins, goal kicks: precision under 0.2 there) are not counted on air. The hook
# for when they are measured countable (the Foundry event checker's work): set True, and their counts
# are said as the comparison again.
RESTARTS_COUNTABLE = False


def passes(ctx: Ctx) -> Reply:
    """Who has made more of the passes, as a share ("about 55% of them"), never a count."""
    w = _window(ctx)
    rows = ctx.events("pass", w)
    n = _by_team(rows)
    total = n["home"] + n["away"]
    r = Reply()
    if not total:
        r.say(f"Neither side has made a pass {_scope(w)}.")
        return r
    share = {t: PASS_SHARE_STEP * round(100 * n[t] / total / PASS_SHARE_STEP) for t in ("home", "away")}
    # The direction is the counts' (it held in every window measured); the share only says how much.
    lead = None if n["home"] == n["away"] else max(("home", "away"), key=lambda t: n[t])
    first, second = _order(ctx, lead)
    f = ctx.fact(f"pass_share:{first}", "ask_pass_share", share[first], "%", first, sources=rows, w=w)
    if lead is None:
        r.say(
            f"It's level: {ctx.clubs[first]} and {ctx.clubs[second]} have each made half of the passes "
            f"{_scope(w)}.",
            f,
        )
        r.head = "Level"
    elif share[first] == 50:  # rounded to half: say which side of it, never a share that reads level
        word, amount = ("more", "a little over half") if first == lead else ("fewer", "a little under half")
        r.say(
            f"{ctx.clubs[first]} have made {word} of the passes than {ctx.clubs[second]}: {amount} of them "
            f"{_scope(w)}.",
            f,
        )
        r.head = f"{_short(ctx, lead)}: more passes"
    else:
        word = "more" if first == lead else "fewer"
        r.say(
            f"{ctx.clubs[first]} have made {word} of the passes than {ctx.clubs[second]}: "
            f"about {share[first]}% of them {_scope(w)}.",
            f,
        )
        r.head = f"{_short(ctx, lead)}: about {share[lead]}% of passes"
    return r


def _goals_compare(ctx: Ctx) -> Reply:
    """The goals each club has scored, from the broadcast's scorebug, as a comparison."""
    bug = _scorebug(ctx)
    if bug is None:
        return Reply()
    n = {"home": bug["home"], "away": bug["away"]}
    if not n["home"] and not n["away"]:
        r = Reply()
        r.say("No goals yet.", bug)
        r.head = "No goals yet"
        return r
    return _compare(ctx, _so_far(ctx), n, "goals", "goals", "goal", "scored", [bug], scope="on the scorebug")


def _clause(r: Reply, clause: str) -> Reply:
    """What was asked is not counted, said in one short clause, then the confident fact in the same
    sentence ("Corners aren't counted here yet, but the ball has been in …"): never a silent pivot to
    another topic (the relevance bug), never a pile of caveats (Kian, Oct 27)."""
    if r.lines and r.lines[0][1]:
        text, cited = r.lines[0]
        r.lines = [(f"{clause}, but {_lower(text)}", cited), *r.lines[1:]]
    return r


def _goals_or_ground(ctx: Ctx, clause: str) -> Reply:
    """The confident fact nearest a count vision cannot make: the goals from the scorebug, or where the
    ball has been while neither side has scored."""
    r = _goals_compare(ctx)
    if not r.lines or r.head == "No goals yet":
        r = territory(ctx)
    r.head = None
    return _clause(r, clause)


def completion(ctx: Ctx) -> Reply:
    """Who has passed more accurately: the direction, which holds while vision misses passes at both
    ends alike; never a percentage, which its pass outcomes do not measure well enough (lesson 297)."""
    w = _window(ctx)
    rows = ctx.events("pass", w)
    tot = _by_team(rows)
    won = _by_team(rows, lambda f: f.get("outcome") == "success")
    if min(tot["home"], tot["away"]) < MIN_PASSES:
        return passes(ctx)
    rate = {t: won[t] / tot[t] for t in ("home", "away")}
    if abs(rate["home"] - rate["away"]) < 0.01:
        return passes(ctx)
    lead = max(("home", "away"), key=rate.get)
    first, second = _order(ctx, lead)
    f = ctx.fact(f"completion:{lead}", "ask_completion_order", None, None, first, sources=rows, w=w)
    r = Reply()
    word = "more" if first == lead else "less"
    r.say(
        f"{ctx.clubs[first]} have passed {word} accurately than {ctx.clubs[second]} {_scope(w)}: more of "
        f"{'their' if first == lead else possessive(ctx.clubs[second])} passes have found a teammate.",
        f,
    )
    r.head = _short(ctx, lead)
    return r


def shots(ctx: Ctx) -> Reply:
    """Who has had more shots, only when the gap is large enough for the detector (SHOT_RATIO and
    SHOT_GAP); else the goals and where the ball has been."""
    w = _window(ctx)
    rows = ctx.events("shot", w)
    n = _by_team(rows)
    hi, lo = max(n["home"], n["away"]), min(n["home"], n["away"])
    if hi >= SHOT_RATIO * lo and hi - lo >= SHOT_GAP:
        lead = "home" if n["home"] > n["away"] else "away"
        first, second = _order(ctx, lead)
        f = ctx.fact(f"shots_direction:{lead}", "ask_shots_direction", None, None, first, sources=rows, w=w)
        r = Reply()
        word = "far more" if first == lead else "far fewer"
        r.say(f"{ctx.clubs[first]} have had {word} shots than {ctx.clubs[second]} {_scope(w)}.", f)
        r.head = f"{_short(ctx, lead)}: more shots"
        return r
    return _goals_or_ground(ctx, "Shots aren't counted reliably yet")


def on_target(ctx: Ctx) -> Reply:
    """Every goal is on target, and saves are not detected well enough to add: the goals from the
    scorebug, else where the ball has been."""
    return _goals_or_ground(ctx, "Shots on target aren't counted reliably yet")


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
    if not RESTARTS_COUNTABLE:  # never a restart count on air (precision under 0.2): where the ball was
        sets = re.search(r"\bset[- ]pieces?\b|\bpenalt(?:y|ies)\b|\bfree[- ]kicks?\b", ctx.read.text, re.I)
        thing = (
            "Set pieces aren't"
            if sets and not re.search(r"\bcorners?\b", ctx.read.text, re.I)
            else "Corners aren't"
        )
        return _clause(territory(ctx), f"{thing} counted here yet")
    w = _window(ctx)
    if re.search(
        r"\bset[- ]pieces?\b|\bpenalt(?:y|ies)\b|\bfree[- ]kicks?\b", ctx.read.text, re.I
    ) and not re.search(r"\bcorners?\b", ctx.read.text, re.I):
        got = _restarts(ctx, w, tuple(RESTART_UNITS))
        total = sum(sum(v.values()) for v in got.values())
        parts = [_plural(sum(got["corner"].values()), *RESTART_UNITS["corner"], zero=True)]
        parts += [
            _plural(sum(v.values()), *RESTART_UNITS[k])
            for k, v in got.items()
            if k != "corner" and sum(v.values())
        ]
        f = ctx.fact(
            "set_pieces:all",
            "ask_set_pieces_all",
            total,
            "set pieces",
            also=[(sum(v.values()), RESTART_UNITS[k][1]) for k, v in got.items()],
            sources=ctx.sources,
            w=w,
        )
        r = Reply()
        r.say(f"There have been {_plural(total, 'set piece', zero=True)} {_scope(w)}: {', '.join(parts)}.", f)
        r.head = _plural(total, "set piece", zero=True)
        return r
    n = _restarts(ctx, w, ("corner",))["corner"]
    return _compare(ctx, w, n, "corners", "corners", "corner", "had", ctx.sources)


def out_of_play(ctx: Ctx) -> Reply:
    if not RESTARTS_COUNTABLE:  # never a restart count on air (precision under 0.2): where the ball was
        thing = (
            "Throw-ins aren't"
            if re.search(r"\bthrow[- ]?ins?\b|\bthrows?\b", ctx.read.text, re.I)
            else "Goal kicks aren't"
            if re.search(r"\bgoal[- ]kicks?\b", ctx.read.text, re.I)
            else "The ball going out of play isn't"
        )
        return _clause(territory(ctx), f"{thing} counted here yet")
    r = Reply()
    w = _window(ctx)
    kinds = ("throw_in", "goal_kick", "corner")
    got = _restarts(ctx, w, kinds)
    asked = next(
        (
            k
            for k, p in (("throw_in", r"throw[- ]?ins?|throws?"), ("goal_kick", r"goal[- ]kicks?"))
            if re.search(rf"\b(?:{p})\b", ctx.read.text, re.I)
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
        w=w,
    )
    # One lead for every paraphrase (the total, by kind); a club's count of the kind asked after it.
    if total:
        r.say(
            f"The ball has gone out of play {_plural(total, 'time')} {_scope(w)}: "
            f"{parts[0]}, {parts[1]} and {parts[2]}.",
            f,
        )
    else:
        r.say(f"The ball hasn't gone out of play {_scope(w)}.", f)
    if asked and ctx.read.club and total:
        n, (one, many) = got[asked], RESTART_UNITS[asked]
        t = ctx.team_of[ctx.read.club]
        fc = ctx.fact(f"{asked}:{t}", f"ask_{asked}", n[t], many, t, sources=ctx.sources, w=w)
        r.say(
            f"{ctx.read.club} have had {_plural(n[t], one, many)} of them."
            if n[t]
            else f"{ctx.read.club} haven't had any of them.",
            fc,
        )
    r.head = f"Out {_plural(total, 'time')}"
    return r


# -- players -------------------------------------------------------------------------------------


def _team_km(ctx: Ctx) -> Reply:
    """The closest measured fact to a player's running: which club has covered more ground."""
    r = Reply()
    dist = (ctx.mi.team_stats or {}).get("distance") or {}
    done = played(ctx.t)
    km = {
        t: round(sum(b["km"] for b in (dist.get(t) or {}).get("bins", ()) if b["minute_to"] <= done), 1)
        for t in ("home", "away")
    }
    if not dist or not any(km.values()):
        return r
    w = _so_far(ctx)
    lead = "home" if km["home"] >= km["away"] else "away"
    first, second = _order(ctx, lead)
    c1, c2 = ctx.clubs[first], ctx.clubs[second]
    f = ctx.fact("team_km", "ask_team_km", km[first], "km", first, also=[(km[second], "km")], w=w)
    r.say(
        f"{c1} have covered {'more' if first == lead else 'less'} ground than {c2}: {km[first]} km to "
        f"{km[second]} km {_scope(w)}.",
        f,
    )
    return r


def _involved(ctx: Ctx, team: str) -> tuple[str, dict] | None:
    """A club's three players most involved in the moves the video picked up, in order and with no
    count (#431's graded order, through the insights' player_rank), or None while it is withheld."""
    rank = getattr(ctx.mi, "player_rank", None)
    if rank is None or not getattr(ctx.mi, "per_player", None):
        return None
    try:
        got = rank(ctx.clubs[team], "involvement", ctx.t / 60.0)
    except ValueError:
        return None
    names = [f["name"] for f in got.get("facts") or ()][:3]
    if got.get("withheld") or len(names) < 3:
        return None
    f = ctx.fact(
        f"involved:{team}",
        "ask_involvement_order",
        None,
        None,
        team,
        sources=[],
        w=_so_far(ctx),
        player_names=names,
        name_source="id_feed",
    )
    # Never "best", never one player "the most involved": an order, as it was graded (#431).
    return (
        f"{possessive(ctx.clubs[team])} most involved players {SCOPE}: {names[0]}, {names[1]} and "
        f"{names[2]} ({FEED})."
    ), f


def best(ctx: Ctx) -> Reply:
    asked = ctx.read.club
    teams = [ctx.team_of[asked]] if asked else ["home", "away"]
    orders = [o for o in (_involved(ctx, t) for t in teams) if o]
    r = Reply()
    if orders:
        for text, f in orders:
            r.say(text, f)
        r.head = "Most involved"
        return r
    # The players tool's leader, when its least beats every other player's most and the name gate let
    # him be said (by name or position, never "a London Athletic player").
    w = _so_far(ctx)
    top = next((f for f in ctx.mi.players(w.lo, w.hi, asked)["facts"] if f.get("rank") == 1 or asked), None)
    who = (top or {}).get("player_is") or ""
    if (
        top is not None
        and top.get("leads")
        and top.get("confident")
        and not who.lower().startswith(("a ", "an "))
    ):
        passes = top["also"][0][0]
        r.say(
            f"{who} has taken the most opponents out of the game with passes: {top['value']} opponents "
            f"in {_plural(passes, 'pass', 'passes')} {SCOPE}.",
            top,
        )
        r.head = who[:48]
        return r
    # The closest measured facts about players: the scorers the Player ID feed names, then the fastest.
    named = [
        g
        for g in _goals(ctx, ctx.team_of[asked] if asked else None)
        if g.get("scorer_is") and g.get("scorer_source") == "id_feed"
    ]
    for g in named[-2:]:
        r.say(_goal_sentence(g), g)
    quick, _ = _ranked(ctx, "fastest")
    if quick is not None:
        r.say(_fastest_sentence(ctx, quick), _fastest_fact(ctx, quick))
    if not r.lines:
        r = _bypassed(ctx)  # the closest measured fact, said plainly (Kian, Oct 27): whose passes did most
    r.head = None
    return r


def _bypassed(ctx: Ctx) -> Reply:
    """Closest to a best player: which club's passes have taken out more opponents."""
    w = _so_far(ctx)
    tot = {
        f["team"]: f["value"]
        for f in ctx.mi.line_breaks(w.lo, w.hi)["summary"]
        if f.get("metric") == "opponents_bypassed_total"
    }
    if len(tot) < 2:
        return Reply()
    asked = ctx.read.club
    lead = "home" if tot["home"] >= tot["away"] else "away"
    first, second = _order(ctx, lead)
    c1, c2 = ctx.clubs[first], ctx.clubs[second]
    f = ctx.fact(
        f"bypassed:{first}",
        "ask_bypassed_compare",
        tot[first],
        "opponents",
        first,
        also=[(tot[second], "opponents")],
        w=w,
    )
    r = Reply()
    r.say(
        f"{possessive(c1)} passes have taken {'more' if first == lead else 'fewer'} opponents out of the "
        f"game: {tot[first]} opponents to {possessive(c2)} {tot[second]} opponents {SCOPE}.",
        f,
    )
    del asked
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


def _fastest_fact(ctx: Ctx, top: dict) -> dict:
    return ctx.fact(
        f"fastest:{top['player']}",
        "ask_top_speed",
        top["value"],
        "km/h",
        top["team"],
        w=_so_far(ctx),
        player_name=top["name"],
        name_source="id_feed",
    )


def _fastest_sentence(ctx: Ctx, top: dict) -> str:
    return f"{top['name']} ({FEED}) has been the fastest, at {top['value']} km/h {SCOPE}."


def _player_row(ctx: Ctx) -> dict | None:
    """The named player's stats up to now (ninety/intel/player_stats.py), or None."""
    fn = getattr(ctx.mi, "player_stats", None)
    if not ctx.read.player or fn is None or not getattr(ctx.mi, "per_player", None):
        return None
    try:
        rows = fn(ctx.t / 60.0, ctx.read.player)["facts"]
    except ValueError:
        return None
    return rows[0] if len(rows) == 1 else None


def _player_running(ctx: Ctx, row: dict, what: str) -> Reply | None:
    """One player's distance or top speed in the footage so far; None when the figure is withheld."""
    key = "distance_m" if what == "distance" else "top_kmh"
    if row.get(key) is None:
        return None
    r = Reply()
    if what == "distance":
        km = round(row["distance_m"] / 1000, 1)
        cover = round(100 * (row.get("footage_coverage") or 0))
        f = ctx.fact(
            f"km:{row['player']}",
            "ask_player_km",
            km,
            "km",
            row["team"],
            w=_so_far(ctx),
            player_name=row["name"],
            name_source="id_feed",
            also=[(cover, "%")],
        )
        # His distance only while the video followed him: far below a full match's, so its scope is said.
        r.say(
            f"{row['name']} ({FEED}) has covered {km} km while the video tracked him, {cover}% of the "
            "footage so far.",
            f,
        )
    else:
        f = ctx.fact(
            f"kmh:{row['player']}",
            "ask_player_kmh",
            row["top_kmh"],
            "km/h",
            row["team"],
            w=_so_far(ctx),
            player_name=row["name"],
            name_source="id_feed",
        )
        r.say(f"{row['name']} ({FEED}) has reached {row['top_kmh']} km/h {SCOPE}.", f)
    r.head = row["name"][:48]
    return r


def _one_player(ctx: Ctx, row: dict | None, what: str) -> Reply:
    """A named player whose asked figure is withheld: his other figure if it is said, else the closest
    measured fact (which club has covered more ground), never an apology."""
    other = "fastest" if what == "distance" else "distance"
    if row is not None and (got := _player_running(ctx, row, other)) is not None:
        return _instead(got)
    return _instead(_team_km(ctx))


def _instead(r: Reply) -> Reply:
    """A closest fact said in place of the one asked for (a club's running for a player's): plainly
    true, and marked as not the answer to the question (status "unanswerable"), with no apology."""
    r.status = "unanswerable" if r.lines else r.status
    return r


def fastest(ctx: Ctx) -> Reply:
    row = _player_row(ctx)
    if row is not None and (got := _player_running(ctx, row, "fastest")) is not None:
        return got
    if ctx.read.player:
        return _one_player(ctx, row, "fastest")
    top, _ = _ranked(ctx, "fastest")
    if top is not None:
        r = Reply()
        r.say(_fastest_sentence(ctx, top), _fastest_fact(ctx, top))
        r.head = top["name"][:48]
        return r
    return _instead(_team_km(ctx))


def distance(ctx: Ctx) -> Reply:
    row = _player_row(ctx)
    if row is not None and (got := _player_running(ctx, row, "distance")) is not None:
        return got
    if ctx.read.player:
        return _one_player(ctx, row, "distance")
    return _instead(_team_km(ctx))  # distance is not ranked (#430): the closest measured is the club's


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
        # Who assisted: the pass's maker when the feed or vision named him, else the move it came from.
        if g.get("assister_is"):
            r.say(f"{g['assister_is']} made the pass for {possessive(club)} goal in minute {g['minute']}.", g)
        else:
            r.say(f"{possessive(club)} goal in minute {g['minute']} came from this move.", g)
    # The move: the scoring side's passes in the minute before the goal, after the last time the other
    # side had the ball or a pass of its own was lost; only what happened before the goal, in order.
    before = sorted(
        (p for p in ctx.mi.facts.get("pass", ()) if gt - BUILD_UP_S <= float(p["t"]) < gt),
        key=lambda p: float(p["t"]),
    )
    chain: list[dict] = []
    for p in before:
        chain = [] if p.get("team") != team or p.get("outcome") != "success" else [*chain, p]
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
                f"{club} scored in minute {g['minute']} straight from a single pass, played from their "
                f"{start} third.",
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
    else:
        breaks = [
            b
            for b in ctx.mi.facts.get("line_break", ())
            if b.get("team") == team
            and gt - BUILD_UP_S <= float(b.get("t") or -1) < gt
            and b.get("value", 0) > 0
            and b.get("confident")
        ]
        r.say(f"{club} scored in minute {g['minute']}.", g)
    if breaks:
        b = max(breaks, key=lambda b: b["value"])
        lead = "The pass that broke the lines" if chain else f"Just before it, a {club} pass"
        r.say(
            f"{lead} took {b['value']} {ctx.clubs[ctx.other(team)]} "
            f"{'player' if b['value'] == 1 else 'players'} out of the game.",
            b,
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
    where = territory(ctx)  # and where the ball has been, the measure that held
    if where.status == "verified" and where.lines:
        text, cited = where.lines[0]
        r.say(text, *cited)
    # A recap leads with its latest goal, as the key moments always have (companion_match.headline).
    r.head = f"Goal: {_short(ctx, goals[-1]['team'])}, minute {goals[-1]['minute']}" if goals else "No goals"
    return r


# -- what vision does not measure: one plain clause, then something real -------------------------


def _offside_reads(ctx: Ctx) -> Reply:
    r = Reply()
    rows = [x for x in ctx.events("offside", _so_far(ctx)) if x.get("verdict") in ("offside", "onside")]
    goal = _goal_asked(ctx) if re.search(r"\bgoal\b", ctx.read.text, re.I) else None
    span = SCOPE
    near = [
        x
        for x in rows
        if isinstance(goal, dict) and float(goal["t"]) - BUILD_UP_S <= float(x["t"]) <= float(goal["t"])
    ]
    if near:
        rows, span = near, f"in the minute before {possessive(goal['club'])} goal"
    off = sum(1 for x in rows if x["verdict"] == "offside")
    f = ctx.fact(
        "offside_reads", "ask_offside_reads", len(rows), "passes", also=[(off, "passes")], sources=rows
    )
    if rows:
        r.say(
            f"The offside line was read at {_plural(len(rows), 'pass', 'passes')} {span}, "
            + (
                f"with {_plural(off, 'pass', 'passes')} to a receiver beyond it."
                if off
                else "with no receiver beyond it."
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
            cl = ctx.clubs
            closest.say(
                f"The scorebug reads {cl['home']} {_plural(bug['home'], 'goal')}, "
                f"{cl['away']} {_plural(bug['away'], 'goal')}.",
                bug,
            )
    else:
        closest = possession(ctx)
    r = Reply()
    r.status = "verified"  # a plain, true reply: what is not measured, then something real
    real = [ln for ln in closest.lines if ln[1]][:1] if closest.status == "verified" else []
    from ninety.agents.ask_intents import MOMENT_CALL

    if topic in ("fouls", "cards", "referee") and MOMENT_CALL.search(ctx.read.text):
        # A call on one moment ("was that a foul?"): the cameras' limit, from the Laws' own fact (it
        # never rules on contact), then something real.
        from ninety.agents.companion_match import code_texts
        from ninety.agents.referee import law_facts

        law = next(f for f in law_facts() if f["id"] == "law:contact")
        r.say(code_texts({**law, "clubs": ctx.clubs})[0], law)
        if real:
            text, cited = real[0]
            r.say("Here's what it does measure: " + _lower(text), *cited)
        r.head = None
        return r
    if real:
        text, cited = real[0]
        r.say(f"{UNMEASURED[topic]}, but {_lower(text)}", *cited)
    else:
        r.say(f"{UNMEASURED[topic]}.")
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
    if read.intent in ("fastest", "distance") and not getattr(insights, "per_player", None):
        # No per-player stats (a match without the Player ID feed): the physical tool's own gated path
        # answers a player's running (ninety/intel/physical.py), as before the table.
        return None
    keeps = ("score", "scorers", "winning", "why_goal", "unmeasured")
    if not (read.window.empty or "").startswith("The second half"):
        # "Since the half hour" at minute 10: on top so far, then the note; a half not begun, nothing.
        keeps += ("on_top", "momentum", "territory")
    if read.window.empty and read.intent not in keeps:
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
        how=HOW.get(read.intent, HOW_DEFAULT),
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
