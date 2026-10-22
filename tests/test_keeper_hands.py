"""Law 12: a keeper who catches the ball holds it in his hands, at his chest, and lets it go within
six seconds, by a throw or a kick from his hands (engine.release). Once it was dropped to his feet
and played like any outfielder's ball, so the footage showed a keeper who never held it."""

import dataclasses
import math

from ninety.sim import decisions
from ninety.sim.engine import (
    DT,
    KEEPER_HOLD_S,
    KEEPER_HOLD_Z,
    KEEPER_RELEASE_S,
    KEEPER_THROW_M,
    Engine,
)
from ninety.sim.firsttouch import CUSHION


def caught(seed: int = 1) -> tuple[Engine, object]:
    """A keeper in his box who has just caught a high ball (tests/test_engine_rules.py's catch)."""
    e = Engine(seed)
    for _ in range(50):  # two seconds in: everyone has looked around (perception)
        e.step()
    e.dribbler = e.windup = e.dribble_to = None
    for p in e.players:
        p.vx = p.vy = 0.0
    k = e.keeper("home")
    k.x, k.y, k.heading = 5.0, 34.0, 0.0
    k.profile.attributes["handling"] = 1.0
    e.possessor, e.last_touch, e.kicker_clear, e.kicked_at = None, "a6", True, e.t - 2.0
    hold = k.profile.absorb_mps(True)
    fast = hold * (1 + CUSHION["chest"]) / 2
    e.ball = (4.6 + fast * DT, 34.0, 1.4, fast, 0.0, 0.0)
    e.contact((4.6, 34.0, 1.4, fast, 0.0, 0.0))
    assert e.possessor == k.id
    return e, k


def test_a_caught_ball_is_held_at_his_chest_and_let_go_within_six_seconds():
    e, k = caught()
    assert e.held_by == k.id
    start, heights = e.t, []
    # The hold itself, before a drop kick's fall (that fall is the release, tested separately).
    while e.held_by == k.id and e.windup is None and e.t - start < KEEPER_HOLD_S + 1.0:
        heights.append(e.ball[2])
        e.step()
    while e.held_by == k.id and e.t - start < KEEPER_HOLD_S + 1.0:
        e.step()
    up = next(i for i, z in enumerate(heights) if abs(z - KEEPER_HOLD_Z) < 1e-6)  # into his hands
    assert min(heights[up:]) > KEEPER_HOLD_Z - 1e-6  # and it stays there, never down at his feet
    assert e.held_by is None and e.t - start < KEEPER_HOLD_S  # let go inside Law 12's limit
    # thrown or kicked (a pass of his), or put down to play with his feet (released: Law 12, L13)
    passed = any(x["type"] == "pass" and x["player"] == k.id and x["t"] >= start for x in e.match.events)
    assert passed or (e.possessor == k.id and e.released_by == k.id)


def test_he_throws_only_to_team_mates_in_range_and_kicks_from_his_hands_beyond_it(monkeypatch):
    e, k = caught()
    asked = []
    original = decisions.options
    monkeypatch.setattr(decisions, "options", lambda scene: asked.append(scene) or original(scene))
    e.release(k, e.scene_for(k))
    # A throw is in his hands (from_hands) as well as thrown. A kick is from_hands and not a throw.
    thrown = next(s for s in asked if s.throw)
    kicked = next(s for s in asked if s.from_hands and not s.throw)
    far = lambda m: math.hypot(m[1] - k.x, m[2] - k.y) > KEEPER_THROW_M  # noqa: E731
    assert thrown.mates and not any(far(m) for m in thrown.mates)
    assert kicked.mates and all(far(m) for m in kicked.mates)


def test_a_throw_leaves_his_hands_and_a_kick_from_them_leaves_the_ground(monkeypatch):
    def struck(throw):
        e, k = caught()
        e.ball = (k.x + 0.3, k.y, KEEPER_HOLD_Z, 0.0, 0.0, 0.0)
        mate = next(m for m in e.scene_for(k).mates)
        option = decisions.Option("pass", 1.0, (mate[1], mate[2]), receiver=mate[0], lofted=True)
        monkeypatch.setattr(decisions, "options", lambda scene: [option] if scene.throw == throw else [])
        used = []
        original = e.execute
        monkeypatch.setattr(e, "execute", lambda *a, **kw: used.append((kw.get("hands"), e.ball[2]))
                            or original(*a, **kw))
        e.release(k, e.scene_for(k))
        start = e.t
        while not used and e.t - start < 2.0:
            e.step()
        return used, e.t - start
    assert struck(True) == ([(True, KEEPER_HOLD_Z)], 0.0)  # thrown from his hands, at once
    # dropped, it falls under gravity and is kicked as it meets the ground: from 1.1 m, about 0.47 s
    kicked, fell = struck(False)
    assert kicked == [(False, 0.0)] and abs(fell - math.sqrt(2 * KEEPER_HOLD_Z / 9.81)) <= 2 * DT


def test_with_nothing_to_choose_he_still_lets_it_go_inside_the_limit(monkeypatch):
    e, k = caught()
    monkeypatch.setattr(decisions, "options", lambda scene: [])
    start = e.t
    while e.possessor == k.id and e.t - start < KEEPER_HOLD_S + 1.0:
        e.step()
    assert KEEPER_RELEASE_S <= e.t - start < KEEPER_HOLD_S


def test_put_down_it_is_at_his_feet_and_his_hands_may_not_take_it_again(monkeypatch):
    # Law 12: he may put it down and play it with his feet; released, he may not handle it again
    # until another player touches it (L13), so it is in play and may be challenged.
    e, k = caught()
    mate = next(m for m in e.scene_for(k).mates)
    option = decisions.Option("pass", 1.0, (mate[1], mate[2]), receiver=mate[0])
    monkeypatch.setattr(decisions, "options",
                        lambda scene: [] if scene.throw or scene.from_hands else [option])
    e.release(k, e.scene_for(k))
    assert e.held_by is None and e.possessor == k.id and e.released_by == k.id
    assert not e.hands(k, k.x, k.y)


def test_he_waits_out_the_window_while_the_team_sets():
    # L15: a throw being available does not end the hold. He lets it go at KEEPER_RELEASE_S.
    e, k = caught()
    start = e.t
    while e.t - start < 2.0:
        e.step()
    assert e.held_by == k.id
    while e.held_by == k.id and e.t - start < KEEPER_HOLD_S + 1.0:
        e.step()
    assert KEEPER_RELEASE_S <= e.t - start < KEEPER_HOLD_S


def test_a_keepers_throw_may_roll_and_a_throw_in_stays_in_the_air(monkeypatch):
    # L15: his throw uses the passer's ground paces. A throw-in (Law 15) stays through the air.
    e, k = caught()
    scene = e.scene_for(k)
    original = decisions.pass_confidence

    def prefer_ground(*args, **kwargs):
        lofted = kwargs["lofted"] if "lofted" in kwargs else args[6]
        return 0.0 if lofted else original(*args, **kwargs)

    monkeypatch.setattr(decisions, "pass_confidence", prefer_ground)
    near = [m for m in scene.mates if math.hypot(m[1] - scene.x, m[2] - scene.y) <= KEEPER_THROW_M]
    keeper_throw = decisions.options(dataclasses.replace(
        scene, throw=True, from_hands=True, mates=near))
    throw_in = decisions.options(dataclasses.replace(
        scene, throw=True, from_hands=False, mates=near))
    assert [o for o in keeper_throw if o.kind == "pass"]
    assert all(not o.lofted for o in keeper_throw if o.kind == "pass")
    assert [o for o in throw_in if o.kind == "pass"]
    assert all(o.lofted for o in throw_in if o.kind == "pass")


def test_a_rolled_throw_leaves_his_hands_along_the_ground(monkeypatch):
    e, k = caught()
    e.ball = (k.x + 0.3, k.y, KEEPER_HOLD_Z, 0.0, 0.0, 0.0)
    mate = next(iter(e.scene_for(k).mates))
    option = decisions.Option("pass", 1.0, (mate[1], mate[2]), receiver=mate[0], lofted=False)
    monkeypatch.setattr(decisions, "options", lambda scene: [option] if scene.throw else [])
    aimed = []
    original = e.execute

    def execute(*args, **kwargs):
        aimed.append((args[3], kwargs.get("hands"), e.ball[2]))
        return original(*args, **kwargs)

    monkeypatch.setattr(e, "execute", execute)
    e.release(k, e.scene_for(k))
    assert aimed == [(0.0, True, KEEPER_HOLD_Z)]  # no upward speed, from his hands, at his chest


def test_a_lunge_already_on_its_way_cannot_take_it_from_his_hands():
    # Law 12: nobody may challenge a keeper for the ball he holds; a lunge struck before the catch
    # that arrives after it finds nothing (once it knocked the ball out of his hands).
    e, k = caught()
    for _ in range(10):
        e.step()
    assert e.held_by == k.id
    attacker = next(q for q in e.players if q.team == "away" and q.role != "GK")
    attacker.x, attacker.y, attacker.vx, attacker.vy = e.ball[0] + 0.3, e.ball[1], 0.0, 0.0
    e.lunges[attacker.id] = e.t  # arriving now
    e.duels()
    assert e.held_by == k.id and e.possessor == k.id and e.ball[2] > 1.0
    assert not [x for x in e.match.events if x["type"] == "tackle"]
