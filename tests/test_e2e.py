"""ninety-e2e runs the whole chain on one clip with no Azure, and writes a bundle the viewer reads."""

import json
from pathlib import Path

import pytest
from jsonschema import validate

from ninety import e2e
from tests.e2e_clip import EVENTS, write_clip

ROOT = Path(__file__).resolve().parent.parent
CUE_SCHEMA = json.loads((ROOT / "schemas/overlay_cue.schema.json").read_text())


def run(tmp_path: Path, *extra: str) -> tuple[Path, dict]:
    clip, detections = write_clip(tmp_path)
    out = tmp_path / "bundle"
    e2e.main([str(clip), "--out", str(out), "--detections", str(detections), "--frames", *extra])
    return out, json.loads((out / "manifest.json").read_text())


def cues(out: Path) -> list[dict]:
    return [json.loads(line) for line in (out / "cues.jsonl").read_text().splitlines()]


def test_bundle_has_every_stage(tmp_path):
    out, manifest = run(tmp_path)
    assert manifest["clip"] == "seed42" and manifest["format"] == e2e.BUNDLE_FORMAT
    assert manifest["detections"] == {"source": "recorded", "frames": 75}
    assert manifest["footage"] == {"kind": "frames", "src": "frames/", "pattern": "%05d.jpg", "frames": 75}
    assert len(list((out / "frames").glob("*.jpg"))) == 75
    assert manifest["facts"] > 0 and json.loads((out / "facts.json").read_text())
    for name in manifest["files"]:
        assert (out / name).exists(), name
    for cue in cues(out):
        validate(cue, CUE_SCHEMA)
    # One template cue per persona for each pass and shot, and the minute's verified insight.
    kinds = sorted((c["kind"], c["persona"]) for c in cues(out))
    assert kinds.count(("pass_arc", "casual")) == 2 and kinds.count(("shot_speed", "analyst")) == 1
    assert [c["persona"] for c in cues(out) if c["kind"] == "insight"] == ["analyst", "casual"]


def test_stand_in_events_are_named_as_ground_truth(tmp_path):
    """Until vision events land, the bundle and the viewer say the events are the simulator's."""
    _, manifest = run(tmp_path)
    assert manifest["events"] == {"source": e2e.STAND_IN, "count": len(EVENTS)}
    assert "ground truth" in manifest["events"]["source"]


def test_the_claim_is_about_the_shot_and_carries_its_numbers(tmp_path):
    out, manifest = run(tmp_path)
    (claim,) = json.loads((out / "trace.json").read_text())["claims"]
    assert claim["status"] == "accepted" and claim["evidence"] == ["e2"]
    assert claim["text"] == "h8 shot, on target, 101 km/h."
    assert claim["mode"] == "offline" and manifest["agents"]["mode"] == "offline"
    # Offline the Judge never ran; the trace must not say it did.
    judge = [s for s in claim["steps"] if s["role"] == "judge"]
    assert judge and all(s["action"] == "skip" and "not run offline" in s["detail"] for s in judge)
    assert not any("replayed" in s["detail"] for s in claim["steps"])


def test_a_planted_number_is_rejected_then_fixed(tmp_path):
    out, manifest = run(tmp_path, "--plant")
    (claim,) = json.loads((out / "trace.json").read_text())["claims"]
    assert claim["drafts"] == 2 and claim["status"] == "accepted" and claim["planted"]
    rejected = [s for s in claim["steps"] if s["role"] == "fact_checker" and s["action"] == "reject"]
    assert len(rejected) == 1 and "143" in rejected[0]["detail"]
    assert [s["action"] for s in claim["steps"]] == ["tamper", "draft", "reject", "draft", "skip", "verify"]
    insight = [c for c in cues(out) if c["kind"] == "insight"]
    assert insight and all("143" not in c["text"] and c["verified"] for c in insight)
    assert manifest["agents"]["planted"]


def test_a_claim_the_fact_checker_never_accepts_never_airs(tmp_path, monkeypatch):
    async def ask(prompt: str) -> str:
        return json.dumps({"text": "h8 shot at 999 km/h.", "evidence": ["e2"]})

    monkeypatch.setattr(e2e, "offline_analyst", lambda events: ask)
    out, manifest = run(tmp_path)
    (claim,) = json.loads((out / "trace.json").read_text())["claims"]
    assert claim["status"] == "held_back" and claim["drafts"] == 3
    assert claim["steps"][-1]["action"] == "hold"
    assert not [c for c in cues(out) if c["kind"] == "insight"]
    assert manifest["agents"]["accepted"] == 0
    # The template cues still air: they passed the code checks on their own.
    assert [c for c in cues(out) if c["kind"] == "shot_speed"]


def test_vision_events_refuse_to_run_until_they_exist(tmp_path, monkeypatch):
    clip, detections = write_clip(tmp_path)
    try:
        import ninety.vision.events  # noqa: F401
    except ImportError:
        with pytest.raises(SystemExit, match="ninety.vision.events"):
            e2e.main([str(clip), "--out", str(tmp_path / "b"), "--detections", str(detections),
                      "--frames", "--events", "vision"])
    else:
        pytest.skip("vision events exist: the stub is no longer the path")


def test_events_that_break_the_schema_stop_the_run(tmp_path, monkeypatch):
    clip, detections = write_clip(tmp_path)
    bad = [dict(EVENTS[0], team="neither")]
    monkeypatch.setitem(e2e.EVENT_SOURCES, "stand-in", lambda c, d: bad)
    with pytest.raises(Exception, match="neither"):
        e2e.main([str(clip), "--out", str(tmp_path / "b"), "--detections", str(detections), "--frames"])


def test_most_interesting_prefers_a_shot_then_the_faster_ball():
    passes = [{"id": "p1", "type": "pass", "player": "h1", "ball_speed_kmh": 30, "second": 1},
              {"id": "p2", "type": "pass", "player": "h2", "ball_speed_kmh": 60, "second": 2}]
    shot = {"id": "s1", "type": "shot", "player": "h3", "ball_speed_kmh": 20, "second": 3}
    assert e2e.most_interesting(passes)["id"] == "p2"
    assert e2e.most_interesting([*passes, shot])["id"] == "s1"
    assert e2e.most_interesting([]) is None


def test_trace_steps_have_the_agent_trace_shape(tmp_path):
    """schemas/agent_trace.schema.json (PR #105): checked against the schema once it is on main."""
    out, _ = run(tmp_path, "--plant")
    (claim,) = json.loads((out / "trace.json").read_text())["claims"]
    schema = ROOT / "schemas/agent_trace.schema.json"
    for step in claim["steps"]:
        assert set(step) == {"role", "moment", "action", "ms", "detail"} and step["moment"] == claim["id"]
        if schema.exists():
            validate(step, json.loads(schema.read_text()))


def test_trace_step_reads_live_timings():
    step = e2e.trace_step("judge: not supported (1.4s)", "claim-m3", judged=True)
    assert step == {"role": "judge", "moment": "claim-m3", "action": "reject", "ms": 1400.0,
                    "detail": "not supported"}


def test_events_file_reads_detected_events_and_refuses_ground_truth(tmp_path):
    clip, detections = write_clip(tmp_path)
    detected = tmp_path / "detected.jsonl"
    detected.write_text("".join(json.dumps(dict(e, source="vision", confidence=0.8)) + "\n" for e in EVENTS))
    out = tmp_path / "b"
    e2e.main([str(clip), "--out", str(out), "--detections", str(detections), "--frames",
              "--events-file", str(detected)])
    manifest = json.loads((out / "manifest.json").read_text())
    assert manifest["events"] == {"source": "vision: detected.jsonl", "count": len(EVENTS)}
    truth = tmp_path / "truth.jsonl"
    truth.write_text("".join(json.dumps(e) + "\n" for e in EVENTS))
    with pytest.raises(SystemExit, match="source=vision"):
        e2e.main([str(clip), "--out", str(tmp_path / "c"), "--detections", str(detections), "--frames",
                  "--events-file", str(truth)])


def test_auto_picks_vision_once_it_exists_and_the_demo_refuses_ground_truth(monkeypatch):
    monkeypatch.setattr(e2e, "vision_available", lambda: True)
    assert e2e.resolve_events("auto", demo=True) == "vision"
    monkeypatch.setattr(e2e, "vision_available", lambda: False)
    assert e2e.resolve_events("auto", demo=False) == "stand-in"
    with pytest.raises(SystemExit, match="--demo refuses"):
        e2e.resolve_events("auto", demo=True)
    with pytest.raises(SystemExit, match="--demo refuses"):
        e2e.resolve_events("stand-in", demo=True)
