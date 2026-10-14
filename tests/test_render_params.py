import pytest

from ninety.render.params import (
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


def test_planned_knobs_fail_loudly():
    with pytest.raises(NotImplementedError):
        sample_params(1, weather="rain")
    with pytest.raises(NotImplementedError):
        sample_params(1, camera_cut=True)


def test_parse_override_types():
    assert parse_override("lighting=night") == ("lighting", "night")
    assert parse_override("camera.half_width_m=12.5") == ("camera.half_width_m", 12.5)
    assert parse_override("camera_cut=false") == ("camera_cut", False)
    with pytest.raises(ValueError):
        parse_override("lighting")


def test_team_codes_are_fictional():
    assert not set(TEAM_CODES) & PREMIER_LEAGUE_CODES
