"""A8: choosing on the ball is split from executing it. Vision decides what he sees, flair what he is
drawn to, habits pull toward one option, teamwork weighs the team's instructions; none of them makes
an option more likely to work."""

import math
import random

import pytest

from ninety.sim import decisions as D
from ninety.sim import roles
from ninety.sim.engine import Engine
from ninety.sim.profiles import ATTRIBUTES, MIND, Profile

PASSER = Profile.generate("CM", random.Random(7))


def scene(**kw) -> D.Scene:
    """A scene as the engine builds one (as in test_decisions), with his choosing attributes."""
    base = dict(x=60.0, y=34.0, goal_x=105.0, mates=[], opponents=[], keeper=None, decisions=0.5,
                composure=0.5, dribbling=0.5, traits=(), risk=0.0, absorb={}, passer=PASSER, heading=0.0)
    base.update(kw)
    base.setdefault("moving", [(ox, oy, 0.0, 0.0, False) for ox, oy in base["opponents"]])
    return D.Scene(**base)

SAFE = D.Option("pass", 0.010, (70.0, 34.0), "h5", chance=0.95)
BOLD = D.Option("pass", 0.010, (95.0, 34.0), "h9", chance=0.30, bypassed=0)
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


def test_an_average_flair_chooses_as_before(monkeypatch):
    monkeypatch.setattr(D, "options", lambda s: [SAFE, BOLD, HOLD])
    sc = scene(flair=0.5)
    tastes: dict = {}
    choice = D.choose(sc, random.Random(5), tastes)
    t = D.temperature(sc) * D.choice_spread([o.value for o in (SAFE, BOLD, HOLD)])
    gumbel = {k: -math.log(-math.log(v)) for k, v in tastes.items() if k[0] != "seen"}
    best = max((SAFE, BOLD, HOLD), key=lambda o: o.value / t + gumbel[D.taste_key(sc, o)])
    assert choice is best


def test_vision_decides_whether_he_sees_a_pass_that_takes_opponents_out(monkeypatch):
    killer = D.Option("pass", 0.030, (95.0, 34.0), "h9", chance=0.6, bypassed=3)
    blind = picks(monkeypatch, [SAFE, killer, HOLD], vision=0.0)
    sharp = picks(monkeypatch, [SAFE, killer, HOLD], vision=1.0)
    assert sharp["h9"] > blind.get("h9", 0) * 2
    level = D.Option("pass", 0.030, (95.0, 34.0), "h9", chance=0.6, bypassed=0)
    assert picks(monkeypatch, [SAFE, level, HOLD], vision=0.0)["h9"] == picks(
        monkeypatch, [SAFE, level, HOLD], vision=1.0)["h9"]  # nothing to notice: vision does not matter


def test_what_he_has_not_noticed_stays_unnoticed_while_he_has_the_ball(monkeypatch):
    killer = D.Option("pass", 0.5, (95.0, 34.0), "h9", chance=0.9, bypassed=4)
    monkeypatch.setattr(D, "options", lambda s: [SAFE, killer, HOLD])
    rng = random.Random(11)
    for _ in range(50):  # the same look, again and again: the first notice decides
        tastes: dict = {}
        first = D.choose(scene(vision=0.0), rng, tastes).receiver
        assert all(D.choose(scene(vision=0.0), rng, tastes).receiver == first for _ in range(10))


def test_a_pass_takes_out_the_opponents_between_the_ball_and_where_it_arrives():
    s = scene(x=50.0, opponents=[(55.0, 30.0), (65.0, 40.0), (85.0, 34.0), (45.0, 34.0)], keeper=None)
    assert D.taken_out(s, 70.0) == 2  # the two between, not the one beyond or the one behind
    passes = [o for o in D.options(scene(x=50.0, mates=[("h9", 75.0, 34.0, 0.0)],
                                         opponents=[(60.0, 20.0), (65.0, 50.0)])) if o.kind == "pass"]
    assert passes and passes[0].bypassed == 2 and 0.0 < passes[0].chance <= 1.0


def test_a_habit_pulls_toward_its_one_option(monkeypatch):
    carry = D.Option("dribble", 0.010, (66.0, 34.0), chance=0.7)
    plain = picks(monkeypatch, [SAFE, carry, HOLD], traits=())
    habit = picks(monkeypatch, [SAFE, carry, HOLD], traits=("takes_players_on",))
    assert habit["dribble"] > plain["dribble"]
    short = D.Option("pass", 0.010, (68.0, 34.0), "h4", chance=0.95)  # 8 m: a short pass
    pulled = picks(monkeypatch, [short, BOLD, HOLD], traits=("plays_short",))
    usual = picks(monkeypatch, [short, BOLD, HOLD], traits=())
    assert pulled["h4"] > usual["h4"] and pulled["h9"] < usual["h9"]  # the 35 m pass gets no pull


def test_teamwork_weighs_the_teams_instruction_on_and_off_the_ball():
    e = Engine(3)
    carrier = e.by_id["h7"]
    e.give(carrier.id)
    style = roles.STYLES[e.brains["home"].build_up]
    carrier.profile.attributes["teamwork"] = 1.0
    assert abs(e.scene_for(carrier).progress - 1.5 * style.progress_per_m) < 1e-12
    carrier.profile.attributes["teamwork"] = 0.0
    assert abs(e.scene_for(carrier).progress - 0.5 * style.progress_per_m) < 1e-12
    p, brain = e.by_id["h10"], e.brains["home"]
    p.profile.archetype, p.profile.traits, brain.build_up = "poacher", [], "direct"
    p.profile.attributes["teamwork"] = 0.5
    assert abs(e.move_prior(p, brain, "in_behind") - 1.5 * 1.5) < 1e-12  # role, then the style
    p.profile.attributes["teamwork"] = 0.0
    assert e.move_prior(p, brain, "in_behind") == 1.5  # he ignores the style
    p.profile.attributes["teamwork"] = 1.0
    assert abs(e.move_prior(p, brain, "in_behind") - 1.5 * 1.5 ** 2) < 1e-12


def test_the_mind_attributes_leave_every_other_attribute_as_it_was():
    a = Profile.generate("RW", random.Random(5), 0.0, mind_rng=random.Random(1))
    b = Profile.generate("RW", random.Random(5), 0.0, mind_rng=random.Random(2))
    assert {k: a[k] for k in ATTRIBUTES} == {k: b[k] for k in ATTRIBUTES}
    assert (a.name, a.foot, a.traits) == (b.name, b.foot, b.traits)
    assert any(a[k] != b[k] for k in MIND)


def test_flair_and_teamwork_follow_the_role():
    rng = random.Random(9)
    winger = [Profile.generate("RW", rng, archetype="inside_forward")["flair"] for _ in range(300)]
    stopper = [Profile.generate("RCB", rng, archetype="stopper")["flair"] for _ in range(300)]
    assert sum(winger) / 300 > sum(stopper) / 300 + 0.2
