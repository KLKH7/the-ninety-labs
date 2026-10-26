"""Mode broadcast_side (ninety/agents/perceive.py; docs/eval/re-perceive-broadcast-plan.md)."""

from ninety.agents import perceive
from ninety.agents.factcheck import MIN_TEAM_CONFIDENCE

EVENT = {"id": "v1", "type": "pass", "team": "home", "player": "h-t7", "confidence": 0.9,
         "team_confidence": 0.6}
SURE = round(MIN_TEAM_CONFIDENCE + 0.01, 3)


def ask(association, broadcast):
    return perceive.broadcast_side(EVENT, association, broadcast)[0]


def test_a_sure_broadcast_vote_through_a_certain_pairing_resolves_on_the_claims_side_only():
    pair = {"a-t3": {"track": "h-t7", "confidence": 1.0}}
    assert ask(pair, {"a-t3": ("home", SURE)}) == "resolved"
    assert ask(pair, {"a-t3": ("away", SURE)}) == "contradicted"
    assert ask(pair, {"a-t3": ("home", MIN_TEAM_CONFIDENCE)}) == "unresolved"  # at the gate is not above it


def test_an_uncertain_pairing_or_none_never_resolves():
    assert ask({"a-t3": {"track": "h-t7", "confidence": 0.99}}, {"a-t3": ("home", SURE)}) == "unresolved"
    assert ask({"a-t3": {"track": "h-t9", "confidence": 1.0}}, {"a-t3": ("home", SURE)}) == "unresolved"
    two = {"a-t3": {"track": "h-t7", "confidence": 1.0}, "a-t4": {"track": "h-t7", "confidence": 1.0}}
    assert ask(two, {"a-t3": ("home", SURE), "a-t4": ("home", SURE)}) == "unresolved"


def test_the_mode_is_not_enabled():
    assert "broadcast_side" not in perceive.MODES  # its plan's enabling rule is unmet (0 resolved of 13)
