"""The Companion agent: answers a viewer's question about one player, on the phone.

The question is viewer text, so it is data, never instructions (SECURITY.md). The model sees it
only as a JSON string inside one JSON object, beside the player's window facts
(ninety/intel/window.py), and may only explain those facts. Its draft then goes through the same
fact-check as the slice's FactCheckExecutor: the code checks (factcheck.check, which allows a cited
fact's value written with its unit), then the Judge. Every number the phone shows is a cited
fact's value; `Answer.value` is read off the fact, never off the model's text.

Code also picks the one metric a question is about (`pick_metric`) and writes the answer for it
itself (`code_answer`). That answer is what the phone shows whenever the model is not used (Replay
mode, a spent budget) or fails: it errors, times out, returns something that is not the reply
format, or its draft is rejected by either half of the fact-check. A rejected draft is not sent
back for a rewrite as the slice does: a phone answer must be quick, and the code answer is always
right. A question about none of the metrics is answered "unanswerable", saying what can be asked.
"""

from __future__ import annotations

import asyncio
import json
import re
from dataclasses import dataclass, field
from typing import Literal

from agent_framework import Agent
from agent_framework.exceptions import AgentFrameworkException
from azure.core.exceptions import AzureError
from pydantic import BaseModel

from ninety.agents.contracts import COMPANION_INSTRUCTIONS, Answer, Ask, Judge, Question, status_for
from ninety.agents.factcheck import Claim, Verdict, check, spelled_as_digits
from ninety.agents.slice import parse_claim
from ninety.intel.stats import Fact
from ninety.intel.window import PlayerWindow

TIMEOUT_S = 10.0  # design: a phone answer later than this is worse than the code answer now; it
# covers the whole Live answer, the model's draft and the Judge together

# The metric a question is about, first match wins: "top speed" before "speed", and "km" only when
# it is not "km/h". Each pattern is a whole word or phrase. The word lists are design: the plain
# English words for each fact, measured on companion_eval's metric-reading set (12 of 13 read
# right, docs/eval/companion.md); a question they miss gets the code answer for no metric, which says
# what can be asked, never a wrong number.
METRIC_WORDS = (
    ("peak_speed", r"\b(?:top|max(?:imum)?|peak|highest|fastest|quickest)\b"),
    ("distance_run", r"\b(?:how far|distance|covered|cover|metres|meters|kilomet\w*|kms?(?!/))\b"),
    ("speed_now", r"\b(?:speed|how fast|fast|pace|quick|running at|km/h|kph)"),
)
CODE_TEXT = {
    "speed_now": "{player} is moving at {value} km/h right now.",
    "peak_speed": "{player}'s top speed so far is {value} km/h.",
    "distance_run": "{player} has covered {value} m so far.",
}
ASKABLE = "their speed now, their top speed or how far they have run"

Source = Literal["model", "code"]


@dataclass(frozen=True)
class Result:
    """The answer, who wrote its text, and why the model's draft was not used, if it was not."""

    answer: Answer
    source: Source
    reasons: tuple[str, ...] = field(default_factory=tuple)


class Reply(BaseModel):
    """One sentence and the ids of the facts it cites."""

    text: str
    evidence: list[str]


def companion_agent(client) -> Agent:
    return Agent(
        client=client,
        name="companion",
        instructions=COMPANION_INSTRUCTIONS,
        default_options={"response_format": Reply, "temperature": 0},
    )


def pick_metric(text: str) -> str | None:
    lowered = text.lower()
    return next((metric for metric, words in METRIC_WORDS if re.search(words, lowered)), None)


def _number(value: float) -> str:
    """A fact's value as the check reads it back: 428.0 is written 428, 27.3 as 27.3."""
    return str(int(value)) if float(value).is_integer() else str(value)


def _known(window: PlayerWindow) -> dict[str, dict]:
    return {f.id: f.as_dict() for f in window.facts()}


def _from_fact(text: str, fact: Fact, evidence: tuple[str, ...], window: PlayerWindow) -> Answer:
    return Answer("verified", text, fact.metric, fact.value, fact.unit, evidence, window.t_from, window.t_to)


def unanswerable(question: Question, window: PlayerWindow | None = None, why: str | None = None) -> Answer:
    if question.player is None:
        text = f"Tap a player first, then ask about {ASKABLE}."
    elif window is None:
        text = f"There is no tracking for {question.player} yet."
    else:
        text = why or f"I can only answer about {question.player}'s speed, top speed and distance run."
    t_from, t_to = (window.t_from, window.t_to) if window else (None, None)
    return Answer("unanswerable", text, None, None, None, (), t_from, t_to)


def code_answer(question: Question, window: PlayerWindow | None, metric: str | None) -> Answer:
    """The answer code writes for one metric. It goes through the code checks like a model's draft,
    so a wrong template could never put a number on screen either."""
    if window is None or metric is None:
        return unanswerable(question, window)
    fact = next(f for f in window.facts() if f.metric == metric)
    claim = Claim(CODE_TEXT[metric].format(player=window.player, value=_number(fact.value)), [fact.id])
    verdict = check(claim, _known(window))
    if not verdict.ok:  # a defect in CODE_TEXT, never the viewer's doing: show nothing rather than it
        raise AssertionError(f"the code answer fails its own check: {verdict.reasons}")
    return _from_fact(claim.text, fact, (fact.id,), window)


def prompt(question: Question, window: PlayerWindow) -> str:
    """One JSON object. json.dumps escapes the viewer's text, so it cannot close the string it sits
    in and become part of the instructions."""
    return json.dumps(
        {
            "question": {"player": question.player, "text": question.text},
            "facts": [f.as_dict() for f in window.facts()],
        },
        separators=(",", ":"),
    )


async def _fact_check(claim: Claim, window: PlayerWindow, judge: Judge | None) -> Verdict:
    """The slice's FactCheckExecutor in one call: the code checks first (free, exact about numbers,
    players and ids), then the Judge (meaning). Without a Judge only the code checks run."""
    known = _known(window)
    verdict = check(claim, known)
    if verdict.ok and judge is not None:
        verdict = await judge(claim, [known[i] for i in claim.evidence])
    return verdict


class _NotTheFormat(ValueError):
    """The model's reply is not one Reply object."""


async def _drafted(
    question: Question, window: PlayerWindow, ask: Ask, judge: Judge | None
) -> tuple[Claim, Verdict | None]:
    """The model's draft and its fact-check, under one deadline in `answer`. No verdict when the
    model says it cannot answer."""
    reply = await ask(prompt(question, window))
    try:
        claim = parse_claim(reply)
    except (json.JSONDecodeError, AttributeError, TypeError, ValueError) as exc:
        raise _NotTheFormat(str(exc)) from None
    if not claim.text.strip():
        return claim, None
    return claim, await _fact_check(claim, window, judge)


async def answer(
    question: Question,
    window: PlayerWindow | None,
    ask: Ask | None = None,
    judge: Judge | None = None,
    timeout: float = TIMEOUT_S,
) -> Result:
    """The phone's answer to `question` about `window` (the asked-about player's facts). With no
    `ask`, code answers. With one, the model drafts and the fact-check decides; anything but a
    verified draft gives the code answer."""
    if question.player is not None and window is not None and window.player != question.player:
        raise ValueError(f"the window is {window.player}'s, the question is about {question.player}")
    metric = pick_metric(question.text)
    if ask is None or window is None:
        return Result(code_answer(question, window, metric), "code")
    try:
        claim, verdict = await asyncio.wait_for(_drafted(question, window, ask, judge), timeout)
    except TimeoutError:
        return Result(code_answer(question, window, metric), "code", ("model timeout",))
    except (AgentFrameworkException, AzureError):
        return Result(code_answer(question, window, metric), "code", ("model service error",))
    except _NotTheFormat:
        return Result(code_answer(question, window, metric), "code", ("model reply is not the reply format",))
    if verdict is None:
        # The model found no fact that answers it; code still answers a question about a metric.
        return Result(code_answer(question, window, metric), "code", ("model: unanswerable",))
    if status_for(verdict) != "verified":
        return Result(code_answer(question, window, metric), "code", tuple(verdict.reasons))
    known = {f.id: f for f in window.facts()}
    cited = [known[i] for i in claim.evidence]  # check() passed, so every cited id is a window fact
    stated = _stated(claim.text, cited)
    if len(stated) > 1:  # two numbers in one sentence: show the one the question asked about
        stated = [f for f in stated if f.metric == metric]
        if len(stated) != 1:
            return Result(code_answer(question, window, metric), "code", ("states more than one fact",))
    if not stated:  # a sentence with no number shows none
        return Result(Answer("verified", claim.text, None, None, None, tuple(claim.evidence),
                             window.t_from, window.t_to), "model")
    return Result(_from_fact(claim.text, stated[0], tuple(claim.evidence), window), "model")


def _stated(text: str, facts: list[Fact]) -> list[Fact]:
    """The cited facts whose value the sentence writes with the fact's unit, as the check reads
    it: the number the phone shows must be the one the sentence says, never another cited fact's."""
    out, text = [], spelled_as_digits(text)
    for fact in facts:
        pattern = rf"(?<![\w.])(\d+(?:\.\d+)?)\s*{re.escape(fact.unit)}(?!\w)"
        if any(float(n) == fact.value for n in re.findall(pattern, text, re.I)):
            out.append(fact)
    return out
