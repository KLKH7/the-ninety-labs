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

from ninety.agents.companion import TIMEOUT_S, Source, _NotTheFormat, _number, service_errors
from ninety.agents.contracts import Answer, Ask, Judge, Question, status_for
from ninety.agents.factcheck import Claim, Verdict, parse_claim

MATCH_TOOLS = (
    "goal_build_up",
    "players",
    "style",
    "counter_press",
    "overloads",
    "line_breaks",
    "pass_options",
    "team_shape",
    "lineup",
)
TOOL_HELP = {
    "goal_build_up": "the latest goal up to minute_to (or one club's), and what happened in the minute "
    "before it",
    "players": "players ranked by the opponents their passes took out of the game",
    "style": "how each club plays: passing channels (left, centre, right), how wide it plays against the "
    "other club, crosses, the keeper going long or short, counter-attacks (regain to shot), one-twos",
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
    ("goal_build_up", r"\b(?:goals?|scor\w*|equali[sz]\w*|that finish)\b"),
    (
        "style",
        r"\b(?:style|playing like|play(?:ing)? like this|tactic\w*|approach|long balls?|go(?:ing)? long"
        r"|cross\w*|wings?|down the (?:left|right|middle)|counter[- ]attack\w*|on the break|one-twos?"
        r"|wall pass\w*"
        r"|goal ?keeper|keeper)\b",
    ),
    ("players", r"\b(?:best|man of the match|stand-?out|star|playing well|who(?:'s| has) been)\b"),
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
        "lineup",
        r"\b(?:who(?:'s| is)|name\w*|number|line-?up|team sheet|playing (?:left|right)|which player)\b",
    ),
)
MAX_TOOLS = 3
WINDOW_MIN = 15  # the stats' window (docs/GROUNDING.md S4): a question about now looks this far back


def route(text: str) -> list[str]:
    lowered = text.lower()
    return [tool for tool, words in TOOL_WORDS if re.search(words, lowered)][:MAX_TOOLS]


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
        "Who took the most players out of the game?",
        "How quickly did {club} win the ball back?",
    ),
    "players": ("Why did {club} score?", "Where are {club} outnumbering them?"),
    "style": ("Do {club} counter-attack?", "Is their keeper going long?"),
    "counter_press": ("Did {club} have options when they lost it?", "And in the first half?"),
    "overloads": ("How quickly do {club} win the ball back?", "Which passes cut through?"),
    "line_breaks": ("Who has been the best player?", "Where are {club} outnumbering them?"),
    "pass_options": ("How quickly do {club} win the ball back?", "Which passes cut through?"),
    "team_shape": ("Where are {club} outnumbered?", "And in the last ten minutes?"),
    "lineup": ("Who has been the best player?", "Why do {club} keep losing the ball?"),
}


def follow_ups(calls: list[dict], cited: list[dict], insights) -> tuple[str, ...]:
    """Two suggested next questions, from the tools the answer used, about the club it was about."""
    club = next((f.get("club") for f in cited if f.get("club")), None) or insights.fixture.clubs["home"]
    out = []
    for c in calls:
        for q in FOLLOW_UPS.get(c["name"], ()):
            q = q.format(club=club)
            if q not in out:
                out.append(q)
    return tuple(out[:2])


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


def _match_answer(text: str, cited: list[dict], insights=None, calls=()) -> Answer:
    t_from, t_to = _span(cited)
    lead = next((f for f in cited if f.get("value") is not None and f.get("unit")), None)
    metric, value, unit = (lead["metric"], float(lead["value"]), lead["unit"]) if lead else (None, None, None)
    visual = visual_of(cited)
    extra = {}
    if insights is not None:
        extra = {
            "names": names_of(cited, visual, insights),
            "follow_ups": follow_ups(list(calls), cited, insights),
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
        **extra,
    )


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
            f"{span.capitalize()}, {who} played a pass that took {fact['value']} {opp} players "
            "out of the game."
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
    if metric == "one_two":
        a, b = fact.get("passer_is"), fact.get("receiver_is")
        if not a or not b:
            return []
        return [f"{span.capitalize()}, {a} and {b} played a one-two."]
    if kind == "goal":
        return [f"{club} scored in minute {fact['minute']}."]
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
    # Fenwick?"): code reads both clubs' facts and the fact-check binds the sentence to the right one.
    return [{"name": n, "club": None, "minute_from": lo, "minute_to": hi} for n in names]


def code_match_answer(
    question: Question, insights, calls: list[dict] | None = None, history=()
) -> tuple[Answer, list[dict]]:
    """Code's answer: the routed tools' facts, the first one code can say and the check passes. A
    goal is told with the strongest thing that led to it."""
    calls = calls if calls is not None else code_calls(question, insights, history)
    facts = run_tools(insights, calls)
    known = {f["id"]: f for f in facts}
    clubs = insights.fixture.clubs
    for f in facts:
        f.setdefault("clubs", clubs)
    if re.search(r"\b(?:which|who|whose)\b", question.text, re.I):
        # "Which pass…?", "Who…?": a moment with a player in it, before a club's total.
        facts = sorted(facts, key=lambda f: f.get("t") is None)
    goal = next((f for f in facts if f.get("kind") == "goal"), None)
    if goal is not None:
        for f in facts:
            if f is goal or f.get("team") != goal["team"]:
                continue
            for text in code_texts(f):
                lead = text[0].lower() + text[1:]
                combined = f"{goal['club']} scored in minute {goal['minute']}. Just before it, {lead}"
                if _verify(Claim(combined, [goal["id"], f["id"]]), known, insights).ok:
                    return _match_answer(combined, [goal, f], insights, calls), calls
    for f in facts:
        for text in code_texts(f):
            claim = Claim(text, [f["id"]])
            if _verify(claim, known, insights).ok:
                return _match_answer(text, [f], insights, calls), calls
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
            body = re.search(r"\{.*\}", plan_reply, re.S)
            plan = json.loads(body.group() if body else plan_reply)
        except (json.JSONDecodeError, TypeError, AttributeError):
            raise _NotTheFormat("plan") from None
        calls = _calls(plan, insights, minute)
        if not calls:
            return calls, None, None, []
        facts = run_tools(insights, calls)
        reply = await ask(answer_prompt(question, facts, history))
        try:
            claim = parse_claim(reply)
        except (json.JSONDecodeError, AttributeError, TypeError, ValueError) as exc:
            raise _NotTheFormat(str(exc)) from None
        known = {f["id"]: f for f in facts}
        if not claim.text.strip():
            return calls, claim, None, facts
        verdict = _verify(claim, known, insights)
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
    return MatchResult(_match_answer(claim.text, cited, insights, calls), "model", tuple(calls))
