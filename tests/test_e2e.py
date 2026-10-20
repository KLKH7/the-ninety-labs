"""ninety-e2e runs the whole chain on one clip with no Azure, and writes a bundle the viewer reads.
Its cues come from R4's live path (ninety/agents/live.py); these tests pin what e2e adds around it."""

import builtins
import io
import json
from pathlib import Path

import pytest
from jsonschema import validate

from ninety import e2e
from ninety.match import detected
from tests.e2e_clip import EVENTS, write_clip

ROOT = Path(__file__).resolve().parent.parent
CUE_SCHEMA = json.loads((ROOT / "schemas/overlay_cue.schema.json").read_text())
TRACE_SCHEMA = json.loads((ROOT / "schemas/agent_trace.schema.json").read_text())


def run(tmp_path: Path, *extra: str, events: list[dict] | None = None) -> tuple[Path, dict]:
    clip, detections, events_file = write_clip(tmp_path)
    if events is not None:
        events_file.write_text("".join(json.dumps(e) + "\n" for e in events))
    out = tmp_path / "bundle"
    e2e.main([str(clip), "--out", str(out), "--detections", str(detections), "--frames",
              "--events-file", str(events_file), *extra])
    return out, json.loads((out / "manifest.json").read_text())


def cues(out: Path) -> list[dict]:
    return [json.loads(line) for line in (out / "cues.jsonl").read_text().splitlines()]


def only_claim(out: Path) -> dict:
    (claim,) = json.loads((out / "trace.json").read_text())["claims"]
    return claim


def test_bundle_has_every_stage(tmp_path):
    out, manifest = run(tmp_path)
    assert manifest["clip"] == "seed42" and manifest["format"] == e2e.BUNDLE_FORMAT
    assert manifest["detections"] == {"source": "recorded", "frames": 75}
    assert manifest["footage"] == {"kind": "frames", "src": "frames/", "pattern": "%05d.jpg", "frames": 75}
    assert len(list((out / "frames").glob("*.jpg"))) == 75
    assert manifest["facts"] > 0 and json.loads((out / "facts.json").read_text())
    assert manifest["events"]["source"] == "detected (detected-seed42.jsonl)"
    assert not manifest["events"]["standin"]
    for name in manifest["files"]:
        assert (out / name).exists(), name
    for cue in cues(out):
        validate(cue, CUE_SCHEMA)
    kinds = [(c["kind"], c["persona"]) for c in cues(out)]
    assert kinds.count(("pass_arc", "casual")) == 2 and kinds.count(("shot_speed", "analyst")) == 1
    assert kinds.count(("insight", "analyst")) == 1


def test_the_answer_key_is_never_opened(tmp_path, monkeypatch):
    """The clip's events.jsonl and frames.jsonl are ground truth: nothing on this path reads them."""
    clip, detections, events = write_clip(tmp_path)
    read: list[str] = []
    real_open, real_read = builtins.open, Path.read_text

    def spy_open(file, mode="r", *a, **k):
        if "r" in mode:
            read.append(str(file))
        return real_open(file, mode, *a, **k)

    def spy_read(self, *a, **k):
        read.append(str(self))
        return real_read(self, *a, **k)

    monkeypatch.setattr(builtins, "open", spy_open)
    monkeypatch.setattr(io, "open", spy_open)
    monkeypatch.setattr(Path, "read_text", spy_read)
    e2e.main([str(clip), "--out", str(tmp_path / "b"), "--detections", str(detections), "--frames",
              "--events-file", str(events)])
    assert str(clip / "clip.json") in read, "the spy did not see the clip read: it is not watching"
    assert not [p for p in read if p.startswith(str(clip)) and p.endswith(("events.jsonl", "frames.jsonl"))]


def test_ground_truth_events_are_refused(tmp_path):
    with pytest.raises(ValueError, match="never ground truth"):
        run(tmp_path, events=[dict(e, source="truth") for e in EVENTS])


def test_the_claim_is_about_the_shot_and_carries_its_numbers(tmp_path):
    out, manifest = run(tmp_path)
    claim = only_claim(out)
    assert claim["status"] == "accepted" and claim["verdict"] == "verified" and claim["evidence"] == ["e2"]
    assert claim["text"] == "h8 shot, on target, 101 km/h."
    assert claim["mode"] == "offline" and manifest["agents"]["mode"] == "offline"
    # Offline the Judge never ran; the trace must not say it did.
    judge = [s for s in claim["steps"] if s["role"] == "judge"]
    assert judge and all(s["action"] == "skip" and "not run offline" in s["detail"] for s in judge)
    (insight,) = [c for c in cues(out) if c["kind"] == "insight"]
    assert insight["text"] == claim["text"] and insight["verified"] and insight["evidence"] == ["e2"]


def test_a_planted_number_is_rejected_then_fixed(tmp_path):
    out, manifest = run(tmp_path, "--plant")
    claim = only_claim(out)
    assert claim["drafts"] == 2 and claim["status"] == "accepted" and claim["planted"]
    assert [s["action"] for s in claim["steps"]] == ["draft", "reject", "draft", "skip", "verify"]
    (rejected,) = [s for s in claim["steps"] if s["action"] == "reject"]
    assert "143" in rejected["detail"] and "143" in claim["steps"][0]["detail"]
    insight = [c for c in cues(out) if c["kind"] == "insight"]
    assert insight and all("143" not in c["text"] for c in insight)
    assert manifest["agents"]["planted"]


def test_a_claim_the_fact_checker_never_accepts_never_airs(tmp_path, monkeypatch):
    async def ask(prompt: str) -> str:
        return json.dumps({"text": "h8 shot at 999 km/h.", "evidence": ["e2"]})

    monkeypatch.setattr(e2e, "offline_analyst", lambda events, plant: ask)
    out, manifest = run(tmp_path)
    claim = only_claim(out)
    assert claim["status"] == "held_back" and claim["verdict"] == "rejected" and claim["drafts"] == 3
    assert claim["steps"][-1]["action"] == "hold"
    assert not [c for c in cues(out) if c["kind"] == "insight"]
    assert manifest["agents"]["accepted"] == 0
    assert [c for c in cues(out) if c["kind"] == "shot_speed"]  # the template cue still airs


def test_an_unsure_detection_is_held_and_named(tmp_path):
    unsure = [dict(e, confidence=0.2) if e["id"] == "e3" else e for e in EVENTS]
    out, manifest = run(tmp_path, events=unsure)
    assert manifest["events"]["held"] == ["e3"]
    assert not [c for c in cues(out) if "e3" in c["evidence"]]


def test_only_events_inside_the_clip_go_on(tmp_path):
    late = dict(EVENTS[0], id="e9", t=500.0, frame=12500)
    out, manifest = run(tmp_path, events=[*EVENTS, late])
    assert manifest["events"]["count"] == len(EVENTS)
    assert "e9" not in (out / "events.jsonl").read_text()


def test_the_stand_in_is_named_and_the_demo_refuses_it(tmp_path):
    clip, detections, _ = write_clip(tmp_path)
    standin = tmp_path / "detected-standin-seed42.jsonl"
    standin.write_text("".join(json.dumps(e) + "\n" for e in EVENTS))
    assert detected.is_standin(standin)
    args = [str(clip), "--detections", str(detections), "--frames", "--events-file", str(standin)]
    e2e.main([*args, "--out", str(tmp_path / "b")])
    manifest = json.loads((tmp_path / "b" / "manifest.json").read_text())
    assert manifest["events"]["standin"] and "not the detector's output" in manifest["events"]["source"]
    with pytest.raises(SystemExit, match="--demo refuses"):
        e2e.main([*args, "--out", str(tmp_path / "c"), "--demo"])


def test_trace_steps_are_agent_trace_records(tmp_path):
    out, _ = run(tmp_path, "--plant")
    claim = only_claim(out)
    for step in claim["steps"]:
        validate(step, TRACE_SCHEMA)
        assert step["moment"] == claim["id"]


def test_trace_step_reads_live_timings():
    step = e2e.trace_step("judge: not supported (1.4s)", "claim-m3", judged=True)
    assert step == {"role": "judge", "moment": "claim-m3", "action": "reject", "ms": 1400.0,
                    "detail": "not supported"}


def test_most_interesting_prefers_a_shot_then_the_faster_ball():
    passes = [{"id": "p1", "type": "pass", "player": "h1", "ball_speed_kmh": 30, "second": 1},
              {"id": "p2", "type": "pass", "player": "h2", "ball_speed_kmh": 60, "second": 2}]
    shot = {"id": "s1", "type": "shot", "player": "h3", "ball_speed_kmh": 20, "second": 3}
    assert e2e.most_interesting(passes)["id"] == "p2"
    assert e2e.most_interesting([*passes, shot])["id"] == "s1"
    assert e2e.most_interesting([]) is None
