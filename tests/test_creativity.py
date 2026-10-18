"""A8: choosing on the ball is split from executing it. Flair decides what he is drawn to, habits
pull toward one option, teamwork weighs the team's instructions; none of them makes an option more
likely to work."""

import dataclasses
import math
import random

import pytest

from ninety.sim import decisions as D
from ninety.sim import engine, roles
from ninety.sim.engine import Engine
from ninety.sim.profiles import ATTRIBUTES, MIND, Profile
from ninety.sim.style import HIGH, Style

PASSER = Profile.generate("CM", random.Random(7))


def scene(**kw) -> D.Scene:
    """A scene as the engine builds one (as in test_decisions), with his choosing attributes."""
    base = dict(x=60.0, y=34.0, goal_x=105.0, mates=[], opponents=[], keeper=None, decisions=0.5,
                composure=0.5, dribbling=0.5, traits=(), risk=0.0, absorb={}, passer=PASSER, heading=0.0)
    base.update(kw)
    base.setdefault("moving", [(ox, oy, 0.0, 0.0, False) for ox, oy in base["opponents"]])
    return D.Scene(**base)


SAFE = D.Option("pass", 0.010, (70.0, 34.0), "h5", chance=0.95)
BOLD = D.Option("pass", 0.010, (95.0, 34.0), "h9", chance=0.30)
HOLD = D.Option("hold", 0.005)


@pytest.fixture(autouse=True)
def hand_written_values(monkeypatch):
    monkeypatch.setattr(D, "POSSESSION", None)


def picks(monkeypatch, opts, n=600, **kw) -> dict[str, int]:
    """How often each option (by receiver, or kind) is chosen over n fresh possessions."""
    monkeypatch.setattr(D, "options", lambda s: opts)
    rng = random.Random(3)
    count: dict[str, int] = {}
    for _ in range(n):
        o = D.choose(scene(**kw), rng, {})
        key = o.receiver or o.kind
        count[key] = count.get(key, 0) + 1
    return count


def test_flair_draws_him_to_the_low_percentage_option_without_changing_what_it_is_worth(monkeypatch):
    plain = picks(monkeypatch, [SAFE, BOLD, HOLD], flair=0.5)
    creative = picks(monkeypatch, [SAFE, BOLD, HOLD], flair=1.0)
    careful = picks(monkeypatch, [SAFE, BOLD, HOLD], flair=0.0)
    assert creative["h9"] > plain["h9"] > careful.get("h9", 0)
    monkeypatch.undo()
    s = dict(x=60.0, mates=[("h9", 80.0, 30.0, 0.0)], opponents=[(70.0, 33.0)])
    worth = [(o.kind, o.value, o.chance) for o in D.options(scene(flair=0.0, **s))]
    assert worth == [(o.kind, o.value, o.chance) for o in D.options(scene(flair=1.0, **s))]


def test_an_average_flair_chooses_as_before_and_flair_is_measured_from_the_average(monkeypatch):
    monkeypatch.setattr(D, "options", lambda s: [SAFE, BOLD, HOLD])
    sc = scene(flair=0.5)
    t = D.temperature(sc) * D.choice_spread([o.value for o in (SAFE, BOLD, HOLD)])
    for seed in range(300):  # at 0.5 every choice is the plain misjudgement's, with no flair term
        tastes: dict = {}
        choice = D.choose(sc, random.Random(seed), tastes)
        assert choice is max((SAFE, BOLD, HOLD), key=lambda o: o.value / t + tastes[D.taste_key(sc, o)])
    monkeypatch.undo()
    below = picks(monkeypatch, [SAFE, BOLD, HOLD], n=3000, flair=0.4)
    above = picks(monkeypatch, [SAFE, BOLD, HOLD], n=3000, flair=0.6)
    plain = picks(monkeypatch, [SAFE, BOLD, HOLD], n=3000, flair=0.5)
    assert below["h9"] < plain["h9"] < above["h9"]  # 0.5 is the middle, not merely somewhere


def test_each_option_carries_his_own_estimate_that_it_works():
    opts = D.options(scene(x=50.0, mates=[("h9", 75.0, 34.0, 0.0)], opponents=[(60.0, 20.0), (65.0, 50.0)]))
    passes = [o for o in opts if o.kind == "pass"]
    carries = [o for o in opts if o.kind == "dribble"]
    assert passes and all(0.0 < o.chance < 1.0 for o in passes + carries)
    assert 0.0 < next(o for o in opts if o.kind == "hold").chance <= 1.0
    shots = [o for o in D.options(scene(x=90.0, opponents=[(95.0, 30.0)])) if o.kind == "shoot"]
    assert shots and 0.0 < shots[0].chance < 1.0


def test_a_habit_pulls_toward_its_one_option(monkeypatch):
    carry = D.Option("dribble", 0.010, (66.0, 34.0), chance=0.7)
    plain = picks(monkeypatch, [SAFE, carry, HOLD], traits=())
    habit = picks(monkeypatch, [SAFE, carry, HOLD], traits=("takes_players_on",))
    assert habit["dribble"] > plain["dribble"]
    short = D.Option("pass", 0.010, (68.0, 34.0), "h4", chance=0.95)  # 8 m: a short pass
    pulled = picks(monkeypatch, [short, BOLD, HOLD], traits=("plays_short",))
    usual = picks(monkeypatch, [short, BOLD, HOLD], traits=())
    assert pulled["h4"] > usual["h4"] and pulled["h9"] < usual["h9"]  # the 35 m pass gets no pull


def test_the_engine_hands_him_his_own_flair():
    e = Engine(3)
    carrier = e.by_id["h7"]
    e.give(carrier.id)
    carrier.profile.attributes["flair"] = 0.91
    assert e.scene_for(carrier).flair == 0.91


def test_teamwork_goes_with_game_intelligence_and_flair_with_neither_it_nor_quality():
    rng = random.Random(4)
    squad = [Profile.generate("CM", rng, archetype="box_to_box") for _ in range(600)]

    def corr(a, b):
        ma, mb = sum(a) / len(a), sum(b) / len(b)
        cov = sum((x - ma) * (y - mb) for x, y in zip(a, b, strict=True))
        return cov / (sum((x - ma) ** 2 for x in a) * sum((y - mb) ** 2 for y in b)) ** 0.5
    decisions = [p["decisions"] for p in squad]
    assert corr([p["teamwork"] for p in squad], decisions) > 0.3
    assert abs(corr([p["flair"] for p in squad], decisions)) < 0.1
    assert abs(corr([p["flair"] for p in squad], [p.quality for p in squad])) < 0.1


def test_teamwork_weighs_the_teams_instruction_on_and_off_the_ball():
    direct = Style(directness=HIGH)
    e = Engine(3, styles={"home": direct, "away": Style()})
    carrier = e.by_id["h7"]
    e.give(carrier.id)
    given = direct.progress_weight(e.brains["home"].attacking_transition(e.t))
    assert given > 1.0  # a direct team: its instruction pulls the weight above 1 (none)
    carrier.profile.attributes["teamwork"] = 0.5
    assert e.scene_for(carrier).progress_weight == given  # as given
    carrier.profile.attributes["teamwork"] = 1.0
    assert math.isclose(e.scene_for(carrier).progress_weight - 1, 1.5 * (given - 1))
    carrier.profile.attributes["teamwork"] = 0.0
    assert math.isclose(e.scene_for(carrier).progress_weight - 1, 0.5 * (given - 1))
    assert engine.instructed(1.0, 0.0) == engine.instructed(1.0, 1.0) == 1.0  # no instruction, no pull
    assert engine.instructed(0.1, 1.0) == 0.0  # a patient side's weight never turns a gain into a loss
    p, brain = e.by_id["h10"], e.brains["home"]
    p.profile = dataclasses.replace(p.profile, archetype="poacher", traits=[])
    w = roles.style_weight(engine.style_tilt(direct.directness), "in_behind")
    role = roles.role_of("poacher").prior("in_behind")
    assert w > 1.0
    p.profile.attributes["teamwork"] = 0.5
    assert math.isclose(e.move_prior(p, brain, "in_behind"), role * w)  # role, then the style
    p.profile.attributes["teamwork"] = 0.0
    assert e.move_prior(p, brain, "in_behind") == role  # he ignores the style
    p.profile.attributes["teamwork"] = 1.0
    assert math.isclose(e.move_prior(p, brain, "in_behind"), role * w ** 2)


def test_the_mind_attributes_leave_every_other_attribute_as_it_was():
    a = Profile.generate("RW", random.Random(5), 0.0, mind_rng=random.Random(1))
    b = Profile.generate("RW", random.Random(5), 0.0, mind_rng=random.Random(2))
    c = Profile.generate("RW", random.Random(5), 0.0)
    assert c == Profile.generate("RW", random.Random(5), 0.0)  # his own stream, from his name
    assert {k: a[k] for k in ATTRIBUTES} == {k: b[k] for k in ATTRIBUTES}
    assert (a.name, a.foot, a.traits) == (b.name, b.foot, b.traits)
    assert any(a[k] != b[k] for k in MIND)


def test_flair_and_teamwork_follow_the_role():
    rng = random.Random(9)
    winger = [Profile.generate("RW", rng, archetype="inside_forward")["flair"] for _ in range(300)]
    stopper = [Profile.generate("RCB", rng, archetype="stopper")["flair"] for _ in range(300)]
    assert sum(winger) / 300 > sum(stopper) / 300 + 0.2
