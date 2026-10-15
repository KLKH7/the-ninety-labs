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


def diving(vx: float, vy: float, aim_y: float) -> list[tuple[float, float]]:
    """A keeper moving at (vx, vy) dives at a shot heading for `aim_y`; his velocity each frame."""
    e = Engine(1)
    k = e.keeper("away")
    k.x, k.y, k.vx, k.vy = 104.0, 34.0, vx, vy
    e.possessor = None
    e.kicked = {"type": "shot", "team": "home", "x": 90.0, "y": 34.0}
    e.ball = (90.0, 34.0, 0.5, 25.0, (aim_y - 34.0) / 14.0 * 25.0, 0.0)
    e.kicked_at = e.free_since = e.t
    e.t += e.reaction(k)
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


def test_the_push_is_the_cited_one():
    """P15: from standing, the peak speed (3.6 to 4.0 m/s) after a push of 0.40 to 0.48 s."""
    assert 3.6 <= offball.DIVE_PEAK_MPS <= 4.0 and 0.40 <= offball.DIVE_PUSH_S <= 0.48
    assert offball.dive_distance(offball.DIVE_PUSH_S) == pytest.approx(
        0.5 * offball.DIVE_PEAK_MPS * offball.DIVE_PUSH_S)
    assert offball.dive_progress(offball.DIVE_TIME_S) == 1.0


def sideways(c: dict, who: dict, x: float, accel: float) -> None:
    """`who` stands at (x, 34), then from 1 s speeds up sideways at `accel` m/s² to 3.8 m/s."""
    y, v = 34.0, 0.0
    for n in range(150):
        f = c["frames"][n]
        f["players"] = [p for p in f["players"] if p["id"] != who["id"]] + [dict(who, x=x, y=y)]
        if n / FPS >= 1.0:
            v = min(3.8, v + accel / FPS)
        y += v / FPS


ROSTER = [{"id": "h1", "team": "home", "role": "CM"}, {"id": "h2", "team": "home", "role": "ST"},
          {"id": "a1", "team": "away", "role": "GK"}]


@pytest.mark.parametrize("role, x, accel, flagged", [
    ("GK", 103.0, 9.5, False),  # a keeper's dive in his area: within the cited push
    ("GK", 103.0, 12.0, True),  # harder than any cited dive
    ("CB", 103.0, 9.5, True),  # an outfield player in the same place: a sprint start
    ("GK", 80.0, 9.5, True),  # a keeper outside his area
], ids=["keeper dive", "keeper too hard", "outfield", "keeper outside his area"])
def test_p2_allows_a_dive_push_to_a_keeper_in_his_own_area_only(tmp_path, role, x, accel, flagged):
    """Mutations caught: the dive limit given to everyone, or anywhere; the limit widened."""
    c = clean_clip()
    roster = [dict(r) for r in ROSTER]
    roster[2]["role"] = role
    c["meta"]["roster"] = roster
    sideways(c, {"id": "a1", "team": "away"}, x, accel)
    assert ("P2 player acceleration" in run(tmp_path, c)) is flagged


def test_dives_in_play_stay_within_the_push():
    """Engine output, not a fixture: shots at a keeper from random angles and speeds; every frame
    of every dive within the push (P2 and P15 agree)."""
    rng = random.Random(5)
    for _ in range(20):
        aim = 34.0 + rng.choice((-1, 1)) * rng.uniform(1.5, 3.5)
        speeds = diving(rng.uniform(-2, 2), rng.uniform(-3, 3), aim_y=aim)
        for (ax, ay), (bx, by) in zip(speeds, speeds[1:], strict=False):
            assert math.hypot(bx - ax, by - ay) * FPS <= offball.DIVE_ACCEL + 1e-6
