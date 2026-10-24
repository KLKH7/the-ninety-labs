"""The Referee: offside readings from tracked positions on planted scenes, and its answers."""

import asyncio
import re
import sys
from pathlib import Path

import pytest

from ninety.agents import referee
from ninety.agents.factcheck import Claim
from ninety.agents.insight_check import verify
from ninety.intel import offside
from ninety.intel.scene import Frames

sys.path.insert(0, str(Path(__file__).parent))
from test_companion_match import Q, insights  # noqa: E402

from ninety.agents import companion_match as companion  # noqa: E402
from ninety.agents.contracts import Question  # noqa: E402


def scene(receiver_x, opp_missing=0, team="home"):
    """A home pass from (60, 34) to h-t9; Fenwick's keeper at the line and a defender at 85 m."""
    home = [
        {"id": "h-t1", "team": "home", "x": 60.0, "y": 34.0},
        {"id": "h-t9", "team": "home", "x": receiver_x, "y": 30.0},
    ]
    away = [
        {"id": "a-t1", "team": "away", "x": 102.0, "y": 34.0},
        {"id": "a-t4", "team": "away", "x": 85.0, "y": 20.0},
    ]
    away += [
        {"id": f"a-t{i}", "team": "away", "x": 70.0, "y": 5.0 + 5 * i} for i in range(5, 14 - opp_missing)
    ]
    players = home + away
    if team == "away":
        players = [
            {
                **p,
                "team": "away" if p["team"] == "home" else "home",
                "x": 105 - p["x"],
                "id": ("a" if p["team"] == "home" else "h") + p["id"][1:],
            }
            for p in players
        ]
    return Frames([{"frame": 100, "t": 4.0, "ball": {"x": 60.0, "y": 34.0}, "players": players}])


def pass_to(receiver="h-t9", team="home", x=60.0):
    return {
        "id": "v1",
        "t": 4.0,
        "frame": 100,
        "type": "pass",
        "team": team,
        "x": x,
        "y": 34.0,
        "end_x": 90.0,
        "end_y": 30.0,
        "outcome": "success",
        "player": receiver[0] + "-t1",
        "receiver": receiver,
        "confidence": 0.9,
    }


@pytest.mark.parametrize(
    "x, want", [(90.0, "offside"), (86.0, "too_close"), (80.0, "onside"), (50.0, "onside")]
)
def test_a_reading_against_the_line(x, want):
    [f] = offside.offsides([pass_to()], scene(x))
    assert f["verdict"] == want
    assert f["visual"]["line_x"] == 85.0 and f["visual"]["second_last"][2] == "a-t4"


def test_away_attacks_the_other_way():
    [f] = offside.offsides([pass_to("a-t9", "away", x=45.0)], scene(90.0, team="away"))
    assert f["verdict"] == "offside" and f["visual"]["line_x"] == 20.0


def test_an_untracked_defender_can_only_make_an_offside_unsure():
    assert offside.offsides([pass_to()], scene(90.0, opp_missing=2))[0]["verdict"] == "unsure"
    assert offside.offsides([pass_to()], scene(80.0, opp_missing=2))[0]["verdict"] == "onside"


def test_a_pass_straight_after_a_restart_is_not_read():
    restart = {"id": "v0", "t": 2.5, "frame": 62, "type": "set_piece", "team": "home", "x": 60.0, "y": 0.0}
    assert offside.offsides([restart, pass_to()], scene(90.0))[0]["verdict"] == "restart"


def test_no_reading_without_the_receiver_tracked():
    assert offside.offsides([pass_to("h-t77")], scene(90.0)) == []


def test_the_laws_carry_no_numbers():
    from ninety.agents.factcheck import spelled_as_digits

    for _, text in referee.LAWS.values():
        assert not re.search(r"\d", spelled_as_digits(text)), text  # "becomes one" would read as 1


def reading(verdict, margin=5.0):
    return {
        "id": "off:v1",
        "kind": "offside",
        "team": "home",
        "club": "Oakfield",
        "minute": 23,
        "t": 1330.0,
        "verdict": verdict,
        "margin_m": margin,
        "confident": True,
        "receiver": "h-t5",
        "receiver_is": "Oakfield's left-back",
        "also": [[margin, "m"]] if verdict in ("onside", "offside") else [],
    }


@pytest.mark.parametrize(
    "verdict, claim, ok",
    [
        (
            "offside",
            "In minute 23, Oakfield's left-back was in an offside position, 5 m beyond the line.",
            True,
        ),
        ("offside", "In minute 23, Oakfield's left-back was onside by 5 m.", False),
        ("too_close", "In minute 23, Oakfield's left-back was offside.", False),
        ("too_close", "In minute 23, the offside line on Oakfield's left-back was too close to call.", True),
        ("onside", "In minute 23, the call was too close to make.", False),
    ],
)
def test_a_call_must_be_the_readings(verdict, claim, ok):
    f = reading(verdict)
    people = {
        "h-t5": {
            "track": "h-t5",
            "team": "home",
            "club": "Oakfield",
            "role": "LB",
            "position": "left-back",
            "name": None,
            "sheet_name": "X",
        }
    }
    assert (
        verify(Claim(claim, [f["id"]]), {f["id"]: f}, {"home": "Oakfield", "away": "Fenwick"}, people).ok
        is ok
    )


def test_the_referee_answers_offside_from_the_reading_and_the_law():
    mi = insights()
    mi.facts["offside"] = [reading("too_close")]
    q = Question("s1", None, "Was that offside?", Q.t)
    a = asyncio.run(companion.answer_match(q, mi)).answer
    assert a.status == "verified" and a.evidence[0] == "off:v1" and "too close" in a.text
    assert "law:11:position" in a.evidence


@pytest.mark.parametrize("text", ["Was that a penalty?", "Was that a foul?", "Was it handball?"])
def test_the_referee_never_rules_on_contact(text):
    a = asyncio.run(companion.answer_match(Question("s1", None, text, Q.t), insights())).answer
    assert a.status == "verified" and a.evidence[0] == "law:contact"
    assert "cannot judge" in a.text and not re.search(
        r"\bwas (?:a|not a) (?:foul|penalty|handball)\b", a.text
    )


def test_the_companion_hands_a_rules_question_to_the_referee():
    import json

    seen = []

    async def ask(prompt):
        seen.append(("companion", json.loads(prompt)["step"]))
        return json.dumps({"tools": [{"name": "referee", "club": None, "minute_from": 1, "minute_to": 29}]})

    async def ref(prompt):
        seen.append(("referee", json.loads(prompt)["step"]))
        return json.dumps(
            {
                "text": "The tracking sees where every player stands, not the contact between them, so "
                "it cannot judge a foul, a handball or a penalty shout: only the referee and the "
                "replays can.",
                "evidence": ["law:contact"],
            }
        )

    q = Question("s1", None, "Was that a penalty?", Q.t)
    r = asyncio.run(companion.answer_match(q, insights(), ask, referee_ask=ref))
    assert seen == [("companion", "plan"), ("referee", "answer")] and r.source == "model"
