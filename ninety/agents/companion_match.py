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
from dataclasses import dataclass, field, replace

from ninety.agents import referee

# A message that tries to change the rules, asks for a prediction, or asks what the tracking never sees
# (lesson 288), and the typo fixes: one definition each, the intent table's.
from ninety.agents.ask_intents import (
    FIX_CUTOFF,
    FIX_LEN,
    FOOTBALL_WORDS,
    FUTURE,
    INJECTION,
    OUTSIDE,
    SHORTHAND,
)
from ninety.agents.companion import (
    TIMEOUT_S,
    NoModel,
    Source,
    _NotTheFormat,
    _number,
    _timeout_reason,
    service_errors,
    within,
)
from ninety.agents.contracts import Answer, Ask, Judge, Question, status_for
from ninety.agents.factcheck import MIN_CONFIDENCE, Claim, Verdict, parse_claim
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
    "on_top",
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
    "score": "each goal vision spotted up to minute_to, with its scorer and the pass that made it (an "
    "assist), and each club's goalkeeper's saves; never a scoreline (the broadcast's scorebug shows it)",
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
    "possession": "each club's share of the time either side had the ball (time in possession: dead and "
    "contested time left out), from the first minute a share can be said",
    "on_top": "which club has been on top over the minutes, by where the ball was: a club leads only when "
    "its share of the footage with the ball in its attacking third is clearly more than the other's, "
    "else neither; both clubs' shares beside it",
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
        r"\b(?:what(?:'s| is) the score|the score|(?<![\w ])score|score (?:please|now|update|so far)"
        r"|final score"
        r"|scoreline|who scored|scorers?|assists?|assisted"
        r"|saves?|how many goals|who(?:'s| is) (?:winning(?! (?:the|in|at|on) )|ahead|leading|in front"
        r"|in the lead)|is it (?:a )?(?:draw|level)"
        r"|is it \d+ ?[-–] ?\d+|drawing|are .{1,30} (?:winning|level|losing|ahead|behind|in front))\b",
    ),
    ("goal_build_up", r"\b(?:goals?|scor\w*|equali[sz]\w*|that finish)\b"),
    (
        "style",
        r"\b(?:style|playing like|play(?:ing)? like this|tactic\w*|approach|long balls?|go(?:ing)? long"
        r"|cross\w*|wings?|down the (?:left|right|middle)|counter[- ]attack\w*|on the break|one-twos?"
        r"|wall pass\w*|how (?:are|is) [\w' ]+ (?:playing|doing|getting on|looking|defending|attacking)"
        r"|how is the (?:game|match) going|going forward|direct\w*|out from the back|from the back"
        r"|play(?:ing)? short"
        r"|how did [\w' ]+ do"
        r"|goal ?keeper|keeper)\b",
    ),
    (
        "on_top",
        r"\b(?:on top|the better (?:side|team)|been better(?! (?:in|on) (?:possession|the ball))|bossing"
        r"|in control(?! of the ball)|momentum|upper hand|better of|finish\w* stronger"
        r"|(?:team|side) is better|playing better|pushing)\b",
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
        r"\b(?:options?|open|free|unmarked|decision\w*|choice\w*|should(?:'ve| have)|who to pass)\b",
    ),
    (
        "team_shape",
        r"\b(?:shape|compact\w*|narrow\w*|stretched|high line|deep|block|back line|defensive line"
        r"|width|wide|spread out)\b",
    ),
    (
        "halves",
        r"\b(?:halves|compar\w*[^?.]{0,40}\b(?:first|second)\b|the two halves|since the break|after the break"
        r"|half[- ]time"
        r"|first half (?:and|v|vs|against) (?:the )?second)\b",
    ),
    (
        "key_moments",
        r"\b(?:key moments?|highlights?|what (?:have|did) i miss\w*|what(?:'s)? happened|catch me up|recap"
        r"|timeline|anything happen\w*|how did the (?:first|second) half (?:end|go))\b",
    ),
    (
        "physical",
        r"\b(?:distance|covered|how far|sprint\w*|fastest|top speed|how fast|heat ?map|work rate|tired"
        r"|ran the most|run the most|running|furthest|farthest|kilomet\w*|km|quickest|stamina|fitness"
        r"|where (?:has|does|did|is) [\w' -]+ (?:been )?play\w*)\b",
    ),
    (
        "passing",
        r"\b(?:progressive|into the final third|final[- ]third entr\w*|intercept\w*|pass network"
        r"|who passes to whom|link(?:ing)? up|combin\w*|partnership|passed to each other|passing)\b",
    ),
    ("shots", r"\b(?:shots?|shooting|shoot|efforts? on goal|chances?|attempts?)\b"),
    (
        "possession",
        r"\b(?:possession|more of the ball|keep(?:ing|s)? the ball"
        r"|(?:have|has|had) (?:had )?the ball (?:more|most)|dominat\w*)\b",
    ),
    (
        "territory",
        r"\b(?:territory|where (?:has|is) the ball|pinned (?:back|in)|camped|on the front foot"
        r"|in (?:their|the other) half|on top|in control)\b",
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
    if SECOND_HALF.search(lowered) and not re.search(r"\b(?:compar\w*|chang\w*|differen\w*|than|vs|versus)\b",
                                                     lowered):
        tools = [t for t in tools if t != "halves"]  # a stretch of the match, not the halves compared
    if re.search(r"\b(?:high|deep|back|defensive|offside) line\b", lowered) and "team_shape" in tools:
        tools = [t for t in tools if t != "line_breaks"]  # a back line's height is the shape's to answer
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


FULL_TIME_MIN = 90  # Law 7's two halves of 45 (GROUNDING L3, I23): the engine plays no added time


def _minute_in(t: float, insights) -> int:
    """The minute now, never past full time: a question at 90:00 or after asks about minute 90, not a
    "minute 91" the match does not have (lesson 287). A match tracked for longer keeps its minutes."""
    return min(_minute_now(t), max(FULL_TIME_MIN, int(getattr(insights, "minutes", 0) or 0)))


# A message that is not a question about the match: a greeting, thanks, small talk, a question about
# the companion itself. Answered by code with a short reply and suggested questions, before any tool
# or model call, so it never gets a statistic (lesson 287). The whole message must be one of these:
# "hi, who's winning?" is a question.
_CHAT_END = r"[\s!.,?:;)(*~^-]*(?:(?:mate|there|all|everyone|guys|team|buddy|pal|bot|companion)[\s!.,?]*)?$"
SMALL_TALK = (
    ("greeting", re.compile(
        r"^\s*(?:h(?:i+|e+y+|ello+|ey+a|iya|owdy)|yo+|sup|wassup|what'?s up"
        r"|good (?:morning|afternoon|evening)|morning|evening|alright|ola|hola)" + _CHAT_END, re.I)),
    ("thanks", re.compile(
        r"^\s*(?:thanks?(?: you)?(?: (?:so|very) much)?|thx|ty|cheers|ta|nice(?: one)?|great|cool|awesome"
        r"|ok(?:ay)?|k|lol|haha+|perfect|got it|brilliant|bye|goodbye|see (?:you|ya)|cya|good night)"
        + _CHAT_END, re.I)),
    ("about", re.compile(
        r"^\s*(?:(?:so |and )?(?:who|what) (?:are|r) (?:you|u)|what (?:can|do) (?:you|u) do|what do you know"
        r"|how (?:does|do) (?:this|it|you) work|help|what is this|what'?s this"
        r"|are you (?:a bot|an? ai|human|real)"
        r"|what should i ask|what can i ask(?: you)?)" + _CHAT_END, re.I)),
)
CHAT_REPLIES = {
    "greeting": "Hi! I'm your match companion. Ask me anything about this match, like one of these:",
    "thanks": "You're welcome! Anything else about the match? Try one of these:",
    "about": ("I'm your match companion: I answer questions about this match from what the cameras "
              "tracked, and every number is checked before you see it. Try one of these:"),
    "other": "I can't answer that one from this match's tracking. Try one of these:",
    "inject": ("I only answer questions about this match, from what the cameras tracked, and I can't "
               "change how I answer. Try one of these:"),
    "future": "I can't predict what will happen: I only know what has happened so far. Try one of these:",
    "outside": ("The match tracking can't tell that: it sees where the players and the ball are, not "
                "names, money, the crowd or the weather. Try one of these:"),
}
# A message that continues the last question ("and in the first half?", "what about them?"): it reuses
# that question's tools. Anything else that routes to no tool is not about the match's facts.
FOLLOW_ON = re.compile(
    r"^\s*(?:and|but|so|what about|how about|same|then|now|in the|during|since|over|before|after)\b"
    r"|\b(?:they|them|their|theirs|he|him|his)\b"
    # "it" / "that" only in a question that starts like a follow-up ("why is that?", "who assisted it?"):
    # "will it rain tomorrow?" is no follow-up (#422's probe).
    r"|^\s*(?:why|really|which|who|how)\b(?:.*\b(?:it|that|this|those|these|one|biggest|best|most|worst"
    r"|first|last)\b|\W*$)", re.I)


# Typed on a phone, mid-match (lesson 288): text-speak spelled out, and a misspelt word taken as the
# football word it is closest to. Design: the words the tools' routes and the clubs need, a close match
# only (difflib ratio 0.85), never a word under five letters (a short typo has too many neighbours).


def normalise(text: str, insights=None) -> str:
    """The question with text-speak spelled out and misspellings of the football words and club names
    corrected; a word code already knows (or a name on the team sheet) is kept as typed."""
    import difflib

    known = set(FOOTBALL_WORDS)
    if insights is not None:
        for words in club_words(insights).values():
            known |= {w.lower() for name in words for w in name.split()}
        known |= {w.lower() for n in insights.sheet_names() for w in n.split()}

    known = {w for w in known if len(w) >= 4}
    out = re.sub(r"[A-Za-z0-9']+", lambda m: SHORTHAND.get(m.group(0).lower(), m.group(0)), text)

    def reads(t: str) -> tuple:
        # The team sheet's "who is" reads almost any question: no tool of its own for this.
        return (tuple(n for n in route(t) if n != "lineup"),
                tuple(clubs_named(t, insights)) if insights is not None else ())

    for m in reversed(list(re.finditer(r"[A-Za-z']+", out))):
        low = m.group(0).lower()
        if low in known or len(low) < FIX_LEN:
            continue
        close = difflib.get_close_matches(low, known, n=1, cutoff=FIX_CUTOFF)
        if not close:
            continue
        fixed = out[: m.start()] + close[0] + out[m.end():]
        # Kept only when it gives a question code could not read a tool, or a club, it lacked: an
        # ordinary word ("going", "long") that looks like a football word is the fan's own.
        (tools, clubs), (new_tools, new_clubs) = reads(out), reads(fixed)
        if set(new_tools) > set(tools) or (not clubs and new_clubs):
            out = fixed
    return out


def chat_kind(text: str, insights, history=()) -> str | None:
    """Which kind of small talk a message is ("greeting", "thanks", "about"), "other" for one that is
    not about the match at all (no tool, no club, not a follow-up: gibberish, the weather), or None
    for a question the tools may answer."""
    kind = next((k for k, pattern in SMALL_TALK if pattern.search(text)), None)
    if kind is not None:
        return kind
    for kind, pattern in (("inject", INJECTION), ("future", FUTURE), ("outside", OUTSIDE)):
        if pattern.search(text):
            return kind
    if route(text) or clubs_named(text, insights) or minutes_of(text, 90) is not None:
        return None
    # A player or a position ("How much has the left back done?") is about the match, asked with "who"
    # or not.
    lowered = text.lower()
    if any(re.search(rf"\b(?:{words})", lowered) for _, words in ROLE_WORDS):
        return None
    if hasattr(insights, "sheet_names") and asked_players(text, insights):
        return None
    if asked_players(text, insights):  # "how much has the left back done?": about a player of this match
        return None
    if history and FOLLOW_ON.search(text):
        return None
    return "other"


def chat_answer(question: Question, insights, history=(), suggest: bool = True,
                small_talk_only: bool = False) -> Answer | None:
    """The reply to small talk (chat_kind): fixed words that state no fact, and three questions the
    tools can answer now. None for a question about the match. `small_talk_only` replies only to a
    greeting, thanks or a question about the companion: a message code routes to no tool ("other")
    may still be one the model's planner can place ("how many passes?"), and is its to try first."""
    kind = chat_kind(question.text, insights, history)
    # Out of scope ("will it rain?") is the planner's to try too; an injection or a prediction never is.
    if kind is None or (small_talk_only and kind in ("other", "outside")):
        return None
    t = 60.0 * _minute_in(question.t, insights)
    asked = [*(h["question"] for h in history), question.text]
    ups = follow_ups([], [], insights, asked, t) if suggest else ()
    return Answer("unanswerable", CHAT_REPLIES[kind], None, None, None, (), None, None, follow_ups=ups)


def first_object(reply: str) -> object:
    """The first JSON object in a model's reply, and nothing after it. The published Companion
    answers a plan with the plan and then goes on to write an "answer" step of its own, with facts
    it made up (lesson 238): only the plan is read, so nothing it invented reaches the tools."""
    return json.JSONDecoder().raw_decode(reply[reply.index("{") :])[0]


def _calls(plan: object, insights, minute: int) -> list[dict]:
    """The model's tool calls, kept only when well formed: a known tool, a club of this match or
    none, minutes within the match so far. A call with an unknown tool is dropped; an unknown club
    becomes both clubs, and a malformed window the default one, never another club or minute. Minute
    0 is read as minute 1: "from minute 0" means from kick-off, and football's first minute is 1
    (the instructions never say so, and without this a first-half question got minutes 31 to 45:
    lesson 284)."""
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
        if lo == 0 and not isinstance(lo, bool):
            lo = 1
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


INTENT_ROWS = ("score", "scorers", "winning", "on_top", "momentum", "possession", "passes", "completion",
               "shots", "on_target", "territory", "corners", "out_of_play", "best", "fastest", "distance",
               "why_goal", "key_moments", "unmeasured")


def _intent_menu() -> list[dict]:
    from ninety.agents.ask_intents import model_menu

    return [r for r in model_menu() if r["id"] in INTENT_ROWS]


def plan_prompt(question: Question, insights, history=()) -> str:
    return json.dumps(
        {
            "step": "plan",
            "question": question.text,
            "history": _history(history),
            "clubs": list(insights.fixture.clubs.values()),
            "minute": _minute_in(question.t, insights),
            "tools": TOOL_HELP,
            # The intent table's rows: a plan may name one ({"intent": id}) instead of tools, and code
            # answers from it (ninety/agents/ask_intents.py).
            "intents": _intent_menu(),
        },
        separators=(",", ":"),
    )


def answer_prompt(question: Question, facts: list[dict], history=(), insights=None) -> str:
    """The answer step's message. Each fact carries `say_as`, code's own sentences for it that the
    fact-checker passes, for the model to word its answer from rather than paraphrase."""
    known = {f["id"]: f for f in facts}
    return json.dumps(
        {
            "step": "answer",
            "question": question.text,
            "history": _history(history),
            "facts": [{**_for_prompt(f), "say_as": _say_as(f, known, insights)} for f in facts],
        },
        separators=(",", ":"),
    )


NOT_CHOSEN = "not one of the checked sentences of the facts it cites"


def _say_as(fact: dict, known: dict, insights) -> list[str]:
    if insights is None:
        return []
    try:
        texts = code_texts({**fact, "clubs": fact.get("clubs") or insights.fixture.clubs})
    except (KeyError, TypeError, ValueError, StopIteration):  # a fact code has no sentence for
        return []
    return [t for t in texts if _verify(Claim(t, [fact["id"]]), known, insights).ok]


# When a question names a stretch of the match ("in the first half", "the last ten minutes"), the
# minutes code looks at; None when it names none. Halves are Law 7's 45 minutes.
WORD_MINUTES = {"five": 5, "ten": 10, "fifteen": 15, "twenty": 20, "thirty": 30}
SECOND_HALF = re.compile(r"\b(?:second half|since the break|after the break|since half[- ]?time"
                         r"|after half[- ]?time)\b", re.I)


def minutes_of(text: str, minute: int) -> tuple[int, int] | None:
    t = text.lower()
    if re.search(r"\bfirst half\b", t):
        return 1, min(45, minute)
    if re.search(r"\bsecond half\b", t):
        return (46, minute) if minute >= 46 else None
    if SECOND_HALF.search(t):
        return (46, minute) if minute >= 46 else None
    m = re.search(r"\blast (\d+|five|ten|fifteen|twenty|thirty) minutes?\b", t)
    if m:
        n = int(m.group(1)) if m.group(1).isdigit() else WORD_MINUTES[m.group(1)]
        return max(1, minute - n + 1), minute
    if re.search(r"\b(?:last|past) half(?: an)? hour\b", t):
        return max(1, minute - 29), minute
    # "Since the half hour" (in the half hour, since the half-hour mark): from 30:00, football's minute 31.
    if re.search(r"\b(?:since|in) the half[- ]hour\b|\bsince half an hour\b", t):
        return (31, minute) if minute >= 31 else None
    m = re.search(r"\b(?:first|opening) (\d+|five|ten|fifteen|twenty|thirty) minutes?\b", t)
    if m:
        n = int(m.group(1)) if m.group(1).isdigit() else WORD_MINUTES[m.group(1)]
        return 1, max(1, min(n, minute))
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
    if t is not None and t_to is not None and t_to > t:
        # A window's last minute is its bin's end; the answer is about what was seen by now.
        t_to = max(float(t), t_from or 0.0)
    # Never the score's counts (option B): an answer's number is from any other fact.
    lead = next((f for f in cited if f.get("value") is not None and f.get("unit")
                 and f.get("metric") not in ("score", "scorebug")), None)
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


def club_words(insights) -> dict[str, set[str]]:
    """Each club's names a fan may use: its full and short name, its code ("LIS"), and each word of its
    full name the other club's does not share ("Esportes")."""
    fx = insights.fixture
    full = {team: fx.clubs[team] for team in ("home", "away")}
    words = {team: {w for w in full[team].split() if len(w) >= 4} for team in full}
    out = {}
    for team, code in (("home", fx.home_code), ("away", fx.away_code)):
        other = words["away" if team == "home" else "home"]
        out[full[team]] = {full[team], short_name(code), code, *(words[team] - other)}
    return out


def clubs_named(text: str, insights) -> list[str]:
    """The clubs a question names, by any name a fan uses for them ("Lisbon's left-back", "LIS",
    "Esportes")."""
    return [club for club, names in club_words(insights).items()
            if any(re.search(rf"\b{re.escape(n)}\b", text, re.I) for n in names)]


# A pass that goes through a side, said of that side: "broke Lisbon's lines", "cut through Lisbon",
# "past Lisbon's midfield". There the named club is the one the pass beat; its passer is the other
# club's (lesson 283). "Which Lisbon pass broke the lines?" names the passer's club, and is not this.
BEATEN_AFTER = (r"\b(?:through|past|beyond|behind|around|into|split\w*|broke|break\w*|bypass\w*|beat\w*"
                r"|cut\w*(?: (?:through|open))?|open\w* up|unlock\w*|penetrat\w*)\s+(?:the\s+)?(?:{name})\b")
BEATEN_BEFORE = (r"\b(?:{name})(?:'s?|s')?\s+(?:lines?|defen[cs]e|defenders?|back (?:line|four|three|five)"
                 r"|midfield|block|press|shape|rearguard)\b")


def beaten_club(text: str, insights) -> str | None:
    """The club a line-breaking pass beat, when the question names one that way ("Which pass broke
    Lisbon's lines?"); else None (no club, two, or the named club is the passer's)."""
    named = clubs_named(text, insights)
    if len(named) != 1:
        return None
    alts = "|".join(re.escape(n) for n in sorted(club_words(insights)[named[0]], key=len, reverse=True))
    beaten = any(re.search(p.format(name=alts), text, re.I) for p in (BEATEN_AFTER, BEATEN_BEFORE))
    return named[0] if beaten else None


def _short(insights, club: str | None) -> str | None:

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
    return f"{v} {_singular(unit) if v == '1' else unit}"


def _singular(unit: str) -> str:
    """"crosses" -> "cross", "passes" -> "pass", "shots" -> "shot"."""
    if unit.endswith(("sses", "shes", "ches", "xes")):
        return unit[:-2]
    return unit[:-1] if unit.endswith("s") else unit


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
    # "Who's winning?" asks the score; "who is winning the battle in midfield?" does not.
    winning = re.search(r"\b(?:winning|ahead|in front|leading)\s*\??\s*$", question, re.I)
    bug = next((f for f in cited if f.get("metric") == "scorebug" and f.get("confident")), None)
    routed = route(question)
    # A score question ("who scored?" too) is headed by the scorebug's reading, never by one scorer.
    asks_score = bool(routed) and routed[0] == "score"
    top = next((f for f in cited if f.get("metric") == "on_top"), None)
    if routed and routed[0] == "on_top" and top is None and not any(
        f.get("metric") == "final_third_share" for f in cited
    ):
        return "Not known yet"  # too little footage to compare (ON_TOP_UNKNOWN)
    if routed and routed[0] == "on_top" and top is not None:
        # The comparison's verdict, never one club's number (Kian's preview, Oct 27).
        if top.get("team") is None:
            return "Too close to call"
        return short_name(insights.fixture.home_code if top["team"] == "home" else insights.fixture.away_code)
    if routed and routed[0] == "possession" and not any(f.get("metric") == "possession_share" for f in cited):
        return "Not known yet"  # the share is unknown (POSSESSION_UNKNOWN): no figure heads it
    if bug is not None and (kind != "who" or winning or asks_score):  # the scorebug's reading
        fx = insights.fixture
        return f"{short_name(fx.home_code)} {bug['home']}, {short_name(fx.away_code)} {bug['away']}"
    if any(f.get("metric") == "score" for f in cited) and (kind != "who" or winning):  # never a scoreline
        spotted = any(f.get("kind") == "goal" for f in cited)
        return "Goals spotted by vision" if spotted else "See the scorebug"
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


def _of(club: str) -> str:
    """A club's possessive as a fan writes it: "Lisbon Esportes'", "London Athletic's"."""
    return f"{club}'" if club.endswith("s") else f"{club}'s"


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


# What code says for a score question (Kian, Oct 26, option B): no scoreline from vision, which
# finds some goals and misses others; the goals it spotted follow, one sentence each.
SCORE_POINTER = "The broadcast's scorebug shows the score; vision does not keep one."
# Design (the Coordinator, Oct 26): a share (of passes by channel, of possession) is said only over at
# least this many passes; fewer is too early to say anything, and the answer says so.
MIN_SHARE_PASSES = 15
TOO_EARLY = "It's too early to say: the match has barely started."
# Fixed text, stating no number but the stretch's minutes: the two clubs' territory ranges overlap, so
# neither leads.
ON_TOP_LEVEL = ("Neither side has clearly been on top {span}: the ball was in each side's attacking third "
                "about as often in the footage we've seen.")
# Fixed text, stating no fact: under a minute of the ball seen in the stretch (on_top's floor).
ON_TOP_UNKNOWN = ("It's too early to say who has been on top: under a minute of the ball has been seen "
                  "in those minutes.")
SHOTS_SIDE_UNKNOWN = "Vision couldn't tell surely which side took them, so it can't say who has had more."


def _sample(fact: dict) -> int | None:
    """How many passes a share fact rests on (its `passes`, or the count it carries in `also`)."""
    if isinstance(fact.get("passes"), int):
        return fact["passes"]
    return next((int(v) for v, unit, *_ in fact.get("also") or () if unit == "passes"), None)
# Fixed text, stating no fact: possession is unknown before a minute of either side on the ball was seen.
POSSESSION_UNKNOWN = ("Possession can't be split between the clubs for those minutes: it is measured "
                      "from kick-off and from each half's start, once a minute of either side on the ball "
                      "has been seen.")


def code_texts(fact: dict) -> list[str]:
    """What code says about one fact or summary, in a fan's words. Empty when there is nothing it
    may say (an unsure fact, or a summary with nothing in it)."""
    if fact.get("metric") == "score":  # no scoreline from vision, ever: the scorebug shows it
        return [SCORE_POINTER]
    if fact.get("metric") == "scorebug":  # the scorebug's reading, once measured (SCOREBUG_MEASURED)
        if not fact.get("confident"):
            return []
        cl = fact["clubs"]
        # The score first, as a fan asks it; where it comes from after it (the broadcast's graphic).
        return [f"{cl['home']} {_plural(fact['home'], 'goal')}, "
                f"{cl['away']} {_plural(fact['away'], 'goal')}, read from the broadcast's scorebug."]
    if not fact.get("confident", False):
        return []
    if fact.get("unit") == "%" and _sample(fact) is not None and _sample(fact) < MIN_SHARE_PASSES:
        return []  # a share of a handful of passes says nothing yet (code_match_answer: too early)
    club, kind, metric = fact.get("club"), fact.get("kind"), fact.get("metric")
    span = (
        f"from minute {fact['minute_from']} to minute {fact['minute_to']}"
        if fact.get("minute_from") and fact.get("minute_to") != fact["minute_from"]
        else f"in minute {fact.get('minute_from') or fact.get('minute')}"  # never "from minute 1 to minute 1"
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
        return [f"{_of(club)} completed passes took out {fact['value']} opponents in all {span}."]
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
            f"{club} stretched the play {fact['value']} m wide {span}, against {_of(other_club)} "
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
            f"{_of(club)} goalkeeper went long {_plural(fact['value'], 'time')} and short "
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
        from ninety.intel.ball_share import ERROR_POINTS

        # Coverage-honest and with its window: what was seen, over the minutes measured.
        return [f"{club} have had {fact['value']}% of the ball in the footage we've seen {span}, "
                f"by time on the ball, give or take {ERROR_POINTS} points."]
    if metric == "final_third_share":
        lo, hi = fact["lo"], fact["hi"]
        from ninety.intel.ball_share import share_words

        # Its bounds (the ball near a line counts for either side), and the plain fraction they make.
        share, words = (f"{lo}%" if lo == hi else f"{lo}–{hi}%"), share_words(lo, hi)
        how = f"{words} of the time ({share})" if words else f"{share} of the time"
        return [f"{club} have had the ball in their attacking third {how} in the footage we've seen {span}."]
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
        # A scorer is said only by name or role: "a London Athletic player scored for London Athletic"
        # says the club twice and no one (Kian, Oct 27).
        clubs_said = {club, *(fact.get("clubs") or {}).values()} - {None}
        who = fact.get("scorer_is") or ""
        # Never a label with a club in it: the club twice, or worse, a Lisbon label on a London goal.
        scorer = who if club and who and not any(c in who for c in clubs_said) else None
        if scorer and fact.get("assister_is"):
            out.append(f"{scorer} scored for {club} in minute {m}, from {fact['assister_is']}'s pass.")
        if scorer:
            out.append(f"{scorer} scored for {club} in minute {m}.")
        return [*out, f"{club} scored in minute {m}."]
    if fact.get("kind") == "set_pieces":
        from ninety.intel.set_pieces import WORDS

        n = fact["value"]
        noun = WORDS[fact["restart"]][0 if n == 1 else 1]
        if fact.get("team") is None:
            return [f"There {'was' if n == 1 else 'were'} {n} {noun} {span}."]
        return [f"{club} had {n} {noun} {span}."]
    if metric == "saves":
        return [f"{club} made {_plural(fact['value'], 'save')} {span}."]
    if metric == "opponents_bypassed_by_player":
        if fact.get("rank") != 1 or not fact.get("leads"):
            return []
        # His name or role past the gate, else his club: tracking follows him but cannot vouch for
        # who he is, so he is "a Lisbon Esportes player", never a track id or a guessed name.
        who = fact.get("player_is") or (f"A {club} player" if club else "A player")
        return [
            f"{who} has taken the most opponents out of the game with passes {span}: "
            f"{fact['value']} opponents in {_plural(fact['also'][0][0], 'pass')}."
        ]
    if kind == "spell":  # a run vision followed receiver to passer: no side needed
        whose = f"{_of(club)} longest" if club else "The longest"
        return [f"{whose} run of passing was {fact['value']} passes in a row, in minute {fact['minute']}."]
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
            f"{span.capitalize()}, {_of(club)} back line {move} {_num(abs(c))} m, "
            f"to {v} m from their own goal."
        )
    if m == "line_height":
        out.append(f"{span.capitalize()}, {_of(club)} back line was {v} m from their own goal.")
    if m == "width":
        out.append(f"{span.capitalize()}, {_of(club)} width was {v} m.")
    return out


# A goal's story asked for, and which goal (lesson 288): "the 2nd goal", "Lisbon's third", "the
# equaliser", "the winner"; the latest when none is named.
GOAL_STORY = re.compile(r"\b(?:how did|why did|explain|what led|led to|set (?:it )?up|build-?up|describe"
                        r"|tell me about|assist\w*|happen\w*|come about|talk me through|walk me through)\b",
                        re.I)
ORDINALS = {"first": 0, "opening": 0, "1st": 0, "second": 1, "2nd": 1, "third": 2, "3rd": 2, "fourth": 3,
            "4th": 3, "fifth": 4, "5th": 4, "last": -1, "latest": -1, "most recent": -1}
GOAL_WORD = r"(?:goal|strike|finish|equali[sz]er|winner)"


def goals_so_far(insights, minute: int, club: str | None = None) -> list[dict]:
    """The goals up to `minute` whose side code can say, in order (a club's own, when named)."""
    rows = insights.score(1, minute, club)["facts"]
    return sorted((g for g in rows if g.get("kind") == "goal" and g.get("club")
                   and (club is None or g["club"] == club)), key=lambda g: g["t"])


def goal_asked(text: str, insights, minute: int, club: str | None) -> dict | str | None:
    """The goal a question names: its fact, "none" when it names one the match has not had yet, or None
    when it names no particular goal."""
    t = text.lower()
    goals = goals_so_far(insights, minute, club)
    if re.search(r"\bequali[sz]\w*", t):
        score, picked = {}, None
        for g in goals_so_far(insights, minute):
            score[g["club"]] = score.get(g["club"], 0) + 1
            if len(set(score.values())) == 1 and len(score) == 2:
                picked = g
        return picked or "none"
    if re.search(r"\bwinner\b|\bwinning goal\b", t):
        everyone = goals_so_far(insights, minute)
        n = {}
        for g in everyone:
            n[g["club"]] = n.get(g["club"], 0) + 1
        if len(n) == 0:
            return "none"
        lead = max(n, key=n.get)
        if list(n.values()).count(n[lead]) > 1 or (club is not None and lead != club):
            return "none"
        other = sum(v for c, v in n.items() if c != lead)
        return [g for g in everyone if g["club"] == lead][other] if other < n[lead] else "none"
    m = re.search(rf"\b(first|opening|1st|second|2nd|third|3rd|fourth|4th|fifth|5th|last|latest|most recent)"
                  rf"\b(?:[\w' ]{{0,20}})?\b{GOAL_WORD}", t) or (
        re.search(rf"\b{GOAL_WORD}\b", t) and re.search(r"\b(first|second|third|fourth|last|latest)\b", t))
    if not m:
        return None
    k = ORDINALS[m.group(1)]
    if not goals:
        return "none"
    return goals[k] if -len(goals) <= k < len(goals) else "none"


def code_calls(question: Question, insights, history=()) -> list[dict]:
    """Code's plan: the routed tools, or a follow-up's ("and in the first half?") the last turn's
    tools; over the stretch the question names, else the last WINDOW_MIN minutes."""
    minute = _minute_in(question.t, insights)
    names = route(question.text)
    if not names and history and chat_kind(question.text, insights, history) is None:
        names = [c["name"] for c in history[-1]["calls"]] if history[-1].get("calls") else []
    lo, hi = minutes_of(question.text, minute) or (max(1, minute - WINDOW_MIN + 1), minute)
    # The club the question is about: named, or "they" / "them" / "their" after a question that named one.
    named = clubs_named(question.text, insights)
    if not named and history and (re.search(r"\b(?:they|them|their|theirs)\b", question.text, re.I)
                                  or (not route(question.text) and FOLLOW_ON.search(question.text))):
        named = clubs_named(history[-1].get("question", ""), insights)
    club = named[0] if len(named) == 1 else None
    stretch = minutes_of(question.text, minute)
    goal = goal_asked(question.text, insights, minute, club)
    prev = history[-1].get("calls", ()) if history else ()
    prev_goal = next((c for c in prev if c["name"] == "goal_build_up"), None)
    if prev_goal is not None and goal is None and re.search(r"\b(?:it|that|the goal|that goal)\b|\bassist",
                                                            question.text, re.I):
        # "Who assisted it?" after a goal's story: that goal, not the score (lesson 288).
        return [dict(prev_goal)]
    if goal is not None or ("goal_build_up" in names and GOAL_STORY.search(question.text)):
        # A goal's story ("how did the 2nd goal happen?"): the goal asked for, its build-up first.
        names = ["goal_build_up", *(n for n in names if n not in ("goal_build_up", "score"))]
        if isinstance(goal, dict):
            return [{"name": "goal_build_up", "club": goal["club"], "minute_from": goal["minute"],
                     "minute_to": goal["minute"]}, *(
                {"name": n, "club": club, "minute_from": lo, "minute_to": hi} for n in names[1:])]
    # The named club is the side acting ("How are Lisbon playing?", "Lisbon's best player"), except for
    # a pass that cut through a side ("which pass cut through Lisbon?"): there both clubs are read and
    # the fact-check binds the sentence to the right one.
    acted_on = {"line_breaks"}
    # A count or a comparison ("who has had more shots?", "how many corners?") asks about the match so
    # far, unless a stretch is named; "how are they playing?" asks about now.
    so_far = {"possession", "shots", "set_pieces", "players"}
    return [{"name": n, "club": None if n in acted_on else club,
             "minute_from": 1 if n in so_far and stretch is None else lo, "minute_to": hi}
            for n in names]


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
# asks for that only by asking where: a side or a third alone ("who is on the left?", "who is out
# of position?") is not a question of where a player was (merge-queue review of #323).
ASKS_ZONE = r"\b(?:where|whereabouts|zones?|heat ?maps?|positioned)\b"


def asked_running(text: str) -> str | None:
    """The running figure a question asks for, the most specific one, or None."""
    return next((m for m, (words, _) in ASKS_RUNNING.items() if re.search(words, text, re.I)), None)


def asked_players(text: str, insights) -> set[str] | None:
    """The players a question names, by a sheet name or a part of one ("Kai") or by a position
    ("the left-back"), as names; None when it names none."""
    said = lambda w: re.search(rf"\b{re.escape(w)}\b", text, re.I)  # noqa: E731
    sheet = insights.sheet_names()
    # A full name the fan gave is that player, whoever shares his first name; a part ("Kai") is
    # matched only when no full name is (merge-queue review of #323).
    names = {n for n in sheet if said(n)} or {
        n for n in sheet if any(said(w) for w in n.split() if len(w) > 2)
    }
    lowered = text.lower()
    roles = {role for role, words in ROLE_WORDS if re.search(rf"\b(?:{words})", lowered)}
    if roles:
        names |= {p["name"] for p in insights.people.values() if p.get("role") in roles and p.get("name")}
        return names
    return names or None


def physical_gate(text: str, calls, facts: list[dict], insights) -> tuple[str | None, list[dict]]:
    """Why a physical question cannot be answered (or None), and the facts in the order to answer
    from. A running figure asked for is held when every fact of it is unsure: the video does not
    yet follow enough of each named player. The zone answers only a question of where, about a
    player it names. A question naming a player hears only about him; one naming none hears the
    highest figure ("who is the fastest?" is the maximum). The fact-check never sees the question,
    so code gates on it here."""
    if not any(c["name"] == "physical" for c in calls):
        return None, facts
    sure = {f.get("metric") for f in facts if f.get("confident")}
    metric = asked_running(text)
    zone = metric is None and re.search(ASKS_ZONE, text, re.I)
    if metric is not None and metric not in sure or metric is None and not zone:
        said = ASKS_RUNNING[metric][1] if metric else "running"
        return (
            f"A player's {said} isn't available yet: the video can't follow enough of each named "
            "player to measure it reliably."
        ), facts
    want = metric or "player_zone"
    wanted = asked_players(text, insights)
    if wanted is None and zone:
        return (
            "Name a player and I can say where he was most often, in the footage the video named him in."
        ), facts
    running = [f for f in facts if f.get("kind") == "running"]
    if wanted is not None:
        running = [f for f in running if f.get("player_is") in wanted]
        named = clubs_named(text, insights)
        if named:
            running = [f for f in running if f.get("club") in named]
        who = {f.get("player_is") for f in running if f.get("metric") == want}
        if not who:
            return "The video hasn't named that player over these minutes, so it can't say.", facts
        if len(who) > 1:  # "Alex", or a position both clubs have: never pick one for the fan
            return (
                f"More than one player fits ({', '.join(sorted(who))}): say which one by his full name."
            ), facts
    rest = [f for f in facts if f.get("kind") != "running"]
    return None, sorted(running, key=lambda f: (f.get("metric") != want, -(f.get("value") or 0))) + rest


# Design (the Coordinator, Oct 26): a count this small, or a stat with no success, says nothing about
# how a side plays, and never answers on its own ("crossed 1 time and found a teammate 0 times").
TINY_COUNT = 5
HOW_PLAYING = re.compile(r"\bhow (?:are|is|have|has|did)\b[^?]*\b(?:play\w*|do(?:ing)?|getting on|look\w*"
                         r"|going"
                         r"|defend\w*|attack\w*)\b", re.I)


TALLIES = frozenset({"crosses"})  # a style tally: what a side did how often (match_insights.style)


def tiny(fact: dict) -> bool:
    """A tally of how a side plays (TALLIES) under TINY_COUNT, or one whose successes are none (crosses
    that found nobody). A moment's own number (opponents a pass took out) is no tally."""
    if fact.get("kind") not in TALLIES or not isinstance(fact.get("value"), (int, float)):
        return False
    return fact["value"] < TINY_COUNT or fact.get("completed") == 0


def _overview(question: Question, calls: list[dict], insights, known: dict, history, suggest):
    """The answer to "how are <club> playing?": up to two checked sentences, where the ball was (and
    the route they attack by, when its sample allows), then their most significant moment."""
    asked = HOW_PLAYING.search(question.text) or (
        history and HOW_PLAYING.search(history[-1].get("question", "")) and not route(question.text))
    if not calls or calls[0]["name"] != "style" or not asked:
        return None
    lo, hi = calls[0]["minute_from"], calls[0]["minute_to"]
    club = calls[0].get("club")
    if club is None:  # "how is the game going?": each club's, in turn
        parts = [_overview(question, [{**calls[0], "club": c}, *calls[1:]], insights, known, history, suggest)
                 for c in insights.fixture.clubs.values()]
        parts = [p for p in parts if p is not None]
        if not parts:
            return None
        return replace(parts[0], text=" ".join(p.text for p in parts),
                       evidence=tuple(i for p in parts for i in p.evidence))
    from ninety.agents import insight_bar  # it reads this module's code_texts: imported when asked

    pool = [*insights.territory(lo, hi, club)["summary"], *insights.style(lo, hi, club)["summary"]]
    moments = [(s, f, t) for s, f, t in insight_bar.candidates(insights)
               if f.get("club") == club and f.get("minute", 0) <= hi]
    moments.sort(key=lambda m: (not (lo <= m[1].get("minute", 0) <= hi), -m[0]))  # this stretch first
    said = []
    for f in pool:
        f = {**f, "clubs": insights.fixture.clubs}
        if f.get("club") != club or tiny(f):
            continue
        ok = (t for t in code_texts(f) if _verify(Claim(t, [f["id"]]), {**known, f["id"]: f}, insights).ok)
        text = next(ok, None)
        if text is not None:
            said.append((text, f))
    if moments:
        _, f, text = moments[0]
        lead = text[0].lower() + text[1:] if text.split()[0] in ("In", "From") else text
        whose = f"{club}'" if club.endswith("s") else f"{club}'s"
        said.append((f"{whose} biggest moment: {lead}", f))
    if not said:
        return None
    return _match_answer(" ".join(t for t, _ in said[:3]), [f for _, f in said[:3]], insights, calls,
                         asked=[*(h["question"] for h in history), question.text], t=question.t,
                         suggest=suggest)


def read_question(text: str, insights, t: float, history=()):
    """The question read against the intent table (ninety/agents/ask_intents.py): one intent and
    its slots. The old tool routing only says whether it is a tactics question; a player or a
    position named, or small talk, is told to the table so it never takes a statistic's row."""
    from ninety.agents import ask_intents

    fx = insights.fixture
    small = next((k for k, pattern in SMALL_TALK if pattern.search(text)), None)
    tactics = any(n in ask_intents.TACTICS_TOOLS for n in route(text))
    lowered = text.lower()
    player = bool(asked_role(text)) or any(re.search(rf"\b(?:{w})", lowered) for _, w in ROLE_WORDS)
    if not player and hasattr(insights, "sheet_names"):
        player = bool(asked_players(text, insights))
    read = ask_intents.classify(
        text, clubs=dict(fx.clubs), codes={"home": fx.home_code, "away": fx.away_code}, t=float(t),
        words=set(insights.sheet_names()) if hasattr(insights, "sheet_names") else set(),
        tactics=tactics, player=player, small_talk=small)
    return replace(read, player=sheet_name_in(read.text, insights))


def sheet_name_in(text: str, insights) -> str | None:
    """The team-sheet name a question names: the full name, or a surname only one player has."""
    names = insights.sheet_names() if hasattr(insights, "sheet_names") else []
    full = [n for n in names if re.search(rf"\b{re.escape(n)}\b", text, re.I)]
    if full:
        return full[0]
    last = [n for n in names
            if len(n.split()[-1]) >= 4 and re.search(rf"\b{re.escape(n.split()[-1])}\b", text, re.I)]
    return last[0] if len(last) == 1 else None


def plausible_rows(read) -> set[str]:
    """The table rows a model may pick for a question: those code's patterns give a score, and the row
    code read it as (on top and momentum are one comparison over two windows)."""
    rows = {iid for iid, n in read.scores if n > 0} | {read.intent}
    if rows & {"on_top", "momentum"}:
        rows |= {"on_top", "momentum"}
    return rows & set(INTENT_ROWS)


CHIP_CANT = re.compile(r"\b(?:can't|cannot|not known|unknown|not tracked|too early|haven't scored"
                       r"|no goals? yet)\b", re.I)


def chips(insights, t: float, club: str | None = None) -> list[dict]:
    """The phone's chips at match second t: the intent table's questions (ninety/agents/ask_chips.json)
    with the fan's club filled in, each kept only when code answers it now from a checked fact."""
    from ninety.agents.ask_intents import chips_table

    club = club or insights.fixture.clubs["home"]
    out = []
    for c in chips_table():
        q = c["q"].format(club=club)
        a, _ = code_match_answer(Question("chips", None, q, float(t)), insights, suggest=False)
        # A checked fact, never only "no goal yet", and never a chip whose answer would be a "can't"
        # (Kian, Oct 27: no chip is offered that the Ask cannot answer outright).
        if a.status == "verified" and a.evidence and not CHIP_CANT.search(a.text):
            out.append({**c, "q": q})
    return out


def table_answer(question: Question, insights, history=(), suggest: bool = True):
    """Code's answer from the question's row of the intent table, or None when the row is left to the
    tools' routing (tactics, one player, small talk, a follow-up of the last question)."""
    from ninety.agents import ask_answers

    if any(pattern.search(question.text) for _, pattern in SMALL_TALK):
        return None
    read = read_question(question.text, insights, question.t, history)
    if read.intent == "small_talk" and read.topic in ("inject", "future"):
        t = 60.0 * _minute_in(question.t, insights)
        asked = [*(h["question"] for h in history), question.text]
        ups = follow_ups([], [], insights, asked, t) if suggest else ()
        return Answer("unanswerable", ask_answers.NOT_MATCH[read.topic], None, None, None, (), None, None,
                      follow_ups=ups), []
    if read.intent == "how_known":
        # "How do you know?": how the last answer's figures were made (its How-we-know), fixed text with
        # only the rates docs/EVALUATION.md measures; with no last answer, how every answer is made.
        last = history[-1].get("question", "") if history else ""
        prev = read_question(last, insights, question.t).intent if last else None
        how = ask_answers.HOW.get(prev, ask_answers.HOW_DEFAULT)
        return Answer("verified", how, None, None, None, (), None, None, spoken=how, how=how), []
    if history and FOLLOW_ON.search(question.text) and read.intent in ("small_talk", "tactics"):
        return None
    if history and FOLLOW_ON.search(question.text):
        # A follow-up ("who assisted it?", "and Lisbon's?") keeps the last question's club and goal.
        from dataclasses import replace as _with

        prev = read_question(history[-1].get("question", ""), insights, question.t)
        pronoun = re.search(r"\b(?:they|them|their|theirs|it|that|he|him|his)\b", question.text, re.I)
        if not read.clubs and pronoun:
            read = _with(read, clubs=prev.clubs)
        if read.goal is None and prev.intent == "why_goal":
            read = _with(read, goal=prev.goal)
    got = ask_answers.build(question, insights, read)
    if got is None:
        return None
    answer, calls = got
    if suggest:
        asked = [*(h["question"] for h in history), question.text]
        answer = replace(answer, follow_ups=follow_ups([], [], insights, asked, question.t))
    return answer, calls


SUPPORT_MAX = 1  # design: one more checked sentence after the answer; more reads as a list


def supporting(
    lead: dict, facts: list[dict], known: dict, insights, said: set[str]
) -> list[tuple[str, dict]]:
    """The next most telling fact after the one that answers, for depth (lesson 288): the same club's
    (or the match's, for a fact of no club), another measure, never a tiny count, never a sentence
    already said."""
    out = []
    for f in facts:
        if len(out) >= SUPPORT_MAX:
            break
        if lead.get("kind") in ("sheet", "law", "offside"):
            break  # who plays a position, or a Law, is the whole answer
        if f is lead or f.get("club") != lead.get("club") or tiny(f) or f.get("kind") in ("sheet", "law",
                                                                                         "score"):
            continue
        if f.get("metric") == lead.get("metric") or f.get("kind") == "goal":
            continue
        text = _checked(f, known, insights)
        if text is not None and text not in said:
            out.append((text, f))
    return out


def _checked(f: dict, known: dict, insights, lead: str = "") -> str | None:
    """The first of code's sentences for a fact that the fact-check passes, after `lead` (fixed words
    that state no fact: "Just before it, "), or None."""
    f.setdefault("clubs", insights.fixture.clubs)
    for text in code_texts(f):
        if lead:
            text = lead + (text[0].lower() + text[1:] if text.split()[0] in ("In", "From") else text)
        if _verify(Claim(text, [f["id"]]), {**known, f["id"]: f}, insights).ok:
            return text
    return None


SHOT_BEFORE_S = 10.0  # design: the shot a goal came from is the goal's own moment, seconds before it


def goal_story(goal: dict, insights, known: dict) -> list[tuple[str, dict]]:
    """A goal told as it happened (lesson 288): who scored (and from whose pass, when named), the shot
    it came from, and the strongest thing in the build-up, each its own checked sentence."""
    said = []
    text = _checked(goal, known, insights)
    if text is None:
        return said
    said.append((text, goal))
    m, club = goal["minute"], goal["club"]
    # The shot just before the goal: the scorer's club's, or one whose side vision could not tell
    # (said without a club), never the other club's.
    shots = [f for f in insights.shots(max(1, m - 1), m, None)["facts"]
             if f.get("t") is not None and goal["t"] - SHOT_BEFORE_S <= f["t"] <= goal["t"] + 1
             and f.get("club") in (None, club)]
    shot = max(shots, key=lambda f: f["t"], default=None)
    if shot is not None:
        text = _checked(shot, known, insights)
        if text is not None:
            said.append((text, shot))
    for f in insights.goal_build_up(m, club)["facts"]:
        if f is goal or f.get("kind") == "goal" or f.get("team") != goal["team"] or tiny(f):
            continue
        text = _checked(f, known, insights, "Just before it, ")
        if text is not None:
            said.append((text, f))
            break
    return said


def _ordinal(n: int) -> str:
    return {1: "one goal", 2: "two goals", 3: "three goals", 4: "four goals"}.get(n, f"{n} goals")


WHY_RESULT = re.compile(r"^\s*(?:so )?why\b.*\b(?:winning(?! (?:the|it|possession))|(?:losing|lose|lost)"
                        r"(?! (?:the ball|it|possession|out|the duel|their))|concede\w*|conced\w*"
                        r"|can'?t score"
                        r"|cannot score|not scoring"
                        r"|struggl\w*|behind|ahead|in front|on top|better|worse|leading|level)\b", re.I)


def why_result(question: Question, insights, minute: int, known: dict) -> list[tuple[str, dict]] | None:
    """ "Why are Lisbon winning?", "why did London concede?": the score, then the goals that made it,
    each told with what led to it. None for any other question."""
    if not WHY_RESULT.search(question.text):
        return None
    named = clubs_named(question.text, insights)
    goals = goals_so_far(insights, minute)
    said = []
    bug = next((f for f in insights.score(1, minute, None)["summary"] if f.get("metric") == "scorebug"
                and f.get("t", 0) <= 60.0 * minute), None)
    if bug is not None:
        text = _checked(bug, known, insights)
        if text is not None:
            said.append((text, bug))
    conceding = re.search(r"\b(?:losing|lose|lost|concede\w*|conced\w*|struggl\w*|behind|worse|can'?t score"
                          r"|cannot score)\b", question.text, re.I)
    club = named[0] if len(named) == 1 else None
    if club is not None and bug is not None:
        # A premise the scorebug contradicts is said first ("why are London losing?" at 1-1): fixed words
        # from its reading, the sentence before them the reading itself.
        home = club == insights.fixture.clubs["home"]
        own, other = (bug["home"], bug["away"]) if home else (bug["away"], bug["home"])
        cant = re.search(r"\bcan'?t score|cannot score|not scoring\b", question.text, re.I)
        losing = conceding and not cant and not re.search(r"\bconced", question.text, re.I)
        winning = re.search(r"\b(?:winning|ahead|in front|leading|on top)\b", question.text, re.I)
        if cant and own > 0:
            said.append((f"{club} have scored, though.", bug))
        elif losing and own >= other:
            state = "it is level" if own == other else "they are ahead"
            said.append((f"{club} aren't behind: {state}.", bug))
        elif winning and own <= other:
            state = "it is level" if own == other else "they are behind"
            said.append((f"{club} aren't ahead: {state}.", bug))
    if not goals:
        return said or None
    if club is not None and conceding:
        wanted = [g for g in goals if g["club"] != club]
    elif club is not None:
        wanted = [g for g in goals if g["club"] == club]
    else:
        wanted = goals
    for g in wanted[-2:]:
        said.extend(goal_story(g, insights, known)[:2])
    return said or None


CODE_FIRST_TOOLS = ("score", "goal_build_up", "key_moments")


def code_first(question: Question, insights, history=()) -> bool:
    """A question code answers better than one chosen sentence: the score, a goal's story, a recap,
    or why a club is winning or losing (lesson 288)."""
    if WHY_RESULT.search(question.text):
        return True
    calls = code_calls(question, insights, history)
    return bool(calls) and calls[0]["name"] in CODE_FIRST_TOOLS


def code_match_answer(
    question: Question, insights, calls: list[dict] | None = None, history=(), suggest: bool = True
) -> tuple[Answer, list[dict]]:
    """Code's answer: the routed tools' facts, the first one code can say and the check passes. A
    goal is told with the strongest thing that led to it."""
    question = replace(question, text=normalise(question.text, insights)[:200])
    if calls is None and not WHY_RESULT.search(question.text):
        tabled = table_answer(question, insights, history, suggest)
        if tabled is not None:  # a row of the intent table: code's answer from that row (lesson 297)
            return tabled
    if calls is None:
        chat = chat_answer(question, insights, history, suggest)
        if chat is not None:  # small talk never gets a statistic (lesson 287)
            return chat, []
    minute = _minute_in(question.t, insights)
    asked_all = [*(h["question"] for h in history), question.text]
    if SECOND_HALF.search(question.text) and minute < 46:
        return Answer("unanswerable", f"The second half hasn't started yet: it's minute {minute}.", None,
                      None, None, (), 0.0, float(question.t)), []
    why = why_result(question, insights, minute, {})
    if why:
        return _match_answer(" ".join(t for t, _ in why), [f for _, f in why], insights, calls or [],
                             asked=asked_all, t=question.t, suggest=suggest), calls or []
    calls = calls if calls is not None else code_calls(question, insights, history)
    facts = run_tools(insights, calls)
    known = {f["id"]: f for f in facts}
    clubs = insights.fixture.clubs
    before = set(re.split(r"(?<=[.!?])\s+", history[-1].get("answer", ""))) if history else set()
    if any(c["name"] == "line_breaks" for c in calls) and re.search(
            r"\b(?:biggest|best|most|largest|furthest)\b", question.text, re.I):
        facts = sorted(facts, key=lambda f: -(f.get("value") or 0) if f.get("kind") == "line_break" else 1)
    for f in facts:
        f.setdefault("clubs", clubs)
    named = clubs_named(question.text, insights)
    if not named and history and not route(question.text) and FOLLOW_ON.search(question.text):
        named = clubs_named(history[-1].get("question", ""), insights)  # "which was the biggest?"
    beaten = beaten_club(question.text, insights) if any(c["name"] == "line_breaks" for c in calls) else None
    if beaten is not None:
        # "Which pass broke Lisbon's lines?" asks for a pass by the other club: its passes first, and no
        # pass of Lisbon's (nor one whose side is not known) is said in its answer (lesson 283).
        passer = next(c for c in clubs.values() if c != beaten)
        facts = [f for f in facts if not str(f.get("metric", "")).startswith("opponents_bypassed")
                 or f.get("club") == passer]
        named = [passer]
    elif len(named) == 1 and any(c["name"] == "line_breaks" for c in calls):
        # "Which Lisbon passes broke the lines?": Lisbon's passes only.
        facts = [f for f in facts if not str(f.get("metric", "")).startswith("opponents_bypassed")
                 or f.get("club") == named[0]]
    if len(named) == 1:
        # A question about one club hears about that club first (its facts before the other's); the
        # fact-check still binds the sentence to the right side.
        facts = sorted(facts, key=lambda f: f.get("club") not in (None, named[0]))
        # A player of that club (the players tool, ranked within it: code_calls) is never answered with
        # another club's player: "Lisbon's most dangerous player" is never a London player.
        facts = [f for f in facts if f.get("kind") != "players" or f.get("club") == named[0]]
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
    facts = sorted(facts, key=tiny)  # a tiny count never leads while there is anything else to say
    why, facts = physical_gate(question.text, calls, facts, insights)
    if why is not None:  # a figure asked for that is held: say so, never answer something else
        return Answer("unanswerable", why, None, None, None, (), 0.0, float(question.t)), calls
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
    # "What's the score?" (Kian, Oct 26, option B): never a scoreline. The scorebug shows it; then each
    # goal vision spotted, its own checked sentence. The pointer is fixed text and states no fact.
    score = next((f for f in facts if f.get("metric") == "score"), None)
    if score is not None and calls and calls[0]["name"] == "score":
        said, unplaced = [], []
        for g in (f for f in facts if f.get("kind") == "goal"):
            text = next((t for t in code_texts(g) if _verify(Claim(t, [g["id"]]), known, insights).ok), None)
            if text is not None:
                said.append((text, g))
            elif (g.get("event_confidence") is None or g["event_confidence"] >= MIN_CONFIDENCE):
                unplaced.append(g)  # a confident goal whose side is in doubt: its minute, no club
        bug = next((f for f in facts if f.get("metric") == "scorebug"), None)
        shown = next((t for t in (code_texts(bug) if bug else [])
                      if _verify(Claim(t, [bug["id"]]), known, insights).ok), None)
        lead = ""
        if shown and bug is not None:
            h, a = bug["home"], bug["away"]
            # Who leads, in words, after the scorebug's own sentence (which the answer leads with).
            lead = (" It's level." if h == a else
                    f" {clubs['home'] if h > a else clubs['away']} are ahead.")
            if re.search(r"\bfinal\b|\bfull[- ]time\b", question.text, re.I) and minute < FULL_TIME_MIN:
                lead += " It isn't over yet."
        leads = re.search(r"\b(?:winning|ahead|level|draw|drawing|lead\w*|in front|losing|behind)\b",
                          question.text, re.I)
        if leads and not re.search(r"\b(?:who scored|goals?|scor(?:ed|er|ers|ing)|assist\w*)\b",
                                   question.text, re.I):
            said, unplaced = [], []  # "who's winning?" hears the score, not every goal again
        lines = [shown + lead if shown else SCORE_POINTER, *(t for t, _ in said)]
        lines += [f"It spotted a goal in minute {g['minute']} too, without telling whose it was."
                  for g in unplaced]
        if not said and not unplaced:  # a goal below the detection gate is no goal to vouch for
            lines.append("It has spotted no goal it can vouch for so far.")
        return _match_answer(
            " ".join(lines),
            [*([bug] if shown else []), score, *(g for _, g in said), *unplaced],
            insights,
            calls,
            asked=[*(h["question"] for h in history), question.text],
            t=question.t,
            suggest=suggest,
        ), calls
    # "Who's been on top since the half hour?": both clubs compared over the stretch asked, each
    # club's territory its own checked sentence; the headline is the comparison's verdict.
    if calls and calls[0]["name"] == "on_top":
        top = next((f for f in facts if f.get("metric") == "on_top"), None)
        terr = [f for f in facts if f.get("metric") == "final_third_share"]
        if top is None or not top.get("confident"):
            return _match_answer(ON_TOP_UNKNOWN, [], insights, calls,
                                 asked=[*(h["question"] for h in history), question.text], t=question.t,
                                 suggest=suggest), calls
        if top is not None:
            lead = top.get("team")
            terr.sort(key=lambda f: f.get("team") != (lead or "home"))
        said = []
        for f in terr:
            text = next((t for t in code_texts(f) if _verify(Claim(t, [f["id"]]), known, insights).ok), None)
            if text is not None:
                said.append((text, f))
        if top is not None and len(said) == 2:
            # The verdict leads, the two clubs' territory under it; it names a club only when the
            # club leads (the on_top fact's own side), checked like any sentence.
            span = f"from minute {top['minute_from']} to minute {top['minute_to']}"
            if top.get("team") is None:
                verdict = ON_TOP_LEVEL.format(span=span)
            else:
                verdict = (f"{top['club']} have been on top {span}, going by how often the ball was in their "
                           "attacking third in the footage we've seen.")
                if not _verify(Claim(verdict, [top["id"]]), known, insights).ok:
                    verdict = None
            text = " ".join([*([verdict] if verdict else []), *(t for t, _ in said)])
            return _match_answer(text, [top, *(f for _, f in said)], insights, calls,
                                 asked=[*(h["question"] for h in history), question.text], t=question.t,
                                 suggest=suggest), calls
    # "How are Lisbon playing?": an overview, not the first count to hand. Where the ball was and the
    # main route (when its sample allows), then the club's most significant moment, each checked.
    overview = _overview(question, calls, insights, known, history, suggest)
    if overview is not None:
        return overview, calls
    # Possession: each club's share when it is known; else why it is not, and the longest run of
    # passing, which needs no side told.
    if calls and calls[0]["name"] == "possession":
        share = [f for f in facts if f.get("metric") == "possession_share"]
        if share and not any(f.get("confident") for f in share):
            said = []
            for f in (f for f in facts if f.get("kind") == "spell"):
                ok = (t for t in code_texts(f) if _verify(Claim(t, [f["id"]]), known, insights).ok)
                text = next(ok, None)
                if text is not None:
                    said.append((text, f))
                    break
            # The pointer cites nothing and states no number; the run of passing is its own checked
            # sentence, citing its fact.
            return _match_answer(" ".join([POSSESSION_UNKNOWN, *(t for t, _ in said)]), [f for _, f in said],
                                 insights, calls, asked=[*(h["question"] for h in history), question.text],
                                 t=question.t, suggest=suggest), calls
    # A comparison of shots: each club's count when its side is known; else the total, and that which
    # side took them is not known (fixed words, stating no number).
    compares = re.search(r"\b(?:more|most|who|which)\b", question.text, re.I)
    if calls and calls[0]["name"] == "shots" and compares:
        total = next((f for f in facts if f.get("metric") == "shots_all"), None)
        per_club = [f for f in facts if f.get("metric") == "shots"]
        if total is not None and per_club and not all(f.get("confident") for f in per_club):
            ok = (t for t in code_texts(total) if _verify(Claim(t, [total["id"]]), known, insights).ok)
            text = next(ok, None)
            if text is not None:
                return _match_answer(f"{text} {SHOTS_SIDE_UNKNOWN}", [total], insights, calls,
                                     asked=[*(h["question"] for h in history), question.text], t=question.t,
                                     suggest=suggest), calls
    # A recap ("what happened in the first half?"): every goal in the stretch, then its strongest other
    # moment, each its own checked sentence.
    if calls and calls[0]["name"] == "key_moments":
        goals = sorted((f for f in facts if f.get("kind") == "goal"), key=lambda f: f.get("t") or 0)
        others = [f for f in facts if f.get("kind") != "goal"]
        said = []
        for f in [*goals, *others]:
            if len(said) >= len(goals) + 1:
                break
            text = next((t for t in code_texts(f) if _verify(Claim(t, [f["id"]]), known, insights).ok), None)
            if text is not None:
                said.append((text, f))
        if not said:
            lo_, hi_ = calls[0]["minute_from"], calls[0]["minute_to"]
            return Answer("unanswerable", f"Nothing stood out from minute {lo_} to minute {hi_}: no goal, "
                          "shot or big pass vision is sure of.", None, None, None, (), 60.0 * (lo_ - 1),
                          60.0 * hi_), calls
        if said:
            return _match_answer(" ".join(t for t, _ in said), [f for _, f in said], insights, calls,
                                 asked=[*(h["question"] for h in history), question.text], t=question.t,
                                 suggest=suggest), calls
    # A goal's story ("why did they score?"): the goal with the strongest thing before it, when the
    # goal build-up is what was asked (a "what's the score?" is the score's to answer).
    goal = next((f for f in facts if f.get("kind") == "goal"), None)
    if calls and calls[0]["name"] == "goal_build_up":
        which = goal_asked(question.text, insights, minute, named[0] if len(named) == 1 else None)
        so_far = goals_so_far(insights, minute, named[0] if len(named) == 1 else None)
        if which == "none":
            # "The 2nd goal" at 1–0: say how many there have been, and tell the latest.
            whose = f" for {named[0]}" if len(named) == 1 else ""
            head = (f"There hasn't been a goal{whose} yet." if not so_far else
                    "Nobody has equalised yet." if re.search(r"equali", question.text, re.I) else
                    "There's no winner yet." if re.search(r"winn", question.text, re.I) else
                    f"There has been {_ordinal(len(so_far))}{whose} so far, not that one.")
            story = goal_story(so_far[-1], insights, known) if so_far else []
            if not story:
                return Answer("unanswerable", head, None, None, None, (), 0.0, float(question.t)), calls
            return _match_answer(" ".join([head, *(t for t, _ in story)]), [f for _, f in story], insights,
                                 calls, asked=asked_all, t=question.t, suggest=suggest), calls
        if goal is None and not so_far:
            whose = f"{named[0]} haven't" if len(named) == 1 else "Nobody has"
            return Answer("unanswerable", f"{whose} scored yet.", None, None, None, (), 0.0,
                          float(question.t)), calls
        if goal is not None:
            story = goal_story(goal, insights, known)
            if story and re.search(r"\bassist\w*|set (?:it )?up|who passed", question.text, re.I) and \
                    not goal.get("assister_is"):
                story = [("Vision couldn't name who set it up.", None), *story]
            if story:
                cited = [f for _, f in story if f is not None]
                return _match_answer(" ".join(t for t, _ in story), cited, insights, calls,
                                     asked=asked_all, t=question.t, suggest=suggest), calls
    for f in facts:
        for text in code_texts(f):
            claim = Claim(text, [f["id"]])
            if text in before:  # a follow-up hears something new, never the answer just given
                continue
            if _verify(claim, known, insights).ok:
                more = supporting(f, facts, known, insights, {text, *before})
                return _match_answer(
                    " ".join([text, *(t for t, _ in more)]),
                    [f, *(g for _, g in more)],
                    insights,
                    calls,
                    asked=[*(h["question"] for h in history), question.text],
                    t=question.t,
                    suggest=suggest,
                ), calls
    names = ", ".join(n.replace("_", " ").replace("build up", "build-up") for n in MATCH_TOOLS[:4])
    ranked = [f for f in facts if f.get("kind") == "players"]
    asked = next((c for c in calls if c["name"] == "players"), None)
    lo_hi = (calls[0]["minute_from"], calls[0]["minute_to"]) if calls else None
    span = ("" if lo_hi is None else f"in minute {lo_hi[0]}" if lo_hi[0] == lo_hi[1]
            else f"from minute {lo_hi[0]} to minute {lo_hi[1]}")
    thin = next((f for f in facts if f.get("unit") == "%" and f.get("confident") and _sample(f) is not None
                 and _sample(f) < MIN_SHARE_PASSES), None)
    if thin is not None and calls and calls[0]["minute_from"] > 1 and \
            minutes_of(question.text, minute) is None:
        # Too few passes in the last minutes to say: the match so far may have enough (lesson 288).
        wider = [{**c, "minute_from": 1} for c in calls]
        return code_match_answer(question, insights, wider, history, suggest)
    shape_held = calls and calls[0]["name"] == "team_shape" and not any(
        f.get("confident") for f in facts if f.get("kind") == "shape")
    if calls and _minute_now(question.t) <= 2:
        why = TOO_EARLY  # nothing yet to rank, count or share: say so, not a canned list
    elif shape_held:
        whose = f"{named[0]}'s" if len(named) == 1 else "A club's"
        why = (f"{whose} shape can't be measured {span}: it needs every one of their players in view at "
               "once, and the cameras didn't have them all.")
    elif thin is not None:
        whose = thin.get("club") or "either side"
        why = (f"Too few of {whose}'s passes {span} to say yet: {_plural(_sample(thin), 'pass')}, and a "
               f"share needs {MIN_SHARE_PASSES}.")
    elif ranked and asked is not None:
        # The players were ranked but none can be named the best: say so, never the canned list.
        club = asked.get("club")
        whose = (f"{club}'" if club.endswith("s") else f"{club}'s") if club else "the"
        why = (f"I can't single out {whose} most dangerous player {span}: tracking missed too many "
               "players, or too many are level, to rank them surely.")
        scorers = [(t, g) for g in goals_so_far(insights, lo_hi[1] if lo_hi else 90, club)
                   if g.get("scorer_is") and (t := _checked(g, known, insights)) is not None
                   and "scored for" in t]
        if scorers:  # who decided the match so far is still worth saying, each a checked sentence
            return _match_answer(" ".join([why, "What I can say: ", *(t for t, _ in scorers[-2:])]).replace(
                ":  ", ": "), [g for _, g in scorers[-2:]], insights, calls, asked=asked_all, t=question.t,
                suggest=suggest), calls
    elif not facts and calls:
        # The match is tracked (these are its insights): nothing in the stretch answers it yet.
        why = f"Nothing {span} answers that yet."
    elif calls:
        why = f"Nothing {span} answers that surely: vision wasn't sure enough of what it saw."
    else:
        why = f"I can answer about {names} and the team sheets."
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
    question = replace(question, text=normalise(question.text, insights)[:200])
    # A row of the intent table (lesson 297): code's answer from that row, with or without a model. The
    # model plans only what the table leaves to the tools (tactics, one player, a question it can't read).
    tabled = None if WHY_RESULT.search(question.text) else table_answer(question, insights, history)
    if tabled is not None:
        return MatchResult(tabled[0], "code", tuple(tabled[1]))
    # Small talk: code's reply, before any tool or model call (lesson 287). With a model, a message code
    # routes to no tool goes to its planner; an empty plan comes back to code, which says so.
    chat = chat_answer(question, insights, history, small_talk_only=ask is not None)
    if chat is not None:
        return MatchResult(chat, "code")
    if HOW_PLAYING.search(question.text):
        # "How are Lisbon playing?" is answered by code's overview in Live mode too: ranked by what
        # matters, never the first small count a model picks ("crossed 1 time and found a teammate 0
        # times"), and with no model call spent.
        calls = code_calls(question, insights, history)
        known = {f["id"]: f for f in run_tools(insights, calls)}
        overview = _overview(question, calls, insights, known, history, True)
        if overview is not None:
            return MatchResult(overview, "code", tuple(calls))
    if ask is None or code_first(question, insights, history):
        # The score, a goal's story, "why are they winning?" and a recap are answered by code in Live
        # mode too: told whole (the goal asked for, the shot, the build-up), where the model chooses a
        # single sentence and on the red-team set chose the scorebug for "explain the last goal"
        # (lesson 288). No model call is spent.
        a, calls = code_match_answer(question, insights, history=history)
        return MatchResult(a, "code", tuple(calls))
    minute = _minute_in(question.t, insights)

    async def drafted():
        plan_reply = await within("plan", ask(plan_prompt(question, insights, history)))
        try:
            plan = first_object(plan_reply)
        except (json.JSONDecodeError, TypeError, AttributeError, ValueError, RecursionError):
            raise _NotTheFormat("plan") from None
        row = plan.get("intent") if isinstance(plan, dict) else None
        if row in INTENT_ROWS:  # the model picked a row of the table: code answers from it
            return [{"name": "intent", "intent": row}], None, None, []
        calls = _calls(plan, insights, minute)
        stretch = minutes_of(question.text, minute)
        if stretch is not None:  # the stretch the fan named, whatever minutes the plan chose
            calls = [c if c["name"] == "goal_build_up"
                     else {**c, "minute_from": stretch[0], "minute_to": stretch[1]} for c in calls]
        if not calls:
            return calls, None, None, []
        facts = run_tools(insights, calls)
        why, order = physical_gate(question.text, calls, facts, insights)
        if why is not None:
            return calls, None, None, facts  # code says why it is not available
        # A rules question is the Referee's to answer (ninety/agents/referee.py): the Companion
        # hands the facts over, and the same fact-check gates what comes back.
        rules = any(c["name"] == "referee" for c in calls)
        writer = referee_ask if referee_ask is not None and rules else ask
        reply = await within("answer", writer(answer_prompt(question, facts, history, insights)))
        try:
            claim = parse_claim(reply)
        except (json.JSONDecodeError, AttributeError, TypeError, ValueError, RecursionError) as exc:
            raise _NotTheFormat(str(exc)[:200]) from None
        known = {f["id"]: f for f in facts}
        if not claim.text.strip():
            return calls, claim, None, facts
        # The model chooses; it does not write (v4): its text must be exactly one of the checked
        # sentences of a fact it cites, or code's answer is shown.
        chosen = {t for i in claim.evidence if i in known for t in _say_as(known[i], known, insights)}
        if claim.text.strip() not in chosen:
            return calls, claim, Verdict(ok=False, reasons=[NOT_CHOSEN]), facts
        claim = Claim(claim.text.strip(), claim.evidence)  # the checked sentence exactly, nothing around it
        verdict = _verify(claim, known, insights)
        if verdict.ok and any(c["name"] == "physical" for c in calls):
            # The answer code would give first is the one the question asks for: the figure (or the
            # zone) of the player it names, else the highest.
            first = next((f for f in order if f.get("kind") == "running"), None)
            cited = [known[i] for i in claim.evidence if known.get(i, {}).get("kind") == "running"]
            if first is not None and not any(
                f.get("metric") == first["metric"] and f.get("value") == first.get("value")
                and (f.get("metric") != "player_zone" or f.get("player_is") == first.get("player_is"))
                for f in cited
            ):
                asked = f"{first.get('player_is')}'s {first['metric']}"
                verdict = Verdict(ok=False, reasons=[f"the question asks for {asked}; it cites another"])
        breaks = any(c["name"] == "line_breaks" for c in calls)
        beaten = beaten_club(question.text, insights) if breaks else None
        if verdict.ok and beaten is not None and any(
            str(known.get(i, {}).get("metric", "")).startswith("opponents_bypassed")
            and known[i].get("club") in (None, beaten) for i in claim.evidence
        ):
            # A pass that broke Lisbon's lines is never Lisbon's own (lesson 283).
            verdict = Verdict(ok=False, reasons=[f"the question asks for a pass that beat {beaten}; it cites "
                                                 f"one of {beaten}'s or of an unknown side"])
        if verdict.ok and judge is not None:
            verdict = await within("judge", judge(claim, [_for_prompt(known[i]) for i in claim.evidence]))
        return calls, claim, verdict, facts

    def fallback(reason: str, calls=None) -> MatchResult:
        a, used = code_match_answer(question, insights, calls or None, history)
        return MatchResult(a, "code", tuple(used), (reason,) if isinstance(reason, str) else tuple(reason))

    try:
        calls, claim, verdict, facts = await asyncio.wait_for(drafted(), timeout)
    except TimeoutError as exc:
        return fallback(_timeout_reason(exc))
    except NoModel as exc:
        return fallback(str(exc))
    except service_errors():
        return fallback("model service error")
    except _NotTheFormat:
        return fallback("model reply is not the reply format")
    if calls and calls[0]["name"] == "intent":
        from dataclasses import replace as _with

        from ninety.agents import ask_answers

        read = read_question(question.text, insights, question.t, history)
        picked = calls[0]["intent"]
        # The model may pick only a row code's own reading finds plausible for this question (a row with
        # a nonzero score): "Where are Lisbon outnumbering London?" never airs a pass count because a
        # model said "passes" (review of #432). Any other pick is code's answer, as if it had not planned.
        if picked not in plausible_rows(read):
            return fallback(f"model picked row {picked}, which the question does not support")
        got = ask_answers.build(question, insights, _with(read, intent=picked))
        if got is not None:
            return MatchResult(got[0], "code", tuple(got[1]), ("model picked row " + picked,))
        return fallback("model picked a row code leaves to the tools")
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
