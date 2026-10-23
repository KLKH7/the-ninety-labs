"""The multi-agent workflow (ninety/agents/workflow.py), with scripted models: no Azure.

The match is built here, not simulated, so every case a test needs is in it by construction and no
engine change can take it away (lessons 47 and 78). Each test fails without the rule it names
(lesson 8).
"""

import asyncio
import json
import logging
import textwrap
import time
import warnings
from pathlib import Path
from types import SimpleNamespace

import pytest

from ninety.agents import workflow
from ninety.agents.contracts import (
    HELD_CATEGORIES,
    REJECTED_CATEGORIES,
    Models,
    schema_validator,
)
from ninety.agents.factcheck import Claim, Verdict
from ninety.agents.ledger import InMemoryLedger
from ninety.agents.replay import ReplayMismatch, Turn, WorkflowRecording, judge_prompt
from ninety.agents.slice import MAX_REWRITES, StaleRecording
from ninety.agents.workflow import MAX_MOMENTS_PER_MINUTE, run_workflow
from ninety.match import detected
from ninety.match.facts import compact
from ninety.mcp import match_server

MINUTE = 2


def event(n: int, t: float, type_: str, team: str, player: str, **fields) -> dict:
    base = dict(
        id=f"e{n:05d}", t=t, frame=int(t * 25), type=type_, team=team, player=player, x=50.0, y=30.0,
        end_x=None, end_y=None, outcome=None, ball_speed_kmh=None, source="truth", confidence=None,
        receiver=None, intended=None, interceptor=None, deflected_by=None,
    )
    return {**base, **fields}


def completed_pass(n: int, t: float, player: str, receiver: str, metres: float, kmh: float) -> dict:
    return event(n, t, "pass", "home", player, receiver=receiver, intended=receiver, outcome="success",
                 end_x=50.0 + metres, end_y=30.0, ball_speed_kmh=kmh)


# Minute 2 is 60 s to 119 s. More passes than a minute's moments, a tackle (no graphic to replace),
# and a pass in minute 3 (outside the window).
PASSES = [completed_pass(10 + i, 62.0 + 9 * i, f"h{2 + i}", f"h{3 + i}", 10 + 4 * i, 40 + 5 * i)
          for i in range(MAX_MOMENTS_PER_MINUTE + 2)]
TACKLE = event(20, 70.5, "tackle", "away", "a4", receiver="h3", outcome="success")
LATER = completed_pass(30, 125.0, "h9", "h10", 12, 44)
EVENTS = [completed_pass(1, 5.0, "h7", "h8", 8, 30), *PASSES, TACKLE, LATER]
KNOWN = {e["id"]: compact(e) for e in EVENTS}
MAIN = PASSES[0]["id"]


def true_claim(event_id: str) -> Claim:
    e = KNOWN[event_id]
    return Claim(f"{e['player']} finds {e['receiver']} with a {e['distance_m']} m pass.", [event_id])


def false_claim(event_id: str) -> Claim:
    return Claim(true_claim(event_id).text.rstrip(".") + " at 199 km/h.", [event_id])


def reply(claim: Claim) -> str:
    return json.dumps({"text": claim.text, "evidence": claim.evidence})


def picks(*main_events: str, evidence: dict[str, list[str]] | None = None) -> str:
    evidence = evidence or {}
    return json.dumps({"moments": [{"main_event": m, "evidence": evidence.get(m, [m])} for m in main_events]})


class Judge:
    """A Judge that answers from a list, then supports; and remembers what it was asked."""

    def __init__(self, *verdicts: Verdict):
        self.verdicts, self.asked = list(verdicts), []

    async def __call__(self, claim: Claim, evidence: list[dict]) -> Verdict:
        self.asked.append(claim)
        return self.verdicts.pop(0) if self.verdicts else Verdict(ok=True)


def run(models: Models, plant: bool = False, ledger=None, events=EVENTS, **kw):
    return asyncio.run(run_workflow(models, events, MINUTE, "test", plant=plant, ledger=ledger, **kw))


def models(analyst=None, tactician=(), challenger=(), judge=None, **override) -> Models:
    replies = {"analyst": list(analyst or [picks(MAIN)]), "tactician": list(tactician),
               "challenger": list(challenger)}
    return Models.scripted(replies, judge=judge or Judge(), **override)


def steps(result) -> list[tuple[str, str]]:
    return [(s.role, s.action) for s in result.trace]


def history(ledger, moment_id: str, author: str = "tactician") -> list[dict]:
    return [r.payload for r in asyncio.run(ledger.history(f"claim-{moment_id}-{author}"))]


def insights(result) -> list[dict]:
    return [c for c in result.cues if c["kind"] == "insight"]


# Producer.start ------------------------------------------------------------------------------


def test_template_cues_are_in_the_ledger_before_the_first_model_call():
    ledger, seen = InMemoryLedger(), []

    async def analyst(prompt: str) -> str:
        seen.append(len(await ledger.query(kind="cue")))
        return picks(MAIN)

    result = run(Models.scripted(analyst=analyst), ledger=ledger)
    templates = [c for c in result.cues if not c["verified"]]
    assert seen == [len(templates)] and len(templates) == 2 * len(PASSES + [EVENTS[0], LATER])


# The Analyst ---------------------------------------------------------------------------------


def test_several_moments_a_minute_each_named_after_its_main_event():
    mains = [p["id"] for p in PASSES[:MAX_MOMENTS_PER_MINUTE]]
    tactician = [reply(true_claim(m)) for m in mains]
    result = run(models(analyst=(picks(*mains),), tactician=tactician))
    assert [m.id for m in result.moments] == [f"m-{m}" for m in mains]
    assert [m.main_event for m in result.moments] == mains
    assert [c["replaces"] for c in insights(result)] == [f"cue-{m}-analyst" for m in mains]


def test_the_window_limits_hold():
    allowed = [p["id"] for p in PASSES]
    reply_ = picks(LATER["id"], TACKLE["id"], "e99999", *allowed, allowed[0])
    result = run(models(analyst=(reply_,)))
    # Only events of the minute, only main events with a graphic, no repeats, at most the cap.
    assert [m.main_event for m in result.moments] == allowed[:MAX_MOMENTS_PER_MINUTE]
    dropped = [s.detail for s in result.trace if s.action == "drop"]
    assert any(d.startswith(LATER["id"]) and "minute 2" in d for d in dropped)
    assert any(d.startswith(TACKLE["id"]) and "no graphic" in d for d in dropped)
    assert any(d.startswith("e99999") for d in dropped)
    assert sum("over" in d for d in dropped) == len(allowed) - MAX_MOMENTS_PER_MINUTE
    assert any("already a moment" in d for d in dropped)


def test_a_moment_whose_evidence_leaves_the_minute_is_dropped():
    result = run(models(analyst=(picks(MAIN, evidence={MAIN: [MAIN, LATER["id"]]}),)))
    assert result.moments == [] and result.model_calls == 1


def test_the_moments_are_in_the_ledger():
    ledger = InMemoryLedger()
    run(models(analyst=(picks(MAIN, evidence={MAIN: [TACKLE["id"], MAIN]}),)), ledger=ledger)
    (moment,) = asyncio.run(ledger.query(kind="moment"))
    assert moment.id == f"m-{MAIN}" and moment.evidence == (MAIN, TACKLE["id"])


@pytest.mark.parametrize("failure", ["raise", "not json", '{"moments": "none"}'])
def test_an_analyst_failure_leaves_the_templates_on_air_and_exits_normally(failure):
    async def analyst(prompt: str) -> str:
        if failure == "raise":
            raise RuntimeError("model down")
        return failure

    result = run(Models.scripted(analyst=analyst))
    assert result.moments == [] and result.reviews == [] and insights(result) == []
    assert result.cues and steps(result)[-1] == ("analyst", "fail")


def test_detected_events_reach_the_analyst_inline():
    detected = [{**e, "source": "vision", "confidence": 0.9} for e in EVENTS]
    asked = []

    async def analyst(prompt: str) -> str:
        asked.append(prompt)
        return picks(MAIN)

    run(Models.scripted({"tactician": [reply(true_claim(MAIN))]}, analyst=analyst),
        events=detected, inline_events=True)
    (prompt,) = asked
    main = next(e for e in detected if e["id"] == MAIN)
    assert "EVENTS: " in prompt and json.dumps(compact(main), separators=(",", ":")) in prompt
    assert LATER["id"] not in prompt  # only the minute's


def test_events_from_a_file_must_be_detected(tmp_path):
    path = tmp_path / "detected.jsonl"
    path.write_text("".join(json.dumps({**e, "source": "vision", "confidence": 0.8}) + "\n" for e in EVENTS))
    events, match, inline = workflow.detected_events(path)
    assert [e["id"] for e in events] == [e["id"] for e in sorted(EVENTS, key=lambda e: e["t"])]
    assert (match, inline) == ("detected", True)
    # One case per half of the loader's guard (lesson 73): the ground truth even with a
    # confidence, then a detection without one.
    path.write_text(json.dumps({**EVENTS[0], "confidence": 0.9}) + "\n")
    with pytest.raises(ValueError, match="never ground truth"):
        workflow.detected_events(path)
    path.write_text(json.dumps({**EVENTS[0], "source": "vision"}) + "\n")
    with pytest.raises(ValueError, match="needs a confidence"):
        workflow.detected_events(path)


def test_a_clip_the_mcp_server_serves_is_read_through_the_tools():
    path = match_server.DETECTED[detected.M1_CLIP]()
    events, match, inline = workflow.detected_events(path)
    assert (match, inline) == (detected.M1_CLIP, False) and events


def test_a_claim_on_an_unsure_detection_is_held_and_never_rewritten():
    # A rewrite cannot make an unsure detection sure (status_for: low_confidence is held).
    sure, unsure = PASSES[0], PASSES[1]
    events = [{**e, "source": "vision", "confidence": 0.3 if e is unsure else 0.9} for e in EVENTS]
    ledger, judge = InMemoryLedger(), Judge()
    evidence = {sure["id"]: [sure["id"], unsure["id"]]}
    result = run(models(analyst=(picks(sure["id"], evidence=evidence),),
                        tactician=[reply(true_claim(unsure["id"])), reply(true_claim(sure["id"]))],
                        judge=judge),
                 events=events, ledger=ledger)
    versions = history(ledger, f"m-{sure['id']}")
    assert [v["status"] for v in versions] == ["draft", "held"]
    assert versions[1]["category"] == "low_confidence" and judge.asked == []
    assert result.reviews[0].status == "held" and insights(result) == []
    assert ("tactician", "rewrite") not in steps(result)


def test_an_unsure_detection_with_no_graphic_on_air_is_no_moment():
    unsure = PASSES[0]
    events = [{**e, "source": "vision", "confidence": 0.3 if e is unsure else 0.9} for e in EVENTS]
    result = run(models(analyst=(picks(unsure["id"]),)), events=events)
    assert result.moments == []
    assert any("no graphic on air" in s.detail for s in result.trace if s.action == "drop")


def test_the_workflow_on_detected_events_reads_no_ground_truth():
    # M1 guard (tests/test_live_reads_no_truth.py), run on the workflow with scripted models.
    from tests.test_live_reads_no_truth import run_live_path, truth_reads

    script = textwrap.dedent("""
        from ninety.agents import workflow
        from ninety.agents.contracts import Models
        standin = detected.FIXTURES / "detected-standin-seed900001.jsonl"
        events, match, inline = workflow.detected_events(standin)
        moment = json.dumps({"moments": [{"main_event": sure["id"], "evidence": [sure["id"]]}]})
        models = Models.scripted({"analyst": [moment], "tactician": [asyncio.run(ask(""))]}, judge=judge)
        minute = int(sure["t"] // 60) + 1
        out = asyncio.run(workflow.run_workflow(models, events, minute, match, inline_events=inline))
        assert [c for c in out.cues if c["kind"] == "insight"], out.trace
    """)
    assert truth_reads(run_live_path(script)) == []


# Tactician, Challenger, fact-checker, Producer -------------------------------------------------


def test_the_planted_number_is_caught_by_the_code_and_the_rewrite_airs():
    judge = Judge()
    result = run(models(tactician=[reply(true_claim(MAIN))] * 2, judge=judge), plant=True)
    first_reject = next(s for s in result.trace if s.action == "reject")
    assert "143 is not a cited ball_speed_kmh" in first_reject.detail
    # The code check rejected it: the Judge only ever saw the rewrite.
    assert judge.asked == [true_claim(MAIN)]
    (cue,) = insights(result)
    assert cue["verified"] is True and cue["replaces"] == f"cue-{MAIN}-analyst"
    assert cue["text"] == true_claim(MAIN).text and cue["evidence"] == [MAIN]
    schema_validator("overlay_cue").validate(cue)
    template = next(c for c in result.cues if c["id"] == cue["replaces"])
    assert (cue["slot"], cue["t_in"], cue["t_out"]) == (template["slot"], template["t_in"], template["t_out"])
    # analyst, tactician twice, challenger, judge once
    assert result.model_calls == 5


def test_a_rejected_version_stays_in_the_ledger_history():
    ledger = InMemoryLedger()
    run(models(tactician=[reply(true_claim(MAIN))] * 2), plant=True, ledger=ledger)
    versions = history(ledger, f"m-{MAIN}")
    assert [v["status"] for v in versions] == ["draft", "rejected", "draft", "verified"]
    assert "143" in versions[0]["text"] and versions[1]["reasons"]
    assert versions[3]["text"] == true_claim(MAIN).text


def test_a_claim_is_written_only_once_it_has_text():
    ledger = InMemoryLedger()
    result = run(models(tactician=['{"text": "", "evidence": []}']), ledger=ledger)
    assert history(ledger, f"m-{MAIN}") == [] and result.reviews[0].status == "held"


def test_once_the_tacticians_claim_is_verified_the_alternative_is_not_checked():
    # Row 3 of the Oct 23 agents audit: checking (and rewriting) a reading that cannot air spent
    # Judge and writer calls. The Tactician's verified claim airs; the alternative is skipped.
    judge, ledger = Judge(), InMemoryLedger()
    other = PASSES[1]["id"]
    alternative = Claim(true_claim(MAIN).text, [MAIN])
    result = run(models(analyst=(picks(MAIN, evidence={MAIN: [MAIN, other]}),),
                        tactician=[reply(true_claim(MAIN))], challenger=[reply(alternative)], judge=judge),
                 ledger=ledger)
    assert judge.asked == [true_claim(MAIN)]
    (review,) = result.reviews
    assert review.aired == true_claim(MAIN) and review.alternative is None
    assert review.author == "tactician" and review.attempts == (("tactician", 1), ("challenger", 1))
    skip = next(s for s in result.trace if s.role == "fact_checker" and s.action == "skip")
    assert "not checked" in skip.detail
    # The alternative stays in the Ledger as the Challenger wrote it, never checked.
    assert history(ledger, f"m-{MAIN}", "challenger")[-1]["status"] == "draft"
    assert next(s for s in result.trace if s.action == "air").detail.startswith("the tactician's claim")


def test_a_wrong_alternative_after_a_verified_claim_costs_no_rewrite():
    # The audit's case: three wasted calls when the Challenger's reading was sent back for rewriting.
    calls = []

    async def challenger(prompt):
        calls.append(prompt)
        return reply(false_claim(MAIN))

    result = run(Models.scripted({"analyst": [picks(MAIN)], "tactician": [reply(true_claim(MAIN))]},
                                 challenger=challenger, judge=Judge()))
    assert len(calls) == 1 and result.model_calls == 3  # analyst, tactician, challenger: no rewrite
    assert result.reviews[0].aired == true_claim(MAIN)


def test_a_recording_made_under_the_old_rule_replays_with_it():
    # Recordings before the rule have no flag: they replay checking the alternative, as they ran.
    judge = Judge()
    alternative = Claim(true_claim(MAIN).text, [MAIN])
    result = run(models(tactician=[reply(true_claim(MAIN))], challenger=[reply(alternative)], judge=judge),
                 check_alternative_after_verified=True)
    assert len(judge.asked) == 2 and result.reviews[0].alternative.ok


def test_the_alternative_airs_only_when_the_tacticians_claim_fails():
    bad = [reply(false_claim(MAIN))] * (1 + MAX_REWRITES)
    alternative = Claim(f"{KNOWN[MAIN]['player']} finds {KNOWN[MAIN]['receiver']}.", [MAIN])
    result = run(models(tactician=bad, challenger=[reply(alternative)]))
    (review,) = result.reviews
    assert not review.primary.ok and review.aired == alternative and review.status == "verified"
    assert insights(result)[0]["text"] == alternative.text
    assert next(s for s in result.trace if s.action == "air").detail.startswith("the challenger's claim")


def test_a_rejected_claim_goes_back_to_its_author():
    ledger = InMemoryLedger()
    alternative = Claim(f"{KNOWN[MAIN]['player']} finds {KNOWN[MAIN]['receiver']}.", [MAIN])
    challenger = [reply(false_claim(MAIN)), reply(alternative)]
    result = run(models(tactician=[reply(false_claim(MAIN))] * (1 + MAX_REWRITES), challenger=challenger),
                 ledger=ledger)
    rewrites = [s.role for s in result.trace if s.action == "rewrite"]
    assert rewrites == ["tactician"] * MAX_REWRITES + ["challenger"]
    assert [v["status"] for v in history(ledger, f"m-{MAIN}", "challenger")] == [
        "draft", "rejected", "draft", "verified"]
    assert result.reviews[0].aired == alternative


def test_a_claim_may_cite_only_its_moments_evidence():
    outside = PASSES[1]["id"]  # an event of the minute, but not of this moment
    result = run(models(tactician=[reply(true_claim(outside))] * (1 + MAX_REWRITES)))
    assert result.reviews[0].status == "rejected" and insights(result) == []
    assert f"unknown event ids: {outside}" in result.reviews[0].primary.reasons


def test_the_challenger_agreeing_leaves_one_claim():
    judge = Judge()
    result = run(models(tactician=[reply(true_claim(MAIN))], challenger=['{"agree": true}'], judge=judge))
    assert len(judge.asked) == 1 and result.reviews[0].alternative is None
    assert ("challenger", "agree") in steps(result)


@pytest.mark.parametrize("category", ["timeout", "service"])
def test_a_judge_timeout_or_service_error_ends_held(category):
    ledger = InMemoryLedger()
    judge = Judge(Verdict(False, [f"judge {category}; claim held back"], category))
    result = run(models(tactician=[reply(true_claim(MAIN))], judge=judge), ledger=ledger)
    (review,) = result.reviews
    assert review.status == "held" and review.aired is None and insights(result) == []
    assert history(ledger, f"m-{MAIN}")[-1]["status"] == "held"
    assert result.model_calls == 4  # held is never sent back for a rewrite


@pytest.mark.parametrize("category", sorted(c for c in REJECTED_CATEGORIES | HELD_CATEGORIES if c))
def test_judge_categories_survive_end_to_end(category):
    ledger = InMemoryLedger()
    verdicts = [Verdict(False, [f"a {category} failure"], category)] * (1 + MAX_REWRITES)
    result = run(models(tactician=[reply(true_claim(MAIN))] * (1 + MAX_REWRITES), judge=Judge(*verdicts)),
                 ledger=ledger)
    (review,) = result.reviews
    assert review.primary.category == category
    assert history(ledger, f"m-{MAIN}")[-1]["category"] == category
    assert any(s.role == "judge" and s.detail == category for s in result.trace)
    assert review.status == ("held" if category in HELD_CATEGORIES else "rejected")


@pytest.mark.parametrize("failure", ["raise", "not json"])
def test_a_tactician_failure_leaves_the_template_on_air_and_exits_normally(failure):
    async def tactician(prompt: str) -> str:
        if failure == "raise":
            raise RuntimeError("model down")
        return failure

    ledger = InMemoryLedger()
    result = run(Models.scripted({"analyst": [picks(MAIN)]}, tactician=tactician), ledger=ledger)
    (review,) = result.reviews
    assert review.status == "held" and insights(result) == [] and history(ledger, f"m-{MAIN}") == []
    assert steps(result)[-1] == ("producer", "template")


def test_a_challenger_failure_is_skipped():
    async def challenger(prompt: str) -> str:
        raise RuntimeError("model down")

    result = run(Models.scripted({"analyst": [picks(MAIN)], "tactician": [reply(true_claim(MAIN))]},
                                 challenger=challenger))
    assert result.reviews[0].aired == true_claim(MAIN) and ("challenger", "skip") in steps(result)


def test_the_trace_runs_in_order_and_says_whose_claim_aired():
    result = run(models(tactician=[reply(true_claim(MAIN))] * 2), plant=True)
    assert steps(result) == [
        ("producer", "templates"), ("analyst", "pick"),
        ("tactician", "tamper"), ("tactician", "draft"), ("challenger", "agree"),
        ("fact_checker", "reject"), ("tactician", "rewrite"),
        ("judge", "verify"), ("fact_checker", "verify"), ("producer", "air"),
    ]
    assert result.trace[-1].detail == f"the tactician's claim replaces cue-{MAIN}-analyst"


# Replay --------------------------------------------------------------------------------------


def recorded(plant: bool = True):
    """A run's answers, as --record would keep them, from scripted models."""
    turns: list[Turn] = []
    scripted = models(tactician=[reply(true_claim(MAIN))] * 2)

    def keep(role, ask):
        async def answer(prompt):
            response = await ask(prompt)
            turns.append(Turn(role, prompt, response))
            return response

        return answer

    async def judge(claim, evidence):
        verdict = await scripted.judge(claim, evidence)
        turns.append(Turn("judge", judge_prompt(claim), json.dumps(vars(verdict))))
        return verdict

    writers = ("analyst", "tactician", "challenger")
    kept = Models.scripted(**{r: keep(r, getattr(scripted, r)) for r in writers}, judge=judge)
    result = run(kept, plant=plant)
    inputs = {"match": "test", "seed": None, "minutes": 5, "minute": MINUTE, "plant": plant,
              "inline_events": False, "events": EVENTS, "moments": [m.id for m in result.moments]}
    return result, WorkflowRecording("minute", "abc1234", {}, inputs, "2026-10-19T00:00:00+00:00", turns)


def test_a_replay_gives_the_recorded_run():
    result, recording = recorded()
    replayed = asyncio.run(workflow.replay_workflow(recording))
    assert steps(replayed) == steps(result) and replayed.cues == result.cues


def test_a_replay_refuses_a_changed_prompt(monkeypatch):
    _, recording = recorded()
    original = workflow.tactician_prompt
    monkeypatch.setattr(workflow, "tactician_prompt", lambda *a: original(*a) + " ")
    with pytest.raises(ReplayMismatch, match="changed since recording"):
        asyncio.run(workflow.replay_workflow(recording))


def test_a_replay_refuses_roles_called_in_another_order():
    _, recording = recorded()
    roles = [t.role for t in recording.turns]
    i = roles.index("challenger")
    recording.turns[i - 1], recording.turns[i] = recording.turns[i], recording.turns[i - 1]
    with pytest.raises(ReplayMismatch):
        asyncio.run(workflow.replay_workflow(recording))


def test_a_replay_refuses_answers_left_over():
    _, recording = recorded()
    recording.turns.append(Turn("tactician", "never asked", "{}"))
    with pytest.raises(ReplayMismatch, match="never asked for"):
        asyncio.run(workflow.replay_workflow(recording))


def test_a_recording_round_trips(tmp_path):
    _, recording = recorded()
    recording.save(tmp_path / "w.json")
    assert WorkflowRecording.load(tmp_path / "w.json") == recording


WORKFLOW_REPLAYS = sorted((Path(__file__).resolve().parent.parent / "replays").glob("workflow-*.json"))


@pytest.mark.parametrize("path", WORKFLOW_REPLAYS, ids=lambda p: p.name)
def test_every_committed_workflow_replay_still_replays(path):
    # Lessons 32 and 44: a recording no test replays rots silently.
    with warnings.catch_warnings():
        warnings.simplefilter("ignore", StaleRecording)
        result = asyncio.run(workflow.replay_workflow(WorkflowRecording.load(path)))
    assert result.moments and result.model_calls == len(WorkflowRecording.load(path).turns)


def test_there_is_a_committed_workflow_replay():
    assert WORKFLOW_REPLAYS, "replays/ holds no workflow recording, so the test above checks nothing"


def test_the_committed_live_recording_shows_the_planted_number_caught_and_insights_on_air():
    # replays/workflow-minute2-plant.json, recorded live on the published agents (agents-live).
    recording = WorkflowRecording.load(WORKFLOW_REPLAYS[0].parent / "workflow-minute2-plant.json")
    assert recording.inputs["plant"] and recording.pins
    with warnings.catch_warnings():
        warnings.simplefilter("ignore", StaleRecording)
        result = asyncio.run(workflow.replay_workflow(recording))
    first = next(s for s in result.trace if s.role == "fact_checker")
    assert first.action == "reject" and "143 is not a cited" in first.detail  # the code check, not the Judge
    aired = insights(result)
    assert aired and all(c["verified"] and c["replaces"].startswith("cue-") for c in aired)
    assert [c["replaces"] for c in aired] == [f"cue-{m.main_event}-analyst" for m in result.moments
                                              if any(r.moment_id == m.id and r.aired for r in result.reviews)]


# Live sign-in ------------------------------------------------------------------------------


class Token:
    def __init__(self, expires_on: float):
        self.token, self.expires_on = "t", expires_on


class Credential:
    """Counts token requests; each token lasts `lifetime` seconds from when it is issued."""

    def __init__(self, lifetime: float):
        self.lifetime, self.asked, self.closed = lifetime, [], False

    async def get_token(self, *scopes, **kwargs):
        self.asked.append(scopes)
        return Token(time.time() + self.lifetime)

    async def close(self):
        self.closed = True


def test_signed_in_keeps_a_token_and_asks_again_only_near_its_expiry():
    # agents-live's OIDC assertion is good for five minutes; a run must not ask again after it.
    hour = Credential(3600)
    signed = workflow.SignedIn(hour)
    for _ in range(3):
        asyncio.run(signed.get_token(workflow.FOUNDRY_SCOPE))
    assert hour.asked == [(workflow.FOUNDRY_SCOPE,)]
    short = Credential(workflow.TOKEN_MARGIN_SECONDS / 2)
    signed = workflow.SignedIn(short)
    asyncio.run(signed.get_token(workflow.FOUNDRY_SCOPE))
    asyncio.run(signed.get_token(workflow.FOUNDRY_SCOPE))
    assert len(short.asked) == 2
    asyncio.run(signed.close())
    assert short.closed


def test_a_live_run_signs_in_before_it_loads_the_events():
    order = []
    hour = Credential(3600)

    async def get_token(*scopes, **kwargs):
        order.append("token")
        return Token(time.time() + 3600)

    hour.get_token = get_token

    def load():
        order.append("events")
        return EVENTS

    events = asyncio.run(workflow.sign_in_then_load(workflow.SignedIn(hour), load))
    assert order == ["token", "events"] and events == EVENTS


# The live path, with fake Foundry agents: no Azure ------------------------------------------

SUPPORTED = json.dumps({"statements": [{"text": "s", "kind": "fact", "verdict": "supported", "reason": "r"}]})
SLOW = object()


class FakeFoundry:
    """Stands in for FoundryAgent: each published agent answers from its own list, in order. A
    reply that is an exception is raised; SLOW never answers."""

    def __init__(self, replies: dict[str, list]):
        self.replies = {f"ninety-{role}": list(answers) for role, answers in replies.items()}
        self.asked: list[str] = []

    def __call__(self, project_endpoint, agent_name, agent_version, credential):
        return FakeAgent(self, agent_name)


class FakeAgent:
    def __init__(self, foundry, name):
        self.foundry, self.name = foundry, name

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        return None

    async def run(self, prompt):
        self.foundry.asked.append(self.name)
        reply = self.foundry.replies[self.name].pop(0)
        if reply is SLOW:
            await asyncio.sleep(60)
        if isinstance(reply, Exception):
            raise reply
        if hasattr(reply, "messages"):  # a whole reply, its contents as Foundry gives them
            return reply
        return SimpleNamespace(text=reply, value=None)


def live(monkeypatch, replies, credential=None):
    foundry = FakeFoundry(replies)
    monkeypatch.setattr(workflow, "FoundryAgent", foundry)
    monkeypatch.setattr(workflow, "new_credential", lambda: workflow.SignedIn(credential or Credential(3600)))
    return foundry


def detected_file(tmp_path) -> Path:
    path = tmp_path / "detected.jsonl"
    path.write_text("".join(json.dumps({**e, "source": "vision", "confidence": 0.9}) + "\n" for e in EVENTS))
    return path


def cli(monkeypatch, *args):
    monkeypatch.setattr("sys.argv", ["ninety-workflow", "--no-trace", *map(str, args)])
    workflow.main()


GOOD_RUN = {"moment-analyst": [picks(MAIN)], "tactician": [reply(true_claim(MAIN))],
            "challenger": ['{"agree": true}'], "judge": [SUPPORTED]}


def test_record_saves_the_live_replies_and_the_cli_prints_the_model_call_count(
    monkeypatch, tmp_path, capsys, caplog
):
    caplog.set_level(logging.INFO, logger="agent_framework")  # restored after the test
    live(monkeypatch, GOOD_RUN)
    out, cues = tmp_path / "w.json", tmp_path / "cues.jsonl"
    cli(monkeypatch, "--events", detected_file(tmp_path), "--record", out, "--cues-out", cues)
    recording = WorkflowRecording.load(out)
    assert [(t.role, t.response) for t in recording.turns] == [
        ("analyst", picks(MAIN)), ("tactician", reply(true_claim(MAIN))), ("challenger", '{"agree": true}'),
        ("judge", json.dumps({"ok": True, "reasons": [], "category": None})),
    ]
    roles = ("moment-analyst", "tactician", "challenger", "judge")
    assert set(recording.pins) == {f"ninety-{role}" for role in roles}
    printed = capsys.readouterr().out
    assert "4 model call(s)" in printed
    assert not [r for r in caplog.records if "superstep" in r.getMessage()]  # the framework is quiet
    aired = [json.loads(line) for line in cues.read_text().splitlines() if '"insight"' in line]
    assert [c["replaces"] for c in aired] == [f"cue-{MAIN}-analyst"]
    # What --record saved replays to the same run, with no Azure.
    replayed = asyncio.run(workflow.replay_workflow(recording))
    assert insights(replayed) == aired


def test_a_failed_live_call_saves_no_recording(monkeypatch, tmp_path, capsys):
    live(monkeypatch, {**GOOD_RUN, "tactician": [RuntimeError("service down")], "judge": []})
    out = tmp_path / "w.json"
    cli(monkeypatch, "--events", detected_file(tmp_path), "--record", out)
    assert not out.exists() and "not recorded" in capsys.readouterr().err


def test_a_slow_live_judge_ends_held_with_its_timeout_and_the_run_is_not_recorded(monkeypatch, tmp_path):
    from functools import partial

    from ninety.agents import judge as judge_module

    # The Judge's own timeout and retry decide (twice 0.6 s), never a cancellation around it.
    monkeypatch.setattr(workflow, "judge_call", partial(judge_module.judge, timeout_seconds=0.6))
    live(monkeypatch, {**GOOD_RUN, "judge": [SLOW, SLOW]})
    result, turns, pins, failed, _ = asyncio.run(workflow.run_live(
        lambda: EVENTS, MINUTE, "test", False, False, trace_to="none"))
    (review,) = result.reviews
    assert review.status == "held" and review.primary.category == "timeout" and failed
    assert json.loads(turns[-1].response)["category"] == "timeout"  # the category reaches the recording
    out = tmp_path / "w.json"
    live(monkeypatch, {**GOOD_RUN, "judge": [SLOW, SLOW]})
    cli(monkeypatch, "--events", detected_file(tmp_path), "--record", out)
    assert not out.exists()


def tool_reply(text: str):
    """A Foundry reply in which the agent called the hosted match tool before answering."""
    from agent_framework import Content

    call = Content.from_mcp_server_tool_call("c1", "list_events", server_name="match",
                                             arguments={"match": "seed21", "minute_from": 2})
    result = Content.from_mcp_server_tool_result("c1")
    message = SimpleNamespace(contents=[call, result, Content.from_text(text)])
    return SimpleNamespace(text=text, value=None, messages=[message])


def test_an_agent_given_its_events_inline_that_calls_the_match_tools_fails_its_call(monkeypatch):
    # Lesson 90: the deployed tools serve the deployed image's match, not the one the run checks.
    live(monkeypatch, {**GOOD_RUN, "moment-analyst": [tool_reply(picks(MAIN))]})
    result, *_ = asyncio.run(workflow.run_live(lambda: EVENTS, MINUTE, "test", True, False, trace_to="none"))
    (step,) = [s for s in result.trace if s.role == "analyst" and s.action == "fail"]
    assert "ReadTheTools" in step.detail and "list_events" in step.detail and not result.reviews
    # Reading the match through the tools is the job when the events are not inline.
    live(monkeypatch, {**GOOD_RUN, "moment-analyst": [tool_reply(picks(MAIN))]})
    result, *_ = asyncio.run(workflow.run_live(lambda: EVENTS, MINUTE, "test", False, False, trace_to="none"))
    assert [r.status for r in result.reviews] == ["verified"]


def foundry_reply(output: list[dict]):
    """A Responses API reply shaped as Foundry returns one for the published agent, through the
    installed agent framework's own parser for FoundryAgent (no network: the credential is never
    asked). An upgrade that renames the tool call's content type turns these tests red."""
    from agent_framework import AgentResponse
    from agent_framework_foundry._agent import RawFoundryAgentChatClient
    from openai.types.responses import Response

    class NoCredential:
        async def get_token(self, *scopes, **kwargs):
            raise AssertionError("parsing a reply asks for no token")

    client = RawFoundryAgentChatClient(project_endpoint="https://ninety.test/api/projects/p",
                                       agent_name="ninety-analyst", agent_version="5",
                                       credential=NoCredential())
    body = {"id": "resp_1", "object": "response", "created_at": 1792500000, "model": "gpt-4.1-mini",
            "status": "completed", "parallel_tool_calls": True, "tool_choice": "auto", "tools": [],
            "output": output}
    parsed = client._parse_response_from_openai(Response.model_validate(body), {})
    return AgentResponse(messages=parsed.messages)


# What the published ninety-analyst returned on 2026-10-20: the tool list always comes first; a
# call to it comes only when the agent read the match through the tools.
LISTED = {"type": "mcp_list_tools", "id": "mcpl_1", "server_label": "match",
          "tools": [{"name": "list_events", "input_schema": {"type": "object"}}]}
CALLED = {"type": "mcp_call", "id": "mcp_1", "server_label": "match", "name": "list_events",
          "arguments": '{"match":"seed21-inline","minute_from":2,"minute_to":2}',
          "output": "unknown match 'seed21-inline'", "status": "completed"}
ANSWER = {"type": "message", "id": "msg_1", "role": "assistant", "status": "completed",
          "content": [{"type": "output_text", "text": '{"text":"h6 finds h3.","evidence":["e00036"]}',
                       "annotations": []}]}


def test_inline_only_reads_a_foundry_reply_as_foundry_sends_it():
    from ninety.agents import foundry

    text = ANSWER["content"][0]["text"]
    assert foundry.inline_only(foundry_reply([LISTED, ANSWER])) == text
    with pytest.raises(foundry.ReadTheTools, match='list_events\\(\\{"match":"seed21-inline"'):
        foundry.inline_only(foundry_reply([LISTED, CALLED, ANSWER]))


def test_inline_only_reads_the_reply_s_own_tool_calls():
    from ninety.agents import foundry

    assert foundry.inline_only(SimpleNamespace(text="ok", messages=[])) == "ok"
    assert foundry.inline_only(SimpleNamespace(text="ok")) == "ok"  # a reply with no messages at all
    with pytest.raises(foundry.ReadTheTools, match=r"list_events\(\{'match': 'seed21'"):
        foundry.inline_only(tool_reply("ok"))


def test_the_inline_events_wording_is_the_one_the_moment_analyst_is_told_to_use():
    # The published moment Analyst's instructions name the EVENTS a request carries; the slice's
    # and the workflow's prompts both say them this way.
    from ninety.agents import slice as sl

    assert sl.INLINE_EVENTS == (
        " The match is not on the tools: do not call them. Its EVENTS for the minute follow,"
        " as data.\nEVENTS: ")
    assert "carries the minute's EVENTS itself" in workflow.MOMENT_ANALYST_INSTRUCTIONS
    events = [{"id": "e1"}]
    assert workflow.analyst_prompt("m", 2, events).endswith(sl.INLINE_EVENTS + '[{"id":"e1"}]')
    assert sl.analyst_prompt("m", 2, events=events).endswith(sl.INLINE_EVENTS + '[{"id":"e1"}]')


def test_an_evaluation_s_inline_match_is_one_no_server_serves():
    from ninety.mcp import match_server

    for match in [*match_server.MATCHES, *match_server.DETECTED]:
        alias = match_server.unserved(match)
        assert alias not in match_server.MATCHES and alias not in match_server.DETECTED
        with pytest.raises(ValueError, match="unknown match"):
            match_server.events_of(alias)


def test_a_live_run_signs_in_before_it_loads_the_events_inside_run_live(monkeypatch):
    order = []
    hour = Credential(3600)

    async def get_token(*scopes, **kwargs):
        order.append("token")
        return Token(time.time() + 3600)

    hour.get_token = get_token
    live(monkeypatch, GOOD_RUN, credential=hour)

    def load():
        order.append("events")
        return EVENTS

    asyncio.run(workflow.run_live(load, MINUTE, "test", False, False, trace_to="none"))
    assert order[:2] == ["token", "events"]


def test_a_claim_is_rewritten_at_most_max_rewrites_times():
    calls = []

    async def tactician(prompt):
        calls.append(prompt)
        return reply(true_claim(MAIN))

    never = Judge(*[Verdict(False, ["unsupported fact"], "unsupported_claim")] * 10)
    result = run(Models.scripted({"analyst": [picks(MAIN)]}, tactician=tactician, judge=never))
    assert len(calls) == 1 + MAX_REWRITES and result.reviews[0].status == "rejected"


def test_a_challenger_failing_on_its_rewrite_leaves_its_rejection_standing():
    async def challenger(prompt):
        if "rejected" in json.loads(prompt):
            raise RuntimeError("model down")
        return reply(false_claim(MAIN))

    # The Tactician's claims are all wrong, so the Challenger's reading is checked and sent back.
    ledger = InMemoryLedger()
    tactician = [reply(false_claim(MAIN))] * (MAX_REWRITES + 1)
    result = run(Models.scripted({"analyst": [picks(MAIN)], "tactician": tactician},
                                 challenger=challenger), ledger=ledger)
    fail = next(s for s in result.trace if s.role == "challenger" and s.action == "fail")
    assert "the rejection stands" in fail.detail
    assert history(ledger, f"m-{MAIN}", "challenger")[-1]["status"] == "rejected"
    assert result.reviews[0].aired is None


# Second review (4a91fa8): crash paths and bounds ---------------------------------------------


@pytest.mark.parametrize("evidence", [None, "e00010", 7, {"id": MAIN}, [MAIN, None]])
def test_a_malformed_moment_is_dropped_and_the_minute_goes_on(evidence):
    reply_ = json.dumps({"moments": [{"main_event": MAIN, "evidence": evidence}]})
    result = run(models(analyst=(reply_,)))
    assert result.moments == [] and result.cues
    assert any("not a moment" in s.detail for s in result.trace if s.action == "drop")


DEEP = "[" * 100_000 + "]" * 100_000  # json.loads raises RecursionError, not ValueError

@pytest.mark.parametrize("reply_", ['{"moments": [7]}', '{"moments": [{"main_event": 7, "evidence": []}]}',
                                    '{"moments": {"a": 1}}', "[]", '{"moments": [null]}',
                                    '{"moments": ' + DEEP + "}"])
def test_an_analyst_reply_of_the_wrong_shape_is_no_moment(reply_):
    result = run(models(analyst=(reply_,)))
    assert result.moments == [] and result.reviews == [] and result.cues


class RaisingAgent:
    """A Judge agent whose service raises an error judge.py does not handle."""

    async def run(self, prompt):
        raise RuntimeError("unexpected")


def test_a_judge_raising_outside_its_handled_errors_holds_the_claim_and_the_template_stays():
    from ninety.agents import judge as judge_module

    async def real_judge(claim, evidence):  # the live judge() on an agent that raises (lesson 96)
        return await judge_module.judge(RaisingAgent(), claim, evidence)

    ledger = InMemoryLedger()
    result = run(models(tactician=[reply(true_claim(MAIN))], judge=real_judge), ledger=ledger)
    (review,) = result.reviews
    assert review.status == "held" and review.primary.category == "service" and insights(result) == []
    assert history(ledger, f"m-{MAIN}")[-1]["status"] == "held"


@pytest.mark.parametrize("failure, category", [
    (TimeoutError(), "timeout"), (RuntimeError("down"), "service"), ("not json", "invalid_response"),
    ('{"text": "", "evidence": []}', "invalid_response"), ('{"text": ' + DEEP + "}", "invalid_response"),
])
def test_a_tactician_failure_keeps_its_category_and_its_status_comes_from_status_for(failure, category):
    async def tactician(prompt):
        if isinstance(failure, Exception):
            raise failure
        return failure

    result = run(Models.scripted({"analyst": [picks(MAIN)]}, tactician=tactician))
    (review,) = result.reviews
    assert review.primary.category == category and review.status == "held"


def test_the_worst_case_minute_fits_the_superstep_budget():
    # Three moments, both writers rejected by the code check on every draft: the most hops a minute
    # can take. Going over the budget raises in the framework and loses the minute.
    mains = [p["id"] for p in PASSES[:MAX_MOMENTS_PER_MINUTE]]
    drafts = 1 + MAX_REWRITES
    bad = [reply(false_claim(m)) for m in mains for _ in range(drafts)]
    result = run(models(analyst=(picks(*mains),), tactician=bad, challenger=bad))
    assert [r.status for r in result.reviews] == ["rejected"] * MAX_MOMENTS_PER_MINUTE
    sent_back = [s for s in result.trace if s.action == "reject" and "back to the" in s.detail]
    assert len(sent_back) == 2 * MAX_REWRITES * MAX_MOMENTS_PER_MINUTE


def test_a_challenger_reply_that_cannot_be_parsed_is_skipped():
    result = run(models(tactician=[reply(true_claim(MAIN))], challenger=['{"text": ' + DEEP + "}"]))
    assert ("challenger", "skip") in steps(result) and result.reviews[0].aired == true_claim(MAIN)
