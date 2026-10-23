"""Team-shape facts in the Explain agents and the audio description: code hands the writers the
minute's confident shape facts, the fact-checker holds their words to them, and a blind fan hears
one plain sentence when a team's shape moves."""

import json

from ninety.agents.contracts import Models
from ninety.agents.factcheck import Claim
from ninety.speech import describe
from tests.test_workflow import EVENTS, MAIN, MINUTE, Judge, insights, picks, reply, run, true_claim


def row(metric, team, value, change, unit="m", minute=MINUTE, confident=True, tracked=11):
    return {"id": f"shape:{metric}:{team}:m{minute}", "type": "shape", "metric": metric, "team": team,
            "minute": minute, "value": value, "unit": unit, "change": change, "tracked": tracked,
            "of": 11, "need": 11, "frames": 1500, "confident": confident}


LINE = row("line_height", "home", 38, 8)
WIDTH = row("width", "home", 46, -4)
UNSURE = row("width", "away", 33, None, confident=False, tracked=7)
OTHER_MINUTE = row("line_height", "home", 30, None, minute=MINUTE - 1)
SHAPE = [OTHER_MINUTE, LINE, WIDTH, UNSURE]


def tactician_saw(result_prompts):
    return json.loads(result_prompts[0])["moment"]["evidence"]


def test_the_minutes_confident_shape_facts_join_every_moment_and_the_writer_sees_them():
    prompts = []

    async def tactician(prompt):
        prompts.append(prompt)
        return reply(Claim("Home's back line pushed up 8 m behind it.", [MAIN, LINE["id"]]))

    result = run(_models(tactician), shape=SHAPE)
    (moment,) = result.moments
    assert moment.evidence == (MAIN, LINE["id"], WIDTH["id"])  # this minute's, confident only
    seen = {e["id"] for e in tactician_saw(prompts)}
    assert {LINE["id"], WIDTH["id"]} <= seen and UNSURE["id"] not in seen
    (aired,) = insights(result)
    assert aired["text"] == "Home's back line pushed up 8 m behind it."
    assert aired["evidence"] == [MAIN, LINE["id"]]


def _models(tactician):
    """The Analyst picks MAIN, the Challenger agrees, the Judge supports; the Tactician is given."""
    return Models.scripted({"analyst": [picks(MAIN)], "challenger": [json.dumps({"agree": True})]},
                           tactician=tactician, judge=Judge())


def test_a_shape_claim_that_disagrees_with_the_facts_is_sent_back_and_its_rewrite_airs():
    answers = [reply(Claim("Home's back line dropped back 8 m.", [MAIN, LINE["id"]])),
               reply(true_claim(MAIN))]

    async def tactician(prompt):
        return answers.pop(0)

    result = run(_models(tactician), shape=SHAPE)
    rejected = [s for s in result.trace if s.role == "fact_checker" and s.action == "reject"]
    assert rejected and "disagrees" in rejected[0].detail
    (aired,) = insights(result)
    assert aired["text"] == true_claim(MAIN).text


def test_without_shape_facts_the_moment_and_the_prompt_are_unchanged():
    # The committed replays pin these prompts (lesson 32): no tracked frames, no change.
    prompts = []

    async def tactician(prompt):
        prompts.append(prompt)
        return reply(true_claim(MAIN))

    result = run(_models(tactician))
    assert result.moments[0].evidence == (MAIN,)
    assert [e["id"] for e in tactician_saw(prompts)] == [MAIN]


def test_the_analyst_never_picks_a_shape_fact_as_a_moment():
    result = run(Models.scripted({"analyst": [picks(LINE["id"])]}, judge=Judge()), shape=SHAPE)
    assert result.moments == []


# The audio description ----------------------------------------------------------------------


def test_a_blind_fan_hears_one_plain_sentence_when_the_back_line_moves():
    track, refused = describe.describe([], [], shape=SHAPE)
    (said,) = [s for s in track.said if s.source == "shape"]
    assert said.spoken == "Home's back line has pushed up 8 metres."
    assert said.evidence == [LINE["id"]] and said.t_event == 60.0 * MINUTE and said.pan == 0.0
    assert not refused


def test_at_most_one_shape_sentence_a_minute_the_largest_change():
    both = [row("line_height", "home", 38, 3), row("width", "home", 46, -6)]
    lines = describe.shape_lines(both)
    assert [text for _, text, _ in lines] == ["home have narrowed by 6 m."]
    assert describe.spoken(lines[0][1]) == "Home have narrowed by 6 metres."


def test_a_change_tracking_error_could_make_is_not_said():
    # 2 m is within twice the 1.26 m position error; 3 m is past it.
    assert describe.shape_lines([row("line_height", "home", 38, 2)]) == []
    assert describe.shape_lines([row("line_height", "home", 38, 3)])


def test_an_unsure_shape_fact_is_never_said():
    unsure = row("line_height", "home", 38, 8, confident=False, tracked=10)
    assert describe.shape_lines([unsure]) == []
    track, _ = describe.describe([], [], shape=[unsure])
    assert not track.said


def test_a_verified_insight_citing_a_shape_fact_is_still_said():
    ev = [e for e in EVENTS if e["id"] == MAIN]
    cue = {"id": "insight-x", "kind": "insight", "verified": True, "t_in": ev[0]["t"],
           "text": "Home's back line pushed up 8 m behind it.", "evidence": [MAIN, LINE["id"]]}
    lines, refused = describe.candidates(ev, [cue], shape=SHAPE)
    assert any(line.source == "insight" for line in lines), refused


def test_a_verified_insight_citing_an_unsure_shape_fact_is_not_said():
    # Defence in depth: the workflow never verifies one, but the Describer's own gate refuses it too.
    ev = [e for e in EVENTS if e["id"] == MAIN]
    cue = {"id": "insight-x", "kind": "insight", "verified": True, "t_in": ev[0]["t"],
           "text": "Away were narrow behind it.", "evidence": [MAIN, UNSURE["id"]]}
    lines, refused = describe.candidates(ev, [cue], shape=SHAPE)
    assert not any(line.source == "insight" for line in lines)
    assert any("7 of 11" in r["reason"] for r in refused)
