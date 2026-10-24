"""The Insight Scout: pushes "hidden stat" cards to the phone as the match unfolds.

Code proposes, the fact-checker decides, a rate limit spaces them out. As match time passes, the
Scout looks at the insight facts so far (ninety/intel/match_insights.py) and picks, for each
CARD_GAP_MIN of play, the most notable confident fact: one that ranks in the top NOTABLE of its
kind among the facts of that kind so far (a line break bypassing more opponents than most passes,
an overload with more extra players for longer, a counter-press that won the ball back fastest,
a lost pass that had open teammates ahead). Its sentence comes from code (`companion.code_texts`),
or from a model that rewrites it, and goes through the insight fact-check (and the Judge, when
there is one); only a verified card is pushed. Each card has a "why?" follow-up, answered ahead of
time by the Companion over the same facts, so the phone shows it without a model call.

Nothing is pushed within GOAL_QUIET_S after a detected goal: the screen belongs to the goal. Then
the goal's build-up jumps the queue (`scout`: spotters per kind, a light Director).

    uv run python -m ninety.agents.scout INSIGHTS.json --out cards.json
"""

from __future__ import annotations

import argparse
import asyncio
import json
from collections.abc import Mapping, Sequence
from html import escape
from pathlib import Path

from agent_framework import Executor, WorkflowBuilder, WorkflowContext, handler

from ninety.agents import companion_match as companion
from ninety.agents import insight_check
from ninety.agents.contracts import Ask, Description, Judge, status_for
from ninety.agents.factcheck import Claim, parse_claim

CARD_GAP_MIN = 3  # design: at most one card every three match minutes, so a card is news, not noise
NOTABLE = 0.9  # design: a fact must rank above 90% of its kind so far (the top tenth)
MIN_SO_FAR = (
    10  # the top tenth needs ten facts of a kind to rank among (with fewer, NOTABLE cannot be reached)
)
GOAL_QUIET_S = 30.0  # design: no card in the half minute after a goal
DEFER_SLOTS = 1  # design: a candidate kept out by the cap may still go in the next slot, then it is stale
HEADLINES = {
    "counter": "{club} break at speed",
    "shape": "{club}'s back line moves",
    "line_break": "{club} slice through",
    "overload": "{club} have the extra man",
    "counter_press": "{club} win it straight back",
    "pass_options": "A pass not taken",
}
WHY = {
    "counter": "What makes a counter-attack?",
    "shape": "Why does the back line matter?",
    "line_break": "Why does a pass like that matter?",
    "overload": "Why does an overload matter?",
    "counter_press": "Why win it back so fast?",
    "pass_options": "What else was on?",
}
# What the "why?" answer adds to the card's fact: the definition, in code's words. Each is checked
# like any sentence, so it may state only the fact's own numbers with their units.
WHY_TEXT = {
    "counter": "A counter-attack is a quick break straight after winning the ball, before the other side "
    "can get back: {club} had a shot {value} seconds after winning it.",
    "shape": "A back line further from its own goal squeezes the space in midfield; one closer to it "
    "protects the space behind: in minute {minute} {club}'s was {value} {unit} from their own goal.",
    "line_break": "Analysts call it packing: every opponent a pass gets past no longer stands between the "
    "ball and goal, and this pass took out {value} {unit}.",
    "overload": "With {own} against {other} around the ball, {club} had a spare player there.",
    "counter_press": "Winning the ball back within 5 seconds of losing it stops the other side "
    "from breaking, "
    "and {club} had {value} {unit} near the ball.",
    "pass_options": "At the moment of that pass {club} had {value} open teammates further forward.",
}


TOOL_OF = {
    "line_break": "line_breaks",
    "overload": "overloads",
    "counter_press": "counter_press",
    "pass_options": "pass_options",
    "counter": "style",
    "shape": "team_shape",
}
SHAPE_CHANGE_M = companion.SHAPE_CHANGE_M


def where_spoken(fact: Mapping, clubs: Mapping[str, str]) -> str:
    """Where it happened, in words for a fan who cannot see it: which end (whose goal: home defends
    x = 0) and which side (y = 0 is the near touchline, under the camera). Code reads it off the fact's
    drawing, so it is as true as the drawing."""
    g = fact.get("visual") or {}
    x = _where_x({"visual": {"geometry": {k: v for k, v in g.items() if k != "kind"}}})
    if x is None:
        return ""
    y = None
    for key in ("from", "ball", "passer"):
        if g.get(key):
            y = float(g[key][1])
            break
    if y is None and g.get("zone"):
        y = (float(g["zone"]["y0"]) + float(g["zone"]["y1"])) / 2
    home, away = clubs["home"], clubs["away"]
    end = (
        f"close to {home}'s goal"
        if x < 16.5
        else f"in {home}'s third"
        if x < 35
        else f"close to {away}'s goal"
        if x > 88.5
        else f"in {away}'s third"
        if x > 70
        else "in midfield"
    )
    side = "" if y is None or 15 <= y <= 53 else (" on the near side" if y < 15 else " on the far side")
    return f"It was {end}{side}."


def notability(f: Mapping) -> tuple:
    """Higher is more notable, within one kind."""
    kind = f["kind"]
    if kind == "line_break":
        return (f["value"],)
    if kind == "overload":
        return (f["value"], f.get("duration_s") or 0.0)
    if kind == "counter_press":
        return (bool(f.get("regained")), f["value"], -(f.get("regain_s") or 99.0))
    if kind == "pass_options":
        return (f.get("outcome") == "fail" and f.get("target_open") is False, f["value"])
    if kind == "shape":
        return (abs(f.get("change") or 0),)
    if kind == "counter":
        return (-f["value"],)
    return ()


def _rank(fact: Mapping, so_far: Sequence[Mapping]) -> float:
    key = notability(fact)
    return sum(notability(g) < key for g in so_far) / len(so_far)


def candidates(insights, t_to: float) -> list[dict]:
    """Every confident fact up to t_to that ranks notable among its kind so far, oldest first."""
    out = []
    for kind, rows in insights.facts.items():
        if kind not in HEADLINES:
            continue
        seen = []
        for f in rows:
            if f["t"] > t_to:
                break
            seen.append(f)
            if kind == "overload" and f.get("third") == "own":
                continue  # design: an overload in a team's own third is its build-up, not news
            if kind == "shape" and (
                f.get("metric") != "line_height" or abs(f.get("change") or 0) < SHAPE_CHANGE_M
            ):
                continue  # the shape spotter tells only of the back line moving, by a change it vouches for
            if (
                len(seen) >= MIN_SO_FAR
                and f["confident"]
                and _rank(f, seen) >= NOTABLE
                and companion.code_texts({**f, "clubs": insights.fixture.clubs})
            ):
                out.append(f)
    return sorted(out, key=lambda f: (f["t"], f["id"]))


def _rewrite_prompt(text: str, fact: Mapping) -> str:
    return json.dumps(
        {
            "step": "answer",
            "question": "Rewrite this insight for a fan, keeping every number.",
            "draft": text,
            "facts": [companion._for_prompt(fact)],
        },
        separators=(",", ":"),
    )


async def card_for(
    fact: Mapping, insights, n: int, ask: Ask | None = None, judge: Judge | None = None
) -> dict | None:
    """One verified card for `fact`, or None if no sentence about it passes."""
    clubs = insights.fixture.clubs
    fact = {**fact, "clubs": clubs}
    known = {fact["id"]: fact}
    texts = companion.code_texts(fact)
    source = "code"
    if ask is not None and texts:
        try:
            claim = parse_claim(await ask(_rewrite_prompt(texts[0], fact)))
            if claim.text.strip() and claim.evidence == [fact["id"]]:
                v = insight_check.verify(claim, known, clubs, insights.people, insights.sheet_names())
                if v.ok and judge is not None:
                    v = await judge(claim, [companion._for_prompt(fact)])
                if status_for(v) == "verified":
                    texts, source = [claim.text], "model"
        except Exception:  # noqa: BLE001  any model failure leaves code's sentence
            pass
    for text in texts:
        if not insight_check.verify(
            Claim(text, [fact["id"]]), known, clubs, insights.people, insights.sheet_names()
        ).ok:
            continue
        why = WHY_TEXT[fact["kind"]].format(
            minute=fact["minute"],
            value=fact["value"],
            unit=fact["unit"],
            club=fact["club"],
            own=companion._plural(fact.get("own_players") or 0, "player"),
            other=companion._plural(fact.get("other_players") or 0, "player"),
        )
        why_ok = insight_check.verify(
            Claim(why, [fact["id"]]), known, clubs, insights.people, insights.sheet_names()
        ).ok
        visual = companion.visual_of([fact])
        spoken = f"{text} {where_spoken(fact, clubs)}".strip()
        if not insight_check.verify(
            Claim(spoken, [fact["id"]]), known, clubs, insights.people, insights.sheet_names()
        ).ok:
            spoken = text
        return {
            "id": f"card-{n:04d}",
            "t": fact["t"],
            "minute": fact["minute"],
            "team": fact["team"],
            "club": fact["club"],
            "kind": fact["kind"],
            "headline": HEADLINES[fact["kind"]].format(club=fact["club"]),
            "text": text,
            "status": "verified",
            "source": source,
            "evidence": [fact["id"]],
            "visual": visual,
            "spoken": spoken,
            "names": companion.names_of([fact], visual, insights),
            "follow_ups": list(companion.follow_ups([{"name": TOOL_OF[fact["kind"]]}], [fact], insights)),
            "why": {
                "question": WHY[fact["kind"]],
                "answer": {"status": "verified", "text": why, "evidence": [fact["id"]], "visual": visual},
            }
            if why_ok
            else None,
        }
    return None


# Spotters: specialists that each watch their own insight kinds and propose candidates. The pressing
# spotter reads counter-presses and overloads; the space spotter line breaks and pass options; the
# shape spotter the back line's moves (#228's facts).
SPOTTERS = {
    "pressing": ("counter_press", "overload", "counter"),
    "space": ("line_break", "pass_options"),
    "shape": ("shape",),
}


def proposals(spotter: str, insights) -> list[dict]:
    """One spotter's proposals: each notable confident fact of its kinds, with its rank among its
    kind so far as the spotter's confidence that it is worth a card."""
    kinds = SPOTTERS[spotter]
    out = []
    for f in candidates(insights, float("inf")):
        if f["kind"] in kinds:
            so_far = [g for g in insights.facts[f["kind"]] if g["t"] <= f["t"]]
            out.append({"spotter": spotter, "fact": f, "confidence": round(_rank(f, so_far), 3)})
    return out


class _Start:
    """The match the spotters fan out over."""

    def __init__(self, insights):
        self.insights = insights


class _Begin(Executor):
    @handler
    async def go(self, match: _Start, ctx: WorkflowContext[_Start]) -> None:
        await ctx.send_message(match)


class _Spotter(Executor):
    def __init__(self, name: str):
        super().__init__(id=f"spotter_{name}")
        self.name = name

    @handler
    async def spot(self, match: _Start, ctx: WorkflowContext[list]) -> None:
        await ctx.send_message(proposals(self.name, match.insights))


class _Directing(Executor):
    def __init__(self, decide):
        super().__init__(id="director")
        self.decide = decide

    @handler
    async def take(self, batches: list[list], ctx: WorkflowContext[list, list]) -> None:
        await ctx.yield_output(await self.decide([p for batch in batches for p in batch]))


def _workflow(director):
    """Start -> the spotters in parallel (fan-out) -> the Director (fan-in), as Agent Framework edges."""
    start = _Begin(id="scout_start")
    spotters = [_Spotter(name) for name in SPOTTERS]
    return (
        WorkflowBuilder(name="ninety-scout", start_executor=start)
        .add_fan_out_edges(start, spotters)
        .add_fan_in_edges(spotters, _Directing(director))
        .build()
    )


def _rank_prompt(slot: list[dict]) -> str:
    return json.dumps(
        {
            "step": "rank",
            "candidates": [
                {
                    "id": p["fact"]["id"],
                    "spotter": p["spotter"],
                    "confidence": p["confidence"],
                    "text": p["text"],
                }
                for p in slot
            ],
        },
        separators=(",", ":"),
    )


async def scout(
    insights,
    goals: Sequence[float] = (),
    ask: Ask | None = None,
    judge: Judge | None = None,
    log: list | None = None,
    rank: Ask | None = None,
    ledger=None,
) -> list[dict]:
    """The match's cards, oldest first, and (into `log`, and the Ledger when given) every decision.

    The spotters propose in parallel; the Director decides, slot by slot of CARD_GAP_MIN minutes. A
    Director model (`rank`), when given, orders a slot's proposals; code's rules always hold:
    - cap: at most one card a slot;
    - no repeats: a fact is pushed once, and one of the last card's kind or players goes last;
    - goal jump: after a goal, the most notable fact of the minute before it is pushed at the end
      of the quiet, whatever the cap;
    - deferral: a proposal the cap kept out waits DEFER_SLOTS slots for a quiet one, then is dropped;
    - logged: each proposal's fate (pushed, deferred, dropped, refused by the fact-check), with why.
    """
    log = [] if log is None else log
    director = Director(insights, goals, ask, judge, log, rank)
    (cards,) = (await _workflow(director.run).run(_Start(insights))).get_outputs()
    if ledger is not None:
        await director.record(ledger, cards)
    return cards


class Director:
    def __init__(self, insights, goals, ask, judge, log, rank):
        self.insights, self.goals, self.ask, self.judge, self.log, self.rank = (
            insights,
            goals,
            ask,
            judge,
            log,
            rank,
        )

    def rank_of(self, f) -> float:
        return _rank(f, [g for g in self.insights.facts[f["kind"]] if g["t"] <= f["t"]])

    async def order(self, slot: list[dict], last: dict | None) -> list[dict]:
        """Code's order (a repeat last, then the spotter's confidence), or the Director model's when
        it names exactly these proposals; code's repeat rule still puts repeats last."""

        def repeat(p):
            f = p["fact"]
            return last is not None and (
                f["kind"] == last["kind"]
                or bool({f.get("passer"), f.get("receiver")} - {None} & set(last.get("_players", ())))
            )

        ordered = sorted(slot, key=lambda p: (repeat(p), -p["confidence"], p["fact"]["t"]))
        if self.rank is not None and len(slot) > 1:
            for p in slot:
                p["text"] = (
                    companion.code_texts({**p["fact"], "clubs": self.insights.fixture.clubs}) or [""]
                )[0]
            try:
                reply = await self.rank(_rank_prompt(slot))
                ids = json.loads(reply[reply.index("{") : reply.rindex("}") + 1])["order"]
                by = {p["fact"]["id"]: p for p in slot}
                if sorted(ids) == sorted(by):
                    ordered = sorted((by[i] for i in ids), key=lambda p: repeat(p))
            except Exception:  # noqa: BLE001  a ranking the Director model could not give: code's order
                self.log.append(
                    {"fact": None, "decision": "ranked by code", "why": "the Director model failed"}
                )
        return ordered

    async def run(self, pool: list[dict]) -> list[dict]:
        insights, log = self.insights, self.log
        pool = sorted(pool, key=lambda p: (p["fact"]["t"], p["fact"]["id"]))
        cards: list[dict] = []
        used: set[str] = set()
        queue: list[tuple[int, dict]] = []
        by_slot: dict[int, list[dict]] = {}
        for p in pool:
            f = p["fact"]
            if any(0 <= f["t"] - g <= GOAL_QUIET_S for g in self.goals):
                log.append(
                    {
                        "fact": f["id"],
                        "spotter": p["spotter"],
                        "decision": "dropped",
                        "why": "in the quiet after a goal",
                    }
                )
                continue
            by_slot.setdefault((f["minute"] - 1) // CARD_GAP_MIN, []).append(p)
        last_slot = max([*by_slot, *(int(g // 60) // CARD_GAP_MIN for g in self.goals)], default=-1)

        async def push(p, why, t=None):
            f = p["fact"] if t is None else {**p["fact"], "t": t}
            card = await card_for(f, insights, len(cards) + 1, self.ask, self.judge)
            if card is None:
                log.append(
                    {
                        "fact": f["id"],
                        "spotter": p["spotter"],
                        "decision": "refused",
                        "why": "no sentence passed the fact-check",
                    }
                )
                return False
            card["t"] = max(card["t"], cards[-1]["t"] if cards else 0.0)
            card["_players"] = [x for x in (f.get("passer"), f.get("receiver")) if x]
            cards.append(card)
            used.add(f["id"])
            log.append(
                {
                    "fact": f["id"],
                    "spotter": p["spotter"],
                    "decision": "pushed",
                    "why": why,
                    "card": card["id"],
                }
            )
            return True

        for slot in range(last_slot + 1):
            for g in [g for g in self.goals if int(g // 60) // CARD_GAP_MIN == slot]:
                build_up = [
                    p for p in pool if g - 60.0 <= p["fact"]["t"] <= g and p["fact"]["id"] not in used
                ]
                for p in sorted(build_up, key=lambda p: -p["confidence"]):
                    if await push(p, "goal jump: the build-up to a goal", g + GOAL_QUIET_S):
                        break
            queue = [(s0, p) for s0, p in queue if slot - s0 <= DEFER_SLOTS] + [
                (slot, p) for p in by_slot.get(slot, [])
            ]
            queue = [(s0, p) for s0, p in queue if p["fact"]["id"] not in used]
            if not queue:
                continue
            ordered = await self.order([p for _, p in queue], cards[-1] if cards else None)
            arrived = {p["fact"]["id"]: s0 for s0, p in queue}
            pushed = False
            for p in ordered:
                s0 = arrived[p["fact"]["id"]]
                if not pushed and await push(
                    p, "most notable in its slot" if s0 == slot else "deferred, then pushed"
                ):
                    pushed = True
                elif s0 == slot and p["fact"]["id"] not in used:
                    log.append(
                        {
                            "fact": p["fact"]["id"],
                            "spotter": p["spotter"],
                            "decision": "deferred",
                            "why": "the slot already had a card",
                        }
                    )
            queue = [(s0, p) for s0, p in queue if p["fact"]["id"] not in used]
        decided = {e["fact"] for e in log if e["decision"] in ("pushed", "dropped", "refused")}
        for _, p in queue:
            if p["fact"]["id"] not in decided:
                log.append(
                    {
                        "fact": p["fact"]["id"],
                        "spotter": p["spotter"],
                        "decision": "dropped",
                        "why": "deferred too long",
                    }
                )
        for c in cards:
            c.pop("_players", None)
        return cards

    async def record(self, ledger, cards: list[dict]) -> None:
        """The cards and every decision on the Ledger, each citing the fact it is about."""
        from ninety.agents.ledger import Record

        facts = {f["id"]: f for rows in self.insights.facts.values() for f in rows}
        cited = {e["fact"] for e in self.log if e.get("fact")} | {i for c in cards for i in c["evidence"]}
        for fid in sorted(cited):
            if fid in facts and await ledger.get(fid) is None:
                f = facts[fid]
                await ledger.append(
                    Record(fid, 1, "fact", float(f.get("t") or 0.0), "insights", None, (), dict(f))
                )
        for c in cards:
            await ledger.append(
                Record(
                    c["id"],
                    1,
                    "claim",
                    float(c["t"]),
                    "scout",
                    None,
                    tuple(c["evidence"]),
                    {**c, "status": "verified"},
                )
            )
        for n, e in enumerate(self.log, 1):
            evidence = (e["fact"],) if e.get("fact") in facts else ()
            await ledger.append(
                Record(f"decision:{n:05d}", 1, "decision", 0.0, "director", None, evidence, dict(e))
            )


def _where_x(card: Mapping) -> float | None:
    g = (card.get("visual") or {}).get("geometry") or {}
    for key in ("from", "ball", "passer"):
        if g.get(key):
            return float(g[key][0])
    if g.get("zone"):
        return (float(g["zone"]["x0"]) + float(g["zone"]["x1"])) / 2
    return None


def spoken(cards: Sequence[Mapping]) -> list[tuple[float, Description]]:
    """The audio description's insight lines: each pushed card's verified sentence, said once at
    its moment, placed in stereo where the play was (-1 the left touchline as the camera sees it,
    x = 0, to 1 at x = 105). The cards are already spaced by CARD_GAP_MIN, so the track says at
    most one insight sentence every three minutes, beside the event lines (ninety/speech/describe.py)."""
    out = []
    for c in cards:
        if c.get("status") != "verified":
            continue
        x = _where_x(c)
        pan = 0.0 if x is None else max(-1.0, min(1.0, x / 52.5 - 1.0))
        text = str(c.get("spoken") or c["text"])  # the text and where it was, in words
        out.append(
            (
                float(c["t"]),
                Description(c["id"], text, f"<speak>{escape(text)}</speak>", round(pan, 2), "code"),
            )
        )
    return out


def main(argv: list[str] | None = None) -> None:
    from ninety.intel.match_insights import MatchInsights

    ap = argparse.ArgumentParser(
        description="The Insight Scout's cards for a match, code-written and fact-checked."
    )
    ap.add_argument("insights", type=Path, help="a MatchInsights file (ninety.intel.match_insights --out)")
    ap.add_argument("--goals", type=Path, help="the clip's detected events, for the quiet after each goal")
    ap.add_argument("--out", type=Path, required=True)
    args = ap.parse_args(argv)
    mi = MatchInsights.from_dict(json.loads(args.insights.read_text()))
    goals = []
    if args.goals:
        from ninety.match import detected

        goals = [float(e["t"]) for e in detected.load(args.goals) if e["type"] == "goal"]
    log: list = []
    cards = asyncio.run(scout(mi, goals, log=log))
    args.out.write_text(json.dumps(cards, indent=1) + "\n")
    args.out.with_suffix(".log.json").write_text(json.dumps(log, indent=1) + "\n")
    print(f"{args.out}: {len(cards)} cards, {len(log)} decisions logged")


if __name__ == "__main__":
    main()
