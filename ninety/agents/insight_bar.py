"""The big screen's INSIGHT bar: what the broadcast can't show, never a restatement of one event.

    cues, claims = await insight_bar.build(mi, timeline, sure, clubs)

Its candidates are the match's insight facts (ninety/intel/match_insights.py), each computed by code
from tracked positions and detected events: a goal and what led to it, a counter-attack, a pass that
took opponents out of the game, an overload around the ball, a team winning the ball straight back,
open teammates a pass ignored, a long run of passing. Each is said in the Companion's words for it
(ninety/agents/companion_match.code_texts) and goes through the same fact-check before it airs (the
code checks and the fact's own words, `_verify`); a fact that is unsure, or whose sentence fails, never
airs. What a single pass or shot was is the audio description's, not the bar's.

Rate: the most significant first, at most one every MIN_GAP_S of footage (the video's clock, so a
condensed match's cuts do not crowd them), and none below MIN_SIGNIFICANCE: silence beats filler. A
goal always airs.

A player is named by the names the bundle passes in (`names`, by track: the player-ID feed's, which
only the e2e path reads, tests/test_identity_feed.py), by his club otherwise; never by a track id,
never by a name the feed does not give, and never as "a player... another player" when his side is
known.
Each insight gets its own claim trace (How we know): the fact it came from, the check, the airing.
"""

from __future__ import annotations

from collections.abc import Callable

from ninety.agents import companion_match as cm
from ninety.agents import onair
from ninety.agents.factcheck import Claim

# Design (the Coordinator's brief, Oct 26): about one insight a minute of footage at most; a goal and
# its build-up first, then a counter, then how many opponents a pass took out, a run of passing, an
# overload, a regain, an ignored open teammate. The weights only order them; each still needs its own
# confident fact and a sentence that passes the check.
MIN_GAP_S = 50.0
MIN_SIGNIFICANCE = 30.0
DISPLAY_S = 8.0
SLOT = "lower_third"
SIGNIFICANCE: dict[str, Callable[[dict], float]] = {
    "goal": lambda f: 100.0,
    "counter": lambda f: 70.0,
    "line_break": lambda f: 10.0 * f["value"],  # 4 opponents or more clears the bar
    "spell": lambda f: 6.0 * f["value"],  # 5 passes in a row or more
    "overload": lambda f: 6.0 * f["value"],  # 5 extra players or more
    "counter_press": lambda f: 12.0 * f["value"] if f.get("regained") else 0.0,  # won straight back
    "pass_options": lambda f: 6.0 * f["value"] if f.get("outcome") == "fail" else 0.0,
}


NAME_FIELDS = {"passer_is": "passer", "receiver_is": "receiver", "player_is": "player", "scorer_is": "player",
               "assister_is": "assister"}


def _named(fact: dict, names: dict) -> dict:
    """The fact with each player it names said by the ID feed's name for his track, or by no name (his
    club, in the sentence) when the feed does not name him: the bar names no one the feed does not."""
    out = dict(fact)
    for field_, role in NAME_FIELDS.items():
        if field_ not in fact and role not in fact:
            continue
        track = fact.get(role)
        named = names.get(track) if isinstance(track, str) else None
        out[field_] = named or None
    return out


def feed_named(mi, names: dict):
    """The match's insights with every name the facts carry replaced by `names`' (or none)."""
    from dataclasses import replace

    facts = {k: [_named(r, names) if isinstance(r, dict) else r for r in rows]
             for k, rows in mi.facts.items()}
    return replace(mi, facts=facts)


def _spell_text(fact: dict) -> str:
    whose = f"{fact['club']} strung" if fact.get("club") else "one side strung"
    return f"In minute {fact['minute']}, {whose} {fact['value']} passes together in a row."


def _goal_story(mi, goal: dict) -> str | None:
    """The goal and the strongest thing that led to it, as the Companion tells it when asked why that
    goal happened (its code path, checked there), asked just after the goal."""
    from ninety.agents.companion import Question

    answer, _ = cm.code_match_answer(Question("insight-bar", None, "Why did that goal happen?",
                                              float(goal["t"]) + 1.0), mi, suggest=False)
    if answer.status != "verified" or f"minute {goal['minute']}" not in answer.text:
        return None
    return answer.text


def _events(fact: dict) -> list[str]:
    ids = fact.get("events") or [fact.get("event")]
    return [i for i in ids if isinstance(i, str)]


def candidates(mi, names: dict | None = None) -> list[tuple[float, dict, str]]:
    """Every insight the bar may air: (significance, fact, its checked sentence), most significant
    first; a fact without a confident row or a sentence that passes the check is not one."""
    out = []
    for kind, weight in SIGNIFICANCE.items():
        for row in mi.facts.get(kind, ()):
            if not isinstance(row, dict) or not row.get("confident") or row.get("t") is None:
                continue
            score = weight(row) if row.get("value") is not None or kind in ("goal",) else 0.0
            if score < MIN_SIGNIFICANCE:
                continue
            fact = _named({**row, "clubs": mi.fixture.clubs}, names or {})
            if kind == "goal":
                story = _goal_story(mi, fact)
                if story is not None:
                    out.append((score, fact, story))
                    continue
            texts = [_spell_text(fact)] if kind == "spell" else cm.code_texts(fact)
            text = next((t for t in texts if cm._verify(Claim(t, [fact["id"]]), {fact["id"]: fact}, mi).ok),
                        None)
            if text is not None:
                out.append((score, fact, text))
    out.sort(key=lambda c: (-c[0], c[1]["t"]))
    return out


def build(mi, to_video: Callable[[float], float], sure, clubs,
          names: dict | None = None) -> tuple[list[dict], list[dict]]:
    """The INSIGHT bar's cues and their claim traces, from the match's insight facts; `names` is the
    feed's name for each track it names (the e2e path reads the feed, never this module)."""
    names = names or {}
    mi = feed_named(mi, names)
    chosen: list[tuple[float, dict, str]] = []
    for score, fact, text in candidates(mi, names):
        v = to_video(float(fact["t"]))
        # A goal always airs, however close to another: everything else keeps its distance.
        if fact["kind"] == "goal" or all(abs(v - to_video(float(f["t"]))) >= MIN_GAP_S for _, f, _ in chosen):
            chosen.append((score, fact, text))
    cues, claims = [], []
    for score, fact, text in sorted(chosen, key=lambda c: c[1]["t"]):
        shown = onair.render(text, sure, clubs)  # never a track id, even one a sentence might carry
        t_in = round(float(fact["t"]), 2)
        evidence = _events(fact)
        cues.append({"id": f"insight-{fact['id']}", "t_in": t_in, "t_out": round(t_in + DISPLAY_S, 2),
                     "kind": "insight", "slot": SLOT, "anchor": None, "persona": "analyst", "lang": "en",
                     "text": shown, "verified": True, "replaces": None, "evidence": evidence})
        claims.append({
            "id": f"bar-{fact['id']}", "minute": fact["minute"], "t": t_in, "status": "accepted",
            "verdict": "verified", "drafts": 1, "author": "analyst", "attempts": {}, "planted": False,
            "mode": "insight bar (code)", "text": shown, "evidence": evidence,
            "steps": [
                {"role": "analyst", "moment": fact["id"], "action": "pick", "ms": 0.0,
                 "detail": f"the {fact['kind'].replace('_', ' ')} fact {fact['id']}, significance {score:g}, "
                           f"computed by code from tracked positions and detected events"},
                {"role": "fact_checker", "moment": fact["id"], "action": "verify", "ms": 0.0,
                 "detail": "the code checks and the fact's own words: every number and name is the fact's"},
                {"role": "producer", "moment": fact["id"], "action": "air", "ms": 0.0,
                 "detail": f"on the INSIGHT bar, at least {MIN_GAP_S:g} s of footage from the next"},
            ],
        })
    return cues, claims


def restates_one_event(cue: dict, kinds: dict[str, str]) -> bool:
    """Whether an insight cue only says what one pass or shot was (the agents' single-event claim):
    the audio description's to say, never the bar's."""
    ev = cue.get("evidence") or []
    return cue.get("kind") == "insight" and len(ev) == 1 and kinds.get(ev[0]) in ("pass", "shot", "goal")
