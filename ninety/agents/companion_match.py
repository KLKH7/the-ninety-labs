"""The Companion agent on match questions: it chooses insight tools, then answers from what they return.

A question about the match, not one player ("why do they keep losing the ball in midfield?"),
is answered in two model steps over the insight tools (ninety/intel/match_insights.py, the same
functions the MCP server serves): the model plans which tools to call and over which minutes,
code runs them (read only, arguments checked), and the model answers citing the facts they
returned. The answer goes through the insight fact-check (ninety/agents/insight_check.py, then
the Judge) against those same facts, and the phone draws the visual of the first cited fact
that has one, taken by code. Without a model, or when its answer fails, code routes the question
(`route`) and writes the answer itself (`code_match_answer`), checked the same way.
"""

from __future__ import annotations

import asyncio
import json
import re
from dataclasses import dataclass, field

from ninety.agents import referee
from ninety.agents.companion import TIMEOUT_S, Source, _NotTheFormat, _number, service_errors
from ninety.agents.contracts import Answer, Ask, Judge, Question, status_for
from ninety.agents.factcheck import Claim, Verdict, parse_claim
from ninety.intel.teamsheet import POSITIONS, short_name


def companion_match_agent(client):
    """The match Companion, published on Foundry as `ninety-companion-match`: one prompt agent for
    both steps (plan, then answer), told apart by the message's `step`. No tools of its own: code runs
    the tools it names, so every fact it sees is one the fact-checker checks against."""
    from agent_framework import Agent

    from ninety.agents.contracts import COMPANION_MATCH_INSTRUCTIONS

    return Agent(
        client=client,
        name="companion-match",
        instructions=COMPANION_MATCH_INSTRUCTIONS,
        default_options={"temperature": 0},
    )


MATCH_TOOLS = (
    "goal_build_up",
    "players",
    "style",
    "referee",
    "counter_press",
    "overloads",
    "line_breaks",
    "pass_options",
    "team_shape",
    "lineup",
    "possession",
    "territory",
    "shots",
    "passing",
    "physical",
    "halves",
    "key_moments",
    "score",
    "set_pieces",
)
TOOL_HELP = {
    "set_pieces": "corners, goal kicks, penalties, throw-ins and free kicks: the total of each, and each "
    "club's (unsure for throw-ins and free kicks while the video could not tell whose)",
    "score": "the score after minute_to (unsure while a goal's side is in doubt), each goal with its scorer "
    "and the pass that made it (an assist), and each club's goalkeeper's saves",
    "halves": "the first half against the second (Law 7's 45 minutes): where the ball was, the shots and "
    "what the passes did in each",
    "key_moments": "the key moments, latest first: goals, shots, regains that led to a shot, one-twos and "
    "the biggest line breaks",
    "physical": "the zone each named player was in most, of the footage the video named him in; a "
    "player's distance, top speed and sprints are not available yet",
    "passing": "what the passes did: progressive passes, passes into the final third, long balls and "
    "passes intercepted, each club's count (unsure while the video could not tell whose some were) and "
    "the total; and the pairs of named players who passed to each other most",
    "shots": "the shot map: each shot's spot, metres from goal and the angle the posts make there, "
    "nearest first; each club's shots and those from inside the penalty area. How a shot ended is not "
    "known yet",
    "possession": "each club's share of the passes, the pass ratio Opta publishes as possession (not time "
    "on the ball); "
    "unsure when the video could not tell whose some passes were",
    "territory": "where the ball was: each club's share of the time with it in its attacking third, as "
    "a range (the ball near a third's line could be on either side)",
    "goal_build_up": "the latest goal up to minute_to (or one club's), and what happened in the minute "
    "before it",
    "players": "players ranked by the opponents their passes took out of the game",
    "referee": "offside lines at each completed pass (onside, offside, or too close for the tracking to "
    "call), and the Laws explained: offside, fouls, handball, cards, VAR. The tracking cannot judge contact",
    "style": "how each club plays: passing channels (left, centre, right), how wide it plays against the "
    "other club, crosses, the keeper going long or short, regains that led to a shot (seconds from "
    "regain to shot), one-twos",
    "counter_press": (
        "turnovers in open play, how many players pressed the ball in the 5 s after, "
        "and how fast it was won back"
    ),
    "overloads": "moments one club had 2 or more extra players in a zone of the pitch",
    "line_breaks": "passes that took opponents out of the game (packing)",
    "pass_options": "open teammates ahead at each pass, and whether the pass used one",
    "team_shape": "each club's shape a minute: width, length, back-line height, area, gaps between the lines",
    "lineup": "the team sheets, and which tracked player may be named",
}
# Code's routing, first match wins, at most MAX_TOOLS. The word lists are design: the plain words a
# fan uses for each question, measured on the labelled question set (ninety/eval/companion_tools.py).
TOOL_WORDS = (
    (
        "referee",
        r"\b(?:offside|onside|referee|ref|var|foul\w*|hand ?ball|penalty|pen|rules?|law|booked|booking"
        r"|yellow|red card|sent off|dive|dived)\b",
    ),
    (
        "set_pieces",
        r"\b(?:corners?|free[- ]kicks?|throw[- ]ins?|goal[- ]kicks?|penalties|how many penalt\w*"
        r"|set[- ]pieces?)\b",
    ),
    (
        "score",
        r"\b(?:what(?:'s| is) the score|the score|scoreline|who scored|scorers?|assists?|assisted|saves?"
        r"|how many goals|who(?:'s| is) (?:winning|ahead)|are .{1,30} (?:winning|level))\b",
    ),
    ("goal_build_up", r"\b(?:goals?|scor\w*|equali[sz]\w*|that finish)\b"),
    (
        "style",
        r"\b(?:style|playing like|play(?:ing)? like this|tactic\w*|approach|long balls?|go(?:ing)? long"
        r"|cross\w*|wings?|down the (?:left|right|middle)|counter[- ]attack\w*|on the break|one-twos?"
        r"|wall pass\w*|how (?:are|is) [\w' ]+ playing"
        r"|goal ?keeper|keeper)\b",
    ),
    (
        "players",
        r"\b(?:best|man of the match|stand-?out|star|playing well|who(?:'s| has) been|dangerous|threat"
        r"|influential|creative|key (?:man|player))\b",
    ),
    (
        "counter_press",
        r"\b(?:los(?:e|es|ing|t)|giv(?:e|es|ing) (?:it|the ball) away|turnovers?|press(?:ing)?"
        r"|win(?:s|ning)? (?:it|the ball) back|won (?:it|the ball) back|regain\w*|counter[- ]?press\w*)\b",
    ),
    (
        "overloads",
        r"\b(?:outnumber\w*|overload\w*|numbers?|extra (?:man|men|player)|spare man|crowd\w*|more players)\b",
    ),
    (
        "line_breaks",
        r"\b(?:break\w*|bypass\w*|through|cut(?:ting)? (?:through|open)|lines?"
        r"|penetrat\w*|progress\w*|packing)\b",
    ),
    (
        "pass_options",
        r"\b(?:options?|open|free|unmarked|decision\w*|choice\w*|should(?:'ve| have)|who to pass|passing)\b",
    ),
    (
        "team_shape",
        r"\b(?:shape|compact\w*|narrow\w*|stretched|high line|deep|block|back line|defensive line"
        r"|width|spread out)\b",
    ),
    (
        "halves",
        r"\b(?:halves|compar\w*[^?.]{0,40}\b(?:first|second)\b|since the break|after the break|half[- ]time"
        r"|first half (?:and|v|vs|against) (?:the )?second)\b",
    ),
    (
        "key_moments",
        r"\b(?:key moments?|highlights?|what (?:have|did) i miss\w*|what happened|catch me up|recap"
        r"|timeline)\b",
    ),
    (
        "physical",
        r"\b(?:distance|covered|how far|sprint\w*|fastest|top speed|how fast|heat ?map|work rate|tired"
        r"|ran the most|run the most|running|furthest|farthest|kilomet\w*|km|quickest|stamina|fitness"
        r"|where (?:has|does|did|is) [\w' ]+ (?:been )?play\w*)\b",
    ),
    (
        "passing",
        r"\b(?:progressive|into the final third|final[- ]third entr\w*|intercept\w*|pass network"
        r"|who passes to whom|link(?:ing)? up|combin\w*|partnership|passed to each other)\b",
    ),
    ("shots", r"\b(?:shots?|shooting|shoot|efforts? on goal|chances?|attempts?)\b"),
    (
        "possession",
        r"\b(?:possession|more of the ball|keep(?:ing|s)? the ball|have the ball more|dominat\w*)\b",
    ),
    (
        "territory",
        r"\b(?:territory|where (?:has|is) the ball|pinned (?:back|in)|camped|on the front foot"
        r"|in (?:their|the other) half)\b",
    ),
    (
        "lineup",
        r"\b(?:who(?:'s| is)|name\w*|number|line-?up|team sheet|playing (?:left|right)|which player)\b",
    ),
)
MAX_TOOLS = 3
WINDOW_MIN = 15  # the stats' window (docs/GROUNDING.md S4): a question about now looks this far back


# A position as a fan names it, to the role code of the 4-3-3, with its shirt number from the team
# sheet (ninety/intel/teamsheet.POSITIONS): "the right wing", "their number 9", "the keeper". A
# centre-back is one of two, so the bare word names none.
FAN_WORDS = {
    "GK": r"goal ?keeper|keeper|goalie",
    "RB": r"right[- ]back",
    "LB": r"left[- ]back",
    "RCB": r"right centre[- ]back",
    "LCB": r"left centre[- ]back",
    "CM": r"holding midfielder|defensive midfielder",
    "RW": r"right wing(?:er)?",
    "RCM": r"right[- ]sided midfielder",
    "ST": r"striker|centre[- ]forward",
    "LCM": r"left[- ]sided midfielder",
    "LW": r"left wing(?:er)?",
}
ROLE_WORDS = tuple((role, rf"{FAN_WORDS[role]}|number {number}\b") for role, number, _, _ in POSITIONS)
ASKS_WHO = r"\b(?:who|whose|which|name\w*)\b"


def asked_role(text: str) -> str | None:
    """The role a question asks the player of ("Who plays on the right wing?": RW), or None when it
    asks who without naming a position, or names one without asking who."""
    lowered = text.lower()
    if not re.search(ASKS_WHO, lowered):
        return None
    return next((role for role, words in ROLE_WORDS if re.search(rf"\b(?:{words})", lowered)), None)


def route(text: str) -> list[str]:
    lowered = text.lower()
    tools = [tool for tool, words in TOOL_WORDS if re.search(words, lowered)]
    if asked_role(text):
        # Who plays a position is the team sheet's to answer, before any word the position shares
        # with another tool ("wing" with style, "number" with overloads).
        tools = ["lineup", *(t for t in tools if t != "lineup")]
    return tools[:MAX_TOOLS]


@dataclass(frozen=True)
class MatchResult:
    """The answer, who wrote it, the tools called (name and arguments), and why the model's draft
    was not used, if it was not."""

    answer: Answer
    source: Source
    tools: tuple[dict, ...] = ()
    reasons: tuple[str, ...] = field(default_factory=tuple)


def _minute_now(t: float) -> int:
    return int(t // 60) + 1


def first_object(reply: str) -> object:
    """The first JSON object in a model's reply, and nothing after it. The published Companion
    answers a plan with the plan and then goes on to write an "answer" step of its own, with facts
    it made up (lesson 238): only the plan is read, so nothing it invented reaches the tools."""
    return json.JSONDecoder().raw_decode(reply[reply.index("{") :])[0]


def _calls(plan: object, insights, minute: int) -> list[dict]:
    """The model's tool calls, kept only when well formed: a known tool, a club of this match or
    none, minutes within the match so far. Anything else is dropped, never repaired into a call."""
    calls = []
    tools = plan.get("tools") if isinstance(plan, dict) else None
    for c in tools if isinstance(tools, list) else []:
        if not isinstance(c, dict) or c.get("name") not in MATCH_TOOLS:
            continue
        club = c.get("club")
        if club is not None and (
            not isinstance(club, str)
            or club.lower() not in {n.lower() for n in insights.fixture.clubs.values()}
        ):
            club = None
        lo, hi = c.get("minute_from"), c.get("minute_to")
        if not isinstance(lo, int) or not isinstance(hi, int) or not 1 <= lo <= hi:
            lo, hi = max(1, minute - WINDOW_MIN + 1), minute
        calls.append({"name": c["name"], "club": club, "minute_from": lo, "minute_to": min(hi, minute)})
    return calls[:MAX_TOOLS]


def run_tools(insights, calls: list[dict]) -> list[dict]:
    """The facts and summaries the calls return, each once, in call order."""
    seen, out = set(), []
    for c in calls:
        if c["name"] == "lineup":
            rows = [
                {**s, "id": f"sheet:{team}:{s['role']}", "kind": "sheet", "team": team, "confident": True}
                for team, sheet in insights.lineup(c["club"])["sheets"].items()
                for s in sheet
            ]
        elif c["name"] == "goal_build_up":
            got = insights.goal_build_up(c["minute_to"], c["club"])
            rows = got["facts"]
        else:
            got = getattr(insights, c["name"])(c["minute_from"], c["minute_to"], c["club"])
            if c["name"] != "goal_build_up":
                rows = [*got["summary"], *got["facts"]]
        for r in rows:
            if r["id"] not in seen:
                seen.add(r["id"])
                out.append(r)
    return out


def _for_prompt(fact: dict) -> dict:
    """A fact as the model reads it: without its drawing, which only the phone needs."""
    return {k: v for k, v in fact.items() if k not in ("visual", "tracked")}


HISTORY_TURNS = 3  # design: the last three exchanges are enough context for a follow-up


def _history(history) -> list[dict]:
    """The session's last turns as the model reads them: what was asked, what was answered, which
    tools. Viewer text, so data, like the question."""
    return [
        {"question": h["question"], "answer": h["answer"], "tools": [c["name"] for c in h.get("calls", ())]}
        for h in list(history)[-HISTORY_TURNS:]
    ]


def plan_prompt(question: Question, insights, history=()) -> str:
    return json.dumps(
        {
            "step": "plan",
            "question": question.text,
            "history": _history(history),
            "clubs": list(insights.fixture.clubs.values()),
            "minute": _minute_now(question.t),
            "tools": TOOL_HELP,
        },
        separators=(",", ":"),
    )


def answer_prompt(question: Question, facts: list[dict], history=()) -> str:
    return json.dumps(
        {
            "step": "answer",
            "question": question.text,
            "history": _history(history),
            "facts": [_for_prompt(f) for f in facts],
        },
        separators=(",", ":"),
    )


# When a question names a stretch of the match ("in the first half", "the last ten minutes"), the
# minutes code looks at; None when it names none. Halves are Law 7's 45 minutes.
WORD_MINUTES = {"five": 5, "ten": 10, "fifteen": 15, "twenty": 20, "thirty": 30}


def minutes_of(text: str, minute: int) -> tuple[int, int] | None:
    t = text.lower()
    if re.search(r"\bfirst half\b", t):
        return 1, min(45, minute)
    if re.search(r"\bsecond half\b", t):
        return (46, minute) if minute >= 46 else None
    m = re.search(r"\blast (\d+|five|ten|fifteen|twenty|thirty) minutes\b", t)
    if m:
        n = int(m.group(1)) if m.group(1).isdigit() else WORD_MINUTES[m.group(1)]
        return max(1, minute - n + 1), minute
    if re.search(r"\b(?:so far|whole (?:match|game)|all (?:match|game)|this (?:match|game)|today)\b", t):
        return 1, minute
    return None


FOLLOW_UPS = {
    "goal_build_up": (
        "Who has been the best player?",
        "How quickly do {club} win the ball back?",
        "Was anyone offside before the goal?",
    ),
    "players": ("Why did {club} score?", "Where are {club} outnumbering them?", "How are {club} playing?"),
    "style": ("How are {club} playing?", "Is the {club} keeper going long?", "Which passes cut through?"),
    "referee": ("What counts as a handball?", "Was anyone offside?", "Why did {club} score?"),
    "counter_press": (
        "Did {club} have options when they lost it?",
        "And in the first half?",
        "Where are {club} outnumbering them?",
    ),
    "overloads": (
        "How quickly do {club} win the ball back?",
        "Which passes cut through?",
        "How are {club} playing?",
    ),
    "line_breaks": (
        "Who has been the best player?",
        "Where are {club} outnumbering them?",
        "How are {club} playing?",
    ),
    "pass_options": (
        "How quickly do {club} win the ball back?",
        "Which passes cut through?",
        "Who has been the best player?",
    ),
    "team_shape": (
        "Where are {club} outnumbering them?",
        "And in the last ten minutes?",
        "How are {club} playing?",
    ),
    "set_pieces": (
        "How many shots have there been?",
        "Where has the ball been?",
        "What's the score?",
    ),
    "score": (
        "Why did {club} score?",
        "How many shots have there been?",
        "What have I missed?",
    ),
    "halves": (
        "Where has the ball been?",
        "How many shots have there been?",
        "Which passes cut through?",
    ),
    "key_moments": (
        "Which passes cut through?",
        "How many shots have there been?",
        "Where has the ball been?",
    ),
    "physical": (
        "Who has been the best player?",
        "How quickly do {club} win the ball back?",
        "Where has the ball been?",
    ),
    "passing": (
        "Which passes cut through?",
        "How many shots have there been?",
        "How are {club} playing?",
    ),
    "shots": (
        "Where has the ball been?",
        "Which passes cut through?",
        "How are {club} playing?",
    ),
    "possession": (
        "Where has the ball been?",
        "How quickly do {club} win the ball back?",
        "Which passes cut through?",
    ),
    "territory": (
        "Who has had more of the ball?",
        "Where are {club} outnumbering them?",
        "How are {club} playing?",
    ),
    "lineup": (
        "Who has been the best player?",
        "Why do {club} keep losing the ball?",
        "How are {club} playing?",
    ),
}
GENERAL = (
    "Who has been the best player?",
    "How are {club} playing?",
    "Why did {club} score?",
    "Which passes cut through?",
    "How quickly do {club} win the ball back?",
)
FOLLOW_UP_COUNT = 3


def answerable(text: str, insights, t: float) -> bool:
    """Can the tools answer this question now: code routes it to a tool and a checked answer comes back."""
    if not route(text):
        return False
    a, _ = code_match_answer(Question("follow-up", None, text, max(0.0, t)), insights, suggest=False)
    return a.status == "verified"


def follow_ups(
    calls: list[dict], cited: list[dict], insights, asked=(), t: float | None = None
) -> tuple[str, ...]:
    """Up to three suggested next questions, from the tools the answer used and then general ones,
    about the club it was about. Each is kept only if the tools can answer it now (`answerable`) and
    it is neither a question already asked in the conversation nor another suggestion again."""
    club = next((f.get("club") for f in cited if f.get("club")), None) or insights.fixture.clubs["home"]
    if t is None:
        ts = [float(f["t"]) for f in cited if f.get("t") is not None]
        ts += [60.0 * f["minute_to"] for f in cited if f.get("minute_to")]
        t = max(ts, default=60.0 * insights.minutes)
    seen = {q.strip().lower() for q in asked}
    # Not the same topic again: a suggestion that routes to exactly the tools of the question just
    # asked would repeat it in other words.
    just_asked = set(route(list(asked)[-1])) if asked else set()
    out: list[str] = []
    pool = [q for c in calls for q in FOLLOW_UPS.get(c["name"], ())] + list(GENERAL)
    for template in pool:
        q = template.format(club=club)
        if q.lower() in seen or q in out or (just_asked and set(route(q)) == just_asked):
            continue
        seen.add(q.lower())
        if answerable(q, insights, t):
            out.append(q)
        if len(out) == FOLLOW_UP_COUNT:
            break
    return tuple(out)


def _point_ids(node) -> set[str]:
    """Every track id in a geometry: the third item of each [x, y, id] point, however nested."""
    if isinstance(node, list):
        if len(node) == 3 and all(isinstance(v, (int, float)) for v in node[:2]) and isinstance(node[2], str):
            return {node[2]}
        return set().union(*(_point_ids(v) for v in node)) if node else set()
    if isinstance(node, dict):
        return set().union(*(_point_ids(v) for v in node.values())) if node else set()
    return set()


def names_of(cited: list[dict], visual: dict | None, insights) -> dict | None:
    """How the phone labels each player its drawing or text shows: the gated name or role, never an id."""
    ids = {f.get(k) for f in cited for k in ("passer", "receiver", "player")}
    ids |= _point_ids((visual or {}).get("geometry"))
    out = {i: insights.people[i]["say"] for i in sorted(i for i in ids if i) if i in insights.people}
    return out or None


def visual_of(cited: list[dict]) -> dict | None:
    """The phone's overlay: the first cited fact that draws one."""
    for f in cited:
        v = f.get("visual")
        if v:
            return {
                "kind": v["kind"],
                "fact": f["id"],
                "t": f.get("t"),
                "team": f.get("team"),
                "club": f.get("club"),
                "geometry": {k: val for k, val in v.items() if k != "kind"},
            }
    return None


def _span(cited: list[dict]) -> tuple[float | None, float | None]:
    ts = [float(f["t"]) for f in cited if f.get("t") is not None]
    ts += [60.0 * (f["minute_from"] - 1) for f in cited if f.get("minute_from")]
    ts += [60.0 * f["minute_to"] for f in cited if f.get("minute_to")]
    return (min(ts), max(ts)) if ts else (None, None)


def _match_answer(
    text: str, cited: list[dict], insights=None, calls=(), asked=(), t=None, suggest=True
) -> Answer:
    t_from, t_to = _span(cited)
    lead = next((f for f in cited if f.get("value") is not None and f.get("unit")), None)
    metric, value, unit = (lead["metric"], float(lead["value"]), lead["unit"]) if lead else (None, None, None)
    visual = visual_of(cited)
    extra = {}
    if insights is not None:
        extra = {
            "names": names_of(cited, visual, insights),
            "follow_ups": follow_ups(list(calls), cited, insights, asked, t) if suggest else (),
        }
    # The answer is spoken as written: code's and the model's sentences carry no visual reference
    # (insight_check rejects one), so the screen reader and the Describer read the text itself.
    return Answer(
        "verified",
        text,
        metric,
        value,
        unit,
        tuple(f["id"] for f in cited),
        t_from,
        t_to,
        visual,
        spoken=text,
        headline=_headline_of(text, asked[-1], cited, insights) if asked and insights is not None else None,
        **extra,
    )


def _headline_of(text: str, question: str, cited: list[dict], insights) -> str | None:
    """The headline, kept only when every number it shows is one the sentence says: the sentence is
    what the fact-checker passed, for a model's answer as for code's."""
    head = headline(question, cited, insights)
    said = re.findall(r"\d+(?:\.\d+)?", text)
    if head is None or any(n not in said for n in re.findall(r"\d+(?:\.\d+)?", head)):
        return None
    return head


def clubs_named(text: str, insights) -> list[str]:
    """The clubs a question names, by full or short name ("Lisbon's left-back")."""
    from ninety.intel.teamsheet import short_name

    fx = insights.fixture
    out = []
    for team, code in (("home", fx.home_code), ("away", fx.away_code)):
        full = fx.clubs[team]
        if any(re.search(rf"\b{re.escape(n)}\b", text, re.I) for n in {full, short_name(code)}):
            out.append(full)
    return out


def _short(insights, club: str | None) -> str | None:
    from ninety.intel.teamsheet import short_name

    fx = insights.fixture
    by = {fx.clubs["home"]: fx.home_code, fx.clubs["away"]: fx.away_code}
    return short_name(by[club]) if club in by else club


# The kind of a question, for its headline: who or which asks a name, how many or how fast a number,
# where a place. Anything else (why, is, how are they playing) has no one-word answer.
QUESTION_KINDS = (
    ("number", r"\bhow (?:many|much|often|quick\w*|fast|long|far|wide|soon)\b"),
    ("who", r"^\W*(?:who|whose|which)\b|\bwho\b|\bname\b"),
    ("where", r"\bwhere\b"),
)
CHANNEL_PHRASE = {"left": "Down the left", "right": "Down the right", "centre": "Through the middle"}


def question_kind(text: str) -> str | None:
    lowered = text.lower()
    return next((k for k, words in QUESTION_KINDS if re.search(words, lowered)), None)


def _figure(f: dict) -> str | None:
    if f.get("value") is None or not f.get("unit"):
        return None
    v, unit = _num(f["value"]), f["unit"]
    if f.get("metric") == "final_third_share":  # said as its range: the ball near a line is either side
        return f"{f['lo']}%" if f["lo"] == f["hi"] else f"{f['lo']} to {f['hi']}%"
    if f.get("metric") == "regains_within_5s":
        return f"{v} {'regain' if v == '1' else 'regains'} in 5 s"  # the window the sentence says
    if unit == "%":
        return f"{v}%"
    if unit in ("m", "s", "km/h"):
        return f"{v} {unit}"
    return f"{v} {unit[:-1] if v == '1' and unit.endswith('s') else unit}"


def _place(f: dict) -> str | None:
    third = channel = None
    if f.get("metric") == "overload_moments" and f.get("most"):
        third, channel = f["most"].split("-")
    elif f.get("metric") == "extra_players":
        third, channel = f.get("third"), f.get("channel")
    elif f.get("metric") == "pass_share_by_channel":
        channel = f.get("most")
    if channel not in CHANNEL_PHRASE:
        return None
    return CHANNEL_PHRASE[channel] + (f", {third} third" if third else "")


def _who(f: dict, insights) -> str | None:
    if f.get("kind") == "sheet":
        return f.get("name")
    # passer_is / player_is hold a name only past the role gate, else the role ("London Athletic's
    # left-back"): the headline says what the sentence may say, with the club's short name.
    who = f.get("scorer_is") or f.get("player_is") or f.get("passer_is")
    if not who:
        return None
    for club in insights.fixture.clubs.values():
        if who.startswith(f"{club}'s "):
            return f"{_short(insights, club)}'s {who[len(club) + 3:]}"
    return who


def headline(question: str, cited: list[dict], insights) -> str | None:
    """The direct answer to the question in a few words, from the cited facts only: the player for
    who or which (his name when it is confident, else his role, else the club), the number with its
    unit for how many or how fast, the place for where; the supporting number stays in the sentence.
    A question of another kind is headed by the lead number, or by nothing."""
    kind = question_kind(question)
    sc = next((f for f in cited if f.get("metric") == "score" and f.get("confident")), None)
    if sc is not None and kind != "who":  # "what's the score?": the score itself
        fx = insights.fixture
        return f"{short_name(fx.home_code)} {sc['home']}, {short_name(fx.away_code)} {sc['away']}"
    goal = next((f for f in cited if f.get("kind") == "goal" and f.get("club") and f.get("minute")), None)
    recap = {"key_moments", "goal_build_up"} & set(route(question))
    if goal is not None and kind != "who" and recap:  # a recap or a goal question leads with the goal
        return f"Goal: {_short(insights, goal['club'])}, minute {goal['minute']}"
    if kind == "who":
        got = next((h for f in cited if (h := _who(f, insights))), None)
        got = got or next((_short(insights, f["club"]) for f in cited if f.get("club")), None)
    elif kind == "where":
        got = next((p for f in cited if (p := _place(f))), None)
    else:
        got = None
    got = got or next((n for f in cited if (n := _figure(f))), None)
    return got[:48] if got else None


def _people(insights) -> dict:
    return insights.people


def _verify(claim: Claim, known: dict, insights) -> Verdict:
    from ninety.agents import insight_check

    return insight_check.verify(
        claim, known, insights.fixture.clubs, _people(insights), insights.sheet_names()
    )


def _num(v: float) -> str:
    return _number(round(float(v), 1))


def _plural(n, word: str) -> str:
    return f"{_num(n)} {word}" + ("" if n == 1 else "es" if word.endswith("s") else "s")


# What a pass kind is called, and the verb for a club's count (ninety/intel/passing.py).
PASS_WORDS = {
    "progressive": ("progressive passes", "completed"),
    "final_third_entry": ("passes into the final third", "completed"),
    "long": ("long passes", "played"),
    "intercepted": ("passes intercepted", "had"),
}
PASS_WORDS.update({f"{k}_all": v for k, v in list(PASS_WORDS.items())})


def code_texts(fact: dict) -> list[str]:
    """What code says about one fact or summary, in a fan's words. Empty when there is nothing it
    may say (an unsure fact, or a summary with nothing in it)."""
    if not fact.get("confident", False):
        return []
    club, kind, metric = fact.get("club"), fact.get("kind"), fact.get("metric")
    span = (
        f"from minute {fact['minute_from']} to minute {fact['minute_to']}"
        if fact.get("minute_from")
        else f"in minute {fact.get('minute')}"
    )
    club = club or ""
    who = fact.get("passer_is") or f"{'an' if club[:1] in 'AEIOU' else 'a'} {club} player"
    if metric == "regains_within_5s":
        lost = fact["also"][0][0]
        if not lost:
            return []
        back = {0: "never won it back", 1: "won it back once"}.get(
            fact["value"], f"won it back {fact['value']} times"
        )
        return [
            f"{club} lost the ball {_plural(lost, 'time')} in open play {span} and {back} within 5 seconds."
        ]
    if metric == "pressers":
        players = _plural(fact["value"], "player")
        if fact.get("regained") and fact.get("regain_s") is not None:
            return [
                f"{span.capitalize()}, {club} won the ball back {_num(fact['regain_s'])} seconds "
                f"after losing it, "
                f"with {players} around it."
            ]
        return [f"{span.capitalize()}, {club} lost the ball and had {players} near it in the next 5 seconds."]
    if metric == "opponents_bypassed":
        if fact["value"] < 1:
            return []
        opp = next(n for t, n in fact["clubs"].items() if t != fact["team"]) if fact.get("clubs") else "their"
        return [
            f"{span.capitalize()}, {who} played a pass that took {fact['value']} {opp} "
            f"{'player' if fact['value'] == 1 else 'players'} out of the game."
        ]
    if metric == "opponents_bypassed_total":
        if not fact["value"]:
            return []
        return [f"{club}'s completed passes took out {fact['value']} opponents in all {span}."]
    if metric == "extra_players":
        return [
            f"{span.capitalize()}, {club} had {_plural(fact['own_players'], 'player')} against "
            f"{_plural(fact['other_players'], 'player')} around the ball, in their {fact['third']} third"
            f"{' in the centre' if fact['channel'] == 'centre' else ' on the ' + fact['channel']}."
        ]
    if metric == "overload_moments":
        if not fact["value"]:
            return []
        third, channel = fact["most"].split("-")
        where = "in the centre" if channel == "centre" else f"on the {channel}"
        return [
            f"{club} built {_plural(fact['value'], 'overload')} {span}, "
            f"most often in their {third} third {where}."
        ]
    if metric == "open_teammates_ahead":
        if fact.get("outcome") == "fail" and fact["value"] == 0:
            return [f"{span.capitalize()}, {who} lost the ball with no teammate free further up the pitch."]
        if fact.get("outcome") == "fail" and fact.get("target_open") is False and fact["value"] > 0:
            return [
                f"{span.capitalize()}, {who} had {_plural(fact['value'], 'teammate')} free further up "
                "the pitch, but the pass went elsewhere and was lost."
            ]
        return []
    if metric == "passes_with_no_open_teammate_ahead":
        if not fact["value"]:
            return []
        return [f"{club} made {fact['value']} passes with no open teammate further forward {span}."]
    if metric == "pass_share_by_channel":
        return [
            f"{club} played most through the {fact['most']}: {fact['value']}% of their passes {span} "
            "started there."
        ]
    if metric == "median_width":
        other_club = (
            next(n for t, n in fact["clubs"].items() if t != fact["team"]) if fact.get("clubs") else ""
        )
        return [
            f"{club} stretched the play {fact['value']} m wide {span}, against {other_club}'s "
            f"{fact['other_width']} m."
        ]
    if metric == "crosses":
        if not fact["value"]:
            return []
        return [
            f"{club} crossed {_plural(fact['value'], 'time')} {span} and found a teammate "
            f"{_plural(fact['completed'], 'time')}."
        ]
    if metric == "keeper_long_balls":
        return [
            f"{club}'s goalkeeper went long {_plural(fact['value'], 'time')} and short "
            f"{_plural(fact['short'], 'time')} {span}."
        ]
    if metric == "regain_to_shot_s":
        return [
            f"{span.capitalize()}, {club} won the ball back and had a shot "
            f"{_num(fact['value'])} seconds later."
        ]
    if metric == "shot_distance_m":
        shooter = f"{who} shot" if fact.get("side_known") else "a shot came"
        return [
            f"{span.capitalize()}, {shooter} from {fact['value']} m out, where the posts were "
            f"{fact['angle_deg']} degrees apart."
        ]
    if metric in ("shots_all", "shots"):
        n, k = fact["value"], fact["inside_box"]
        lead = f"There were {_plural(n, 'shot')} {span}" if metric == "shots_all" else (
            f"{club} had {_plural(n, 'shot')} {span}"
        )
        if not fact.get("inside_exact", True):  # a shot near the area's line: the inside count is unsure
            return [f"{lead}."]
        who = "players took" if metric == "shots_all" else "took"
        return [f"{lead}, and {who} {_plural(k, 'shot')} from inside the penalty area."]
    if metric == "player_km":
        label = f", give or take {fact['within_pct']}%" if fact.get("within_pct") is not None else ""
        return [f"{fact['player_is']} has covered {fact['value']} km {span}, from the footage shown{label}."]
    if metric == "player_top_kmh":
        return [f"{fact['player_is']} reached a top speed of {fact['value']} km/h {span}."]
    if metric == "player_sprints":
        if not fact["value"]:
            return [f"{fact['player_is']} did not sprint above 25.2 km/h {span}."]
        return [f"{fact['player_is']} sprinted {_plural(fact['value'], 'time')} above 25.2 km/h {span}."]
    if metric == "player_zone":
        where = "in the centre" if fact["channel"] == "centre" else f"on the {fact['channel']}"
        return [
            f"{fact['player_is']} was most often in their {fact['third']} third {where} {span}, in the "
            "footage the video named him in."
        ]
    if metric in PASS_WORDS:
        n = fact["value"]
        what, verb = PASS_WORDS[metric]
        noun = what.replace("passes", "pass") if n == 1 else what
        if fact.get("team") is None:
            return [f"There {'was' if n == 1 else 'were'} {n} {noun} {span}."]
        return [f"{club} {verb} {n} {noun} {span}."]
    if metric == "pair_passes":
        return [
            f"{fact['passer_is']} passed to {fact['receiver_is']} {_plural(fact['value'], 'time')} {span}, "
            "of the passes the video could name both players of."
        ]
    if metric == "possession_share":
        if fact.get("value") is None:
            return []
        return [f"{club} had {fact['value']}% of possession {span}, counted by share of passes."]
    if metric == "final_third_share":
        lo, hi = fact["lo"], fact["hi"]
        share = f"{lo}%" if lo == hi else f"between {lo}% and {hi}%"
        return [f"The ball was in {club}'s attacking third {share} of the footage shown {span}."]
    if metric == "one_two":
        a, b = fact.get("passer_is"), fact.get("receiver_is")
        if not a or not b or a == b:  # one name twice is no one-two a fan would believe
            return []
        return [f"{span.capitalize()}, {a} and {b} played a one-two."]
    if kind == "offside":
        return referee.offside_texts(fact, span)
    if kind == "law":
        # No Law number in the sentence: a number the fact-checker would find in no fact.
        text = fact["text"]
        return [text] if fact["law"] == "our cameras" else [f"The Laws say that {text[0].lower()}{text[1:]}"]
    if kind == "goal":
        m = fact["minute"]
        out = []
        if fact.get("scorer_is") and fact.get("assister_is"):
            out.append(
                f"{fact['scorer_is']} scored for {club} in minute {m}, from {fact['assister_is']}'s pass."
            )
        if fact.get("scorer_is"):
            out.append(f"{fact['scorer_is']} scored for {club} in minute {m}.")
        return [*out, f"{club} scored in minute {m}."]
    if fact.get("kind") == "set_pieces":
        from ninety.intel.set_pieces import WORDS

        n = fact["value"]
        noun = WORDS[fact["restart"]][0 if n == 1 else 1]
        if fact.get("team") is None:
            return [f"There {'was' if n == 1 else 'were'} {n} {noun} {span}."]
        return [f"{club} had {n} {noun} {span}."]
    if metric == "score":
        cl = fact["clubs"]
        h, a, m = fact["home"], fact["away"], fact["minute"]
        if not h and not a:
            return [f"By minute {m}, neither {cl['home']} nor {cl['away']} had scored."]
        return [
            f"By minute {m}, {cl['home']} had scored {_plural(h, 'goal')} and {cl['away']} "
            f"{_plural(a, 'goal')}."
        ]
    if metric == "saves":
        return [f"{club} made {_plural(fact['value'], 'save')} {span}."]
    if metric == "opponents_bypassed_by_player":
        if fact.get("rank") != 1 or not fact.get("leads") or not fact.get("player_is"):
            return []
        return [
            f"{fact['player_is']} has taken the most opponents out of the game with passes {span}: "
            f"{fact['value']} opponents in {_plural(fact['also'][0][0], 'pass')}."
        ]
    if fact.get("type") == "shape":
        return _shape_texts(fact, club or "", span)
    if kind == "sheet":
        return [f"{fact['name']} plays {fact['position']} for {club}, by the team sheet."]
    return []


SHAPE_CHANGE_M = 3  # the least change said, as the audio description (ninety/speech/describe.py)


def _shape_texts(fact: dict, club: str, span: str) -> list[str]:
    v, c, m = _num(fact["value"]), fact.get("change"), fact["metric"]
    out = []
    if m == "line_height" and c is not None and abs(c) >= SHAPE_CHANGE_M:
        move = "pushed up" if c > 0 else "dropped back"  # the shape check reads the change right after it
        out.append(
            f"{span.capitalize()}, {club}'s back line {move} {_num(abs(c))} m, to {v} m from their own goal."
        )
    if m == "line_height":
        out.append(f"{span.capitalize()}, {club}'s back line was {v} m from their own goal.")
    if m == "width":
        out.append(f"{span.capitalize()}, {club}'s width was {v} m.")
    return out


def code_calls(question: Question, insights, history=()) -> list[dict]:
    """Code's plan: the routed tools, or a follow-up's ("and in the first half?") the last turn's
    tools; over the stretch the question names, else the last WINDOW_MIN minutes."""
    minute = _minute_now(question.t)
    names = route(question.text)
    if not names and history:
        names = [c["name"] for c in history[-1]["calls"]] if history[-1].get("calls") else []
    lo, hi = minutes_of(question.text, minute) or (max(1, minute - WINDOW_MIN + 1), minute)
    # A club the question names may be the side acting or the side acted on ("which pass cut through
    # Lisbon Esportes?"): code reads both clubs' facts and the fact-check binds the sentence to the right one.
    return [{"name": n, "club": None, "minute_from": lo, "minute_to": hi} for n in names]


# What a fan calls each running figure the physical tool may hold, the most specific first: a
# sprint before a speed, a speed before a distance (merge-queue reviews of #323).
ASKS_RUNNING = {
    "player_sprints": (r"\b(?:sprint\w*|bursts?)\b", "sprint count"),
    "player_top_kmh": (
        r"\b(?:fastest|quickest|top speed|how fast|speed\w*|pace|km/h|quick(?:er)?)\b", "top speed"
    ),
    "player_km": (
        r"\b(?:distance|covered|how far|km|kms|kilomet\w*|miles?|ground|ran|run|runs|running|furthest"
        r"|farthest|tired\w*|work rate|stamina|legs|energy|fitness|engine)\b",
        "distance",
    ),
}
# What the physical tool says when its figures are held: the zone a player was in most. A question
# asks for that only with a word of place.
ASKS_ZONE = (
    r"\b(?:where|zones?|positions?|positioned|heat ?maps?|thirds?|wings?|flanks?|channels?|left|right"
    r"|middle|centre|center|areas?|parts? of the pitch)\b"
)


def asked_running(text: str) -> str | None:
    """The running figure a question asks for, the most specific one, or None."""
    return next((m for m, (words, _) in ASKS_RUNNING.items() if re.search(words, text, re.I)), None)


def held_ask(text: str, calls, facts) -> str | None:
    """Why a physical question cannot be answered, or None. A running figure asked for is held when
    every fact of it is unsure: the video does not yet follow enough of each named player. A
    question that asks no figure and no place is answered only while some figure is said: the zone
    is never the answer to a question that did not ask where (the fact-check never sees the
    question, so code gates on it here)."""
    if not any(c["name"] == "physical" for c in calls):
        return None
    sure = {f.get("metric") for f in facts if f.get("confident")}
    metric = asked_running(text)
    if metric is not None:
        if metric in sure:
            return None
        said = ASKS_RUNNING[metric][1]
    elif re.search(ASKS_ZONE, text, re.I) or sure & set(ASKS_RUNNING):
        return None
    else:
        said = "running"
    return (
        f"A player's {said} isn't available yet: the video can't follow enough of each named "
        "player to measure it reliably."
    )


def running_first(text: str, facts: list[dict]) -> list[dict]:
    """A running figure asked for: its facts first, the player the question names first, else the
    highest value first ("who is the fastest?" is the maximum, not the first by distance)."""
    metric = asked_running(text)
    if metric is None:
        return facts
    def key(f):
        if f.get("metric") != metric:
            return (1, 0, 0.0)
        named = bool(f.get("player_is")) and re.search(rf"\b{re.escape(f['player_is'])}\b", text, re.I)
        return (0, not named, -(f.get("value") or 0))
    return sorted(facts, key=key)


def code_match_answer(
    question: Question, insights, calls: list[dict] | None = None, history=(), suggest: bool = True
) -> tuple[Answer, list[dict]]:
    """Code's answer: the routed tools' facts, the first one code can say and the check passes. A
    goal is told with the strongest thing that led to it."""
    calls = calls if calls is not None else code_calls(question, insights, history)
    facts = run_tools(insights, calls)
    known = {f["id"]: f for f in facts}
    clubs = insights.fixture.clubs
    for f in facts:
        f.setdefault("clubs", clubs)
    named = clubs_named(question.text, insights)
    if len(named) == 1:
        # A question about one club hears about that club first (its facts before the other's); the
        # fact-check still binds the sentence to the right side.
        facts = sorted(facts, key=lambda f: f.get("club") not in (None, named[0]))
    if re.search(r"\b(?:which|who|whose)\b", question.text, re.I):
        # "Which pass…?", "Who…?": a moment with a player in it, before a club's total.
        facts = sorted(facts, key=lambda f: f.get("t") is None)
    role = asked_role(question.text)
    if role is None:
        # A team-sheet row answers only who plays a position: "who is the best player?" is never
        # answered with the first name on the sheet.
        facts = [f for f in facts if f.get("kind") != "sheet"]
    else:
        # "Who is Lisbon's left-back?": that row of the named club's sheet (else either club's), first.
        facts = sorted(
            facts,
            key=lambda f: (f.get("kind") != "sheet" or f.get("role") != role, f.get("club") not in named),
        )
    why = held_ask(question.text, calls, facts)
    if why is not None:  # a figure asked for that is held: say so, never answer something else
        return Answer("unanswerable", why, None, None, None, (), 0.0, float(question.t)), calls
    facts = running_first(question.text, facts)
    asked = referee.topic(question.text) if any(c["name"] == "referee" for c in calls) else None
    if asked is not None:
        # A referee question: an offside reading first when it is about offside, then the Laws the
        # topic needs, the cameras' limit first for a contact call. Never a ruling on a foul.
        name, ids = asked
        reading = next((f for f in facts if f.get("kind") == "offside" and code_texts(f)), None)
        laws = [f for i in ids for f in facts if f["id"] == i]
        cited = ([reading] if reading is not None and name == "offside" else []) + laws[:2]
        if cited:
            text = " ".join(code_texts(f)[0] for f in cited)
            if _verify(Claim(text, [f["id"] for f in cited]), known, insights).ok:
                return _match_answer(
                    text,
                    cited,
                    insights,
                    calls,
                    asked=[*(h["question"] for h in history), question.text],
                    t=question.t,
                    suggest=suggest,
                ), calls
    # A goal's story ("why did they score?"): the goal with the strongest thing before it, when the
    # goal build-up is what was asked (a "what's the score?" is the score's to answer).
    goal = next((f for f in facts if f.get("kind") == "goal"), None)
    if goal is not None and calls and calls[0]["name"] == "goal_build_up":
        for f in facts:
            if f is goal or f.get("team") != goal["team"] or f.get("kind") == "goal":
                continue
            for text in code_texts(f):
                lead = text[0].lower() + text[1:] if text.split()[0] in ("In", "From") else text
                combined = f"{goal['club']} scored in minute {goal['minute']}. Just before it, {lead}"
                if _verify(Claim(combined, [goal["id"], f["id"]]), known, insights).ok:
                    return _match_answer(
                        combined,
                        [goal, f],
                        insights,
                        calls,
                        asked=[*(h["question"] for h in history), question.text],
                        t=question.t,
                        suggest=suggest,
                    ), calls
    for f in facts:
        for text in code_texts(f):
            claim = Claim(text, [f["id"]])
            if _verify(claim, known, insights).ok:
                return _match_answer(
                    text,
                    [f],
                    insights,
                    calls,
                    asked=[*(h["question"] for h in history), question.text],
                    t=question.t,
                    suggest=suggest,
                ), calls
    names = ", ".join(n.replace("_", " ") for n in MATCH_TOOLS[:4])
    why = (
        "I have no tracked positions for this match yet."
        if not facts and calls
        else f"I can answer about {names} and the team sheets."
    )
    t_from, t_to = 0.0, float(question.t)
    return Answer("unanswerable", why, None, None, None, (), t_from, t_to), calls


async def answer_match(
    question: Question,
    insights,
    ask: Ask | None = None,
    judge: Judge | None = None,
    timeout: float = TIMEOUT_S,
    history=(),
    referee_ask: Ask | None = None,
) -> MatchResult:
    """The phone's answer to a match question. With no `ask`, code routes and answers. With one,
    the model plans the tool calls and writes the answer; anything but a verified draft gives
    code's answer over the model's chosen tools (or code's, if the plan was unusable). `history` is
    the session's earlier turns ({question, answer, calls}), so a follow-up has its context."""
    history = list(history)
    if ask is None:
        a, calls = code_match_answer(question, insights, history=history)
        return MatchResult(a, "code", tuple(calls))
    minute = _minute_now(question.t)

    async def drafted():
        plan_reply = await ask(plan_prompt(question, insights, history))
        try:
            plan = first_object(plan_reply)
        except (json.JSONDecodeError, TypeError, AttributeError, ValueError, RecursionError):
            raise _NotTheFormat("plan") from None
        calls = _calls(plan, insights, minute)
        if not calls:
            return calls, None, None, []
        facts = run_tools(insights, calls)
        if held_ask(question.text, calls, facts) is not None:
            return calls, None, None, facts  # code says why it is not available
        # A rules question is the Referee's to answer (ninety/agents/referee.py): the Companion
        # hands the facts over, and the same fact-check gates what comes back.
        rules = any(c["name"] == "referee" for c in calls)
        writer = referee_ask if referee_ask is not None and rules else ask
        reply = await writer(answer_prompt(question, facts, history))
        try:
            claim = parse_claim(reply)
        except (json.JSONDecodeError, AttributeError, TypeError, ValueError, RecursionError) as exc:
            raise _NotTheFormat(str(exc)[:200]) from None
        known = {f["id"]: f for f in facts}
        if not claim.text.strip():
            return calls, claim, None, facts
        verdict = _verify(claim, known, insights)
        metric = asked_running(question.text) if any(c["name"] == "physical" for c in calls) else None
        if verdict.ok and metric and all(known.get(i, {}).get("metric") != metric for i in claim.evidence):
            said = ASKS_RUNNING[metric][1]
            verdict = Verdict(ok=False, reasons=[f"the question asks for a {said}; the answer cites none"])
        if verdict.ok and judge is not None:
            verdict = await judge(claim, [_for_prompt(known[i]) for i in claim.evidence])
        return calls, claim, verdict, facts

    def fallback(reason: str, calls=None) -> MatchResult:
        a, used = code_match_answer(question, insights, calls or None, history)
        return MatchResult(a, "code", tuple(used), (reason,) if isinstance(reason, str) else tuple(reason))

    try:
        calls, claim, verdict, facts = await asyncio.wait_for(drafted(), timeout)
    except TimeoutError:
        return fallback("model timeout")
    except service_errors():
        return fallback("model service error")
    except _NotTheFormat:
        return fallback("model reply is not the reply format")
    if not calls:
        return fallback("model chose no tool")
    if verdict is None:
        return fallback("model: unanswerable", calls)
    if status_for(verdict) != "verified":
        return fallback(tuple(verdict.reasons), calls)
    known = {f["id"]: f for f in facts}
    cited = [known[i] for i in claim.evidence]
    asked = [*(h["question"] for h in history), question.text]
    return MatchResult(
        _match_answer(claim.text, cited, insights, calls, asked, question.t), "model", tuple(calls)
    )
