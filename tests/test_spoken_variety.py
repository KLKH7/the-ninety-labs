"""The spoken tracks after the demo audit (docs/LESSONS.md, lesson 261): every goal said as a goal and in
order, a run of passes said once as a spell, the same words not said again within half a minute, and
no speed a kick cannot give, in a graphic, a line or a rewrite."""

import asyncio
import json

from ninety.agents import cues
from ninety.agents.factcheck import Claim, check
from ninety.speech import commentary, describe, spells

CLUBS = {"home": "London", "away": "Lisbon"}


def ev(i, t, kind, player=None, receiver=None, outcome=None, side=0.99, conf=0.9, x=60.0, **kw):
    out = {"id": i, "t": t, "type": kind, "team": "home", "team_confidence": side, "player": player,
           "x": x, "y": 34.0, "source": "vision", "confidence": conf, "outcome": outcome, **kw}
    if receiver:
        out |= {"receiver": receiver, "end_x": x + 8, "end_y": 34.0}
    return out


def chain(n, t0=10.0, conf=0.9, side=0.99):
    """n completed passes, each receiver playing the next one."""
    return [ev(f"p{i}", t0 + 2.0 * i, "pass", f"h-t{i}", f"h-t{i + 1}", "success", side=side, conf=conf)
            for i in range(n)]


def said(events, cue_list=()):
    track, _ = describe.describe(events, list(cue_list), clubs=CLUBS)
    return [(s.event, s.spoken) for s in track.said]


def called(events, cue_list=()):
    return [li["text"] for li in commentary.commentary(events, list(cue_list), CLUBS)["lines"]]


# ---------------------------------------------------------------- goals


SHOT_THEN_GOAL = [ev("s1", 100.0, "shot", "h-t9", outcome="goal", x=95.0), ev("g1", 100.4, "goal", x=95.0)]


def test_a_shot_its_goal_follows_is_not_said_before_the_goal():
    # The 70:36 defect: "Goal!" then "A shot." 2 s later, and the AD's "shoots from the right" alone.
    assert [e for e, _ in said(SHOT_THEN_GOAL)] == ["g1"]
    assert called(SHOT_THEN_GOAL) == ["Goal! London score!"]


def test_a_shot_that_went_in_with_no_goal_event_is_said_as_the_goal():
    shot = [ev("s1", 100.0, "shot", "h-t9", outcome="goal", x=95.0)]
    assert said(shot)[0][1].startswith("Goal! ")
    assert called(shot) == ["Goal! London score!"]


def test_a_goal_with_a_verified_claim_is_said_as_a_goal_and_not_crowded_out_by_its_shot():
    # The 67:08 defect: the claim ("a player scores.") took the goal's place at a claim's priority,
    # and the shot line before it pushed it out, so the goal was never said.
    events = [ev("s1", 100.0, "shot", "h-t9", outcome="on_target", x=95.0),
              ev("g1", 100.8, "goal", "h-t9", x=95.0)]
    claim = {"id": "insight-m-g1", "kind": "insight", "verified": True, "t_in": 100.8, "persona": "analyst",
             "text": "h-t9 scores.", "evidence": ["g1"]}
    lines = said(events, [claim])
    assert any(e == "g1" and words.startswith("Goal! A London player scores") for e, words in lines), lines


# ---------------------------------------------------------------- spells


def test_a_chain_of_completed_passes_is_one_spell():
    found = spells.spells(chain(6))
    assert [len(s) for s in found] == [6]
    assert spells.spells(chain(spells.MIN_PASSES - 1)) == []


def test_a_spell_breaks_at_an_unsure_or_unfinished_pass_or_a_new_passer():
    events = chain(5)
    events[2] = events[2] | {"confidence": 0.3}
    assert spells.spells(events) == []  # two passes, then two: neither is a spell
    events = chain(5)
    events[3] = events[3] | {"player": "h-t99"}  # not the last receiver
    assert spells.spells(events) == []
    events = chain(9)
    events[4] = events[4] | {"outcome": "fail"}
    assert [len(s) for s in spells.spells(events)] == [4, 4]


def test_a_spell_is_said_once_with_its_count_and_checked():
    lines = said(chain(6))
    spoken = [w for _, w in lines]
    # The first pass, then the spell.
    assert spoken[-1] == "6 passes in a row for London, in the middle." and len(spoken) == 2
    ids = [e["id"] for e in chain(6)]
    assert check(Claim("6 passes in a row.", ids), {e["id"]: e for e in chain(6)}).ok
    assert not check(Claim("7 passes in a row.", ids), {e["id"]: e for e in chain(6)}).ok
    assert "6 passes in a row for London, in the middle." in called(chain(6))


def test_a_spell_names_no_side_it_was_not_told_surely():
    assert [w for _, w in said(chain(5, side=0.5))][-1] == "5 passes in a row, in the middle."
    assert "5 passes in a row, in the middle." in called(chain(5, side=0.5))


# ---------------------------------------------------------------- repeats


def test_a_pass_line_in_the_same_words_is_not_said_again_within_half_a_minute():
    # Unnamed players: every completed pass is "A player finds another player, ..." (the audit's x20).
    passes = [ev(f"p{i}", 10.0 + 8.0 * i, "pass", f"h-t{10 * i}", f"h-t{10 * i + 5}", "success", side=0.5)
              for i in range(5)]
    times = [t for t, _ in [(e["t"], e) for e in passes]]
    lines = said(passes)
    assert len(lines) == 2  # 10 s, then 42 s: the ones between repeat the 10 s line within REPEAT_S
    assert describe.REPEAT_S == 30.0 and times[-1] - times[0] > describe.REPEAT_S


def test_the_voice_says_an_before_eight_and_eleven_and_a_capital_after_a_full_stop():
    assert describe.spoken("a-t1 plays a 8 m pass.", False) == "A player plays an 8-metre pass."
    assert describe.spoken("a-t1 plays a 11 m pass.", False) == "A player plays an 11-metre pass."
    assert describe.spoken("a-t1 plays a 12 m pass.", False) == "A player plays a 12-metre pass."
    assert describe.spoken("Goal! a-t1 scores.", False) == "Goal! A player scores."


# ---------------------------------------------------------------- speeds no kick gives


def test_a_graphic_never_shows_a_speed_no_kick_can_give():
    fast = ev("p1", 10.0, "pass", "h-t1", "h-t2", "success", ball_speed_kmh=137.2, distance_m=19)
    text = cues._text(fast, "analyst")
    assert "km/h" not in text and check(Claim(text, ["p1"]), {"p1": fast}).ok
    assert "100.0 km/h" in cues._text(fast | {"ball_speed_kmh": 100.0}, "analyst")


def test_the_offline_writer_sent_back_for_a_speed_says_it_again_without_it():
    from ninety import e2e

    fast = ev("p1", 10.0, "pass", "h-t1", "h-t2", "success", ball_speed_kmh=100.0, distance_m=19, minute=1,
              second=10)
    models = e2e.offline_models([fast])
    moment = {"moment": {"main_event": "p1"}}
    first = json.loads(asyncio.run(models.tactician(json.dumps(moment))))["text"]
    again = json.loads(asyncio.run(models.tactician(json.dumps(
        moment | {"rejected": {"reasons": ["implausible speed: 100 km/h ..."]}}))))["text"]
    assert "km/h" in first and "km/h" not in again
