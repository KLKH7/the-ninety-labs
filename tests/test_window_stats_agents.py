"""The window stats on detected events, and how the agents read and check them.

The stand-in's values are worked by hand from its 16 events; the other tests read whichever M1
detections are in place (R3's once landed, else the stand-in), so they keep running on the real
detector output.
"""

import asyncio
import json

import pytest

from ninety.agents import live
from ninety.agents.factcheck import Claim, Verdict, check
from ninety.agents.ledger import InMemoryLedger, load_match
from ninety.intel.windows import agent_rows
from ninety.match import detected
from ninety.match.facts import AGENT_TYPES, compact
from ninety.mcp import match_server

STANDIN = detected.FIXTURES / "detected-standin-seed900001.jsonl"


def by_id(rows):
    return {r["id"]: r for r in rows}


def as_truth(events):
    return [{**e, "source": "truth", "confidence": None} for e in events]


def test_detected_and_ground_truth_events_give_the_same_stats():
    """One rule for both: the stats read only t, type, team and x, never the source."""
    events = detected.load(detected.m1_path())
    rows = agent_rows(events)
    assert {r["metric"] for r in rows} >= {"ppda", "field_tilt", "passes_per_minute"}
    assert agent_rows(as_truth(events)) == rows


def test_the_stand_in_by_hand():
    """Home passes 6 times by t = 101.5 s, the clip's last event: 6 / 1.69 min = 3.55 a minute.
    Home presses away, who defends x = 105: away's 4 passes at x >= 42 over home's one tackle
    there (x = 70.2) is a PPDA of 4. Away presses home: home's 5 passes at x <= 63 over away's one
    interception there (x = 47.2) is 5; the pass at 70.2 is outside the zone."""
    rows = by_id(agent_rows(detected.load(STANDIN)))
    assert rows["passes_per_minute:team_home_window_0"]["value"] == 3.55
    assert rows["ppda:team_home_window_0"]["value"] == 4.0
    assert rows["ppda:team_away_window_0"]["value"] == 5.0
    tilt = rows["field_tilt:team_home_window_0"]
    assert (tilt["value"], tilt["percent"], tilt["events"]) == (1.0, 100, 1)
    assert {(r["minute_from"], r["minute_to"]) for r in rows.values()} == {(1, 2)}


def ev(i, t, kind="pass", team="home", x=50.0):
    return {"id": f"e{i:03d}", "t": t, "type": kind, "team": team, "x": x, "y": 34.0}


def test_a_clip_that_stops_mid_window_measures_tempo_over_what_was_played():
    """Ten passes in two minutes is 5 a minute, not 10 over fifteen minutes (0.67)."""
    clip = [ev(i, 12.0 * i + 12.0) for i in range(10)]
    assert by_id(agent_rows(clip))["passes_per_minute:team_home_window_0"]["value"] == 5.0
    # A window the match played to its end keeps its full fifteen minutes.
    later = [*clip, ev(99, 1000.0, team="away")]
    rows = by_id(agent_rows(later))
    assert rows["passes_per_minute:team_home_window_0"]["value"] == 0.67
    assert rows["passes_per_minute:team_home_window_0"]["minute_to"] == 15
    assert rows["passes_per_minute:team_away_window_1"]["minute_from"] == 16


def test_the_ledger_and_the_mcp_server_carry_the_same_stats(monkeypatch):
    events = detected.load(STANDIN)
    ledger = InMemoryLedger()
    asyncio.run(load_match(ledger, events, ()))
    facts = {r.id: r for r in asyncio.run(ledger.query(kind="fact"))}
    rows = agent_rows(events)
    for row in rows:
        assert facts[row["id"]].payload["value"] == row["value"]
        assert len(facts[row["id"]].evidence) == row["events"]
    monkeypatch.setitem(match_server.DETECTED, detected.M1_CLIP, lambda: STANDIN)
    match_server.stats_of.cache_clear()
    match_server.events_of.cache_clear()
    try:
        assert match_server.match_info(detected.M1_CLIP)["stats"] == rows
    finally:
        match_server.stats_of.cache_clear()
        match_server.events_of.cache_clear()


def known_with_stats():
    events = detected.load(STANDIN)
    rows = [compact(e) for e in events if e["type"] in AGENT_TYPES]
    return {r["id"]: r for r in [*rows, *agent_rows(events)]}


PPDA = "ppda:team_home_window_0"
TILT = "field_tilt:team_home_window_0"


@pytest.mark.parametrize("text, evidence", [
    ("Home pressed hard: a PPDA of 4.0 by minute 2.", [PPDA]),
    ("Home played 100% of the attacking-third passes in minutes 1 to 2.", [TILT]),
    ("Home's field tilt was 1.0 against away's 0.0.", [TILT, "field_tilt:team_away_window_0"]),
])
def test_the_fact_checker_accepts_a_stats_own_numbers(text, evidence):
    assert check(Claim(text, evidence), known_with_stats()).ok


@pytest.mark.parametrize("text, evidence, reason", [
    ("Home pressed hard: a PPDA of 3.0.", [PPDA], "number 3.0"),
    ("Home pressed hard: a PPDA of 4.0 in minute 30.", [PPDA], "not a cited minute"),
    ("Home had 90% of the territory.", [TILT], "number 90"),
    ("h9 led a press with a PPDA of 4.0.", [PPDA], "player h9"),
    ("A PPDA of 4.0.", ["ppda:team_home_window_7"], "unknown event ids"),
    # How many events a stat counts is shown for context, not a number a claim may state.
    ("Home's PPDA of 4.0 rests on 5 events.", [PPDA], "number 5"),
])
def test_the_fact_checker_rejects_a_number_no_cited_stat_has(text, evidence, reason):
    verdict = check(Claim(text, evidence), known_with_stats())
    assert not verdict.ok and any(reason in r for r in verdict.reasons), verdict.reasons


def test_a_verified_stat_claim_airs_citing_the_events_the_stat_counts():
    events = detected.load(STANDIN)

    async def ask(prompt):
        return json.dumps({"text": "Home pressed hard: a PPDA of 4.0 by minute 2.", "evidence": [PPDA]})

    async def judge(claim, evidence):
        assert [e["id"] for e in evidence] == [PPDA]
        return Verdict(ok=True)

    result = asyncio.run(live.run(events, ask=ask, judge=judge, minute=2))
    assert result.outcome.accepted
    cue = next(c for c in result.cues if c["kind"] == "insight")
    counted = {e["id"] for e in events if e["type"] in {"pass", "tackle", "interception"}}
    ppda = by_id(agent_rows(events))[PPDA]
    assert len(cue["evidence"]) == ppda["events"] and set(cue["evidence"]) <= counted
    assert cue["t_in"] == max(e["t"] for e in events if e["id"] in cue["evidence"])
