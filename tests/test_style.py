"""A style changes what a team intends (where it stands, when it goes to the ball), never what
happens; the default style is the engine as it was before styles."""

import math
from statistics import mean

import pytest

from ninety.sim import style as style_mod
from ninety.sim.engine import Engine, simulate
from ninety.sim.style import HIGH, LOW, PRESETS, Style, band, preset_name
from ninety.sim.team import TRANSITION_S, TeamBrain

DEFENDERS = {"RB", "RCB", "LCB", "LB"}


def test_a_dial_is_read_in_thirds_and_must_be_between_0_and_1():
    levels = [band(v) for v in (0.0, 0.33, 0.34, 0.66, 0.67, 1.0)]
    assert levels == ["low", "low", "mid", "mid", "high", "high"]
    for bad in (-0.1, 1.1):
        with pytest.raises(ValueError):
            band(bad)
    with pytest.raises(ValueError):
        Style(line_height=2.0)


def test_the_default_style_is_the_engine_before_styles():
    """The values the engine used before it had styles: mid block, engagement 60 m from goal, the
    presser goes from 20 m and stands 2 m off, counter-press in the T1 window from 20 m."""
    brain = TeamBrain("home")
    assert brain.block == "mid"
    assert brain.engage_from_goal_m == 60.0
    assert brain.press_gap_m == 2.0
    brain.update(0.0, True, 52.5, {})
    brain.update(0.5, False, 52.5, {})
    assert brain.counter_pressing(1.0) and brain.engage_m(1.0) == 20.0
    assert not brain.counter_pressing(TRANSITION_S + 1) and brain.engage_m(TRANSITION_S + 1) == 20.0


def test_line_height_picks_the_block():
    assert [TeamBrain("home", Style(line_height=v)).block for v in (LOW, 0.5, HIGH)] == ["low", "mid", "high"]


def test_pressing_height_moves_where_the_team_starts_going_to_the_ball():
    """Ball 50 m from the home goal, long after the ball changed hands: a high press goes, a low
    press waits (T3)."""
    for level, goes in ((HIGH, True), (LOW, False)):
        brain = TeamBrain("home", Style(pressing_height=level))
        brain.update(0.0, False, 50.0, {})
        assert brain.presses(TRANSITION_S + 1, 50.0) is goes


def test_a_team_that_does_not_counter_press_drops_back_after_losing_the_ball():
    """Just after losing the ball 80 m from its own goal, outside its engagement line."""
    for level, goes in ((HIGH, True), (0.5, True), (LOW, False)):
        brain = TeamBrain("home", Style(counter_pressing=level))
        brain.update(10.0, True, 80.0, {})
        brain.update(11.0, False, 80.0, {})
        assert brain.presses(12.0, 80.0) is goes


def test_a_high_counter_press_goes_from_further_only_in_the_window():
    brain = TeamBrain("home", Style(counter_pressing=HIGH))
    brain.update(10.0, True, 80.0, {})
    brain.update(11.0, False, 80.0, {})
    assert brain.engage_m(12.0) > style_mod.ENGAGE_M["mid"]
    assert brain.engage_m(11.0 + TRANSITION_S + 1) == style_mod.ENGAGE_M["mid"]


def test_pressing_intensity_sets_how_far_the_presser_goes_and_how_tight_he_stands():
    low = TeamBrain("home", Style(pressing_intensity=LOW))
    high = TeamBrain("home", Style(pressing_intensity=HIGH))
    assert high.engage_m(99.0) > low.engage_m(99.0)
    assert high.press_gap_m < low.press_gap_m


def pressing_scene(style: Style, presser_x: float):
    """The away striker has the ball at (60, 34), just after home lost it; home's h7 is the first
    presser, standing still on the halfway side of the ball."""
    e = Engine(1, styles={"home": style})
    for p in e.players:
        p.vx = p.vy = 0.0
    carrier, presser = e.by_id["a10"], e.by_id["h7"]
    carrier.x, carrier.y, presser.x, presser.y = 60.0, 34.0, presser_x, 34.0
    e.possessor, e.restart = carrier.id, None
    e.ball = (60.0, 34.0, 0.0, 0.0, 0.0, 0.0)
    brain = e.brains["home"]
    brain.in_possession, brain.changed_at, brain.markers = False, e.t - TRANSITION_S - 1, {}
    brain.pressers = [presser.id, "h6"]
    return e, presser, brain


def test_the_presser_stands_as_tight_as_his_teams_style_says():
    """In a match: the first presser jockeys goal-side at the style's distance from the carrier."""
    for level in (LOW, HIGH):
        e, presser, brain = pressing_scene(Style(pressing_height=HIGH, pressing_intensity=level), 52.0)
        x, y, _ = e.shape_target(presser)
        assert math.isclose(math.hypot(x - 60.0, y - 34.0), brain.press_gap_m, abs_tol=1e-9)
    assert style_mod.PRESS_GAP_M["high"] < style_mod.PRESS_GAP_M["low"]


def test_a_high_intensity_presser_goes_to_the_ball_from_further():
    """22 m from the ball: inside the high-intensity reach (25 m), outside the low one (15 m)."""
    for level, goes in ((HIGH, True), (LOW, False)):
        e, presser, brain = pressing_scene(Style(pressing_height=HIGH, pressing_intensity=level), 38.0)
        x, y, _ = e.shape_target(presser)
        assert (math.hypot(x - 60.0, y - 34.0) < 3.0) is goes


def test_presets_are_distinct_and_named():
    assert len(set(PRESETS.values())) == len(PRESETS)
    assert all(preset_name(s) == name for name, s in PRESETS.items())
    assert preset_name(Style(line_height=LOW)) is None


def test_explicit_default_styles_change_nothing():
    a = simulate(3, 1)
    b = simulate(3, 1, styles={"home": Style(), "away": Style()})
    assert a.events == b.events and a.frames[-1] == b.frames[-1]


def test_strengths_given_are_used_and_one_left_out_is_drawn():
    e = Engine(1, strengths={"home": 1.5, "away": -1.0})
    assert e.strength == {"home": 1.5, "away": -1.0}
    assert e.match.teams["home"]["strength"] == 1.5
    drawn = Engine(1).strength
    assert Engine(1, strengths={"away": -1.0}).strength["home"] == drawn["home"]  # same draw, home first


def test_the_scenario_records_each_teams_style_and_strength():
    e = Engine(1, styles={"home": PRESETS["high_press"]})
    assert e.match.teams["home"]["preset"] == "high_press"
    assert e.match.teams["away"]["preset"] == "balanced"
    assert e.match.teams["home"]["style"]["line_height"] == HIGH


def line_depths(match, team: str) -> list[float]:
    """The back four's mean distance from their own goal line, sampled every 5 frames while the
    other team has the ball 45 to 80 m from that goal (the line follows the ball, T2, so like is
    compared with like; there every block stands at its own height)."""
    own = 0.0 if team == "home" else 105.0
    return [
        mean(abs(p["x"] - own) for p in fr["players"] if p["team"] == team and p["role"] in DEFENDERS)
        for fr in match.frames[::5]
        if fr["possessor"] and not fr["possessor"].startswith(team[0])
        and 45.0 <= abs(fr["ball"]["x"] - own) <= 80.0
    ]


def test_out_of_possession_a_high_press_defends_higher_up_the_pitch_than_a_low_block():
    """Intent shows in where players stand, after they have run there. Both ways round, so the
    side does not decide it. Blocks: low 12 to 22 m, high 35 to 50 m (T2); the 5 m margin allows
    for players still on their way."""
    depths = {"high_press": [], "low_block": []}
    for home, away in (("high_press", "low_block"), ("low_block", "high_press")):
        m = simulate(2, 3, strengths={"home": 0.0, "away": 0.0},
                     styles={"home": PRESETS[home], "away": PRESETS[away]})
        for name, team in ((home, "home"), (away, "away")):
            depths[name] += line_depths(m, team)
    assert min(len(d) for d in depths.values()) >= 20, {k: len(d) for k, d in depths.items()}
    assert mean(depths["high_press"]) > mean(depths["low_block"]) + 5.0, depths
