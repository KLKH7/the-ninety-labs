import pytest

from ninety.render.params import (
    PATTERNS,
    TEAM_CODES,
    apply_overrides,
    color_distance,
    kits_differ,
    luminance,
    parse_override,
    sample_params,
)

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


def test_kits_contrast_by_default_and_on_request():
    for seed in range(30):
        p = sample_params(seed)
        assert kits_differ(p.home_kit.shirt, p.away_kit.shirt, "normal")
        for gk in (p.home_gk.shirt, p.away_gk.shirt):
            assert color_distance(gk, p.home_kit.shirt) >= 0.5 and color_distance(gk, p.away_kit.shirt) >= 0.5
        low = sample_params(seed, kit_contrast="low")
        assert abs(luminance(low.home_kit.shirt) - luminance(low.away_kit.shirt)) <= 0.08


def test_overrides_apply_and_are_validated():
    p = sample_params(1, lighting="night", **{"camera.half_width_m": 12.0})
    assert p.lighting == "night" and p.camera.half_width_m == 12.0
    with pytest.raises(ValueError):
        apply_overrides(p, {"lighting": "noon"})
    with pytest.raises(ValueError):
        apply_overrides(p, {"no_such_knob": 1})


def test_rain_cuts_and_patterns_are_built():
    p = sample_params(1, weather="rain", camera_cut=True, home_pattern="hoops", away_pattern="stripes")
    assert p.weather == "rain" and p.camera_cut is True
    assert p.home_pattern == "hoops" and p.away_pattern == "stripes"
    with pytest.raises(ValueError):
        sample_params(1, weather="hail")
    with pytest.raises(ValueError):
        sample_params(1, home_pattern="tartan")
    with pytest.raises(ValueError):
        sample_params(1, camera_cut="sometimes")


def test_sampling_adds_rain_cuts_and_patterns_without_moving_the_camera():
    # Seed 5's camera and kits were fixed before rain, cuts and patterns were appended.
    p = sample_params(5)
    assert p.lighting == "dusk" and p.sun_azimuth_deg == 164.5 and p.sun_elevation_deg == 10.3
    assert p.camera.height_m == 21.76 and p.camera.back_m == 38.33 and p.camera.half_width_m == 17.57
    assert p.home_kit.shirt == "#1a1a1a" and p.away_kit.shirt == "#694eb0"
    assert p.home_code == "DUN" and p.away_code == "GRV"
    assert p.grass_hue == 0.279 and p.motion_blur == 0.31 and p.noise == 0.019
    assert p.home_pattern in PATTERNS and p.away_pattern in PATTERNS
    assert "rain" in {sample_params(s).weather for s in range(60)}
    assert any(sample_params(s).camera_cut for s in range(40))
    assert any(not sample_params(s).camera_cut for s in range(40))
    for s in range(40):
        q = sample_params(s)
        if q.lighting == "overcast":
            assert q.weather == "overcast"


def test_parse_override_types():
    assert parse_override("lighting=night") == ("lighting", "night")
    assert parse_override("camera.half_width_m=12.5") == ("camera.half_width_m", 12.5)
    assert parse_override("camera_cut=false") == ("camera_cut", False)
    with pytest.raises(ValueError):
        parse_override("lighting")


def test_team_codes_are_fictional():
    assert not set(TEAM_CODES) & PREMIER_LEAGUE_CODES
