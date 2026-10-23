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

Nothing is pushed within GOAL_QUIET_S after a detected goal: the screen belongs to the goal.

    uv run python -m ninety.agents.scout INSIGHTS.json --out cards.json
"""

from __future__ import annotations

import argparse
import asyncio
import json
from collections.abc import Mapping, Sequence
from pathlib import Path

from ninety.agents import companion_match as companion
from ninety.agents import insight_check
from ninety.agents.contracts import Ask, Judge, status_for
from ninety.agents.factcheck import Claim, parse_claim

CARD_GAP_MIN = 3  # design: at most one card every three match minutes, so a card is news, not noise
NOTABLE = 0.9  # design: a fact must rank above 90% of its kind so far (the top tenth)
MIN_SO_FAR = (
    10  # the top tenth needs ten facts of a kind to rank among (with fewer, NOTABLE cannot be reached)
)
GOAL_QUIET_S = 30.0  # design: no card in the half minute after a goal
HEADLINES = {
    "line_break": "{club} cut through",
    "overload": "{club} outnumber them",
    "counter_press": "{club} win it straight back",
    "pass_options": "An option missed",
}
WHY = {
    "line_break": "Why does a pass like that matter?",
    "overload": "Why does an overload matter?",
    "counter_press": "Why win it back so fast?",
    "pass_options": "What else was on?",
}
# What the "why?" answer adds to the card's fact: the definition, in code's words. Each is checked
# like any sentence, so it may state only the fact's own numbers with their units.
WHY_TEXT = {
    "line_break": "Every opponent a pass takes out of the game no longer stands between the ball and goal: "
    "this pass took out {value} {unit}.",
    "overload": "With {own} against {other} around the ball, {club} had a spare player there.",
    "counter_press": "Winning the ball back within 5 seconds of losing it stops the other side "
    "from breaking, "
    "and {club} had {value} {unit} near the ball.",
    "pass_options": "At the moment of that pass {club} had {value} open teammates ahead of the ball.",
}


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
    return ()


def _rank(fact: Mapping, so_far: Sequence[Mapping]) -> float:
    key = notability(fact)
    return sum(notability(g) < key for g in so_far) / len(so_far)


def candidates(insights, t_to: float) -> list[dict]:
    """Every confident fact up to t_to that ranks notable among its kind so far, oldest first."""
    out = []
    for kind, rows in insights.facts.items():
        seen = []
        for f in rows:
            if f["t"] > t_to:
                break
            seen.append(f)
            if kind == "overload" and f.get("third") == "own":
                continue  # design: an overload in a team's own third is its build-up, not news
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
            "why": {
                "question": WHY[fact["kind"]],
                "answer": {"status": "verified", "text": why, "evidence": [fact["id"]], "visual": visual},
            }
            if why_ok
            else None,
        }
    return None


async def scout(
    insights, goals: Sequence[float] = (), ask: Ask | None = None, judge: Judge | None = None
) -> list[dict]:
    """The match's cards, oldest first: per CARD_GAP_MIN of play, the most notable verified one."""
    pool = candidates(insights, float("inf"))
    cards: list[dict] = []
    last_min = -CARD_GAP_MIN
    slots: dict[int, list[dict]] = {}
    for f in pool:
        if any(0 <= f["t"] - g <= GOAL_QUIET_S for g in goals):
            continue
        slots.setdefault((f["minute"] - 1) // CARD_GAP_MIN, []).append(f)
    for slot in sorted(slots):
        if slot * CARD_GAP_MIN < last_min + CARD_GAP_MIN:
            continue
        last_kind = cards[-1]["kind"] if cards else None
        ranked = sorted(
            slots[slot],
            key=lambda f: (
                f["kind"] == last_kind,  # a different kind first: variety
                -_rank(f, [g for g in insights.facts[f["kind"]] if g["t"] <= f["t"]]),
                f["t"],
            ),
        )
        for f in ranked:
            card = await card_for(f, insights, len(cards) + 1, ask, judge)
            if card:
                cards.append(card)
                last_min = slot * CARD_GAP_MIN
                break
    return cards


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
    cards = asyncio.run(scout(mi, goals))
    args.out.write_text(json.dumps(cards, indent=1) + "\n")
    print(f"{args.out}: {len(cards)} cards")


if __name__ == "__main__":
    main()
