"""A style changes what a team intends (where it stands, when it goes to the ball, how the player on
the ball weighs his options), never what happens; the default style is the engine as it was before
styles."""

import math
import random
from statistics import mean

import pytest

from ninety.sim import decisions as D
from ninety.sim import perception
from ninety.sim import style as style_mod
from ninety.sim.engine import Engine, simulate
from ninety.sim.profiles import Profile
from ninety.sim.style import HIGH, LOW, MID, PRESETS, Style, band, preset_name, tilt
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
    """The values the engine used before it had styles, for a mid block: engagement 60 m from goal,
    the presser goes from wherever he is (no distance gate) and stands 2 m off, counter-press in
    the T1 window."""
    brain = TeamBrain("home")
    assert brain.block == "mid"
    assert brain.engage_from_goal_m == 60.0
    assert brain.press_gap_m == 2.0
    brain.update(0.0, True, 52.5, {})
    brain.update(0.5, False, 52.5, {})
    assert brain.counter_pressing(1.0) and brain.engage_m(1.0) == math.inf
    assert not brain.counter_pressing(TRANSITION_S + 1) and brain.engage_m(TRANSITION_S + 1) == math.inf


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


def test_a_counter_press_goes_from_further_only_in_the_window():
    """A low-intensity team's presser only goes from 20 m, except while it counter-presses."""
    brain = TeamBrain("home", Style(pressing_intensity=LOW, counter_pressing=HIGH))
    brain.update(10.0, True, 80.0, {})
    brain.update(11.0, False, 80.0, {})
    assert brain.engage_m(12.0) > style_mod.ENGAGE_M["low"]
    assert brain.engage_m(11.0 + TRANSITION_S + 1) == style_mod.ENGAGE_M["low"]
    mid = TeamBrain("home", Style(pressing_intensity=LOW, counter_pressing=MID))
    mid.update(10.0, True, 80.0, {})
    mid.update(11.0, False, 80.0, {})
    assert mid.engage_m(12.0) == brain.engage_m(12.0) == math.inf  # whatever the pressing intensity


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
    """2 m beyond a low-intensity presser's reach: a high-intensity one goes, a low one does not."""
    for level, goes in ((HIGH, True), (LOW, False)):
        start = 60.0 - (style_mod.ENGAGE_M["low"] + 2.0)
        e, presser, brain = pressing_scene(Style(pressing_height=HIGH, pressing_intensity=level), start)
        x, y, _ = e.shape_target(presser)
        assert (math.hypot(x - 60.0, y - 34.0) < 3.0) is goes


def test_presets_are_distinct_and_named():
    assert len(set(PRESETS.values())) == len(PRESETS)
    assert all(preset_name(s) == name for name, s in PRESETS.items())
    assert preset_name(Style(line_height=LOW)) is None


def test_a_side_given_no_style_draws_a_block_and_giving_that_style_is_the_same_match():
    """With no style a side draws its block (T2, T3), its line and engagement at that height and
    every other dial mid; giving the drawn styles explicitly plays the same match."""
    drawn = Engine(3).styles
    for style in drawn.values():
        assert style.line_height == style.pressing_height
        assert style == Style(line_height=style.line_height, pressing_height=style.pressing_height)
    a = simulate(3, 1)
    b = simulate(3, 1, styles=dict(drawn))
    assert a.events == b.events and a.frames[-1] == b.frames[-1]
    assert Engine(3, styles={"home": PRESETS["high_press"]}).styles["away"] == drawn["away"]
    # Its own stream: giving the strengths (which otherwise consume the match's draws) changes nothing.
    assert Engine(3, strengths={"home": 0.0, "away": 0.0}).styles == drawn


def test_strengths_given_are_used_and_one_left_out_is_drawn():
    e = Engine(1, strengths={"home": 1.5, "away": -1.0})
    assert e.strength == {"home": 1.5, "away": -1.0}
    assert e.match.teams["home"]["strength"] == 1.5
    drawn = Engine(1).strength
    assert Engine(1, strengths={"away": -1.0}).strength["home"] == drawn["home"]  # same draw, home first


def test_a_misspelt_team_is_refused():
    with pytest.raises(ValueError):
        Engine(1, styles={"Home": PRESETS["high_press"]})
    with pytest.raises(ValueError):
        Engine(1, strengths={"hme": 1.0})


def test_the_scenario_records_each_teams_style_and_strength():
    e = Engine(1, styles={"home": PRESETS["high_press"]})
    assert e.match.teams["home"]["preset"] == "high_press"
    assert e.match.teams["away"]["preset"] == preset_name(e.styles["away"])  # drawn: a block, else mid
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
    side does not decide it. Blocks: low 12 to 22 m, high 35 to 50 m (T2), so at least 13 m
    apart once players are in place; the 5 m margin, set before running, is under half that,
    because a line that has just lost the ball is still running up to its block."""
    depths = {"high_press": [], "low_block": []}
    for home, away in (("high_press", "low_block"), ("low_block", "high_press")):
        m = simulate(2, 3, strengths={"home": 0.0, "away": 0.0},
                     styles={"home": PRESETS[home], "away": PRESETS[away]})
        for name, team in ((home, "home"), (away, "away")):
            depths[name] += line_depths(m, team)
    assert min(len(d) for d in depths.values()) >= 20, {k: len(d) for k, d in depths.items()}
    assert mean(depths["high_press"]) > mean(depths["low_block"]) + 5.0, depths


# On the ball: directness, counter-attacking and risk tilt how options are weighed (D1, D4).


@pytest.fixture
def hand_written_values(monkeypatch):
    """Pin the decision rules, not whatever possession table was last measured."""
    monkeypatch.setattr(D, "POSSESSION", None)


PASSER = Profile.generate("CM", random.Random(7))  # a real passer, as tests/test_decisions.py builds


def on_ball(style: Style, transition: bool = False, **kw) -> D.Scene:
    """A scene as the engine builds one (engine.scene_for), opponents standing where he sees them."""
    base = dict(x=40.0, y=34.0, goal_x=105.0, mates=[], opponents=[], keeper=None, decisions=0.5,
                composure=0.5, dribbling=0.5, traits=(), risk=0.0, absorb={}, passer=PASSER,
                progress_weight=style.progress_weight(transition), loss_weight=style.loss_weight())
    base.update(kw)
    base.setdefault("heading", 0.0 if base["goal_x"] > 52.5 else math.pi)
    base.setdefault("moving", [(ox, oy, 0.0, 0.0, (ox, oy) == base["keeper"])
                               for ox, oy in base["opponents"]])
    return D.Scene(**base)


def test_a_mid_on_ball_dial_leaves_the_weights_as_they_were():
    assert tilt(MID) == 0.0 and tilt(LOW) < 0 < tilt(HIGH)
    assert Style().progress_weight(False) == Style().progress_weight(True) == 1.0
    assert Style().loss_weight() == 1.0


def test_a_direct_team_values_the_long_forward_pass_more_against_the_short_one(hand_written_values):
    """The same two passes: 30 m forward or 10 m square. Directness widens the forward pass's lead."""
    forward, square = ("h9", 70.0, 34.0, 0.0), ("h6", 40.0, 44.0, 0.0)

    def lead(directness: float) -> float:
        scene = on_ball(Style(directness=directness))
        return D.pass_option(scene, forward).value - D.pass_option(scene, square).value

    assert lead(HIGH) > lead(MID) > lead(LOW)


def test_a_counter_attacking_team_goes_forward_more_only_just_after_winning_the_ball():
    high = Style(counter_attacking=HIGH)
    assert high.progress_weight(True) > high.progress_weight(False) == 1.0
    assert Style(counter_attacking=LOW).progress_weight(True) < 1.0


def test_a_risky_team_fears_losing_the_ball_less(hand_written_values):
    """A pass through a lane an opponent may cut: worth more to a risk-taking team, as it judges it;
    whether it gets through is still physics."""
    mate, blocker = ("h9", 70.0, 34.0, 0.0), (55.0, 35.0)
    values = {r: D.pass_option(on_ball(Style(risk=r), opponents=[blocker]), mate).value
              for r in (LOW, MID, HIGH)}
    assert values[HIGH] > values[MID] > values[LOW]


def test_the_carrier_reads_his_teams_style_and_whether_the_counter_is_on():
    e = Engine(1, styles={"home": Style(directness=HIGH, counter_attacking=HIGH, risk=HIGH)})
    carrier = e.by_id["h7"]
    e.possessor = carrier.id
    brain = e.brains["home"]
    brain.update(e.t, True, 52.5, {})  # home has just won it
    brain.changed_at = e.t
    countering = e.scene_for(carrier)
    brain.changed_at = e.t - TRANSITION_S - 1
    settled = e.scene_for(carrier)
    assert countering.progress_weight > settled.progress_weight > 1.0
    assert settled.loss_weight < 1.0
    assert e.scene_for(e.by_id["a7"]).progress_weight == 1.0  # the away side plays the default


def test_a_high_counter_attacking_team_sends_its_midfielders_in_behind_while_the_counter_is_on():
    for level, runs in ((HIGH, True), (MID, False)):
        e = Engine(1, styles={"home": Style(counter_attacking=level)})
        for p in e.players:
            p.vx = p.vy = 0.0
        carrier, runner = e.by_id["h7"], e.by_id["h6"]  # CM on the ball, RCM ahead of him
        carrier.x, carrier.y, runner.x, runner.y = 45.0, 34.0, 55.0, 20.0
        e.possessor, e.hold_until = carrier.id, 0.0
        for q in e.players:  # opponents well away from the carrier, so he can play
            if q.team == "away" and q.role != "GK":
                q.x = 70.0
        sight = e.beliefs[runner.id]
        for q in e.players:  # he has seen the away back line at 70 m, so he knows he is onside
            if q.team == "away":
                sight.seen[q.id] = perception.Sighting(q.x, q.y, 0.0, 0.0, t=e.t)
        brain = e.brains["home"]
        brain.in_possession, brain.changed_at = True, e.t
        e.brains["away"].line_x = 70.0
        assert "runs_in_behind" not in runner.profile.traits
        runner.profile.archetype = "ball_winner"  # no run in behind of his own (roles.py)
        # O10: the counter opens the run to him; whether he makes it is his choice among his moves.
        assert (e.move_spot(runner, carrier, brain, "in_behind") is not None) is runs


def test_on_ball_weights_never_go_negative_anywhere_on_the_dial():
    for d in (0.0, 0.1, 0.5, 1.0):
        for c in (0.0, 0.1, 0.5, 1.0):
            style = Style(directness=d, counter_attacking=c)
            assert style.progress_weight(False) >= 0 and style.progress_weight(True) >= 0
    assert Style(directness=1.0, counter_attacking=0.0).progress_weight(True) == 0.0  # never backward-seeking
    assert 0.5 <= Style(risk=1.0).loss_weight() < Style(risk=0.0).loss_weight() <= 1.5


def test_directness_reads_forward_for_both_ends(hand_written_values):
    """Attacking the goal at x = 0 (the away side): forward is toward smaller x."""
    forward, square = ("a9", 35.0, 34.0, 0.0), ("a6", 65.0, 44.0, 0.0)

    def lead(directness: float) -> float:
        scene = on_ball(Style(directness=directness), x=65.0, goal_x=0.0)
        return D.pass_option(scene, forward).value - D.pass_option(scene, square).value

    assert lead(HIGH) > lead(MID) > lead(LOW)


def test_risk_reaches_every_option_that_can_lose_the_ball(hand_written_values):
    """Near goal with defenders close: passing, shooting, dribbling and holding all count the cost
    of losing the ball, so each is worth more to a team that fears it less."""
    mate = ("h9", 92.0, 25.0, 0.0)
    near = [(84.0, 35.0), (86.0, 31.0), (95.0, 34.0)]

    def values(risk: float) -> dict[str, float]:
        opts = D.options(on_ball(Style(risk=risk), x=82.0, y=34.0, mates=[mate], opponents=near))
        best: dict[str, float] = {}
        for o in opts:
            best[o.kind] = max(best.get(o.kind, -9.0), o.value)
        return best

    low, high = values(LOW), values(HIGH)
    for kind in ("pass", "shoot", "dribble", "hold"):
        assert high[kind] > low[kind], kind


def test_a_patient_team_never_values_going_back_and_mid_changes_nothing(hand_written_values):
    """The weight scales the change in the ball's worth: at 0.1 a tenth of the gain forward and of
    the loss going back, so going back is never a gain; at mid the value is untouched."""
    for x in (25.0, 40.0, 55.0, 85.0):
        here = D.value(x, 34.0, 105.0)
        for gained in (10.0, -10.0):
            change = D.value(x + gained, 34.0, 105.0) - here
            for style in (Style(directness=LOW), Style(), Style(directness=HIGH)):
                scene = on_ball(style, x=x)
                assert math.isclose(D.our_value(scene, x + gained, 34.0) - here,
                                    style.progress_weight(False) * change, abs_tol=1e-12)


def test_dribbling_forward_is_worth_more_to_a_direct_team(hand_written_values):
    def straight_on(directness: float) -> float:
        opts = D.options(on_ball(Style(directness=directness)))
        return next(o.value for o in opts if o.kind == "dribble")  # the first carry is straight at goal

    assert straight_on(HIGH) > straight_on(MID) > straight_on(LOW)


def test_the_counter_is_on_only_for_the_team_with_the_ball():
    brain = TeamBrain("home")
    brain.update(10.0, True, 52.5, {})
    assert brain.attacking_transition(11.0) and not brain.attacking_transition(10.0 + TRANSITION_S + 1)
    brain.update(12.0, False, 52.5, {})
    assert not brain.attacking_transition(12.5)
