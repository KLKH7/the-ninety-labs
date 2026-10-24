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

MATCH_TOOLS = ("counter_press", "overloads", "line_breaks", "pass_options", "team_shape", "lineup")
TOOL_HELP = {
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
        else:
            got = getattr(insights, c["name"])(c["minute_from"], c["minute_to"], c["club"])
            rows = [*got["summary"], *got["facts"]]
        for r in rows:
            if r["id"] not in seen:
                seen.add(r["id"])
                out.append(r)
    return out


def _for_prompt(fact: dict) -> dict:
    """A fact as the model reads it: without its drawing, which only the phone needs."""
    return {k: v for k, v in fact.items() if k not in ("visual", "tracked")}


def plan_prompt(question: Question, insights) -> str:
    return json.dumps(
        {
            "step": "plan",
            "question": question.text,
            "clubs": list(insights.fixture.clubs.values()),
            "minute": _minute_now(question.t),
            "tools": TOOL_HELP,
        },
        separators=(",", ":"),
    )


def answer_prompt(question: Question, facts: list[dict]) -> str:
    return json.dumps(
        {"step": "answer", "question": question.text, "facts": [_for_prompt(f) for f in facts]},
        separators=(",", ":"),
    )


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


def _span(cited: list[dict]) -> tuple[float | None, float | None]:
    ts = [float(f["t"]) for f in cited if f.get("t") is not None]
    ts += [60.0 * (f["minute_from"] - 1) for f in cited if f.get("minute_from")]
    ts += [60.0 * f["minute_to"] for f in cited if f.get("minute_to")]
    return (min(ts), max(ts)) if ts else (None, None)


def _match_answer(text: str, cited: list[dict], insights=None) -> Answer:
    t_from, t_to = _span(cited)
    lead = next((f for f in cited if f.get("value") is not None and f.get("unit")), None)
    metric, value, unit = (lead["metric"], float(lead["value"]), lead["unit"]) if lead else (None, None, None)
    visual = visual_of(cited)
    names = names_of(cited, visual, insights) if insights is not None else None
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
        names=names,
        spoken=text,  # code's and the model's sentences carry no visual reference (insight_check)
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
    return f"{_num(n)} {word}" + ("" if n == 1 else "s")


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


def code_match_answer(
    question: Question, insights, calls: list[dict] | None = None
) -> tuple[Answer, list[dict]]:
    """Code's answer: the routed tools' facts, the first one code can say and the check passes."""
    minute = _minute_now(question.t)
    calls = (
        calls
        if calls is not None
        else [
            {"name": n, "club": None, "minute_from": max(1, minute - WINDOW_MIN + 1), "minute_to": minute}
            for n in route(question.text)
        ]
    )
    facts = run_tools(insights, calls)
    known = {f["id"]: f for f in facts}
    clubs = insights.fixture.clubs
    if re.search(r"\b(?:which|who|whose)\b", question.text, re.I):
        # "Which pass…?", "Who…?": a moment with a player in it, before a club's total.
        facts = sorted(facts, key=lambda f: f.get("t") is None)
    for f in facts:
        f.setdefault("clubs", clubs)
        for text in code_texts(f):
            claim = Claim(text, [f["id"]])
            if _verify(claim, known, insights).ok:
                return _match_answer(text, [f], insights), calls
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
) -> MatchResult:
    """The phone's answer to a match question. With no `ask`, code routes and answers. With one,
    the model plans the tool calls and writes the answer; anything but a verified draft gives
    code's answer over the model's chosen tools (or code's, if the plan was unusable)."""
    if ask is None:
        a, calls = code_match_answer(question, insights)
        return MatchResult(a, "code", tuple(calls))
    minute = _minute_now(question.t)

    async def drafted():
        plan_reply = await ask(plan_prompt(question, insights))
        try:
            body = re.search(r"\{.*\}", plan_reply, re.S)
            plan = json.loads(body.group() if body else plan_reply)
        except (json.JSONDecodeError, TypeError, AttributeError):
            raise _NotTheFormat("plan") from None
        calls = _calls(plan, insights, minute)
        if not calls:
            return calls, None, None, []
        facts = run_tools(insights, calls)
        reply = await ask(answer_prompt(question, facts))
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
        a, used = code_match_answer(question, insights, calls or None)
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
    return MatchResult(_match_answer(claim.text, cited, insights), "model", tuple(calls))
