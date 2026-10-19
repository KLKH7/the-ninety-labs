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


def test_a_whole_squad_keeps_the_sourced_physical_distributions():
    from ninety.sim import body
    from ninety.sim.profiles import FORMATION_ROLES
    rng = random.Random(2)
    bodies = [Profile.generate(role, rng).physique() for _ in range(500) for role in FORMATION_ROLES]
    for name, mu, sd in (("f0", body.F0_MEAN, body.F0_SD), ("v0", body.V0_MEAN, body.V0_SD),
                         ("cs", body.CS_MEAN, body.CS_SD)):
        values = [getattr(b, name) for b in bodies]
        assert abs(mean(values) - mu) < 0.05 * sd
        assert abs(pstdev(values) - sd) < 0.15 * sd  # positions add a little spread


def test_a_physical_role_shift_moves_the_mean_by_that_many_spreads():
    from ninety.sim import body
    from ninety.sim.profiles import PHYSICAL_CENTRE
    rng = random.Random(5)
    wingers = [Profile.generate("RW", rng, archetype="touchline_winger").physique().v0 for _ in range(4000)]
    assert abs(mean(wingers) - (body.V0_MEAN + (0.9 - PHYSICAL_CENTRE["pace"]) * body.V0_SD)) < 0.05


def test_each_physical_attribute_drives_its_own_parameter():
    fast, slow = player(pace=0.9).physique(), player(pace=0.1).physique()
    assert fast.v0 > slow.v0 and fast.f0 == slow.f0 and fast.cs == slow.cs
    quick, sluggish = player(acceleration=0.9).physique(), player(acceleration=0.1).physique()
    assert quick.f0 > sluggish.f0 and quick.v0 == sluggish.v0
    fit, unfit = player(stamina=0.9).physique(), player(stamina=0.1).physique()
    assert fit.cs > unfit.cs and fit.v0 == unfit.v0


def test_no_skill_piles_up_at_the_ends_of_the_scale():
    rng = random.Random(8)
    keepers = [Profile.generate("GK", rng) for _ in range(2000)]
    assert sum(k["handling"] >= 0.999 for k in keepers) / len(keepers) < 0.01


def test_an_average_weak_foot_carries_the_sourced_penalty():
    p = player()
    _, _, up = p.kick_error("finishing", 21.0, 0.0, 1.0, False)
    _, _, weak_up = p.kick_error("finishing", 21.0, 0.0, 1.0, True)
    # A3: the weaker foot's own measured ellipse, about a third wider each way
    assert abs(error(p, weak_foot=True) / error(p) - 1.34) < 0.01 and abs(weak_up / up - 1.35) < 0.01
    assert math.isclose(p.weak_foot_speed(), 0.88)
    assert error(p, turn_deg=90.0) > error(p)  # across the body is harder on either side


def test_keepers_get_no_outfield_habits():
    rng = random.Random(4)
    assert all(not Profile.generate("GK", rng).traits for _ in range(500))


def error(p: Profile, **kw) -> float:
    args = {"skill": "finishing", "speed": 21.0, "pressure": 0.0, "capacity": 1.0, "weak_foot": False}
    args.update(kw)
    return p.kick_error(**args)[0]


def measured_sds_deg(axes_m: tuple[float, float], tilt_deg: float) -> tuple[float, float]:
    """A3's ellipse seen from the kick, worked out from the geometry itself: the SDs in metres on
    the goal's plane, turned into angles by how far the bearing and elevation to the target
    (3.5 m across, 1.6 m up, from 11 m) move when the ball lands a little off it."""
    long_sd, short_sd = (a / 2 / 2.448 for a in axes_m)
    t = math.radians(tilt_deg)
    across_m = math.sqrt((long_sd * math.cos(t)) ** 2 + (short_sd * math.sin(t)) ** 2)
    up_m = math.sqrt((long_sd * math.sin(t)) ** 2 + (short_sd * math.cos(t)) ** 2)
    eps, ground = 1e-4, math.hypot(11.0, 3.5)
    across = (math.atan((3.5 + eps) / 11.0) - math.atan((3.5 - eps) / 11.0)) / (2 * eps)
    up = (math.atan((1.6 + eps) / ground) - math.atan((1.6 - eps) / ground)) / (2 * eps)
    return math.degrees(across_m * across), math.degrees(up_m * up)


def test_average_skill_at_penalty_speed_gives_the_measured_ellipse():
    # A3: preferred-foot straight kicks, 95% axes 4.08 m and 1.91 m, tilted 26.9 degrees (Figure 5)
    across, _, up = player().kick_error("finishing", 21.0, 0.0, 1.0, False)
    assert abs(across - 3.61) < 0.01 and abs(up - 2.50) < 0.01
    want = measured_sds_deg((4.08, 1.91), 26.9)
    assert math.isclose(across, want[0], rel_tol=1e-6) and math.isclose(up, want[1], rel_tol=1e-6)


def test_the_weaker_foot_follows_its_own_measured_ellipse():
    # A3: weaker-foot straight kicks, 95% axes 5.60 m and 2.28 m, tilted 29.4 degrees (Figure 5)
    p = player(weak_foot=0.5)
    across, _, up = p.kick_error("finishing", 21.0, 0.0, 1.0, True)
    want = measured_sds_deg((5.60, 2.28), 29.4)
    assert math.isclose(across, want[0], rel_tol=1e-6) and math.isclose(up, want[1], rel_tol=1e-6)


def test_launch_angle_error_grows_with_everything_direction_error_grows_with():
    def both(p: Profile, **kw) -> tuple[float, float]:
        args = {"skill": "finishing", "speed": 21.0, "pressure": 0.0, "capacity": 1.0, "weak_foot": False}
        args.update(kw)
        across, _, up = p.kick_error(**args)
        return across, up
    p = player()
    ratio = both(p)[1] / both(p)[0]
    for q, kw in ((player(finishing=0.1), {}), (p, {"speed": 30.0}), (p, {"pressure": 1.0}),
                  (p, {"capacity": 0.0}), (p, {"turn_deg": 90.0})):
        across, up = both(q, **kw)
        assert up > both(p)[1]  # a harder, more hurried, tired or awkward strike also flies higher or lower
        assert math.isclose(up / across, ratio)  # one ellipse, scaled
    assert both(p, weak_foot=True)[1] > both(p)[1]  # the weaker foot has its own, wider ellipse


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
    args = {"skill": "finishing", "speed": 21.0, "pressure": 0.0, "capacity": 1.0}
    up = [player(weak_foot=r).kick_error(**args, weak_foot=True)[2] for r in (1.0, 0.5, 0.0)]
    assert up[0] == player(weak_foot=1.0).kick_error(**args, weak_foot=False)[2]  # two-footed, up too
    assert up[0] < up[1] < up[2]  # the weaker foot's launch spread widens as the rating falls


def test_reflexes_set_the_choice_reaction_within_the_measured_range():
    assert player(reflexes=0.9).reaction() < player(reflexes=0.1).reaction()
    assert math.isclose(player(reflexes=1.0).reaction(), 0.32)
    assert math.isclose(player(reflexes=0.0).reaction(), 0.41)
    assert player(anticipation=1.0).reaction() == player(anticipation=0.0).reaction()  # reading != reacting


def test_anticipation_narrows_a_keepers_read_of_the_kicker():
    assert player(anticipation=0.9).read_error_m() < player(anticipation=0.1).read_error_m()
    assert player(anticipation=1.0).read_error_m() > 0  # a read can always be wrong


def test_vision_widens_view_and_scans_more_often():
    sharp, poor = player(vision=1.0), player(vision=0.0)
    assert sharp.view_half_angle() > poor.view_half_angle()
    assert mean(sharp.scan_interval()) < mean(poor.scan_interval())
    assert abs(math.degrees(player().view_half_angle()) - 60) < 1e-9


def test_first_touch_and_handling_raise_what_can_be_controlled():
    assert player(first_touch=0.9).absorb_mps(False) > player(first_touch=0.1).absorb_mps(False)
    assert player(handling=0.9).absorb_mps(True) > player(handling=0.1).absorb_mps(True)


def corr(xs, ys):
    from statistics import correlation
    return correlation(xs, ys)


def squad_sample(n=3000, role="CM", strength=0.0, seed=11, **kw):
    rng = random.Random(seed)
    return [Profile.generate(role, rng, strength, **kw) for _ in range(n)]


def test_acceleration_and_top_speed_go_together_as_measured():
    ps = squad_sample(archetype="box_to_box")
    assert abs(corr([p["pace"] for p in ps], [p["acceleration"] for p in ps]) - 0.6) < 0.06
    assert abs(corr([p["pace"] for p in ps], [p["stamina"] for p in ps])) < 0.06  # separate capacities


def test_skills_that_belong_together_correlate_more_than_skills_that_do_not():
    ps = squad_sample(archetype="box_to_box")
    same = corr([p["passing"] for p in ps], [p["first_touch"] for p in ps])
    across = corr([p["passing"] for p in ps], [p["tackling"] for p in ps])
    assert same > across + 0.15 and across > 0.1  # quality still lifts both


def test_a_stronger_team_has_better_players_but_not_faster_ones():
    strong, weak = squad_sample(strength=1.0), squad_sample(strength=-1.0)
    assert mean(p["passing"] for p in strong) > mean(p["passing"] for p in weak) + 0.1
    assert abs(mean(p["pace"] for p in strong) - mean(p["pace"] for p in weak)) < 0.03


def test_archetypes_differ_where_they_should():
    stoppers = squad_sample(role="RCB", archetype="stopper")
    playmakers = squad_sample(role="RCB", archetype="ball_playing")
    assert mean(p["tackling"] for p in stoppers) > mean(p["tackling"] for p in playmakers)
    assert mean(p["passing"] for p in playmakers) > mean(p["passing"] for p in stoppers)
    ps = squad_sample(role="ST", n=4000)
    shares = {a: sum(p.archetype == a for p in ps) / len(ps) for a in ("poacher", "target_forward")}
    assert abs(shares["poacher"] - 0.4) < 0.03 and abs(shares["target_forward"] - 0.3) < 0.03


def test_a_trait_follows_the_skill_behind_it():
    ps = squad_sample(role="ST", n=4000)
    good = [p for p in ps if p["finishing"] > 0.75]
    poor = [p for p in ps if p["finishing"] < 0.6]
    rate = lambda group: sum("shoots_from_distance" in p.traits for p in group) / len(group)  # noqa: E731
    assert rate(good) > 2 * rate(poor)


def test_left_sided_players_are_more_often_left_footed_and_inside_forwards_cut_in():
    left_backs = squad_sample(role="LB", n=2000)
    right_backs = squad_sample(role="RB", n=2000)
    lefty = lambda group: sum(p.foot == "left" for p in group) / len(group)  # noqa: E731
    assert lefty(left_backs) > lefty(right_backs) + 0.4
    assert lefty(squad_sample(role="RW", archetype="inside_forward")) > lefty(
        squad_sample(role="LW", archetype="inside_forward"))


def test_the_same_seed_gives_the_same_squad():
    assert squad_sample(n=20, seed=3) == squad_sample(n=20, seed=3)


def test_forty_percent_of_player_quality_varies_between_teams():
    from statistics import pvariance

    from ninety.sim.profiles import FORMATION_ROLES, team_strength
    rng = random.Random(6)
    teams = []
    for _ in range(400):
        s = team_strength(rng)
        teams.append([Profile.generate(r, rng, s).quality for r in FORMATION_ROLES])
    within = mean(pvariance(t) for t in teams) * 11 / 10
    between = pvariance([mean(t) for t in teams]) - within / 11
    assert abs(between / (between + within) - 0.4) < 0.05
