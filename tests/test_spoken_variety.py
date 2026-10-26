"""The spoken tracks after the demo audit (docs/LESSONS.md, lesson 261): every goal said as a goal and in
order, a run of passes said once as a spell, the same words not said again within half a minute, and
no speed a kick cannot give, in a graphic, a line or a rewrite."""

import asyncio
import json

import pytest

from ninety.agents import cues
from ninety.agents.factcheck import WITHOUT_SPEED, Claim, check
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
    # A possible speed is shown from the simulator; vision's waits for its measured error (SPEED_MEASURED).
    assert "100.0 km/h" in cues._text(fast | {"ball_speed_kmh": 100.0, "confidence": None}, "analyst")
    assert "km/h" not in cues._text(fast | {"ball_speed_kmh": 100.0}, "analyst")


def test_visions_speed_airs_only_for_a_pass_it_marks_on_the_ground(monkeypatch):
    from ninety.agents import factcheck
    from ninety.agents.contracts import status_for
    from ninety.agents.workflow import sent_back

    seen = ev("p1", 10.0, "pass", "h-t1", "h-t2", "success", ball_speed_kmh=60.0, distance_m=19, minute=1,
              second=10, clock="00:10")
    claim = Claim("h-t1 plays it 19 m to h-t2, at 60 km/h.", ["p1"])
    gate = factcheck.confidence_gate
    # Today vision's ground mark is not measured (the band was split by the true height): held.
    held = gate(claim, {"p1": seen | {"lofted": False}})
    assert status_for(held) == "held" and "ground mark is not measured" in held.reasons[0]
    monkeypatch.setattr(factcheck, "LOFTED_FLAG_MEASURED", True)
    assert gate(claim, {"p1": seen | {"lofted": False}}).ok  # measured: a pass along the ground
    # In digits with km/h only: any other form would air with no band on screen.
    for other in ("h-t1 plays it 19 m to h-t2, at sixty km/h.", "h-t1 plays it 19 m to h-t2, at 60 kmh."):
        verdict = gate(Claim(other, ["p1"]), {"p1": seen | {"lofted": False}})
        assert status_for(verdict) == "held" and "digits" in verdict.reasons[-1], other
    for unmeasured, why in ((seen, "not marked on the ground"), (seen | {"lofted": True}, "in the air"),
                            (seen | {"lofted": False, "type": "shot"}, "not a pass")):
        verdict = gate(claim, {"p1": unmeasured})
        assert status_for(verdict) == "held" and why in verdict.reasons[0], unmeasured
        assert verdict.reasons[0].endswith(factcheck.WITHOUT_SPEED) and sent_back(verdict)
    assert gate(Claim("h-t1 plays it 19 m to h-t2.", ["p1"]), {"p1": seen}).ok  # no speed stated
    assert gate(claim, {"p1": seen | {"confidence": None}}).ok  # the simulator's
    monkeypatch.setattr(factcheck, "SPEED_MEASURED", False)
    assert status_for(gate(claim, {"p1": seen | {"lofted": False}})) == "held"
    # A hold the writer cannot fix (an unsure detection) is still not sent back.
    unsure = gate(Claim("h-t1 plays it 19 m to h-t2.", ["p1"]), {"p1": seen | {"confidence": 0.2}})
    assert status_for(unsure) == "held" and not sent_back(unsure)


def test_the_speed_band_is_the_measured_p90_for_ground_passes_rounded_up():
    import math
    from pathlib import Path

    from ninety.agents import factcheck

    path = Path(__file__).resolve().parents[1] / "docs/eval/speed-report-freeze.json"
    report = json.loads(path.read_text())
    ground = report["pooled"]["event_speed"]["pass, along the ground"]
    assert ground["enough"] and factcheck.SPEED_ERROR_KMH == math.ceil(ground["p90_abs_kmh"]) == 8
    assert not report["pooled"]["event_speed"]["pass, lofted"]["enough"]  # why a lofted pass is held
    assert not report["pooled"]["event_speed"]["shot"]["enough"]


def test_a_graphic_shows_a_measured_speed_and_the_schema_and_facts_carry_lofted(monkeypatch):
    from jsonschema import validate

    from ninety.agents import factcheck
    from ninety.match.facts import compact

    ground = ev("p1", 10.0, "pass", "h-t1", "h-t2", "success", ball_speed_kmh=60.0, distance_m=19,
                lofted=False)
    assert "km/h" not in cues._text(ground, "analyst")  # the ground mark is not measured yet
    monkeypatch.setattr(factcheck, "LOFTED_FLAG_MEASURED", True)
    assert "60.0 km/h" in cues._text(ground, "analyst")
    assert "km/h" not in cues._text(ground | {"lofted": True}, "analyst")
    assert "km/h" not in cues._text(ground | {"ball_speed_kmh": 150.0}, "analyst")  # never above the cap
    assert compact(ground)["lofted"] is False and "lofted" not in compact(ground | {"lofted": None})
    from pathlib import Path

    schema = json.loads((Path(__file__).resolve().parents[1] / "schemas/match_event.schema.json").read_text())
    row = {k: v for k, v in ground.items() if k != "distance_m"}
    for lofted in (False, True, None):
        validate(row | {"lofted": lofted}, schema)
    from jsonschema import ValidationError

    with pytest.raises(ValidationError):
        validate(row | {"lofted": "no"}, schema)


def test_the_offline_writer_sent_back_for_a_speed_says_it_again_without_it():
    from ninety import e2e

    fast = ev("p1", 10.0, "pass", "h-t1", "h-t2", "success", ball_speed_kmh=100.0, distance_m=19, minute=1,
              second=10)
    models = e2e.offline_models([fast])
    moment = {"moment": {"main_event": "p1"}}
    first = json.loads(asyncio.run(models.tactician(json.dumps(moment))))["text"]
    again = json.loads(asyncio.run(models.tactician(json.dumps(
        moment | {"rejected": {"reasons": [f"implausible speed: 100 km/h ...: {WITHOUT_SPEED}"]}}))))["text"]
    assert "km/h" in first and "km/h" not in again


# ---------------------------------------------------------------- the independent review's cases


def test_a_shot_is_not_skipped_for_a_goal_that_will_not_be_said():
    # The goal event is under the confidence gate: the shot that went in is said as the goal instead.
    events = [ev("s1", 100.0, "shot", "h-t9", outcome="goal", x=95.0),
              ev("g1", 100.4, "goal", x=95.0, conf=0.3)]
    assert [w for _, w in said(events)][0].startswith("Goal! ")
    assert called(events) == ["Goal! London score!"]


def test_a_goal_long_after_its_shot_is_said_once_and_a_goal_after_more_play_is_not_the_shots():
    late = [ev("s1", 100.0, "shot", "h-t9", outcome="goal", x=95.0), ev("g1", 103.5, "goal", x=95.0)]
    assert [e for e, _ in said(late)] == ["g1"] and called(late) == ["Goal! London score!"]
    between = [late[0], ev("p1", 101.0, "pass", "h-t2", "h-t3", "success"), late[1]]
    assert "s1" in describe.scored_by(late) and describe.scored_by(between) == set()


def test_a_spell_ends_at_any_other_event_or_a_long_gap():
    passes = chain(6)
    shot = ev("x1", passes[2]["t"] + 0.5, "shot", "h-t3", outcome="off_target")
    assert spells.spells([*passes, shot]) == []  # 3 passes, then 3: neither is a spell
    gap = [p | {"t": p["t"] + (spells.MAX_GAP_S + 1 if i >= 3 else 0)} for i, p in enumerate(passes)]
    assert spells.spells(gap) == []


def test_a_spell_names_a_side_only_when_every_pass_is_that_sides():
    mixed = chain(5)
    mixed[2] = mixed[2] | {"team": "away"}
    assert spells.versions(mixed, "in the middle")[0] == "5 passes in a row, in the middle."
    assert spells.versions(chain(5), "in the middle")[0] == "5 passes in a row for home, in the middle."


def test_two_interceptions_or_two_corners_in_half_a_minute_are_both_said():
    wins = [ev("i1", 10.0, "interception", "h-t1", side=0.5),
            ev("i2", 25.0, "interception", "h-t7", side=0.5)]
    assert len(said(wins)) == 2
    corners = [ev("c1", 10.0, "set_piece", restart="corner"),
               ev("c2", 30.0, "set_piece", restart="corner")]
    assert len(said(corners)) == 2 and called(corners) == ["Corner to London.", "Corner to London."]


def test_an_out_of_play_that_is_not_called_does_not_silence_the_next_one():
    events = [ev("o1", 10.0, "out_of_play", source="truth"), ev("o2", 20.0, "out_of_play")]
    assert called(events) == [commentary.OUT_SAID[0]]
    # Given out of order, the calls are still made in time order.
    backwards = [ev("o2", 50.0, "out_of_play"), ev("o1", 10.0, "out_of_play")]
    assert called(backwards) == list(commentary.OUT_SAID[:2])


def test_the_voice_says_an_before_every_number_said_with_a_vowel():
    for n, art in [("8", "an"), ("8.5", "an"), ("11", "an"), ("18", "an"), ("80", "an"), ("85", "an"),
                   ("800", "an"), ("8000", "an"), ("11000", "an"), ("18000", "an"), ("12", "a"),
                   ("1", "a"), ("100", "a"), ("110", "a"), ("1800", "a"), ("90", "a")]:
        assert describe._article(n) == art, n


def test_a_shot_that_went_in_is_placed_as_a_goal():
    lines, _ = describe.candidates([ev("s1", 100.0, "shot", "h-t9", outcome="goal", x=95.0)], [])
    assert [line.priority for line in lines] == [describe.PRIORITY["goal"]]


def test_a_shot_graphic_never_shows_visions_speed_until_it_is_measured():
    shot = ev("s1", 100.0, "shot", "h-t9", outcome="on_target", ball_speed_kmh=100.0)
    assert "km/h" not in cues._text(shot, "analyst")
    assert "100.0 km/h" in cues._text(shot | {"confidence": None}, "analyst")


def test_onair_keeps_only_the_speeds_a_cited_event_may_state_and_leaves_tidy_text():
    from ninety.agents import onair

    sim = {"id": "p1", "type": "pass", "ball_speed_kmh": 61.4, "confidence": None}  # the simulator's
    shot = {"id": "s1", "type": "shot", "ball_speed_kmh": 101.0, "confidence": 0.9}  # vision's, held
    assert onair.speeds("it went at 61 km/h, then 61.4 km/h", [sim]) == "it went at 61 km/h, then 61.4 km/h"
    assert onair.speeds("Shot speed: 101 km/h.", [shot]) == "Shot speed."
    assert onair.speeds("h1 shot (101 km/h) wide.", [shot]) == "h1 shot wide."
    assert onair.speeds("h1 shoots at 101 kmh.", [shot]) == "h1 shoots."
    assert onair.speeds("h1 shoots, 101 k.p.h., on target.", [shot]) == "h1 shoots, on target."
    cue_rows = [{"id": "c1", "text": "h1 shoots at 101 km/h.", "evidence": ["s1"]}]
    claims = [{"id": "m1", "text": "h1 shoots at 101 km/h.", "evidence": ["s1"],
               "steps": [{"detail": "'h1 shoots at 101 km/h.' evidence=['s1']"}]}]
    rows, traced = onair.gate_speeds(cue_rows, claims, [shot])
    assert rows[0]["text"] == "h1 shoots." and traced[0]["text"] == "h1 shoots."
    assert "101" not in traced[0]["steps"][0]["detail"]


# ---------------------------------------------------------------- radio-style: names, the score, chances


NAMES = {"h-t9": "Rondell", "h-t1": "Carrick"}
# The scorebug read 1-1 before the goal and 2-1 at it: only a reading that differs from the one before
# it follows a goal with a score.
SCORES = [{"t": 0.0, "home": 1, "away": 1, "confident": True},
          {"t": 100.4, "home": 2, "away": 1, "confident": True}]


def test_the_voices_name_a_player_by_the_feed_and_say_the_score_after_a_goal():
    goal = [ev("g1", 100.4, "goal", "h-t9", x=95.0)]
    track, _ = describe.describe(goal, [], clubs=CLUBS, names=NAMES, scores=SCORES)
    assert [s.spoken for s in track.said] == ["Goal! Rondell scores, on the right. London lead 2–1."]
    calls = [li["text"] for li in commentary.commentary(goal, [], CLUBS, names=NAMES, scores=SCORES)["lines"]]
    assert calls == ["Goal! Rondell scores! London lead 2–1."]
    # Without the feed, his club; without a reading, no score: never counted from goals.
    track, _ = describe.describe(goal, [], clubs=CLUBS)
    assert [s.spoken for s in track.said] == ["Goal! A London player scores, on the right."]
    assert called(goal) == ["Goal! London score!"]


def test_a_pass_is_said_with_the_feeds_names_and_a_level_score_as_level():
    passes = [ev("p1", 10.0, "pass", "h-t1", "h-t9", "success", side=0.5)]
    track, _ = describe.describe(passes, [], clubs=CLUBS, names=NAMES)
    assert track.said[0].spoken.startswith("Carrick finds Rondell")
    assert describe.score_said((1, 1), CLUBS) == "It's 1–1."
    assert describe.score_said((0, 2), CLUBS) == "Lisbon lead 2–0."


def test_a_shot_on_target_is_a_big_chance():
    shot = [ev("s1", 100.0, "shot", "h-t9", outcome="on_target", x=95.0)]
    assert said(shot)[0][1].startswith("Big chance! ")
    calls = [li["text"] for li in commentary.commentary(shot, [], CLUBS, names=NAMES)["lines"]]
    assert calls == ["Big chance! Rondell shoots, on target!"]


def test_a_goal_beside_a_scorebug_that_did_not_change_is_followed_by_no_score():
    goal = [ev("g1", 100.4, "goal", "h-t9", x=95.0)]
    steady = [{"t": 0.0, "home": 2, "away": 1, "confident": True},
              {"t": 100.4, "home": 2, "away": 1, "confident": True}]
    track, _ = describe.describe(goal, [], clubs=CLUBS, names=NAMES, scores=steady)
    assert [s.spoken for s in track.said] == ["Goal! Rondell scores, on the right."]
    calls = [li["text"] for li in commentary.commentary(goal, [], CLUBS, names=NAMES, scores=steady)["lines"]]
    assert calls == ["Goal! Rondell scores!"]
    only = [{"t": 100.4, "home": 2, "away": 1, "confident": True}]  # no earlier reading: unknown
    assert describe.score_after(100.4, only) is None
