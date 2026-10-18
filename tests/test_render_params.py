import pytest

from ninety.render.params import (
    HARD_CASE_RATE,
    PATTERNS,
    TEAM_CODES,
    apply_overrides,
    color_distance,
    kits_differ,
    luminance,
    parse_override,
    sample_params,
)
from ninety.render.splits import TEST_SEEDS

PREMIER_LEAGUE_CODES = {
    "ARS",
    "AVL",
    "BOU",
    "BRE",
    "BHA",
    "BUR",
    "CHE",
    "CRY",
    "EVE",
    "FUL",
    "LEE",
    "LIV",
    "MCI",
    "MUN",
    "NEW",
    "NFO",
    "SUN",
    "TOT",
    "WHU",
    "WOL",
}


def test_same_seed_same_parameters():
    assert sample_params(5) == sample_params(5)
    assert sample_params(5) != sample_params(6)


def test_every_sampled_choice_is_recorded():
    d = sample_params(3).to_dict()
    for key in (
        "camera",
        "lighting",
        "home_kit",
        "away_kit",
        "home_gk",
        "away_gk",
        "grass_hue",
        "motion_blur",
        "noise",
        "occlusion",
        "weather",
    ):
        assert key in d


def test_camera_stays_in_broadcast_ranges():
    for seed in range(40):
        c = sample_params(seed).camera
        assert 15 <= c.height_m <= 25 and 30 <= c.back_m <= 40


def test_kits_contrast_when_normal_and_on_request():
    for seed in range(30):
        p = sample_params(seed, kit_contrast="normal")
        assert kits_differ(p.home_kit.shirt, p.away_kit.shirt, "normal")
        for gk in (p.home_gk.shirt, p.away_gk.shirt):
            assert color_distance(gk, p.home_kit.shirt) >= 0.5 and color_distance(gk, p.away_kit.shirt) >= 0.5
        low = sample_params(seed, kit_contrast="low")
        assert abs(luminance(low.home_kit.shirt) - luminance(low.away_kit.shirt)) <= 0.08


def test_overrides_apply_and_are_validated():
    p = sample_params(1, occlusion="crowded", **{"camera.half_width_m": 12.0})
    assert p.occlusion == "crowded" and p.camera.half_width_m == 12.0
    with pytest.raises(ValueError):
        apply_overrides(p, {"lighting": "noon"})
    with pytest.raises(ValueError):
        apply_overrides(p, {"no_such_knob": 1})


def test_cuts_and_patterns_are_built():
    p = sample_params(1, camera_cut=True, home_pattern="hoops", away_pattern="stripes")
    assert p.camera_cut is True
    assert p.home_pattern == "hoops" and p.away_pattern == "stripes"
    with pytest.raises(ValueError):
        sample_params(1, weather="hail")
    with pytest.raises(ValueError):
        sample_params(1, home_pattern="tartan")
    with pytest.raises(ValueError):
        sample_params(1, camera_cut="sometimes")


@pytest.mark.parametrize("override", [{"lighting": v} for v in ("dusk", "night", "overcast")]
                         + [{"weather": v} for v in ("overcast", "rain")])
def test_lighting_and_weather_that_render_badly_are_refused(override):
    with pytest.raises(NotImplementedError):
        sample_params(1, **override)


def test_every_clip_is_a_clear_day():
    for s in [*range(100), 900001, 900002, 900003, 900004, 900005]:
        p = sample_params(s)
        assert p.lighting == "day" and p.weather == "clear" and 30 <= p.sun_elevation_deg <= 60


def test_sampling_adds_cuts_and_patterns_without_moving_the_camera():
    # Seed 5's camera and kits were fixed before cuts and patterns were appended, and stay put
    # now that lighting and weather are pinned (seed 5 was drawn as dusk; the sun is now a day sun).
    p = sample_params(5)
    assert p.lighting == "day" and p.sun_azimuth_deg == 164.5 and p.sun_elevation_deg == 43.7
    assert p.camera.height_m == 21.76 and p.camera.back_m == 38.33 and p.camera.half_width_m == 17.57
    assert p.home_kit.shirt == "#1a1a1a" and p.away_kit.shirt == "#694eb0"
    assert p.home_code == "DUN" and p.away_code == "GRV"
    assert p.grass_hue == 0.279 and p.motion_blur == 0.31 and p.noise == 0.019
    assert p.home_pattern in PATTERNS and p.away_pattern in PATTERNS
    assert any(sample_params(s).camera_cut for s in range(40))
    assert any(not sample_params(s).camera_cut for s in range(40))


def test_parse_override_types():
    assert parse_override("lighting=night") == ("lighting", "night")
    assert parse_override("camera.half_width_m=12.5") == ("camera.half_width_m", 12.5)
    assert parse_override("camera_cut=false") == ("camera_cut", False)
    with pytest.raises(ValueError):
        parse_override("lighting")


def test_team_codes_are_fictional():
    assert not set(TEAM_CODES) & PREMIER_LEAGUE_CODES


def test_hard_cases_are_drawn_from_the_seed():
    # Each at HARD_CASE_RATE (0.3); 1,000 seeds give a binomial sd of about 0.015, so +-0.05 is
    # over 3 sd and the test does not flake.
    ps = [sample_params(s) for s in range(1, 1001)]
    assert abs(sum(p.kit_contrast == "low" for p in ps) / 1000 - HARD_CASE_RATE) < 0.05
    assert abs(sum(p.occlusion == "crowded" for p in ps) / 1000 - HARD_CASE_RATE) < 0.05
    # an override still wins over the draw
    assert sample_params(900004, kit_contrast="normal", occlusion="natural").occlusion == "natural"


def test_the_fixed_test_set_holds_each_hard_case():
    # The test set refuses overrides, so its hard cases must come from its seeds.
    test = [sample_params(s) for s in TEST_SEEDS]
    assert any(p.occlusion == "crowded" for p in test)
    assert any(p.kit_contrast == "low" for p in test)
