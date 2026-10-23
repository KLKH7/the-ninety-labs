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


def test_he_throws_no_faster_than_a_ball_can_be_thrown_and_may_kick_to_anyone(monkeypatch):
    # L15: how far he throws is limited by how fast a ball can be thrown (21.5 m/s: van den Tillaar
    # and Ettema 2004), not by a set distance; any team-mate may be kicked to from his hands, and a
    # kick from his hands goes through the air.
    e, k = caught()
    scene = e.scene_for(k)
    original = decisions.pass_confidence
    want = {}

    def only(*args, **kwargs):  # every way fails but the one under test, so only the limit can stop it
        lofted = kwargs["lofted"] if "lofted" in kwargs else args[6]
        pace = kwargs["pace"] if "pace" in kwargs else args[7]
        return original(*args, **kwargs) if (lofted, pace) == want["way"] else 0.0

    monkeypatch.setattr(decisions, "pass_confidence", only)
    for d, lofted, pace, throwable in [
        (25.0, True, decisions.ARRIVE_MPS, True),  # 25 m through the air: 19 m/s
        (38.0, True, decisions.ARRIVE_MPS, False),  # 38 m through the air: about 25 m/s
        (38.0, False, decisions.PASS_PACES[0], True),  # rolled softly: 17 m/s
        (38.0, False, decisions.PASS_PACES[-1], False),  # rolled hard: about 26 m/s
    ]:
        want["way"] = (lofted, pace)
        alone = dataclasses.replace(scene, mates=[("h9", k.x + d - 1.5, k.y, 0.0)], opponents=[], moving=[],
                                    throw=True, from_hands=True)
        ways = {(o.lofted, o.pace) for o in decisions.options(alone) if o.kind == "pass"}
        assert ((lofted, pace) in ways) == throwable, (d, lofted, pace, ways)
    far = dataclasses.replace(scene, mates=[("h9", 40.0, 34.0, 0.0)], opponents=[], moving=[])
    monkeypatch.setattr(decisions, "pass_confidence", original)
    kicked = [o for o in decisions.options(dataclasses.replace(far, from_hands=True)) if o.kind == "pass"]
    assert kicked and kicked[0].receiver == "h9"
    assert all(o.lofted for o in kicked)  # dropped from his hands and struck, it goes through the air

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


def test_a_keepers_throw_may_roll_and_a_throw_in_stays_in_the_air(monkeypatch):
    # L15: his throw uses the passer's ground paces. A throw-in (Law 15) stays through the air.
    e, k = caught()
    scene = e.scene_for(k)
    original = decisions.pass_confidence

    def prefer_ground(*args, **kwargs):
        lofted = kwargs["lofted"] if "lofted" in kwargs else args[6]
        return 0.0 if lofted else original(*args, **kwargs)

    monkeypatch.setattr(decisions, "pass_confidence", prefer_ground)
    near = scene.mates
    keeper_throw = decisions.options(dataclasses.replace(
        scene, throw=True, from_hands=True, mates=near))
    throw_in = decisions.options(dataclasses.replace(
        scene, throw=True, from_hands=False, mates=near))
    assert [o for o in keeper_throw if o.kind == "pass"]
    assert all(not o.lofted for o in keeper_throw if o.kind == "pass")
    assert [o for o in throw_in if o.kind == "pass"]
    assert all(o.lofted for o in throw_in if o.kind == "pass")


def test_a_rolled_throw_is_bowled_from_the_grass_as_the_estimate_flies_it(monkeypatch):
    # L15, lessons 23 and 69: the estimate flies a rolled throw from the ground at launch_speed. He
    # brings the ball down in his hands to the grass, no faster than it came up (P6), and lets it go
    # from there at that speed. Released from his chest, it dropped, bounced and arrived at a third
    # of the speed the estimate gave it.
    from ninety.sim.engine import BALL_TO_FEET
    e, k = caught()
    e.ball = (k.x + 0.3, k.y, KEEPER_HOLD_Z, 0.0, 0.0, 0.0)
    mate = next(iter(e.scene_for(k).mates))
    pace = decisions.PASS_PACES[0]
    option = decisions.Option("pass", 1.0, (mate[1], mate[2]), receiver=mate[0], lofted=False, pace=pace)
    monkeypatch.setattr(decisions, "options", lambda scene: [option] if scene.throw else [])
    aimed, heights = [], []
    original = e.execute

    def execute(*args, **kwargs):
        aimed.append((math.hypot(args[1], args[2]), args[3], kwargs.get("hands"), e.ball[2]))
        return original(*args, **kwargs)

    monkeypatch.setattr(e, "execute", execute)
    e.release(k, e.scene_for(k))
    start = e.t
    while not aimed and e.t - start < 2.0:
        heights.append(e.ball[2])
        e.step()
    want = decisions.launch_speed(math.hypot(mate[1] - e.ball[0], mate[2] - e.ball[1]), pace)
    # along the ground, from his hands, from the grass
    assert len(aimed) == 1 and aimed[0][1:] == (0.0, True, 0.0)
    assert abs(aimed[0][0] - want) < 1e-9
    drops = [a - b for a, b in zip(heights, heights[1:], strict=False)]
    assert drops and max(drops) <= BALL_TO_FEET * DT + 1e-9  # brought down, not dropped in one frame
    down = [d for d in drops if d > 0]  # and at that rate: as fast as it came up (P6), no slower
    # the last part goes in the frame it is let go
    assert len(down) == int(KEEPER_HOLD_Z / (BALL_TO_FEET * DT))
    assert all(abs(d - BALL_TO_FEET * DT) < 1e-9 for d in down)

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


def test_with_nothing_to_choose_he_still_lets_it_go_inside_the_limit(monkeypatch):
    e, k = caught()
    monkeypatch.setattr(decisions, "options", lambda scene: [])
    start = e.t
    while e.possessor == k.id and e.t - start < KEEPER_HOLD_S + 1.0:
        e.step()
    assert KEEPER_RELEASE_S <= e.t - start < KEEPER_HOLD_S


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


def test_he_lets_it_go_the_way_his_estimate_values_most(monkeypatch):
    # L15: thrown, kicked from his hands, or put down: whichever is worth most (D1).
    def released(values):
        e, k = caught()
        mate = next(iter(e.scene_for(k).mates))
        throw, kick, feet = (decisions.Option("pass", v, (mate[1], mate[2]), receiver=mate[0], lofted=lofted)
                             for v, lofted in zip(values, (False, True, False), strict=True))
        monkeypatch.setattr(e, "release_options", lambda scene: (throw, kick, feet))
        e.release(k, e.scene_for(k))
        if e.held_by is None:
            return "put down"
        return "kick" if e.windup and e.windup[3] == "drop" else "throw"
    assert released((0.003, 0.002, 0.001)) == "throw"
    assert released((0.001, 0.003, 0.002)) == "kick"
    assert released((0.001, 0.002, 0.003)) == "put down"


def test_holding_it_he_stops_and_turns_to_face_up_the_pitch():
    # L15: he stops, braking within his body (P2), and turns up the pitch no faster than a body
    # turns (P16), carrying the ball at his chest.
    from ninety.sim.body import BRAKE_MAX, TURN_RATE
    e, k = caught()
    k.vx, k.vy, k.heading = 0.0, 3.0, math.pi / 2  # running across his box as he caught it
    speeds, headings = [], []
    for _ in range(50):
        e.step()
        speeds.append(math.hypot(k.vx, k.vy))
        headings.append(k.heading)
    assert e.held_by == k.id
    slowed = [a - b for a, b in zip([3.0] + speeds, speeds, strict=False)]
    assert speeds[-1] < 0.05 and max(slowed) <= BRAKE_MAX * DT + 1e-9
    assert abs(headings[-1]) < 1e-6  # facing up the pitch (home attacks +x)
    turns = [abs(b - a) for a, b in zip([math.pi / 2] + headings, headings, strict=False)]
    assert max(turns) <= TURN_RATE * DT + 1e-9


def test_the_ball_comes_up_into_his_hands_no_faster_than_a_carried_ball_settles():
    from ninety.sim.engine import BALL_TO_FEET
    e, k = caught()
    e.ball = (k.x + 0.3, k.y, 0.2, 0.0, 0.0, 0.0)  # taken low
    path = [e.ball[:3]]
    for _ in range(30):
        e.step()
        path.append(e.ball[:3])
    steps = [math.dist(a, b) - math.hypot(k.vx, k.vy) * DT for a, b in zip(path, path[1:], strict=False)]
    assert max(steps) <= BALL_TO_FEET * DT + 1e-6 and abs(path[-1][2] - KEEPER_HOLD_Z) < 1e-9


def test_let_go_it_is_no_longer_in_his_hands(monkeypatch):
    # Thrown, or kicked from his hands, the ball is in nobody's hands once it has left him.
    for lofted, throw in ((False, True), (True, False)):
        e, k = caught()
        mate = next(iter(e.scene_for(k).mates))
        o = decisions.Option("pass", 1.0, (mate[1], mate[2]), receiver=mate[0], lofted=lofted)
        none = decisions.Option("pass", -1.0, (mate[1], mate[2]), receiver=mate[0], lofted=True)
        monkeypatch.setattr(e, "release_options",
                            lambda scene, o=o, n=none, t=throw: (o, n, None) if t else (n, o, None))
        e.release(k, e.scene_for(k))
        start = e.t
        while e.possessor == k.id and e.t - start < 2.0:
            e.step()
        assert e.possessor is None and e.held_by is None


def test_he_throws_at_any_angle_but_turns_to_kick_it_from_his_hands(monkeypatch):
    # L15, P16: thrown with both hands, he needs no kicking side, so the way he faces changes
    # neither what the estimate expects nor when the engine throws. A kick from his hands is a kick:
    # he faces it first (STRIKE_FACING), in the estimate (strike_turn's wait) and on the pitch.
    e, k = caught()
    scene = e.scene_for(k)
    behind = dataclasses.replace(scene, mates=[("h2", k.x + 3.0, k.y + 20.0, 0.0)], opponents=[], moving=[])

    def values(throw):
        return [{(o.kind, round(o.value, 12)) for o in decisions.options(
            dataclasses.replace(behind, throw=throw, from_hands=True, heading=h))} for h in (0.0, math.pi)]

    assert values(True)[0] == values(True)[1]  # thrown: his facing does not matter
    assert values(False)[0] != values(False)[1]  # kicked: turning round first costs him
    for lofted, thrown in ((False, True), (True, False)):
        e, k = caught()
        for _ in range(10):
            e.step()
        k.heading = math.pi  # facing his own goal
        o = decisions.Option("pass", 1.0, (k.x + 3.0, k.y + 20.0), receiver="h2", lofted=lofted)
        n = decisions.Option("pass", -1.0, (k.x + 3.0, k.y + 20.0), receiver="h2", lofted=True)
        monkeypatch.setattr(e, "release_options",
                            lambda scene, o=o, n=n, t=thrown: (o, n, None) if t else (n, o, None))
        e.release(k, e.scene_for(k))
        if thrown:  # bowled from the grass at once, not turned first
            assert e.windup and e.windup[3] == "bowl"
        else:
            assert e.windup and e.windup[3] == "turn"
            frames = 0
            while e.windup and e.windup[3] == "turn" and frames < 50:
                e.step()
                frames += 1
            assert e.windup and e.windup[3] == "drop"  # let fall only once he faces it
            off = decisions.turn_deg(math.atan2(20.0, 3.0), k.heading)
            assert abs(off) <= math.degrees(decisions.STRIKE_FACING)


def test_a_kick_to_a_team_mate_behind_him_still_leaves_inside_six_seconds(monkeypatch):
    # Law 12, the worst case: at KEEPER_RELEASE_S he chooses a kick from his hands to a team-mate
    # behind him; he turns to face it (P16), lets it fall and strikes it, all before six seconds.
    e, k = caught()
    start = e.t
    target = (k.x - 0.5, k.y + 15.0)  # behind his facing up the pitch, by more than STRIKE_FACING
    n = decisions.Option("pass", -1.0, target, receiver="h2", lofted=True)
    o = decisions.Option("pass", 1.0, target, receiver="h2", lofted=True)
    monkeypatch.setattr(e, "release_options", lambda scene: (n, o, None))
    struck = None
    while e.t - start < KEEPER_HOLD_S + 1.0:
        e.step()
        if e.held_by != k.id:
            struck = e.t - start
            break
    assert struck is not None and struck < KEEPER_HOLD_S
    assert e.kicked and e.kicked["type"] == "pass" and e.kicked["player"] == k.id


def test_a_lunge_he_would_evade_does_not_push_the_ball_out_of_his_hands():
    # Law 12: nobody may challenge him, and he has no dribble to push away from a lunge on its way.
    e, k = caught()
    for _ in range(10):
        e.step()
    attacker = next(q for q in e.players if q.team == "away" and q.role != "GK")
    attacker.x, attacker.y = e.ball[0] + 1.5, e.ball[1]
    e.lunges[attacker.id] = e.t + 0.3  # still on its way,
    e.evade_at[attacker.id] = e.t  # and he would have reacted to it by now
    e.duels()
    assert e.held_by == k.id and e.possessor == k.id and e.dribbler is None
    assert abs(e.ball[2] - KEEPER_HOLD_Z) < 1e-9


def test_his_error_never_throws_it_faster_than_an_arm_can_and_a_kick_is_not_held_to_that(monkeypatch):
    # L15: the executed throw, with his error, stays under KEEPER_THROW_MPS; a drop kick does not.
    for lofted, throw in ((True, True), (True, False)):
        e, k = caught()
        mate = next(iter(e.scene_for(k).mates))
        o = decisions.Option("pass", 1.0, (mate[1], mate[2]), receiver=mate[0], lofted=lofted)
        n = decisions.Option("pass", -1.0, (mate[1], mate[2]), receiver=mate[0], lofted=True)
        monkeypatch.setattr(e, "release_options",
                            lambda scene, o=o, n=n, t=throw: (o, n, None) if t else (n, o, None))
        original = e.execute
        monkeypatch.setattr(e, "execute", lambda *a, original=original, **kw: tuple(
            30.0 * v / max(math.hypot(*original(*a, **kw)), 1e-9) for v in original(*a, **kw)))  # 30 m/s
        e.release(k, e.scene_for(k))
        start = e.t
        while e.possessor == k.id and e.t - start < 2.0:
            e.step()
        speed = math.hypot(*e.ball[3:])
        if throw:
            assert speed <= decisions.KEEPER_THROW_MPS + 1e-6
        else:
            assert speed > 25.0


def test_a_bowled_throw_is_drawn_as_a_bowl_and_a_kick_from_his_hands_as_a_strike(monkeypatch):
    # The exported truth names what he does (Engine.pose, the frame's `action`): bringing the ball
    # down to bowl it is "bowl", never "strike" (the renderer drew it with a kicking leg).
    for lofted, thrown, want in ((False, True, "bowl"), (True, False, "strike")):
        e, k = caught()
        mate = next(iter(e.scene_for(k).mates))
        o = decisions.Option("pass", 1.0, (mate[1], mate[2]), receiver=mate[0], lofted=lofted)
        n = decisions.Option("pass", -1.0, (mate[1], mate[2]), receiver=mate[0], lofted=True)
        monkeypatch.setattr(e, "release_options",
                            lambda scene, o=o, n=n, t=thrown: (o, n, None) if t else (n, o, None))
        e.release(k, e.scene_for(k))
        drawn = []
        while e.windup and len(drawn) < 50:
            drawn.append(e.pose(k)[0])
            e.step()
        assert drawn and set(drawn) == {want}
