"""Half-time (lesson 213, Laws 7 and 8): the referee ends the first half after 45 minutes, nothing is
played across it, and the second half starts with a kick-off by the team that did not take the
first. A half here is shortened (engine.HALF_S) so a test runs in seconds; the rule reads the
constant at run time. Each test fails on the engine before this change (lesson 8): there play ran on
through 45:00 and nobody kicked off again."""

import pytest

from ninety.sim import engine
from ninety.sim.engine import DT, PITCH_X, PITCH_Y, Engine

HALF = 70.0  # seconds: a short first half for the test


@pytest.fixture
def short_half(monkeypatch):
    monkeypatch.setattr(engine, "HALF_S", HALF)


def play(e: Engine, until: float) -> None:
    while e.t < until:
        e.step()


@pytest.mark.parametrize("seed", [3, 7, 11, 21])
def test_the_first_half_ends_at_its_time_and_the_other_team_kicks_off_the_second(short_half, seed):
    e = Engine(seed)
    e.kickoff("home", setup=True)
    play(e, HALF + 120.0)
    kicks = [ev for ev in e.match.events if ev["type"] == "kickoff"]
    goals = [ev for ev in e.match.events if ev["type"] == "goal"]
    assert e.half_time_at == pytest.approx(HALF, abs=DT)  # the whistle, at the half's time
    second = next(k for k in kicks if k["t"] >= e.half_time_at)
    assert second["team"] == "away"  # Law 8: the team that did not take the first kick-off
    assert not any(e.half_time_at <= g["t"] < second["t"] for g in goals)
    # nothing is played across the whistle: no pass, shot, tackle or restart until the kick-off
    played = [ev for ev in e.match.events if e.half_time_at <= ev["t"] < second["t"]
              and ev["type"] in ("pass", "shot", "set_piece", "tackle", "interception", "deflection")]
    assert played == []
    # and a pass or shot on its way at the whistle was closed there, as at a foul
    assert all(ev["outcome"] is not None for ev in e.match.events
               if ev["type"] in ("pass", "shot") and ev["t"] < e.half_time_at)


def test_the_first_half_waits_for_a_penalty_to_be_completed(short_half):
    """Law 7: the half is extended for a penalty kick awarded before its end to be taken and
    completed; then it ends, and the second half starts with the other team's kick-off."""
    e = Engine(3)
    e.kickoff("home", setup=True)
    play(e, HALF - 2.0)
    e.possessor, e.set_by, e.throw_by, e.dribbler, e.kicked = None, None, None, None, None
    e.stop("penalty_kick", "home", (PITCH_X - 11.0, PITCH_Y / 2))
    play(e, HALF + 200.0)
    taken = next(ev for ev in e.match.events if ev["type"] == "shot" and ev["t"] >= HALF - 2.0)
    assert taken["t"] > HALF  # premise: struck after the half's time
    assert e.half_time_at is not None and e.half_time_at >= taken["t"]
    second = next(k for k in e.match.events if k["type"] == "kickoff" and k["t"] >= e.half_time_at)
    assert second["team"] == "away"


def test_a_match_shorter_than_a_half_is_unchanged(monkeypatch):
    """Nothing happens before the half's time: a 20-minute match is the same frame for frame."""
    e = Engine(7)
    e.kickoff("home", setup=True)
    play(e, 30.0)
    assert e.half_time_at is None
    monkeypatch.setattr(engine, "HALF_S", 1e9)
    f = Engine(7)
    f.kickoff("home", setup=True)
    play(f, 30.0)
    assert e.match.events == f.match.events and e.frame == f.frame
