"""The M1 live path: detected events in, overlay cues out (ninety/agents/live.py)."""

import asyncio
import json

from jsonschema import validate

from ninety.agents import live
from ninety.agents.cues import SCHEMA
from ninety.agents.factcheck import MIN_CONFIDENCE, Claim, Verdict
from ninety.match import detected
from ninety.match.facts import compact

EVENTS = detected.load(detected.FIXTURES / "detected-standin-seed900001.jsonl")
BY_ID = {e["id"]: e for e in EVENTS}
SURE = next(e for e in EVENTS if e["type"] == "pass" and e.get("receiver") and e["confidence"] >= 0.8
            and compact(e)["minute"] == 2)


async def ask(prompt: str) -> str:
    return json.dumps({"text": f"{SURE['player']} finds {SURE['receiver']}.", "evidence": [SURE["id"]]})


async def judge(claim: Claim, evidence: list[dict]) -> Verdict:
    return Verdict(ok=True)


def test_template_cues_from_detected_events_only():
    result = asyncio.run(live.run(EVENTS))
    assert result.cues and result.facts and result.outcome is None
    for cue in result.cues:
        validate(cue, SCHEMA)
        assert all(BY_ID[i]["confidence"] >= MIN_CONFIDENCE for i in cue["evidence"])
    assert result.held_detections == [
        e["id"] for e in EVENTS if e["type"] in {"pass", "shot", "goal"} and e["confidence"] < MIN_CONFIDENCE
    ]
    assert [c["t_in"] for c in result.cues] == sorted(c["t_in"] for c in result.cues)


def test_a_verified_claim_airs_as_an_insight_cue():
    result = asyncio.run(live.run(EVENTS, ask=ask, judge=judge, minute=2))
    assert result.outcome.accepted
    insight = [c for c in result.cues if c["kind"] == "insight"]
    assert len(insight) == 1 and insight[0]["verified"] and insight[0]["evidence"] == [SURE["id"]]
    assert insight[0]["t_in"] == SURE["t"]
    validate(insight[0], SCHEMA)


def test_a_held_claim_does_not_air():
    unsure = next(e for e in EVENTS if e["type"] == "pass" and e.get("receiver")
                  and e["confidence"] < MIN_CONFIDENCE)

    async def ask_unsure(prompt: str) -> str:
        text = f"{unsure['player']} finds {unsure['receiver']}."
        return json.dumps({"text": text, "evidence": [unsure["id"]]})

    result = asyncio.run(live.run(EVENTS, ask=ask_unsure, judge=judge, minute=2))
    assert result.outcome.status == "held"
    assert not any(c["kind"] == "insight" for c in result.cues)


def test_the_cli_writes_cues_from_the_m1_clip(tmp_path, monkeypatch, capsys):
    out = tmp_path / "cues.jsonl"
    monkeypatch.setattr("sys.argv", ["ninety-live", "--out", str(out)])
    live.main()
    cues = [json.loads(line) for line in out.read_text().splitlines()]
    on_air = {i for c in cues for i in c["evidence"]}
    assert cues and on_air <= {e["id"] for e in detected.load(detected.m1_path())}
    assert ("stand-in" in capsys.readouterr().out) == detected.is_standin(detected.m1_path())
