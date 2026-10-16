"""Heading (docs/GROUNDING.md P11, P17): the head plays a ball above a foot's reach, higher with a
jump once there is time to rise; a header is struck from where the ball is met, no harder than the
head can send it, with a header's error; a player heads a ball only when it is contested and lets
an unchallenged one drop to his feet; the passer's race decides the same way. Each test names the
mutation it must catch."""

import math

import pytest

from ninety.sim import ball, decisions, offball
from ninety.sim.body import (
    BODY_RESTITUTION,
    CONTROL_M,
    FOOT_REACH_Z,
    HAND_REACH_Z,
    HEAD_JUMP_Z,
    HEAD_REACH_M,
    HEAD_SPEED_MPS,
    HEAD_STAND_Z,
    JUMP_RISE_S,
)
from ninety.sim.engine import DT, Engine
from ninety.sim.profiles import HEADER_ERROR

LATE = JUMP_RISE_S + 0.1  # long enough after his reaction to have jumped


@pytest.mark.parametrize("z, since, heads, hands, reach", [
    (0.5, LATE, True, False, CONTROL_M),  # a foot
    (FOOT_REACH_Z + 0.2, 0.0, True, False, HEAD_REACH_M),  # a stooping header, no jump needed
    (HEAD_STAND_Z, 0.0, True, False, HEAD_REACH_M),  # a standing header at its highest
    (HEAD_STAND_Z + 0.1, JUMP_RISE_S * 0.5, True, False, None),  # needs a jump he has not had time for
    (HEAD_STAND_Z + 0.1, LATE, True, False, HEAD_REACH_M),  # jumping
    (HEAD_JUMP_Z + 0.05, LATE, True, False, None),  # over his jump
    (FOOT_REACH_Z + 0.2, LATE, False, False, None),  # letting it drop: only his feet
    (0.5, LATE, False, False, CONTROL_M),
    (HAND_REACH_Z - 0.1, 0.0, True, True, offball.arm_reach_m(0.0)),  # a keeper's hands
    (HAND_REACH_Z + 0.1, LATE, True, True, None),
], ids=["foot", "stooping", "standing", "too soon to jump", "jumping", "over the jump", "feet only above",
        "feet only below", "keeper hands", "over the keeper"])
def test_what_a_player_reaches_at_each_height(z, since, heads, hands, reach):
    """Mutations caught: no jump time; the head reaching any height; the jump's or the standing
    header's limit widened; `heads` ignored; a keeper's hands above his reach."""
    assert offball.reach_at(hands, since, z, heads) == reach


def test_a_header_is_judged_a_header_only_above_a_foot_and_out_of_a_keepers_hands():
    assert offball.headed(False, FOOT_REACH_Z + 0.01) and not offball.headed(False, FOOT_REACH_Z)
    assert not offball.headed(True, 2.0)


@pytest.mark.parametrize("distance, speed, z0, aim", [(10.0, 14.0, 1.9, 0.5), (8.0, 14.0, 1.9, 2.0),
                                                      (12.0, 12.0, 1.8, 0.1), (5.0, 10.0, 1.9, 0.1)])
def test_a_header_launch_reaches_its_aim_in_flight(distance, speed, z0, aim):
    """ball.aim_from: flown by the engine's ball physics, the ball is at the aimed height when it has
    travelled the distance, and has not come down before. Mutation caught: accepting a bounce."""
    ground, up = ball.aim_from(distance, speed, z0, aim, DT)
    assert math.hypot(ground, up) == pytest.approx(speed)
    path = ball.predict((0.0, 0.0, z0, ground, 0.0, up), DT, 5.0)
    k = next(k for k, s in enumerate(path) if s[0] >= distance)
    a, b = path[k - 1], path[k]
    height = a[2] + (distance - a[0]) / (b[0] - a[0]) * (b[2] - a[2])
    assert height == pytest.approx(aim, abs=0.02)
    assert all(s[2] > 0.0 for s in path[1:k])  # still in the air


def test_a_header_cannot_reach_what_is_beyond_it():
    assert ball.aim_from(30.0, 12.0, 1.8, 0.1, DT) is None


def scene_at(x: float, y: float, z: float, incoming: tuple[float, float, float]) -> decisions.Scene:
    e = Engine(1)
    p = next(q for q in e.players if q.role == "ST" and q.team == "home")
    p.x, p.y = x, y
    e.ball = (x + 0.2, y, z, *incoming)
    s = e.scene_for(p)
    s.header, s.z, s.incoming = True, z, incoming
    return s


def test_the_hardest_header_is_the_heads_drive_and_what_the_ball_keeps_of_its_own_speed():
    """P17. Mutations caught: the ball's own speed ignored; added when it is moving away; the wrong
    restitution."""
    still = scene_at(95.0, 34.0, 1.6, (0.0, 0.0, 0.0))
    hardest = (1 + BODY_RESTITUTION) * HEAD_SPEED_MPS
    assert decisions.header_cap(still, 105.0, 34.0) == pytest.approx(hardest)
    along = scene_at(95.0, 34.0, 1.6, (15.0, 0.0, 0.0))  # already going the way he heads it
    against = scene_at(95.0, 34.0, 1.6, (-15.0, 0.0, 0.0))  # coming at him: headed back where it came from
    assert decisions.header_cap(against, 105.0, 34.0) == pytest.approx(hardest + BODY_RESTITUTION * 15.0)
    assert decisions.header_cap(along, 105.0, 34.0) == pytest.approx(hardest - BODY_RESTITUTION * 15.0)
    across = scene_at(95.0, 34.0, 1.6, (0.0, 15.0, 0.0))  # its speed across the line is lost
    assert decisions.header_cap(across, 105.0, 34.0) == pytest.approx(hardest)
    assert hardest == pytest.approx(1.3 * 11.0)  # P17: 11 m/s and 0.3, pinned


def test_a_header_is_less_precise_than_a_kick():
    """Mutation caught: the header error not applied (or applied to kicks)."""
    p = Engine(1).players[9].profile
    kick = p.strike_error("finishing", 15.0, 5.0, 1.0, 0.0)
    head = p.strike_error("finishing", 15.0, 5.0, 1.0, 0.0, header=True)
    assert head[0] == pytest.approx(kick[0] * HEADER_ERROR)
    assert head[2] == pytest.approx(kick[2] * HEADER_ERROR)
    assert head[3] == 1.0  # no weaker foot


CROSS = (96.0, 24.0, 1.5, 0.0, 14.0, 3.7)  # fast, at his head height as it reaches him 0.7 s later
DROPPING = (96.0, 29.0, 3.0, 0.0, 6.0, 1.0)  # coming down onto him: head height, then his feet


def cross_at_head(defender_gap: float | None, state: tuple = CROSS,
                  upstream: float = 0.0) -> tuple[Engine, list[dict]]:
    """A ball played toward an attacker (`state`: by default crossed at his head height from the
    wing), with a defender `defender_gap` metres from him (None: nobody near), everyone else far
    away (`upstream`: the defender that much nearer where the ball comes from); played on for 1.2 s."""
    e = Engine(3)
    att = next(q for q in e.players if q.role == "ST" and q.team == "home")
    dfd = next(q for q in e.players if q.role == "RCB" and q.team == "away")
    for k, q in enumerate(e.players):
        if q not in (att, dfd):
            q.x, q.y, q.vx, q.vy = 30.0 + k, 5.0 + 2.5 * (k % 20), 0.0, 0.0
    att.x, att.y, att.vx, att.vy = 96.0, 34.0, 0.0, 0.0
    if defender_gap is None:
        dfd.x, dfd.y = 60.0, 60.0
    else:
        dfd.x, dfd.y = 96.0 + defender_gap, 34.0 - upstream
    dfd.vx = dfd.vy = 0.0
    e.possessor = e.restart = e.set_play = None
    e.ball = state
    e.kicked = e.emit("pass", "home", state[0], state[1], player="h7")
    e.pass_target = (96.0, 34.0)  # aimed at the striker
    e.last_touch = "h7"
    e.kicked_at = e.free_since = e.t - 2.0  # everyone has long reacted
    start = len(e.match.events)
    for _ in range(int(1.2 / DT)):
        e.step()
    return e, e.match.events[start:]


def test_a_contested_cross_is_headed_from_where_it_is_met_no_harder_than_a_head_can():
    """Mutations caught: no header (the ball passes over the box, as before heading); a header struck
    from the ground; a header harder than the cap."""
    e, events = cross_at_head(0.6)
    headers = [ev for ev in events if ev["type"] in ("pass", "shot")]
    assert headers, "nobody headed a contested cross at head height"
    h = headers[0]
    z = e.match.frames[h["frame"]]["ball"]["z"]
    assert FOOT_REACH_Z < z <= HEAD_JUMP_Z
    cap = (1 + BODY_RESTITUTION) * HEAD_SPEED_MPS + BODY_RESTITUTION * 14.0
    assert h["ball_speed_kmh"] / 3.6 <= cap * 1.25  # the cap, with his speed error (a few SD of 6%)


def headers_in(e: Engine, events: list[dict]) -> list[dict]:
    return [ev for ev in events if ev["type"] in ("pass", "shot")
            and e.match.frames[ev["frame"]]["ball"]["z"] > FOOT_REACH_Z]


def test_an_unchallenged_ball_dropping_onto_him_is_brought_down_and_a_contested_one_headed():
    """P17 (engine.goes_up): the same ball, alone and with a defender at his shoulder. Mutations
    caught: heading whatever reaches the head first; never heading."""
    e, events = cross_at_head(None, DROPPING)
    assert not headers_in(e, events)
    striker = next(q.id for q in e.players if q.role == "ST" and q.team == "home")
    assert any(f["possessor"] == striker for f in e.match.frames[-10:])  # he has it at his feet
    e, events = cross_at_head(0.6, DROPPING)
    assert headers_in(e, events)


def test_a_ball_flying_past_him_that_he_cannot_bring_down_is_headed():
    """Unchallenged, but past him before he could get it at his feet: heading it is the only way to
    play it. Mutation caught: an unchallenged ball never headed."""
    e, events = cross_at_head(None, CROSS)
    assert headers_in(e, events)


def touches(z: float, who: str = "h1", x: float = 60.0) -> dict[str, list[str]]:
    """check_contacts on one touch (a headed pass) by `who` standing at (x, 34) with the ball `z` up."""
    from collections import defaultdict

    from ninety.validate import check_contacts
    frames = [{"frame": 0, "t": 0.0, "ball": {"x": x, "y": 34.0, "z": z}, "possessor": None,
               "players": [{"id": who, "team": "home", "x": x, "y": 34.0}]}]
    events = [{"id": "e1", "frame": 0, "type": "pass", "team": "home", "player": who}]
    problems: dict[str, list[str]] = defaultdict(list)
    check_contacts(events, frames, {"k1"}, problems)
    return dict(problems)


@pytest.mark.parametrize("z, who, x, flagged", [
    (2.0, "h1", 60.0, False),  # a header
    (3.39, "h1", 60.0, False),  # under a jumping keeper's hands, plus a frame of motion
    (3.41, "h1", 60.0, True),  # over it
    (3.3, "k1", 103.0, False),  # a keeper with his hands
    (3.6, "k1", 103.0, True),  # not even a keeper's hands reach that
], ids=["header", "just under", "just over", "keeper's hands", "over a keeper's hands"])
def test_no_touch_is_higher_than_a_player_can_reach(z, who, x, flagged):
    """P14 (P11). Mutations caught: the check dropped; its limit or slack widened; keepers exempt."""
    assert ("P14 touch possible" in touches(z, who, x)) is flagged


# --- audit 9: the numbers, the estimate against the engine, Law 11, the physics -------------------

def test_the_sourced_and_design_numbers_are_the_documented_ones():
    """P11, P17. Pinned, so a changed value cannot pass by changing the test's expectation with it.
    Mutations caught: each constant moved."""
    from ninety.sim import body
    assert body.JUMP_M == 0.45 and body.HEAD_REACH_M == 0.5 and body.HEAD_SPEED_MPS == 11.0
    assert HEAD_STAND_Z == pytest.approx(1.59) and HEAD_JUMP_Z == pytest.approx(2.04)
    assert JUMP_RISE_S == pytest.approx(0.303, abs=1e-3)
    assert HEADER_ERROR == 2.0 and BODY_RESTITUTION == 0.3
    assert decisions.HEADED_PASS_Z == 0.1 and decisions.HEADER_AWAY_DEG == 35.0
    assert decisions.DROP_HORIZON_S == 3.0
    assert offball.reach_at(False, LATE, FOOT_REACH_Z) == CONTROL_M  # the foot's height included


def test_a_header_completes_the_pass_to_him_and_an_opponents_header_ends_it():
    """Law 11 and the pass's end (P17): a header is deliberate play. Mutations caught: the header
    skipping the touch (no offside check, the pass left open); the header not counted as deliberate."""
    for gap in (0.6, -0.6):  # the defender behind him, or in front, so either may win it
        e, events = cross_at_head(gap)
        heads = headers_in(e, events)
        assert heads
        cross = next(ev for ev in e.match.events if ev["type"] == "pass" and ev["player"] == "h7")
        assert cross["receiver"] == heads[0]["player"]
        assert cross["outcome"] == ("success" if heads[0]["team"] == "home" else "fail")


def save_engine(on_target: bool) -> tuple[Engine, object]:
    e = Engine(1)
    dfd = next(q for q in e.players if q.role == "RCB" and q.team == "away")
    dfd.x, dfd.y = 100.0, 34.0
    e.ball = (99.0, 34.0, 1.6, 20.0, 0.0 if on_target else 20.0, 0.0)  # wide: 6 m across by the line
    e.kicked = e.emit("shot", "home", 90.0, 34.0, player="h9")
    e.last_touch = "h9"
    e.possessor = None
    e.offside = {"h10"}
    return e, dfd


def test_a_defender_heading_a_shot_off_the_line_does_not_restart_offside():
    """Law 11: a deliberate save is not a new phase; any other deliberate play by an opponent is.
    Mutations caught: the save exemption dropped; applied to a shot going wide."""
    e, dfd = save_engine(on_target=True)
    e.touched(dfd, 100.0, 34.0, True)
    assert e.offside == {"h10"}
    e, dfd = save_engine(on_target=False)
    e.touched(dfd, 100.0, 34.0, True)
    assert e.offside == set()


def test_the_estimate_of_a_headed_pass_is_the_naive_race_from_the_headers_height():
    """lesson 23: the passer's estimate from a header scene, flown from where he meets the ball, is
    the reference race. Mutations caught: flights from the ground; the header scene's height lost."""
    from test_pass_race_reference import reference
    s = scene_at(80.0, 30.0, 1.8, (0.0, 12.0, -2.0))
    s.mates = [("h10", 88.0, 34.0, 0.0, 0.0, 0.0), ("h11", 84.0, 22.0, 0.0, 1.0, 0.0)]
    s.moving = [(86.0, 33.0, 0.0, 0.0, False), (83.0, 25.0, 0.0, 0.0, False)]
    s.opponents = [(86.0, 33.0), (83.0, 25.0)]
    for mid, tx, ty in (("h10", 89.0, 34.0), ("h11", 85.0, 23.0)):
        est = decisions.pass_confidence(s, tx, ty, tx - 1.0, ty, 0.0, True, decisions.ARRIVE_MPS, mid)
        assert est == pytest.approx(reference(s, tx, ty, tx - 1.0, ty, 0.0, True, decisions.ARRIVE_MPS, mid),
                                    abs=1e-12)
    ground, up = decisions.headed_pass(s, 89.0, 34.0)
    path = ball.predict((0.0, 0.0, 1.8, ground, 0.0, up), DT, 3.0)
    d = math.hypot(9.0, 4.0)
    k = next(k for k, st in enumerate(path) if st[0] >= d)
    assert path[k][2] < 0.5  # it arrives at his feet, from the header's height


def header_strike(kind: str) -> tuple[Engine, decisions.Scene, list]:
    """A striker meeting a ball at 1.8 m, 10 m from goal, his strike recorded as asked for."""
    e = Engine(2)
    p = next(q for q in e.players if q.role == "ST" and q.team == "home")
    p.x, p.y = 95.0, 34.0
    e.ball = (95.3, 34.0, 1.8, -12.0, 0.0, -1.0)
    s = e.scene_for(p)
    s.header, s.z, s.incoming = True, 1.8, (-12.0, 0.0, -1.0)
    asked = []
    original = e.execute
    e.execute = lambda *a, **k: asked.append((a, k)) or original(*a, **k)
    if kind == "shot":
        e.shoot(p, header=s)
    else:
        e.pass_to(p, 88.0, 28.0, lofted=True, header=s)
    return e, s, asked


def test_a_header_is_struck_as_estimated_no_harder_than_the_cap_from_its_height():
    """Mutations caught: a header shot launched as a kick (ball.shot); a headed pass launched as a
    kick (loft_launch); the cap ignored; the header's error not asked for; launched from the ground."""
    e, s, asked = header_strike("shot")
    (args, kw), = asked
    vx, vy, vz = args[1:4]
    assert kw.get("header") is True
    assert math.sqrt(vx * vx + vy * vy + vz * vz) <= decisions.header_cap(s, 105.0, 34.0) + 1e-9
    assert e.ball[2] == pytest.approx(1.8)  # from where he met it
    e, s, asked = header_strike("pass")
    (args, kw), = asked
    want = decisions.headed_pass(s, 88.0, 28.0)
    assert kw.get("header") is True
    assert math.hypot(*args[1:3]) == pytest.approx(want[0]) and args[3] == pytest.approx(want[1])


def test_a_header_only_offers_what_a_header_can_reach():
    """Mutations caught: a header at goal from anywhere in shooting range; a headed pass to anyone."""
    far = scene_at(70.0, 34.0, 1.8, (0.0, 0.0, 0.0))  # 35 m out: no header reaches the goal
    far.mates = [("h10", 100.0, 34.0, 0.0, 0.0, 0.0), ("h11", 76.0, 30.0, 0.0, 0.0, 0.0)]
    kinds = [(o.kind, o.receiver) for o in decisions.options(far)]
    assert ("shoot", None) not in kinds and ("pass", "h10") not in kinds and ("pass", "h11") in kinds
    away = next(o for o in decisions.options(far) if o.kind == "clear")
    assert away.launch is not None  # struck as estimated (engine.pass_to)


def test_a_header_never_deflects_off_the_man_who_headed_it():
    """H1 (audit 9): the ball is met where it enters his head's reach and is not his body's until
    it is clear of him and moving away. Mutation caught: met at its closest point to him; his own
    body in the way of his strike."""
    import random
    rng = random.Random(9)
    headers = 0
    for _ in range(30):
        e, events = cross_at_head(rng.choice([None, 0.6, -0.6]),
                                  (96.0 + rng.uniform(-0.4, 0.4), 24.0, 1.5, rng.uniform(-1, 1), 14.0, 3.7))
        for h in headers_in(e, events):
            headers += 1
            after = [ev for ev in events if h["frame"] <= ev["frame"] <= h["frame"] + 10
                     and ev["type"] == "deflection" and ev["player"] == h["player"]]
            assert not after, (h, after)
    assert headers >= 10


def test_a_ball_he_lets_drop_does_not_pass_through_his_body():
    """H2 (audit 9): alone, he lets a ball at chest height drop; meeting his body it is cushioned
    there (a first touch), never through him. Mutation caught: letting it drop skips his body."""
    e = Engine(3)
    st = next(q for q in e.players if q.role == "ST" and q.team == "home")
    for k, q in enumerate(e.players):
        if q is not st:
            q.x, q.y, q.vx, q.vy = 20.0 + k, 5.0 + 2.5 * (k % 20), 0.0, 0.0
    st.x, st.y, st.vx, st.vy = 60.0, 34.0, 0.0, 0.0
    e.possessor = e.restart = e.set_play = None
    e.ball = (57.0, 34.0, 1.3, 7.0, 0.0, 2.5)
    e.kicked = e.emit("pass", "home", 57.0, 34.0, player="h7")
    e.last_touch, e.kicked_at = "h7", e.t - 2.0
    for _ in range(20):
        e.step()
        if e.possessor == st.id or e.ball[0] > 61.0:
            break
    assert e.possessor == st.id or any(ev["type"] == "deflection" and ev["player"] == st.id
                                       for ev in e.match.events)


@pytest.mark.parametrize("kind", ["pass", "shot", "deflection", "interception"])
def test_the_height_check_covers_every_touch(kind):
    """Mutation caught: the check limited to some touches."""
    from collections import defaultdict

    from ninety.validate import check_contacts
    frames = [{"frame": 0, "t": 0.0, "ball": {"x": 60.0, "y": 34.0, "z": 3.6}, "possessor": None,
               "players": [{"id": "h1", "team": "home", "x": 60.0, "y": 34.0}]}]
    problems: dict[str, list[str]] = defaultdict(list)
    check_contacts([{"id": "e1", "frame": 0, "type": kind, "team": "home", "player": "h1"}], frames, set(),
                   problems)
    assert any("3.6 m up" in m for m in problems["P14 touch possible"])


def test_a_header_interception_meets_the_event_order_and_a_missing_pass_fails(tmp_path):
    """Lesson 27: on engine output. A defender who heads a cross away intercepts it and plays it on
    in the same frame; the contract reads events in the order recorded (C8). Mutations caught: C8
    reading the interceptor's own header as the pass he intercepted; the check dropped."""
    import json

    from ninety.sim.engine import FPS
    from ninety.validate import validate
    for up in (1.0, 1.5, 2.0):  # the defender on the cross's line, nearer where it comes from
        e, events = cross_at_head(0.0, upstream=up)
        ev = e.match.events
        hit = next((k for k, x in enumerate(ev) if x["type"] == "interception" and k + 1 < len(ev)
                    and ev[k + 1]["type"] == "pass" and ev[k + 1]["player"] == x["player"]
                    and ev[k + 1]["frame"] == x["frame"]), None)
        if hit is not None:
            break
    else:
        pytest.fail("the defender never headed the cross away")

    def problems(events):
        (tmp_path / "events.jsonl").write_text("".join(json.dumps(x) + "\n" for x in events))
        (tmp_path / "frames.jsonl").write_text("".join(json.dumps(f) + "\n" for f in e.match.frames))
        (tmp_path / "meta.json").write_text(json.dumps({"fps": FPS, "score": e.match.score,
                                                        "roster": e.match.roster}))
        return validate(tmp_path)

    assert "C8 event order" not in problems(ev)
    crossed = max(k for k in range(hit) if ev[k]["type"] == "pass")
    planted = [dict(x, receiver=None) if k == crossed else x for k, x in enumerate(ev)]
    assert "C8 event order" in problems(planted)


def test_rules_each_checked_directly():
    """Each caught by its own assertion, not by a scene that happens to change (lesson 28).
    Mutations caught: aim_from accepting a target it cannot get down to; flights from the ground; a
    header at goal estimated as a kick (M3)."""
    assert ball.aim_from(0.6, 12.0, 2.0, 0.1, DT) is None  # struck down as far as allowed, still above
    points, _ = decisions.flight(10.0, 2.0, 1.8)
    assert points[0][2] == pytest.approx(1.8, abs=decisions.HEIGHT_STEP_M)
    head = scene_at(95.0, 34.0, 1.8, (0.0, 0.0, 0.0))
    foot = scene_at(95.0, 34.0, 1.8, (0.0, 0.0, 0.0))
    foot.header = False
    head.keeper = foot.keeper = (104.0, 34.0)
    assert decisions.shot_chance(head) < decisions.shot_chance(foot)  # slower: the keeper has more time


def test_the_header_scene_is_where_he_met_it_and_the_header_away_is_struck_as_estimated(monkeypatch):
    """Mutations caught: the scene's height or the incoming ball lost; the header away's launch not
    carried to the strike (M2); the ball met at its closest point to him, inside his body (H1)."""
    seen = {}

    def choose(scene, rng):
        seen["scene"] = scene
        away = next(o for o in decisions.options(scene) if o.kind == "clear")
        seen["away"] = away
        return away

    monkeypatch.setattr(decisions, "choose", choose)
    struck = []
    e, events = cross_at_head(0.0, upstream=1.0)
    s = seen["scene"]
    h = headers_in(e, events)[0]
    assert s.z == pytest.approx(e.match.frames[h["frame"]]["ball"]["z"], abs=1e-3)  # frames: to 1 mm
    assert s.incoming[1] > 10.0  # the cross, coming across at about 14 m/s
    me = next(q for q in e.match.frames[h["frame"]]["players"] if q["id"] == h["player"])
    assert math.hypot(h["x"] - me["x"], h["y"] - me["y"]) >= HEAD_REACH_M - 0.15  # at his reach, not inside
    e3 = Engine(3)  # the strike as asked for (execute records it before its error)
    st = next(q for q in e3.players if q.role == "ST" and q.team == "home")
    e3.ball = (st.x + 0.3, st.y, 1.8, 0.0, 0.0, 0.0)
    e3.execute = lambda *a, **k: struck.append(a) or (a[1], a[2], a[3])
    e3.pass_to(st, st.x + 10.0, st.y, lofted=True, header=s, launch=(9.0, 6.0))
    assert math.hypot(*struck[0][1:3]) == pytest.approx(9.0) and struck[0][3] == pytest.approx(6.0)


def test_the_engine_strikes_the_header_away_with_the_options_launch(monkeypatch):
    """M2 (audit 9). Mutation caught: engine.header dropping the option's launch."""
    asked = {}
    monkeypatch.setattr(decisions, "choose",
                        lambda scene, rng: next(o for o in decisions.options(scene) if o.kind == "clear"))
    original = Engine.pass_to

    def record(self, *a, **k):
        asked.setdefault("launch", k.get("launch"))
        return original(self, *a, **k)

    monkeypatch.setattr(Engine, "pass_to", record)
    cross_at_head(0.0, upstream=1.0)
    assert asked["launch"] is not None


def test_a_ball_flying_past_his_head_is_not_one_he_can_let_drop():
    """engine.goes_up, at the moment the ball is in his head's reach. Mutation caught: the feet-only
    check allowed to use his head (then every ball in reach of his head is 'at his feet first')."""
    e2 = Engine(3)
    st = next(q for q in e2.players if q.role == "ST" and q.team == "home")
    for k, q in enumerate(e2.players):
        if q is not st:
            q.x, q.y, q.vx, q.vy = 30.0 + k, 5.0 + 2.5 * (k % 20), 0.0, 0.0
    st.x, st.y, st.vx, st.vy = 96.0, 34.0, 0.0, 0.0
    e2.kicked_at = e2.t - 2.0
    e2.ball = (96.0, 33.6, 1.7, 0.0, 14.0, 0.5)  # at his head now, going past at 14 m/s
    assert e2.goes_up(st)
