"""The fact-checker holds back what rests on an unsure detection (docs/PLAN.md, confidence gating)."""

import asyncio
import json

import pytest

from ninety.agents.contracts import status_for
from ninety.agents.cues import template_cues
from ninety.agents.factcheck import MIN_CONFIDENCE, Claim, Verdict, check, confidence_gate
from ninety.agents.ledger import InMemoryLedger, load_match
from ninety.agents.slice import MAX_REWRITES, run_workflow
from ninety.match import detected
from ninety.match.facts import AGENT_TYPES, compact

EVENTS = detected.load(detected.FIXTURES / "detected-standin-seed900001.jsonl")
KNOWN = {e["id"]: compact(e) for e in EVENTS if e["type"] in AGENT_TYPES}
# A completed pass detected with high confidence, and one detected below the gate.
SURE = next(e for e in KNOWN.values() if e["type"] == "pass" and e.get("receiver") and e["confidence"] >= 0.8)
UNSURE = next(e for e in KNOWN.values() if e["type"] == "pass" and e.get("receiver")
              and e["confidence"] < MIN_CONFIDENCE)
GOOD = Claim(f"{SURE['player']} finds {SURE['receiver']}.", [SURE["id"]])
LOW = Claim(f"{UNSURE['player']} finds {UNSURE['receiver']}.", [UNSURE["id"]])


def reply(claim: Claim) -> str:
    return json.dumps({"text": claim.text, "evidence": claim.evidence})


def test_a_claim_on_an_unsure_detection_passes_the_code_check_but_is_held():
    assert check(LOW, KNOWN).ok  # every word of it is true of the detection
    verdict = confidence_gate(LOW, KNOWN)
    assert not verdict.ok and verdict.category == "low_confidence"
    assert status_for(verdict) == "held"
    assert UNSURE["id"] in verdict.reasons[0]


def test_a_claim_on_a_confident_detection_passes():
    assert confidence_gate(GOOD, KNOWN) == Verdict(ok=True, reasons=[], category=None)


def test_one_unsure_event_among_the_evidence_is_enough_to_hold():
    both = Claim("Two passes.", [SURE["id"], UNSURE["id"]])
    assert not confidence_gate(both, KNOWN).ok


def test_the_gate_is_at_the_threshold_not_above_it():
    at = {SURE["id"]: {**SURE, "confidence": MIN_CONFIDENCE}}
    below = {SURE["id"]: {**SURE, "confidence": MIN_CONFIDENCE - 0.01}}
    assert confidence_gate(GOOD, at).ok
    assert not confidence_gate(GOOD, below).ok


def test_ground_truth_events_without_confidence_are_not_gated():
    truth = {SURE["id"]: {k: v for k, v in SURE.items() if k != "confidence"}}
    assert confidence_gate(GOOD, truth).ok


class Models:
    def __init__(self, replies: list[str]):
        self.replies, self.judged = list(replies), []

    async def ask(self, prompt: str) -> str:
        return self.replies.pop(0) if len(self.replies) > 1 else self.replies[0]

    async def judge(self, claim: Claim, evidence: list[dict]) -> Verdict:
        self.judged.append(claim.evidence)
        return Verdict(ok=True)


def run(models: Models):
    events = list(KNOWN.values())
    return asyncio.run(run_workflow(models.ask, models.judge, 2, False, 900001, 0, False, events))


def test_the_workflow_sends_a_held_claim_back_and_airs_the_confident_rewrite():
    models = Models([reply(LOW), reply(GOOD)])
    outcome = run(models)
    assert outcome.accepted and outcome.status == "verified" and outcome.attempts == 2
    assert any(line.startswith("fact_checker: held: ") for line in outcome.trace)
    assert models.judged == [GOOD.evidence]  # the Judge never saw the unsure claim


def test_a_claim_that_stays_on_an_unsure_detection_is_held_not_aired():
    models = Models([reply(LOW)])
    outcome = run(models)
    assert not outcome.accepted and outcome.status == "held"
    assert outcome.attempts == MAX_REWRITES + 1 and models.judged == []
    assert outcome.trace[-1].startswith("fact_checker: held, out of rewrites")


def test_a_wrong_claim_out_of_rewrites_is_rejected_not_held():
    wrong = Claim(f"{SURE['player']} finds {SURE['receiver']} at 143 km/h.", [SURE["id"]])
    outcome = run(Models([reply(wrong)]))
    assert not outcome.accepted and outcome.status == "rejected"


@pytest.mark.parametrize("persona", ["analyst", "casual"])
def test_no_template_cue_airs_on_an_unsure_detection(persona):
    async def cues():
        ledger = InMemoryLedger()
        await load_match(ledger, EVENTS, ())
        return await template_cues(ledger)

    shown = {i for c in asyncio.run(cues()) if c["persona"] == persona for i in c["evidence"]}
    confidence = {e["id"]: e["confidence"] for e in EVENTS}
    assert UNSURE["id"] not in shown and SURE["id"] in shown
    assert all(confidence[i] >= MIN_CONFIDENCE for i in shown)


# Team claims on an unsure side (audit Q3) ----------------------------------------------------------

M1 = detected.load(detected.m1_path(detected.M1_CLIP))  # the M1 clip's pixel-detected events


def pass_on_side(side: float | None) -> dict:
    e = {"id": "v1", "t": 61.0, "type": "pass", "team": "away", "player": None, "confidence": 0.9,
         "x": 40.0, "y": 30.0, "end_x": 52.0, "end_y": 30.0, "ball_speed_kmh": 40.0, "outcome": "success"}
    return compact(e | ({} if side is None else {"team_confidence": side}))


def test_the_agents_see_how_firmly_the_side_was_told():
    rows = [compact(e) for e in M1 if e.get("team_confidence") is not None]
    assert rows and all("team_confidence" in r for r in rows)


@pytest.mark.parametrize("side", [0.529, 0.96, None])  # the M1 clip's; the measured wrong-side top; unknown
def test_a_claim_naming_a_team_on_an_unsure_side_is_held_not_rejected(side):
    known = {"v1": pass_on_side(side)}
    claim = Claim("Away complete a pass of 12 m.", ["v1"])
    assert check(claim, known).ok
    gated = confidence_gate(claim, known)
    assert not gated.ok and gated.category == "low_confidence" and status_for(gated) == "held"
    assert "side was told" in gated.reasons[0]


def test_a_claim_naming_a_team_on_a_sure_side_passes():
    claim = Claim("Away complete a pass of 12 m.", ["v1"])
    assert confidence_gate(claim, {"v1": pass_on_side(0.97)}).ok  # above every measured wrong side


@pytest.mark.parametrize("text", ["A completed pass of 12 m.", "a-t9 finds a-t4 with a 12 m pass."])
def test_a_claim_that_names_no_team_is_not_held_for_its_side(text):
    known = {"v1": pass_on_side(0.529) | {"player": "a-t9", "receiver": "a-t4"}}
    assert confidence_gate(Claim(text, ["v1"]), known).ok


def test_a_ground_truth_event_has_no_side_to_doubt():
    e = compact({"id": "e1", "t": 61.0, "type": "pass", "team": "home", "player": "h7", "x": 40.0,
                 "y": 30.0, "end_x": 52.0, "end_y": 30.0, "ball_speed_kmh": 40.0, "outcome": "success"})
    assert confidence_gate(Claim("Home complete a pass of 12 m.", ["e1"]), {"e1": e}).ok


def test_the_m1_clip_s_team_claims_are_all_held_today():
    # The measured consequence on the clip the demo started from: every side told at 0.529.
    known = {compact(e)["id"]: compact(e) for e in M1}
    for i, e in known.items():
        side = "Away" if e["team"] == "away" else "Home"
        verdict = confidence_gate(Claim(f"{side} on the ball.", [i]), known)
        assert (not verdict.ok) == (e["team_confidence"] <= 0.96), i


def nameless_pass(side: float | None) -> dict:
    e = {"id": "v9", "t": 61.0, "frame": 1525, "type": "pass", "team": "away", "player": None,
         "confidence": 0.9, "x": 40.0, "y": 30.0, "end_x": 52.0, "end_y": 30.0, "ball_speed_kmh": 40.0,
         "outcome": "success", "source": "vision"}
    return e | ({} if side is None else {"team_confidence": side})


@pytest.mark.parametrize(("side", "named"), [(0.529, False), (None, False), (0.97, True)])
def test_a_template_graphic_names_a_side_only_when_it_was_told_firmly(side, named):
    # Review of #249: a template airs without the gate; when the detector named nobody it fell back
    # to the team, so "away plays a pass" aired at 0.529.
    ledger = InMemoryLedger()
    asyncio.run(load_match(ledger, [nameless_pass(side)], ()))
    texts = [c["text"] for c in asyncio.run(template_cues(ledger))]
    assert texts and all(("away" in t) == named for t in texts), texts


@pytest.mark.parametrize("kind", ["pass", "shot", "interception"])
@pytest.mark.parametrize(("side", "named"), [(0.529, False), (0.97, True)])
def test_the_describer_s_own_line_names_a_side_only_when_it_was_told_firmly(side, named, kind):
    from ninety.speech import describe

    versions = describe.event_versions(nameless_pass(side) | {"type": kind})
    assert versions and all(("away" in v) == named for v in versions), versions


@pytest.mark.parametrize("text", ["Los visitantes completan un pase de 12 m.", "El equipo local juega.",
                                  "The visitors complete a pass of 12 m.", "The hosts complete a pass."])
def test_a_side_named_in_other_words_is_held_too(text):
    gated = confidence_gate(Claim(text, ["v1"]), {"v1": pass_on_side(0.529)})
    assert not gated.ok and gated.category == "low_confidence"


def test_a_club_s_view_is_a_team_claim_whatever_its_words():
    claim = Claim("Our side keep the ball moving.", ["v1"])
    known = {"v1": pass_on_side(0.529)}
    assert confidence_gate(claim, known).ok
    assert not confidence_gate(claim, known, team_view=True).ok


def test_no_club_variant_is_asked_for_when_the_side_is_unsure():
    from ninety.personalizer.cues import profiles_for

    assert not [p for p in profiles_for(nameless_pass(0.529)) if p.persona == "club"]
    assert [p for p in profiles_for(nameless_pass(0.97)) if p.persona == "club"]
