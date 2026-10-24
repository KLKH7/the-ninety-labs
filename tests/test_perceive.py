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
LOCATED = {"v00001": detected()}
TEAM_CLAIM = "Away complete a pass."
PLAIN = "A completed pass."
UNSURE_DETECTION = {"v00001": compact(detected(confidence=0.3))}


def sure(**over):
    return {"type": "pass", "t": 66.9, "team": "away", "team_confidence": 0.99, "player": None,
            "confidence": 0.9, **over}


def recheck(p, text, scope=None):
    scope = scope or SCOPE
    return perceive.recheck(p, text, list(scope), scope, LOCATED, 2, own_camera="broadcast")


def test_a_look_never_re_reads_a_side_so_a_team_claim_on_an_unsure_side_stays_held():
    # A tactical lens telling the side at 0.99 is another reading from the one 0.96 was measured on
    # (lesson 227; wrong sides reach 0.994 on the lenses): it cannot open the side gate, so no look
    # is spent on such a claim at all.
    p = stub(sure())
    scope, looks = recheck(p, TEAM_CLAIM)
    assert scope is None and looks == [] and p.looks == []


def test_a_side_only_doubt_leaves_the_minute_s_looks_for_a_detection_doubt():
    p = stub(sure())
    recheck(p, TEAM_CLAIM)  # held on its side: spends nothing
    scope, looks = recheck(p, PLAIN, UNSURE_DETECTION)
    assert scope is not None and looks


def test_a_claim_on_two_doubtful_detections_airs_only_when_both_are_confirmed():
    two = UNSURE_DETECTION | {"v00002": compact(detected(id="v00002", t=68.4, x=87.0, y=52.5,
                                                         confidence=0.2))}
    located = {**LOCATED, "v00002": detected(id="v00002", t=68.4, x=87.0, y=52.5)}
    p = stub(None)
    p.re_perceive = lambda event, camera, mode: perceive.Look(
        event["id"], camera, mode, sure() if event["id"] == "v00001" else None, "")
    scope, _ = perceive.recheck(p, PLAIN, ["v00001", "v00002"], two, located, 2, own_camera="broadcast")
    assert scope is None  # v00002 was not confirmed


def test_a_window_look_reads_only_the_3_s_around_the_event():
    p = perceive.Perceiver({"tactical1": ROWS})
    seen = []
    from ninety.vision import events as vision_events

    real = vision_events.detect

    def spy(rows, *a, **k):
        seen.append([r["t"] for r in rows])
        return real(rows, *a, **k)

    vision_events.detect = spy
    try:
        p.re_perceive(detected(), "tactical1", "window")
        p.re_perceive(detected(), "tactical1", "track")
    finally:
        vision_events.detect = real
    window, track = seen
    assert max(window) - min(window) <= perceive.WINDOW_S and len(track) == len(ROWS)


def test_a_cached_look_keeps_each_claim_s_own_reason():
    p = stub(sure())
    _, first = recheck(p, PLAIN, UNSURE_DETECTION)
    _, second = recheck(p, "A completed pass, it was.", UNSURE_DETECTION)
    assert first[0] is not second[0] and p.looks[0].why == ""


def test_another_camera_confirms_an_unsure_detection_for_a_claim_naming_no_side():
    scope, looks = recheck(stub(sure()), PLAIN, UNSURE_DETECTION)
    assert scope is not None and scope["v00001"]["confidence"] == 0.9
    assert scope["v00001"]["re_perceived"]["camera"] == "tactical1"


def test_the_other_side_told_over_the_whole_clip_keeps_the_claim_held():
    scope, looks = recheck(stub(sure(team="home")), PLAIN, UNSURE_DETECTION)
    assert scope is None and "other side" in looks[-1].why and looks[-1].mode == "track"


def test_a_window_s_or_an_unknown_side_contradicts_nothing():
    p = stub(None)
    p.re_perceive = lambda event, camera, mode: perceive.Look(
        event["id"], camera, mode, sure(team="home" if mode == "window" else None), "")
    scope, looks = recheck(p, PLAIN, UNSURE_DETECTION)
    assert scope is not None and not any("other side" in lk.why for lk in looks)


def test_a_contradiction_from_one_camera_is_not_overruled_by_another_s_confirmation():
    p = perceive.Perceiver({"broadcast": [], "tac-l": [], "tac-r": []})
    p.re_perceive = lambda event, camera, mode: perceive.Look(
        event["id"], camera, mode, sure(team="home" if camera == "tac-l" else "away"), "")
    scope, _ = recheck(p, PLAIN, UNSURE_DETECTION)
    assert scope is None


def test_a_found_event_with_no_confidence_confirms_nothing():
    scope, _ = recheck(stub(sure(confidence=None)), PLAIN, UNSURE_DETECTION)
    assert scope is None


def test_a_look_no_surer_confirms_nothing():
    scope, looks = recheck(stub(sure(confidence=0.4)), PLAIN, UNSURE_DETECTION)
    assert scope is None and [lk.mode for lk in looks] == ["window", "track"]  # both tried, neither sure


def test_a_claim_naming_no_side_on_a_confident_detection_needs_no_look():
    scope, looks = recheck(stub(None), PLAIN)
    assert scope is None and looks == []


def test_only_the_detections_the_claim_cites_are_looked_at():
    two = UNSURE_DETECTION | {"v00002": compact(detected(id="v00002", t=68.4, x=87.0, y=52.5,
                                                         confidence=0.2))}
    located = {**LOCATED, "v00002": detected(id="v00002", t=68.4, x=87.0, y=52.5)}
    scope, looks = perceive.recheck(stub(sure()), PLAIN, ["v00001"], two, located, 2, own_camera="broadcast")
    assert scope is not None and {lk.event for lk in looks} == {"v00001"}


def test_looks_are_capped_each_match_minute_and_a_look_taken_is_reused():
    p = stub(None)
    for _ in range(5):
        recheck(p, PLAIN, UNSURE_DETECTION)
    assert len(p.looks) == 2  # one camera: a window and a whole-clip look, then reused, not re-taken
    many = perceive.Perceiver({c: [] for c in ("a", "b", "c", "d")})
    many.re_perceive = lambda event, camera, mode: perceive.Look(event["id"], camera, mode, None, "")
    perceive.recheck(many, PLAIN, ["v00001"], UNSURE_DETECTION, LOCATED, 2)
    assert len(many.looks) == perceive.MAX_PER_MINUTE  # the cap, then no more looks that minute
    perceive.recheck(many, PLAIN, ["v00001"], UNSURE_DETECTION, LOCATED, 3)
    assert len(many.looks) == 2 * perceive.MAX_PER_MINUTE  # a new minute has its own


def test_a_detection_with_no_place_is_not_looked_for():
    scope, looks = perceive.recheck(stub(sure()), PLAIN, ["v00001"], UNSURE_DETECTION, {}, 2)
    assert scope is None and looks == []


# Through the workflow: the fact-checker holds, looks again, and decides again --------------------


EVENT = detected()
UNSURE_EVENT = detected(confidence=0.3)


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


def run(text: str, perceiver, event=EVENT, **kw):
    return asyncio.run(workflow.run_workflow(models(text), [event], 2, "seed900001-inline",
                                             inline_events=True, perceiver=perceiver, **kw))


def test_a_real_camera_look_runs_inside_the_workflow():
    # Review of #267: the workflow's scope is compact events, with no time or place; a real look must
    # find the event from the full detected events, not crash the graph. On the M1 rows the second
    # pass (v00002, really detected there at 0.812) is confirmed when cited at 0.3, so the claim airs.
    p = perceive.Perceiver({"tactical1": ROWS})
    result = asyncio.run(workflow.run_workflow(two_event_models("Two completed passes."), [EVENT, SECOND], 2,
                                               "seed900001-inline", inline_events=True, perceiver=p))
    assert [s for s in result.trace if s.action == "re_perceive"] and p.looks
    assert result.reviews[0].aired is not None


SECOND = detected(id="v00002", t=68.4, frame=1710, x=87.0, y=52.5, confidence=0.3)


def two_event_models(text: str) -> Models:
    # The moment is the sure pass (it has a graphic on air); the claim cites the unsure one as well.
    async def analyst(prompt):
        return json.dumps({"moments": [{"main_event": "v00001", "evidence": ["v00001", "v00002"]}]})

    async def tactician(prompt):
        return json.dumps({"text": text, "evidence": ["v00001", "v00002"]})

    async def challenger(prompt):
        return json.dumps({"agree": True})

    async def judge(claim, evidence):
        return Verdict(ok=True)

    return Models.scripted({}, analyst=analyst, tactician=tactician, challenger=challenger, judge=judge)


@pytest.mark.parametrize(("found", "aired"), [(sure(), True), (sure(team="home"), False), (None, False)])
def test_a_claim_on_an_unsure_detection_airs_only_when_another_camera_confirms_it(found, aired):
    events = [EVENT, SECOND]
    # Both passes happen in minute 2 (61 s to 119 s).
    result = asyncio.run(workflow.run_workflow(two_event_models("Two completed passes."), events, 2,
                                               "seed900001-inline", inline_events=True,
                                               perceiver=stub(found)))
    (review,) = result.reviews
    assert (review.aired is not None) == aired
    assert [s for s in result.trace if s.action == "re_perceive"]
    # Review of #267: the gate held the claim before the Judge saw it; a claim checked again after a
    # confirming look did reach the Judge, and its step is on the trace after the looks.
    first_look = next(n for n, s in enumerate(result.trace) if s.action == "re_perceive")
    judged_after = any(s.role == "judge" for s in result.trace[first_look:])
    assert judged_after == aired


def test_a_team_claim_on_an_unsure_side_is_never_aired_by_a_look():
    result = run(TEAM_CLAIM, stub(sure()))
    (review,) = result.reviews
    assert review.status == "held" and review.aired is None


def test_a_rejected_claim_is_not_looked_at_again():
    result = run("Away complete a pass of 99 m.", stub(sure()))
    assert not [s for s in result.trace if s.action == "re_perceive"]


def test_the_confirmed_reading_goes_through_the_whole_gate_again():
    # The re-check is the whole fact-checker on the confirmed reading: the run's own gate sees it.
    from ninety.agents.factcheck import confidence_gate

    seen = []

    def gate(claim, known):
        seen.append({i: dict(e) for i, e in known.items()})
        return confidence_gate(claim, known)

    asyncio.run(workflow.run_workflow(two_event_models("Two completed passes."), [EVENT, SECOND], 2,
                                      "seed900001-inline", inline_events=True, perceiver=stub(sure()),
                                      gate=gate))
    assert len(seen) == 2 and "re_perceived" not in seen[0]["v00002"]
    assert seen[1]["v00002"]["re_perceived"]["camera"] in {"broadcast", "tactical1"}  # no own camera here


def test_without_cameras_to_look_through_the_claim_is_held_as_before():
    (review,) = run(TEAM_CLAIM, None).reviews
    assert review.status == "held" and review.aired is None


def test_every_look_is_in_the_ledger_with_its_source():
    from ninety.agents.ledger import InMemoryLedger

    ledger = InMemoryLedger()
    asyncio.run(workflow.run_workflow(models(TEAM_CLAIM), [EVENT], 2, "seed900001-inline", ledger=ledger,
                                      inline_events=True, perceiver=stub(sure())))
    looks = [r for r in asyncio.run(ledger.query(kind="fact")) if r.source == "re_perceive"]
    assert looks == []  # a team claim on an unsure side: no look is spent on it
    asyncio.run(workflow.run_workflow(two_event_models("Two completed passes."), [EVENT, SECOND], 2,
                                      "seed900001-inline", ledger=ledger, inline_events=True,
                                      perceiver=stub(sure())))
    looks = [r for r in asyncio.run(ledger.query(kind="fact")) if r.source == "re_perceive"]
    assert looks and looks[0].payload["event"] == "v00002"
    assert looks[0].t == SECOND["t"]  # the looked-at event's time, not the moment's


def test_an_event_at_the_same_time_elsewhere_on_the_pitch_is_not_the_same_event():
    a = {"type": "pass", "t": 66.9, "x": 82.5, "y": 46.4}
    assert perceive._same(a, {**a, "x": 82.5 + perceive.MATCH_M - 0.1})
    assert not perceive._same(a, {**a, "x": 82.5 + perceive.MATCH_M + 0.1})
    assert not perceive._same(a, {**a, "t": 66.9 + perceive.MATCH_S + 0.01})
    assert not perceive._same(a, {**a, "type": "shot"})
