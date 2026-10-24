"""Active perception (ninety/agents/perceive.py): a claim the fact-checker would hold on a doubtful
detection is looked at again through another camera, with R3's own event detection, and decided
again on what that look saw. No model, no ground truth."""

import asyncio
import json
from pathlib import Path

import pytest

from ninety.agents import perceive, workflow
from ninety.agents.contracts import Models
from ninety.agents.factcheck import Verdict
from ninety.match.facts import compact

ROOT = Path(__file__).resolve().parents[1]
ROWS = [json.loads(line) for line in (ROOT / "tests/fixtures/observations-seed900001.jsonl").read_text()
        .splitlines()]


def detected(**over) -> dict:
    """The M1 clip's first detected pass (v00001: away, 66.88 s, at 82.5, 46.4), as an event."""
    e = {"id": "v00001", "t": 66.88, "frame": 1672, "type": "pass", "team": "away", "player": None,
         "x": 82.5, "y": 46.4, "end_x": 87.0, "end_y": 52.5, "outcome": "success", "ball_speed_kmh": 30.0,
         "source": "vision", "confidence": 0.801, "team_confidence": 0.529}
    return {**e, **over}


def test_a_look_through_a_camera_re_runs_the_event_detector_and_finds_the_same_event():
    # The same observations under a second camera's name: the look must find the very event.
    p = perceive.Perceiver({"broadcast": ROWS, "tactical1": ROWS})
    for mode in perceive.MODES:
        look = p.re_perceive(detected(), "tactical1", mode)
        assert look.found and look.found["type"] == "pass" and look.found["team"] == "away", look
        assert abs(look.found["t"] - 66.88) <= perceive.MATCH_S


def test_a_look_that_sees_nothing_there_finds_nothing():
    p = perceive.Perceiver({"tactical1": ROWS})
    assert p.re_perceive(detected(t=10.0, x=20.0, y=10.0), "tactical1", "window").found is None
    assert p.re_perceive(detected(), "tactical2", "window").why.startswith("no camera")


def stub(found: dict | None):
    """A Perceiver whose every look returns `found` (the logic below, without the detector)."""
    p = perceive.Perceiver({"broadcast": [], "tactical1": []})
    p.re_perceive = lambda event, camera, mode: perceive.Look(event["id"], camera, mode,
                                                                 dict(found) if found else None, "")
    return p


SCOPE = {"v00001": compact(detected())}
TEAM_CLAIM = "Away complete a pass."


def test_a_side_the_other_camera_tells_surely_confirms_a_team_claim():
    sure = {"type": "pass", "t": 66.9, "team": "away", "team_confidence": 0.99, "player": None,
            "confidence": 0.9}
    scope, looks = perceive.recheck(stub(sure), TEAM_CLAIM, SCOPE, 2, own_camera="broadcast")
    assert scope is not None and scope["v00001"]["team_confidence"] == 0.99
    # The window confirms the event; the side is re-read only by the whole-clip (track) look.
    assert scope["v00001"]["re_perceived"]["mode"] == "track" and len(looks) == 2


def test_the_other_side_seen_from_another_camera_keeps_the_claim_held():
    other = {"type": "pass", "t": 66.9, "team": "home", "team_confidence": 0.99, "player": None,
             "confidence": 0.9}
    scope, looks = perceive.recheck(stub(other), TEAM_CLAIM, SCOPE, 2, own_camera="broadcast")
    assert scope is None and "other side" in looks[0].why


def test_a_look_no_surer_confirms_nothing():
    unsure = {"type": "pass", "t": 66.9, "team": "away", "team_confidence": 0.6, "player": None,
              "confidence": 0.9}
    scope, looks = perceive.recheck(stub(unsure), TEAM_CLAIM, SCOPE, 2, own_camera="broadcast")
    assert scope is None and [lk.mode for lk in looks] == ["window", "track"]  # both tried, neither sure


def test_a_claim_naming_no_side_on_a_confident_detection_needs_no_look():
    scope, looks = perceive.recheck(stub(None), "A completed pass.", SCOPE, 2)
    assert scope is None and looks == []


def test_looks_are_capped_each_match_minute():
    p = stub(None)
    for _ in range(5):
        perceive.recheck(p, TEAM_CLAIM, SCOPE, 2)
    assert len(p.looks) == perceive.MAX_PER_MINUTE  # the cap, then no more looks that minute
    perceive.recheck(p, TEAM_CLAIM, SCOPE, 3)
    assert len(p.looks) == 2 * perceive.MAX_PER_MINUTE  # a new minute has its own


# Through the workflow: the fact-checker holds, looks again, and airs on the confirmed reading -----


EVENT = detected()


def models(text: str) -> Models:
    async def analyst(prompt):
        return json.dumps({"moments": [{"main_event": "v00001", "evidence": ["v00001"]}]})

    async def tactician(prompt):
        return json.dumps({"text": text, "evidence": ["v00001"]})

    async def challenger(prompt):
        return json.dumps({"agree": True})

    async def judge(claim, evidence):
        return Verdict(ok=True)

    return Models.scripted({}, analyst=analyst, tactician=tactician, challenger=challenger, judge=judge)


def run(text: str, perceiver):
    return asyncio.run(workflow.run_workflow(models(text), [EVENT], 2, "seed900001-inline",
                                             inline_events=True, perceiver=perceiver))


@pytest.mark.parametrize(("found", "aired"), [
    ({"type": "pass", "t": 66.9, "team": "away", "team_confidence": 0.99, "player": None, "confidence": 0.9},
     True),
    ({"type": "pass", "t": 66.9, "team": "home", "team_confidence": 0.99, "player": None, "confidence": 0.9},
     False),
    (None, False),
])
def test_the_fact_checker_looks_again_and_airs_only_a_confirmed_team_claim(found, aired):
    result = run(TEAM_CLAIM, stub(found))
    (review,) = result.reviews
    assert (review.aired is not None) == aired
    steps = [s for s in result.trace if s.action == "re_perceive"]
    assert steps and all(s.role == "fact_checker" for s in steps)
    if not aired:
        assert review.status == "held"


def test_without_cameras_to_look_through_the_claim_is_held_as_before():
    (review,) = run(TEAM_CLAIM, None).reviews
    assert review.status == "held" and review.aired is None


def test_every_look_is_in_the_ledger_with_its_source():
    from ninety.agents.ledger import InMemoryLedger

    ledger = InMemoryLedger()
    sure = {"type": "pass", "t": 66.9, "team": "away", "team_confidence": 0.99, "player": None,
            "confidence": 0.9}
    asyncio.run(workflow.run_workflow(models(TEAM_CLAIM), [EVENT], 2, "seed900001-inline", ledger=ledger,
                                      inline_events=True, perceiver=stub(sure)))
    looks = [r for r in asyncio.run(ledger.query(kind="fact")) if r.source == "re_perceive"]
    assert looks and looks[0].payload["camera"] in {"broadcast", "tactical1"}
    assert looks[0].payload["found"]["team_confidence"] == 0.99


def test_a_window_s_side_vote_never_confirms_a_side():
    # On the M1 clip a 3 s window reads the false v00003's side at 1.0, the whole clip at 0.529:
    # only the whole-clip vote, the reading the threshold was measured on, may re-read a side.
    window_sure = {"type": "pass", "t": 66.9, "team": "away", "team_confidence": 1.0, "player": None,
                   "confidence": 0.9}
    p = stub(window_sure)
    p.re_perceive = lambda event, camera, mode: perceive.Look(
        event["id"], camera, mode, dict(window_sure, team_confidence=1.0 if mode == "window" else 0.6), "")
    scope, looks = perceive.recheck(p, TEAM_CLAIM, SCOPE, 2, own_camera="broadcast")
    assert scope is None and [lk.mode for lk in looks] == ["window", "track"]


def test_on_the_m1_clip_no_look_resolves_the_false_detection():
    p = perceive.Perceiver({"tactical1": ROWS})
    v3 = detected(id="v00003", t=71.52, team="home", x=82.9, y=42.2, confidence=0.849)
    scope, _ = perceive.recheck(p, "Home complete a pass.", {"v00003": compact(v3) | {"t": 71.52, "x": 82.9,
                                                                                        "y": 42.2}}, 2)
    assert scope is None


def test_a_claim_on_two_doubtful_detections_airs_only_when_both_are_confirmed():
    two = SCOPE | {"v00002": compact(detected(id="v00002", t=68.4, x=87.0, y=52.5))}
    sure = {"type": "pass", "t": 66.9, "team": "away", "team_confidence": 0.99, "player": None,
            "confidence": 0.9}
    p = stub(None)
    p.re_perceive = lambda event, camera, mode: perceive.Look(
        event["id"], camera, mode, dict(sure) if event["id"] == "v00001" else None, "")
    scope, _ = perceive.recheck(p, TEAM_CLAIM, two, 2, own_camera="broadcast")
    assert scope is None  # v00002 was not confirmed


def test_an_event_at_the_same_time_elsewhere_on_the_pitch_is_not_the_same_event():
    a = {"type": "pass", "t": 66.9, "x": 82.5, "y": 46.4}
    assert perceive._same(a, {**a, "x": 82.5 + perceive.MATCH_M - 0.1})
    assert not perceive._same(a, {**a, "x": 82.5 + perceive.MATCH_M + 0.1})
    assert not perceive._same(a, {**a, "t": 66.9 + perceive.MATCH_S + 0.01})
    assert not perceive._same(a, {**a, "type": "shot"})
