"""The keeper's dive (docs/GROUNDING.md P15) and the acceleration check (P2): the push-off is one
force no stronger than the cited push (3.6 to 4.0 m/s in about 0.40 to 0.48 s), applied to however
the keeper was moving, so the body never changes speed in a jump; and the validator allows that
push to a keeper in his own penalty area, and to nobody else. Each test names the mutation it must
catch."""

import math
import random

import pytest
from test_validate import FPS, clean_clip, run

from ninety.sim import offball
from ninety.sim.engine import Engine


def dive_engine(vx: float, vy: float, aim_y: float) -> Engine:
    """A keeper moving at (vx, vy) as a shot heading for `aim_y` is struck; he has just reacted."""
    e = Engine(1)
    k = e.keeper("away")
    k.x, k.y, k.vx, k.vy = 104.0, 34.0, vx, vy
    e.possessor = None
    e.kicked = {"type": "shot", "team": "home", "x": 90.0, "y": 34.0}
    e.ball = (90.0, 34.0, 0.5, 25.0, (aim_y - 34.0) / 14.0 * 25.0, 0.0)
    e.kicked_at = e.free_since = e.t
    e.t += e.reaction(k)
    return e


def diving(vx: float, vy: float, aim_y: float) -> list[tuple[float, float]]:
    """His velocity each frame of the dive."""
    e = dive_engine(vx, vy, aim_y)
    k = e.keeper("away")
    speeds = [(k.vx, k.vy)]
    while e.keeper_dive(k):
        speeds.append((k.vx, k.vy))
        e.t += 1 / FPS
    return speeds


@pytest.mark.parametrize("vx, vy", [(0.0, 0.0), (0.0, -2.5), (2.0, 0.0), (1.5, -2.0)],
                         ids=["standing", "shuffling the other way", "coming off his line", "both"])
def test_the_push_never_changes_his_speed_faster_than_the_dive_can(vx, vy):
    """Regression (corner report): the dive reached its peak in 0.24 s (16 m/s²), a short dive
    played the same profile faster, it started from rest whatever he was doing (a keeper moving
    the other way reversed in one frame), and it stopped him dead at the end. Mutations caught:
    each of those."""
    speeds = diving(vx, vy, aim_y=37.5)
    assert len(speeds) > 3
    for (ax, ay), (bx, by) in zip(speeds, speeds[1:], strict=False):
        assert math.hypot(bx - ax, by - ay) * FPS <= offball.DIVE_ACCEL + 1e-6
    assert speeds[-1][1] > 1.0  # still moving when the push ends: he lands, he does not stop dead


def test_the_dive_goes_along_his_line_no_faster_than_its_peak():
    """Mutations caught: the push applied only along the line (he would keep running off it); a
    target speed above the cited peak. A keeper coming off his line is turned onto it; from
    standing he reaches the peak and no more."""
    speeds = diving(2.0, 0.0, aim_y=37.5)
    assert abs(speeds[-1][0]) < 0.5 * abs(speeds[0][0])  # his run off the line taken out
    peak = max(math.hypot(*v) for v in diving(0.0, 0.0, aim_y=37.9))
    assert peak <= 4.0 + 1e-9 and peak == pytest.approx(offball.DIVE_PEAK_MPS, abs=0.05)


def test_a_keeper_running_the_wrong_way_still_completes_his_dive():
    """Audit 8: a fixed give-up time could end a dive short, on the wrong side. Each dive's limit
    is the longest the push can take from how he started, so it always covers its travel.
    Mutations caught: a fixed or shorter limit."""
    for vy in (-6.0, -3.8, 0.0, 3.0, 5.0):
        e = dive_engine(1.5, vy, aim_y=37.5)
        k = e.keeper("away")
        assert e.keeper_dive(k)
        _, start, y0, travel, _, bound = e.dive
        while e.keeper_dive(k):
            e.t += 1 / FPS
        assert math.copysign(1.0, travel) * (k.y - y0) >= abs(travel) - 1e-9, vy
        assert e.t - start <= bound + 1 / FPS, vy


def test_a_diving_keeper_in_contact_is_pushed_no_harder_than_the_dive():
    """Audit 8: the dive did not count as his grip, so bracing against a player in his way was
    added on top of the push. Mutation caught: the push not recorded as grip used."""
    e = dive_engine(0.0, 0.0, aim_y=37.5)
    k = e.keeper("away")
    other = next(p for p in e.players if p.team == "home" and p.role != "GK")
    for _ in range(5):
        other.x, other.y, other.vx, other.vy = k.x - 0.4, k.y, 3.0, 0.0  # running into his side
        before = (k.vx, k.vy)
        e.move_players()
        assert math.hypot(k.vx - before[0], k.vy - before[1]) * FPS <= offball.DIVE_ACCEL + 1e-6
        e.t += 1 / FPS


def test_the_push_is_the_cited_one():
    """P15: from standing, the peak speed (3.6 to 4.0 m/s) after a push of 0.40 to 0.48 s."""
    assert 3.6 <= offball.DIVE_PEAK_MPS <= 4.0 and 0.40 <= offball.DIVE_PUSH_S <= 0.48
    assert offball.dive_distance(offball.DIVE_PUSH_S) == pytest.approx(
        0.5 * offball.DIVE_PEAK_MPS * offball.DIVE_PUSH_S)
    assert offball.dive_progress(offball.DIVE_TIME_S) == 1.0


def sideways(c: dict, who: dict, x: float, accel: float, y: float = 34.0, top: float = 3.8,
             along_x: bool = False) -> None:
    """`who` stands at (x, y), then from 1 s speeds up at `accel` m/s² to `top` m/s, along the
    goal line (y), or off it toward the field (x) if `along_x`."""
    v = 0.0
    for n in range(150):
        f = c["frames"][n]
        f["players"] = [p for p in f["players"] if p["id"] != who["id"]] + [dict(who, x=x, y=y)]
        if n / FPS >= 1.0:
            v = min(top, v + accel / FPS)
        if along_x:
            x -= v / FPS
        else:
            y += v / FPS


ROSTER = [{"id": "h1", "team": "home", "role": "CM"}, {"id": "h2", "team": "home", "role": "ST"},
          {"id": "a1", "team": "away", "role": "GK"}]


@pytest.mark.parametrize("role, x, accel, kw, flagged", [
    ("GK", 103.0, 9.5, {}, False),  # a keeper's dive in his area: within the cited push
    ("GK", 103.0, 12.0, {}, True),  # harder than any cited dive
    ("CB", 103.0, 9.5, {}, True),  # an outfield player in the same place: a sprint start
    ("GK", 80.0, 9.5, {}, True),  # a keeper well outside his area
    ("GK", 86.0, 9.5, {}, True),  # just outside its depth (16.5 m)
    ("GK", 103.0, 9.5, {"y": 10.0}, True),  # beside his area, not in it
    ("GK", 104.0, 9.5, {"along_x": True, "top": 7.0}, True),  # sprinting off his line
    ("GK", 104.0, 9.5, {"along_x": True, "top": 3.5}, True),  # off his line, slower than a dive
    ("GK", 103.0, 9.5, {"top": 7.0}, True),  # running along his line past a dive's speed
], ids=["keeper dive", "keeper too hard", "outfield", "keeper outside his area",
        "keeper just past the area's depth", "keeper beside his area", "keeper sprinting off his line",
        "keeper off his line at a dive's speed",
        "keeper running past a dive's speed"])
def test_p2_allows_a_dive_push_only_for_what_a_dive_can_be(tmp_path, role, x, accel, kw, flagged):
    """Audit 8: the allowance was any acceleration by a keeper anywhere in his area. Now only a
    dive's: in his own area, along his goal line, to no more than the dive's peak. Mutations
    caught: given to everyone, anywhere, in any direction, to any speed; the area's width or
    depth widened."""
    c = clean_clip()
    roster = [dict(r) for r in ROSTER]
    roster[2]["role"] = role
    c["meta"]["roster"] = roster
    sideways(c, {"id": "a1", "team": "away"}, x, accel, **kw)
    assert ("P2 player acceleration" in run(tmp_path, c)) is flagged


def test_random_dives_stay_within_the_push():
    """Keepers moving every which way (built states, not a played match: the corner contract test
    covers dives in play) dive at shots from random angles; every frame within the push."""
    rng = random.Random(5)
    for _ in range(20):
        aim = 34.0 + rng.choice((-1, 1)) * rng.uniform(1.5, 3.5)
        speeds = diving(rng.uniform(-2, 2), rng.uniform(-3, 3), aim_y=aim)
        for (ax, ay), (bx, by) in zip(speeds, speeds[1:], strict=False):
            assert math.hypot(bx - ax, by - ay) * FPS <= offball.DIVE_ACCEL + 1e-6
