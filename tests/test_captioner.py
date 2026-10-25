"""The Captioner (ninety/agents/captioner.py): a model caption for a highlight airs only if the code
checks, the label check and the Judge all pass it; anything else keeps the code caption and says why.
No Azure: the model and the Judge are fakes of their contracts."""

import asyncio

import pytest

from ninety import e2e
from ninety.agents import captioner
from ninety.agents.captioner import kind_reasons
from ninety.agents.factcheck import Verdict, label_reasons
from ninety.highlights import Verdict as Measured
from ninety.highlights import reel

MEASURED = Measured(save_filter=True, margins={"v_kmh": 1.0, "d_m": 0.5, "x_m": 0.2, "y_m": 0.2, "T_s": 0.02})


def ev(eid, t, kind="pass", team="home", player="h4", x=60.0, y=34.0, confidence=0.9, **more):
    return {"id": eid, "t": t, "frame": round(t * 25), "type": kind, "team": team, "player": player,
            "x": x, "y": y, "source": "vision", "confidence": confidence, **more}


def scene(x=105 - 26.0, kmh=112.4, outcome="goal", around_confidence=0.9):
    """A pass from h4 to h9, then h9's shot 26 m out at 112.4 km/h: a THUNDERBOLT when it scores."""
    events = [ev("p1", 60.0, receiver="h9", outcome="success", end_x=x, end_y=34.0, ball_speed_kmh=50.0,
                 confidence=around_confidence),
              ev("s1", 61.0, "shot", player="h9", x=x, outcome=outcome, ball_speed_kmh=kmh)]
    return events, reel(events, MEASURED)


def says(text):
    async def model(body):
        says.prompt = body
        return text
    return model


def judge_says(ok, category=None):
    async def judge(claim, evidence):
        return Verdict(ok=ok, reasons=[] if ok else ["no"], category=category)
    return judge


PASSES = judge_says(True)


def run(text_or_model, judge=PASSES, events_reel=None, **kw):
    events, r = events_reel or scene()
    model = says(text_or_model) if isinstance(text_or_model, str) else text_or_model
    return asyncio.run(captioner.captions(r["moments"], events, model, judge, **kw))[0]


# What airs


def test_a_caption_the_fact_checker_passes_airs():
    out = run("A thunderbolt from h9, 26 m out at 112 km/h!")
    assert (out["source"], out["text"], out["call"]["problem"]) == (
        "model", "A thunderbolt from h9, 26 m out at 112 km/h!", None)


def test_the_model_is_given_the_label_the_shot_its_build_up_and_the_distance():
    run("h9 scores.")
    body = says.prompt
    assert body["moment"] == {"kind": "goal", "label": "THUNDERBOLT", "team": "home", "origin": None}
    assert body["shot"]["id"] == "s1" and [e["id"] for e in body["around"]] == ["p1"]
    assert (body["distance"]["value"], body["distance"]["unit"]) == (26, "m")


def test_a_fan_word_the_code_did_not_give_keeps_the_code_caption():
    events, r = scene(x=105 - 12.0, kmh=80.0)  # 12 m at 80 km/h: no label, a plain GOAL
    out = run("What a screamer from h9!", events_reel=(events, r))
    assert out["source"] == "code"
    assert "screamer" in out["call"]["problem"]


def test_a_number_not_in_the_evidence_keeps_the_code_caption():
    out = run("h9 rifles it in from 30 m!")  # it was 26 m
    assert out["source"] == "code" and "30" in out["call"]["problem"]


def test_a_judge_that_rejects_or_holds_keeps_the_code_caption():
    assert run("h9 scores.", judge_says(False))["source"] == "code"
    held = run("h9 scores.", judge_says(False, "timeout"))
    assert held["source"] == "code" and held["call"]["problem"].startswith("judge held")


def test_a_failing_judge_or_none_keeps_the_code_caption():
    async def broken(claim, evidence):
        raise ConnectionError("https://secret.example/endpoint")
    out = run("h9 scores.", broken)
    assert out["source"] == "code"
    assert out["call"]["problem"] == "judge unavailable: ConnectionError"  # the type, never the message
    assert run("h9 scores.", None)["source"] == "code"


def test_a_model_that_fails_or_is_late_keeps_the_code_caption():
    async def slow(body):
        await asyncio.sleep(1)
        return "h9 scores."
    assert run(slow, timeout_s=0.01)["call"]["problem"] == "model unavailable: TimeoutError"

    async def broken(body):
        raise RuntimeError("token=abc")
    assert run(broken)["call"]["problem"] == "model unavailable: RuntimeError"


def test_an_unsure_detection_in_the_build_up_holds_the_caption():
    out = run("h4 finds h9, who scores.", events_reel=scene(around_confidence=0.3))
    assert out["source"] == "code" and out["call"]["problem"].startswith("held")


def test_without_a_model_every_caption_is_code_written_and_no_call_is_made():
    events, r = scene()
    out = asyncio.run(captioner.captions(r["moments"], events, None, None))
    assert out == [{"event": "s1", "text": "h9 scores from 26 m at 112 km/h.", "source": "code"}]


def test_the_code_caption_follows_the_moment():
    events, r = scene(x=105 - 6.0, kmh=56.0, outcome="on_target")
    out = asyncio.run(captioner.captions(r["moments"], events, None, None))
    assert out[0]["text"] == "h9 is denied from 6 m at 56 km/h."


def test_the_build_up_is_the_clip_before_the_shot_and_at_most_six_events():
    before = [ev(f"p{i}", 50.0 + i, receiver="h9", outcome="success") for i in range(10)]  # 50 to 59 s
    events = [ev("old", 40.0), *before, ev("s1", 61.0, "shot", player="h9", x=94.0, outcome="goal",
                                         ball_speed_kmh=80.0), ev("after", 62.0)]
    moment = reel(events, MEASURED)["moments"][0]  # clip from 53 s
    _, around, _ = captioner.evidence_for(moment, events)
    assert [e["id"] for e in around] == ["p4", "p5", "p6", "p7", "p8", "p9"]


def test_the_build_up_starts_where_the_moments_clip_does():
    events = [ev("old", 52.9), ev("p1", 55.0), ev("p2", 58.0),
              ev("s1", 61.0, "shot", player="h9", x=94.0, outcome="goal", ball_speed_kmh=80.0)]
    moment = reel(events, MEASURED)["moments"][0]  # clip from 53 s: 52.9 s is before it
    _, around, _ = captioner.evidence_for(moment, events)
    assert [e["id"] for e in around] == ["p1", "p2"]


def test_the_distance_is_given_in_whole_metres_as_a_caption_writes_it():
    events, r = scene(x=105 - 26.4)  # 26.4 m
    assert captioner.distance_fact(r["moments"][0])["value"] == 26
    assert run("A thunderbolt from 26 m by h9!", events_reel=(events, r))["source"] == "model"


def test_apply_puts_each_caption_on_its_moment():
    events, r = scene()
    captioner.apply(r, [{"event": "s1", "text": "x", "source": "model"}])
    assert (r["moments"][0]["caption"], r["moments"][0]["caption_source"]) == ("x", "model")


# The label check (factcheck.label_reasons)


@pytest.mark.parametrize("text,label,ok", [
    ("a screamer from h9", "SCREAMER", True),
    ("a screamer from h9", "THUNDERBOLT", True),
    ("a screamer from h9", "LONG-RANGE", False),
    ("a rocket from h9", "ROCKET", True),
    ("a rocket from h9", "THUNDERBOLT", True),
    ("a rocket from h9", "GOAL", False),
    ("a powerful strike", "SCREAMER", False),
    ("a thunderbolt", "SCREAMER", False),
    ("a long-range effort", "LONG-RANGE", True),
    ("a long-ranger", "GOAL", False),
    ("struck from distance", "THUNDERBOLT", True),
    ("great reflexes", "REFLEX SAVE", True),
    ("a point-blank stop", "SAVE", False),
    ("a simple tap-in", "TAP-IN", True),
    ("tapped in by h9", "GOAL", False),
    ("into the top corner", "THUNDERBOLT", False),
    ("off the bar and in", "GOAL", False),
    ("an absolute worldie", "THUNDERBOLT", False),
    ("h9 scores from 12 m", "GOAL", True),
])
def test_a_fan_word_is_said_only_of_the_label_that_earns_it(text, label, ok):
    assert (label_reasons(text, label) == []) is ok


# In the bundle


def test_the_bundle_captions_every_highlight_with_code_by_default():
    events, r = scene()
    record = asyncio.run(e2e.caption_reel(r, events, "code"))
    assert r["moments"][0]["caption_source"] == "code"
    assert record == {"mode": "code", "calls": [], "tokens": {}, "unavailable": None}


def test_an_outage_keeps_the_code_captions_and_says_so(monkeypatch):
    def down(tokens):
        raise ConnectionError("https://secret.example")
    monkeypatch.setattr(captioner, "foundry_model", down)
    events, r = scene()
    record = asyncio.run(e2e.caption_reel(r, events, "foundry"))
    assert r["moments"][0]["caption_source"] == "code"
    assert record["unavailable"] == "ConnectionError"


def test_an_unpublished_captioner_refuses_to_run(monkeypatch):
    from ninety.agents.foundry import RegistryDrift

    def drift(tokens):
        raise RegistryDrift("ninety-captioner has never been published")
    monkeypatch.setattr(captioner, "foundry_model", drift)
    events, r = scene()
    with pytest.raises(RegistryDrift):
        asyncio.run(e2e.caption_reel(r, events, "foundry"))


# How the attack started, in the captions


def corner_scene():
    """The scene, with a corner before it: the ball out over home's attacking line off away."""
    events, _ = scene()
    events = [ev("o1", 59.0, "out_of_play", team="away", player=None, x=105.3, y=60.0), *events]
    return events, reel(events, MEASURED)


def test_a_caption_may_name_the_restart_the_attack_came_from():
    events, r = corner_scene()
    assert r["moments"][0]["origin"] == "corner"
    assert run("From the corner, h9 smashes a thunderbolt in!", events_reel=(events, r))["source"] == "model"


def test_a_restart_the_code_did_not_find_keeps_the_code_caption():
    out = run("From the corner, h9 smashes a thunderbolt in!")  # this attack's start was not seen
    assert out["source"] == "code" and "corner" in out["call"]["problem"]
    events, r = corner_scene()
    out = run("A free kick, and h9 smashes a thunderbolt in!", events_reel=(events, r))
    assert out["source"] == "code" and "free kick" in out["call"]["problem"]


def test_the_code_caption_says_where_the_attack_started():
    events, r = corner_scene()
    out = asyncio.run(captioner.captions(r["moments"], events, None, None))
    assert out[0]["text"] == "h9 scores from 26 m at 112 km/h, from a corner."


@pytest.mark.parametrize("text,origin,ok", [
    ("from a corner", "corner", True),
    ("from a corner", "open_play", False),
    ("a corner kick", None, False),
    ("into the top corner", "open_play", True),  # a part of the goal, not the restart
    ("the far corner of the net", "open_play", True),
    ("tucked into the corner of the net", "open_play", True),
    ("a penalty", None, False),
    ("from the spot kick", "corner", False),
    ("a long throw-in", "throw_in", True),
    ("a long throw-in", "corner", False),
    ("from the goal kick", "goal_kick", True),
    ("straight from the kick-off", "kick_off", True),
    ("a set piece", "throw_in", True),
    ("a set piece", "open_play", False),
    ("a free kick", "corner", False),
    ("on the counter", "open_play", False),
    ("won back and finished", "open_play", True),
])
def test_a_restart_is_named_only_as_the_code_found_it(text, origin, ok):
    from ninety.agents.factcheck import origin_reasons
    assert (origin_reasons(text, origin) == []) is ok


# The kind check (captioner.kind_reasons): a save is never a goal and a goal never a save


@pytest.mark.parametrize("text,kind,ok", [
    ("h9 scores from 26 m", "goal", True),
    ("h9 scores from 26 m", "save", False),
    ("h9 finds the net", "save", False),
    ("h9's rocket is into the net", "save", False),
    ("what a goal", "save", False),
    ("h9 beats the keeper", "save", False),
    ("h9's effort from 26 m is kept out", "save", True),
    ("h9's effort from 26 m is kept out", "goal", False),
    ("Denied! the keeper stops h9", "goal", False),
    ("a fine save", "goal", False),
    ("h9 puts it wide", "goal", False),
    ("a thunderbolt from h9, 26 m out", "goal", True),
    ("a goalkeeper's day at the office", "save", True),
    ("saved by the keeper", "save", True),
    ("h9 beats the goalkeeper", "save", False),
    ("h9 puts the home side ahead", "save", False),
    ("it is 1-0", "save", False),
    ("h9 pulls one back", "save", False),
    ("h9 lashes it in", "save", False),
    ("the keeper claws it away", "goal", False),
    ("what a stop", "goal", False),
    ("the keeper gets a hand to it", "goal", False),
    ("it flashes past the post", "goal", False),
    ("Great stop by the keeper from h9's rocket", "save", True),
    ("A thunderbolt from h9, 26 m out at 112 km/h!", "goal", True),
    ("h9 is denied from 26 m", "save", True),
])
def test_a_save_is_never_captioned_as_a_goal_nor_a_goal_as_a_save(text, kind, ok):
    assert (kind_reasons(text, kind) == []) is ok


def test_a_save_captioned_as_a_goal_keeps_the_code_caption_even_when_the_judge_passes_it():
    events, r = scene(outcome="on_target")  # the same strike, saved: a ROCKET, kind save
    assert r["moments"][0]["kind"] == "save"
    out = run("h9 scores from 26 m!", events_reel=(events, r))
    assert out["source"] == "code" and "scores" in out["call"]["problem"]
    ok = run("A rocket from h9, kept out by the keeper.", events_reel=(events, r))
    assert ok["source"] == "model"


def test_a_goal_captioned_as_a_save_keeps_the_code_caption():
    out = run("A thunderbolt from h9 and the keeper makes the save!")
    assert out["source"] == "code" and "save" in out["call"]["problem"]
