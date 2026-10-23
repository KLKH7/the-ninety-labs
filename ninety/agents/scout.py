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
    "line_break": "{club} slice through",
    "overload": "{club} have the extra man",
    "counter_press": "{club} win it straight back",
    "pass_options": "A pass not taken",
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
    "line_break": "Analysts call it packing: every opponent a pass gets past no longer stands between the "
    "ball and goal, and this pass took out {value} {unit}.",
    "overload": "With {own} against {other} around the ball, {club} had a spare player there.",
    "counter_press": "Winning the ball back within 5 seconds of losing it stops the other side "
    "from breaking, "
    "and {club} had {value} {unit} near the ball.",
    "pass_options": "At the moment of that pass {club} had {value} open teammates further forward.",
}


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
    return ()


def _rank(fact: Mapping, so_far: Sequence[Mapping]) -> float:
    key = notability(fact)
    return sum(notability(g) < key for g in so_far) / len(so_far)


def candidates(insights, t_to: float) -> list[dict]:
    """Every confident fact up to t_to that ranks notable among its kind so far, oldest first."""
    out = []
    for kind, rows in insights.facts.items():
        if kind not in HEADLINES:  # shape facts answer questions; the Scout does not push them
            continue
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
            "why": {
                "question": WHY[fact["kind"]],
                "answer": {"status": "verified", "text": why, "evidence": [fact["id"]], "visual": visual},
            }
            if why_ok
            else None,
        }
    return None


async def spot(kind: str, insights, t_to: float) -> list[dict]:
    """One spotter: the notable confident facts of its kind up to t_to (see `candidates`)."""
    return [f for f in candidates(insights, t_to) if f["kind"] == kind]


async def scout(
    insights,
    goals: Sequence[float] = (),
    ask: Ask | None = None,
    judge: Judge | None = None,
    log: list | None = None,
) -> list[dict]:
    """The match's cards, oldest first, and (into `log`) every decision the Director made.

    One spotter per kind proposes in parallel (`spot`); the Director decides, slot by slot of
    CARD_GAP_MIN match minutes:
    - cap: at most one card a slot;
    - no repeats: a candidate of the last card's kind, or about the last card's player, goes last;
    - goal jump: after a goal, the most notable fact of the minute before it is pushed at the end
      of the quiet, whatever the cap (a goal is when a fan wants the why);
    - deferral: a candidate the cap kept out waits in a queue for DEFER_SLOTS slots, then is dropped;
    - logged: each candidate's fate (pushed, deferred, dropped, refused by the fact-check), with why.
    """
    log = [] if log is None else log
    pools = await asyncio.gather(*(spot(k, insights, float("inf")) for k in insights.facts if k in HEADLINES))
    pool = sorted((f for rows in pools for f in rows), key=lambda f: (f["t"], f["id"]))
    so_far = {k: rows for k, rows in insights.facts.items()}

    def rank(f):
        return _rank(f, [g for g in so_far[f["kind"]] if g["t"] <= f["t"]])

    cards: list[dict] = []
    used: set[str] = set()
    queue: list[tuple[int, dict]] = []  # (slot it arrived in, fact)
    jumps = sorted(goals)
    by_slot: dict[int, list[dict]] = {}
    for f in pool:
        if any(0 <= f["t"] - g <= GOAL_QUIET_S for g in goals):
            log.append({"fact": f["id"], "decision": "dropped", "why": "in the quiet after a goal"})
            continue
        by_slot.setdefault((f["minute"] - 1) // CARD_GAP_MIN, []).append(f)
    last_slot = max([*by_slot, *(int(g // 60) // CARD_GAP_MIN for g in jumps)], default=-1)

    async def push(f, why):
        card = await card_for(f, insights, len(cards) + 1, ask, judge)
        if card is None:
            log.append({"fact": f["id"], "decision": "refused", "why": "no sentence passed the fact-check"})
            return False
        card["t"] = max(card["t"], cards[-1]["t"] if cards else 0.0)
        cards.append(card)
        used.add(f["id"])
        log.append({"fact": f["id"], "decision": "pushed", "why": why, "card": card["id"]})
        return True

    for slot in range(last_slot + 1):
        # A goal in this slot: its build-up jumps the cap.
        for g in [g for g in jumps if int(g // 60) // CARD_GAP_MIN == slot]:
            build_up = [f for f in pool if g - 60.0 <= f["t"] <= g and f["id"] not in used]
            for f in sorted(build_up, key=lambda f: -rank(f)):
                if await push({**f, "t": g + GOAL_QUIET_S}, "goal jump: the build-up to a goal"):
                    break
        fresh = [(slot, f) for f in by_slot.get(slot, [])]
        queue = [(s0, f) for s0, f in queue if slot - s0 <= DEFER_SLOTS] + fresh
        if not queue:
            continue
        last = cards[-1] if cards else None

        def order(item, last=last):
            _, f = item
            repeat = last is not None and (
                f["kind"] == last["kind"]
                or (f.get("passer") and f.get("passer") in (last.get("players") or ()))
            )
            return (repeat, -rank(f), f["t"])

        pushed = False
        for s0, f in sorted(queue, key=order):
            if f["id"] in used:
                continue
            if not pushed and await push(
                f, "most notable in its slot" if s0 == slot else "deferred, then pushed"
            ):
                pushed = True
                if cards:
                    cards[-1]["players"] = [p for p in (f.get("passer"), f.get("receiver")) if p]
                continue
            if s0 == slot:
                log.append({"fact": f["id"], "decision": "deferred", "why": "the slot already had a card"})
        queue = [(s0, f) for s0, f in queue if f["id"] not in used]
    dropped = {e["fact"] for e in log if e["decision"] in ("pushed", "dropped", "refused")}
    for _, f in queue:
        if f["id"] not in dropped:
            log.append({"fact": f["id"], "decision": "dropped", "why": "deferred too long"})
    for c in cards:
        c.pop("players", None)
    return cards


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
