"""Player profiles change causes, never outcomes: each attribute moves its parameter the right way."""

import math
import random
from statistics import mean, pstdev

from ninety.sim.profiles import ATTRIBUTES, Profile


def player(**attributes) -> Profile:
    base = {a: 0.5 for a in ATTRIBUTES}
    base.update(attributes)
    return Profile("Test Player", "right", base)


def test_profiles_are_synthetic_complete_and_reproducible():
    a, b = Profile.generate("ST", random.Random(4)), Profile.generate("ST", random.Random(4))
    assert a == b
    assert set(a.attributes) == set(ATTRIBUTES)
    assert all(0.0 <= v <= 1.0 for v in a.attributes.values())
    assert all(1 <= a.rating(x) <= 20 for x in ATTRIBUTES)
    assert len(a.name.split()) == 2


def test_roles_differ_in_the_expected_direction():
    rng = random.Random(9)
    strikers = [Profile.generate("ST", rng)["finishing"] for _ in range(300)]
    centre_backs = [Profile.generate("RCB", rng)["finishing"] for _ in range(300)]
    assert mean(strikers) > mean(centre_backs) + 0.3


def test_physical_attributes_keep_the_sourced_means():
    rng = random.Random(2)
    bodies = [Profile.generate("CM", rng).physique() for _ in range(2000)]
    assert abs(mean(b.f0 for b in bodies) - 5.2) < 0.1
    assert 0.35 < pstdev([b.f0 for b in bodies]) < 0.55


def error(p: Profile, **kw) -> float:
    args = {"skill": "finishing", "speed": 21.0, "pressure": 0.0, "capacity": 1.0, "weak_foot": False}
    args.update(kw)
    return p.kick_error(**args)[0]


def test_average_skill_at_penalty_speed_is_about_three_degrees():
    assert abs(error(player()) - 3.0) < 0.01


def test_skill_narrows_error_and_speed_widens_it():
    assert error(player(finishing=0.9)) < error(player(finishing=0.2))
    assert error(player(), speed=30.0) > error(player(), speed=15.0)


def test_pressure_fatigue_and_the_weaker_foot_widen_error():
    p = player()
    assert error(p, pressure=1.0) > error(p)
    assert error(p, capacity=0.0) > error(p)
    assert error(p, weak_foot=True) > error(p)
    assert error(player(composure=1.0), pressure=1.0) == error(player(composure=1.0))  # composed: no effect
    assert error(player(weak_foot=1.0), weak_foot=True) == error(player(weak_foot=1.0))  # two-footed


def test_better_anticipation_reacts_sooner_and_keepers_read_the_kicker():
    assert player(anticipation=0.9).reaction(False, 0.25) < player(anticipation=0.1).reaction(False, 0.25)
    assert player().reaction(True, 0.25) < player().reaction(False, 0.25)
    fastest = player(anticipation=1.0).reaction(False, 0.25)
    slowest = player(anticipation=0.0).reaction(False, 0.25)
    assert 0.31 < fastest < slowest < 0.41


def test_vision_widens_view_and_scans_more_often():
    sharp, poor = player(vision=1.0), player(vision=0.0)
    assert sharp.view_half_angle() > poor.view_half_angle()
    assert mean(sharp.scan_interval()) < mean(poor.scan_interval())
    assert abs(math.degrees(player().view_half_angle()) - 60) < 1e-9


def test_first_touch_and_handling_raise_what_can_be_controlled():
    assert player(first_touch=0.9).absorb_mps(False) > player(first_touch=0.1).absorb_mps(False)
    assert player(handling=0.9).absorb_mps(True) > player(handling=0.1).absorb_mps(True)
