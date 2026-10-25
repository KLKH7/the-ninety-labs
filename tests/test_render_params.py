import pytest

from ninety.render.params import (
    HARD_CASE_RATE,
    PATTERNS,
    TEAM_CODES,
    TEAMS,
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
    assert p.home_code == "LON" and p.away_code == "LIS"  # the two teams every clip shows (TEAMS)
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
    assert not {code for code, _ in TEAMS.values()} & PREMIER_LEAGUE_CODES


def test_every_seed_shows_london_athletic_against_lisbon_esportes_and_keeps_its_other_draws():
    """Kian's teams on every clip; the codes the seed draws are still drawn, so seed 5's camera,
    kits, grass and patterns are what they were (test_sampling_adds_cuts... pins them)."""
    for s in (1, 5, 7, 42, 900001):
        p = sample_params(s)
        assert (p.home_code, p.away_code) == ("LON", "LIS")


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


def test_only_a_broadcast_clip_cuts_through_dead_balls(monkeypatch, tmp_path):
    """Coordinator decision (Oct 20): datasets, the Azure job, training rounds and the test sets show
    every frame; `ninety-render` (viewer and demo clips) cuts through long dead balls, outside the
    test set (edit.py)."""
    from contextlib import contextmanager

    from ninety.render import cli

    assert not any(sample_params(s).dead_ball_cut for s in list(range(1, 40)) + list(TEST_SEEDS))
    calls = []

    def fake_render(seed, out, **kw):
        calls.append((seed, dict(kw["overrides"])))
        return {"split": "x", "frames": 1, "params": {"lighting": "day"}, "event_counts": {},
                "overrides": kw["overrides"]}

    @contextmanager
    def fake_page(gpu=False):
        yield None, "stand-in"

    monkeypatch.setattr(cli, "render_clip", fake_render)
    monkeypatch.setattr(cli, "check_clip", lambda out: {"passed": {}})
    monkeypatch.setattr(cli, "browser_page", fake_page)
    cli.render_main(["--seed", "7", "--out", str(tmp_path / "a")])
    test_seed = sorted(TEST_SEEDS)[0]
    cli.render_main(["--seed", str(test_seed), "--out", str(tmp_path / "b")])
    cli.render_main(["--seed", "7", "--out", str(tmp_path / "c"), "--set", "dead_ball_cut=false"])
    for d in ("d", "e"):
        (tmp_path / d).mkdir()
    cli.dataset_main(["--split", "test", "--out", str(tmp_path / "d")])
    cli.dataset_main(["--split", "train", "--count", "2", "--out", str(tmp_path / "e")])
    cut = {seed: sample_params(seed, **ov).dead_ball_cut for seed, ov in calls}
    assert [sample_params(s, **ov).dead_ball_cut for s, ov in calls[:3]] == [True, False, False]
    assert len(calls) == 3 + len(TEST_SEEDS) + 2 and not any(cut[s] for s, _ in calls[3:])


def _wcag_luminance(hex_):
    """WCAG 2.1 relative luminance (sRGB channels linearised)."""
    def lin(c):
        return c / 12.92 if c <= 0.04045 else ((c + 0.055) / 1.055) ** 2.4
    r, g, b = (int(hex_.lstrip("#")[i:i + 2], 16) / 255 for i in (0, 2, 4))
    return 0.2126 * lin(r) + 0.7152 * lin(g) + 0.0722 * lin(b)


def _hue_saturation(hex_):
    import colorsys
    r, g, b = (int(hex_.lstrip("#")[i:i + 2], 16) / 255 for i in (0, 2, 4))
    h, s, _ = colorsys.rgb_to_hsv(r, g, b)
    return h * 360, s


def test_a_broadcast_kit_pair_is_clearly_told_apart():
    """kit_contrast=broadcast (the demo clip's footage, never training): the two outfield shirts meet
    WCAG 2.1's 3:1 contrast floor for graphical objects (SC 1.4.11) and, unless one is white, black or
    grey, sit at least 60 degrees apart in hue. Bounds written before the rule was built."""
    for seed in range(1, 201):
        p = sample_params(seed, kit_contrast="broadcast")
        a, b = p.home_kit.shirt, p.away_kit.shirt
        la, lb = sorted((_wcag_luminance(a), _wcag_luminance(b)))
        assert (lb + 0.05) / (la + 0.05) >= 3.0, (seed, a, b)
        (ha, sa), (hb, sb) = _hue_saturation(a), _hue_saturation(b)
        if sa > 0.1 and sb > 0.1:
            assert min(abs(ha - hb), 360 - abs(ha - hb)) >= 60, (seed, a, b)


def test_training_kit_draws_are_unchanged_by_the_broadcast_rule():
    """normal and low (and each seed's own draw) are what they were before broadcast existed: a digest
    of 125 seeds' parameters taken on main before the change. The team codes are left out since every
    clip shows London Athletic and Lisbon Esportes (TEAMS, Oct 24); that digest was taken on main's
    code (ac21ccc) with the codes left out, so every other draw is still pinned."""
    import hashlib
    import json

    h = hashlib.sha256()
    for s in list(range(1, 121)) + [2001, 3001, 4001, 8001, 900001]:
        for c in ("normal", "low", None):
            p = sample_params(s) if c is None else sample_params(s, kit_contrast=c)
            # edge_stingers (0.5.19) is a setting, never a draw
            d = {k: v for k, v in p.to_dict().items() if k not in ("home_code", "away_code", "edge_stingers")}
            h.update(json.dumps(d, sort_keys=True).encode())
    assert h.hexdigest() == "4f11f5522698c3f5bcc041be96211dfec58aec86a5d8ddaa5c1047b0821f9e6c"


def test_only_footage_asks_for_a_broadcast_stadium():
    """No seed draws the broadcast stadium (crowd, hoardings, softer mowing): every training,
    validation and test render is plain, and its clip.json records no stadium key, as before the
    knob existed. Footage asks for it by name; anything else is refused."""
    for seed in list(range(1, 60)) + [8001, 900001]:
        p = sample_params(seed)
        assert p.stadium == "plain"
        assert "stadium" not in p.to_dict()
    assert sample_params(8001, stadium="broadcast").to_dict()["stadium"] == "broadcast"
    with pytest.raises(ValueError):
        sample_params(8001, stadium="packed")


def test_the_shirt_as_seen_mixes_its_pattern_in_by_area():
    """A solid shirt is seen as its colour; hoops in white over a dark shirt lighten it by the shader's
    0.46 share, mixed in linear light; a shirt whose shorts match it is trimmed in the page's neutral."""
    from ninety.render.params import NEUTRAL_TRIM, Kit, visible_shirt

    navy = Kit("#1f2a5a", "#ffffff", "#1f2a5a")
    assert visible_shirt(navy, "solid") == "#1f2a5a"
    seen = visible_shirt(navy, "hoops")
    assert seen != "#1f2a5a" and int(seen[1:3], 16) > 0x1f  # lighter, towards white
    own = Kit("#1f2a5a", "#1f2a5a", "#1f2a5a")
    assert visible_shirt(own, "halves") == visible_shirt(Kit("#1f2a5a", NEUTRAL_TRIM, "#000000"), "halves")


def test_seed_8080s_broadcast_kits_look_apart_once_the_pattern_is_on():
    """The demo match's kits on main before this rule: purple hoops in white over white shorts
    against a near-white shirt, which passed on shirt colour alone (14:1) and looked alike as seen
    (1.9:1). Now the shirts as seen meet the same 3:1."""
    from ninety.render.params import Kit, kits_seen_apart, visible_shirt, wcag_contrast

    before = (Kit("#40083f", "#ffffff", "#ffffff"), "hoops", Kit("#f2f2f2", "#ffffff", "#f2f2f2"), "hoops")
    assert wcag_contrast(before[0].shirt, before[2].shirt) > 3 and not kits_seen_apart(*before)
    p = sample_params(8080, kit_contrast="broadcast")
    a, b = visible_shirt(p.home_kit, p.home_pattern), visible_shirt(p.away_kit, p.away_pattern)
    assert wcag_contrast(a, b) >= 3.0, (a, b)


def test_every_broadcast_seed_is_told_apart_as_seen_and_a_passing_seed_keeps_its_draws(monkeypatch):
    """Seeds 1-300 in broadcast: the shirts differ as colours, as drawn and as seen, and each keeper
    is far from every outfield colour. A seed whose kits already passed is drawn exactly as before."""
    from ninety.render import params as P

    plain = {}
    with monkeypatch.context() as m:
        m.setattr(P, "_kits_seen_apart", lambda p, seed: p)
        m.setattr(P, "broadcast_kits_ok", lambda *a: True)  # the "before": no redraw, no refusal
        for seed in range(1, 301):
            plain[seed] = P.sample_params(seed, kit_contrast="broadcast")
    changed = 0
    for seed in range(1, 301):
        p = P.sample_params(seed, kit_contrast="broadcast")
        assert P.kits_differ(p.home_kit.shirt, p.away_kit.shirt, "broadcast"), seed
        assert P.kits_seen_apart(p.home_kit, p.home_pattern, p.away_kit, p.away_pattern), seed
        assert P.broadcast_kits_ok(p.home_kit, p.home_pattern, p.away_kit, p.away_pattern,
                                   p.home_gk, p.away_gk), seed  # the keepers' rule is part of it
        q = plain[seed]
        if P.broadcast_kits_ok(q.home_kit, q.home_pattern, q.away_kit, q.away_pattern, q.home_gk, q.away_gk):
            assert p == q, seed
        else:
            changed += 1
    assert 0 < changed < 300  # the rule bites on some seeds and leaves the rest alone
