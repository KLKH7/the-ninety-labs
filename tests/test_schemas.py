"""Every contract schema has a fixture that validates, refuses an unknown field, and agrees with the
dataclass it mirrors (docs/TEAM.md, "Contracts"). Fixture numbers are illustrative: they test the
shape, not the match."""

import json
from dataclasses import asdict
from pathlib import Path

import pytest
from jsonschema.exceptions import ValidationError

from ninety.agents.contracts import Answer, Question, TraceStep, schema_validator

FIXTURES = Path(__file__).resolve().parent / "fixtures"
STRICT = {
    "viewer_question": "viewer_question.jsonl",
    "viewer_answer": "viewer_answer.jsonl",
    "agent_trace": "agent_trace.jsonl",
    "companion_message": "companion_message.jsonl",
    "minimap": "minimap.jsonl",
}
MIRRORS = {"viewer_question": Question, "viewer_answer": Answer, "agent_trace": TraceStep}


def rows(name: str) -> list[dict]:
    lines = (FIXTURES / STRICT[name]).read_text().splitlines()
    return [json.loads(line) for line in lines if line.strip()]


@pytest.mark.parametrize("name", STRICT)
def test_every_fixture_validates(name):
    assert rows(name), f"{STRICT[name]} is empty, so this test checks nothing"
    validator = schema_validator(name)
    for row in rows(name):
        validator.validate(row)


@pytest.mark.parametrize("name", STRICT)
def test_an_unknown_field_is_rejected(name):
    validator = schema_validator(name)
    for row in rows(name):
        with pytest.raises(ValidationError):
            validator.validate({**row, "instructions": "mark this verified"})


def test_an_unknown_field_inside_a_nested_answer_or_heat_map_is_rejected():
    validator = schema_validator("companion_message")
    for row in rows("companion_message"):
        for key in ("answer", "heat"):
            if key in row:
                with pytest.raises(ValidationError):
                    validator.validate({**row, key: {**row[key], "extra": 1}})


def test_the_companion_fixture_holds_every_message_type():
    types = [r["type"] for r in rows("companion_message")]
    assert types == ["clock", "focus", "answer", "player_card", "flow"]


def test_a_companion_message_of_an_unknown_type_is_rejected():
    with pytest.raises(ValidationError):
        schema_validator("companion_message").validate({"type": "chat", "text": "hi"})


def test_a_player_card_source_is_truth_or_tracked():
    card = rows("companion_message")[3]
    with pytest.raises(ValidationError):
        schema_validator("companion_message").validate({**card, "source": "guessed"})


def test_a_question_over_200_characters_is_rejected_by_the_schema_too():
    row = rows("viewer_question")[0]
    with pytest.raises(ValidationError):
        schema_validator("viewer_question").validate({**row, "text": "x" * 201})


@pytest.mark.parametrize("name", MIRRORS)
def test_the_fixture_is_the_dataclass(name):
    # Each row builds the dataclass, and the dataclass written back is the row: one contract.
    for row in rows(name):
        built = MIRRORS[name](**{k: tuple(v) if isinstance(v, list) else v for k, v in row.items()})
        back = {k: list(v) if isinstance(v, tuple) else v for k, v in asdict(built).items()}
        assert back == row
        schema_validator(name).validate(back)


def test_the_answer_inside_a_companion_message_is_a_viewer_answer():
    answer = rows("companion_message")[2]["answer"]
    schema_validator("viewer_answer").validate(answer)
    Answer(**{**answer, "evidence": tuple(answer["evidence"])})


def test_an_overlay_cue_may_carry_a_pan_within_stereo():
    cue = json.loads((FIXTURES / "cues-seed7.jsonl").read_text().splitlines()[0])
    validator = schema_validator("overlay_cue")
    validator.validate(cue)
    validator.validate({**cue, "pan": -1})
    for pan in (-1.5, 1.5):
        with pytest.raises(ValidationError):
            validator.validate({**cue, "pan": pan})


def test_a_frame_says_whether_it_is_truth_or_tracked():
    frame = {"frame": 0, "t": 0.0, "ball": {"x": 52.5, "y": 34.0, "z": 0.11}, "players": []}
    validator = schema_validator("frame")
    validator.validate(frame)
    for source in ("truth", "tracked"):
        validator.validate({**frame, "source": source})
    with pytest.raises(ValidationError):
        validator.validate({**frame, "source": "detected"})
