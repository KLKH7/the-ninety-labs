"""A foul made legible on screen (lesson 173): the body is down on the frames the engine has it
down (`fall`, `fall_dir`), and up when it has it up. Inside that spell the drawing is a person's
(lesson 280, `falls`, `drawn_spell`): a stumble, a topple that gathers pace the way his run carries
him, arms out to the grass, the engine's get-up. x and y stay the feet; `tip` pivots the drawn
body over them. (The fouler's leg going out is a contact like a tackle's: scene.contacts.)

`fall` is degrees over the feet. `fall_dir` is radians, the same convention as heading: the way
the head goes. `tip` takes the angle in radians.

The players react to the whistle (lesson 234), drawn from the engine's own foul event (its frame,
`player` the fouler, `receiver` the fouled) and positions, never moving anyone: the engine already
stops play, so they walk and stand there. The fouler raises a hand, owning up to it, and the fouled
side's nearest team-mates turn their heads to the man on the grass. The head only: a body's facing is
the engine's `heading`, a truth field, which the drawing never contradicts.
"""

from __future__ import annotations

import math
import random
import zlib


def drawn_fall(player: dict) -> tuple[float, float]:
    """(radians over, direction in radians) from the engine's fields. Standing when `fall` is
    absent or not above 0. Does not change the player."""
    deg = player.get("fall")
    if type(deg) not in (int, float) or deg <= 0:
        return 0.0, 0.0
    way = player.get("fall_dir")
    if type(way) not in (int, float):
        way = 0.0
    return math.radians(float(deg)), float(way)


def apply_fall(gait, player: dict) -> None:
    """Put the engine's fall on the gait this frame. A frame with no fall stands him up."""
    gait.fall, gait.fall_dir = drawn_fall(player)
    gait.brace = None
    gait.crouch = None
    gait.tip_ahead = 0.0


# How a fall is drawn inside the engine's spell down (lesson 280, *design*: chosen by eye on seed
# 8324's fouls, not fitted to any check). The engine says when he is down and for how long; the
# drawing gives the body a stumble, a topple that gathers pace, a settle on the grass, and arms out
# to break it, and keeps the get-up the engine's. Each spell draws its own from a generator seeded by
# the player and the engine frame it starts on, so the same foul falls the same way in every clip.
FALL_DOWN_S = (0.55, 0.85)  # contact to the body on the grass, standing still
FALL_MOMENTUM_MPS = 7.0  # a run this fast or faster carries him down quickest
FALL_QUICKER = 0.25  # the share of FALL_DOWN_S a full-pace run takes off it
STUMBLE_SHARE = (0.35, 0.55)  # of the way down, the stumble before the topple
STUMBLE_DEG = (8.0, 16.0)  # how far over the stumble takes him, standing; more with pace
STUMBLE_PACE_DEG = 6.0
LAND_SHARE = (0.92, 1.0)  # of the engine's deepest angle, where he comes to rest (never deeper)
SETTLE_S = 0.2  # the body gives a little as it lands, and rests
SETTLE_DEG = 3.0
FALL_JITTER = math.radians(20.0)  # either side of the engine's way down
MOMENTUM_SHARE = 0.6  # at full pace, the weight of his run in the way he goes down
MOMENTUM_MIN_MPS = 1.0  # slower than this, no run to carry him
BRACE_FROM = 0.3  # of the stumble, when the arms start out (the reflex, after the contact)
SHOULDER_Z = 0.82  # shoulder height, of his height (the asset's: meshpose)
SHOULDER_SIDE_M = 0.19
ARM_M = 0.36  # of his height, shoulder to hand
ARM_REACH = 0.9  # of ARM_M: the hand reaches near the arm's length, the elbow soft
ARM_DROP = 0.7  # of the reach, how far below the shoulder the hand goes: forward and down
HAND_GRASS_M = 0.06  # the lowest a hand goes: on the grass
SPREAD = (0.25, 0.6)  # radians each hand goes out either side of the way he falls
GET_UP_S = 1.5  # getting up takes this long, starting before the engine's own get-up, never before
GET_UP_AFTER_S = 0.4  # he has been on the grass this long
GET_UP_PUSH = 0.35  # of the get-up: pushing up on his hands, the knees coming under him
GET_UP_KNEE = 0.2  # then a beat on one knee
GET_UP_PUSHED = 0.55  # of the way over he lies, after the push
GET_UP_KNELT = 0.35  # and on the knee
GET_UP_CROUCH = 0.6  # how far into the kneel after the push


def _stable_seed(pid: str, frame: int) -> int:
    return zlib.crc32(f"{pid}:{frame}".encode())


def falls(frames: list[dict], fps: int) -> dict[str, list[dict]]:
    """Per player, each spell down in `frames` (a run of frames with the engine's fall) and how it
    is drawn. A spell that is already under way on the first frame is drawn as the engine has it."""
    out: dict[str, list[dict]] = {}
    open_: dict[str, dict] = {}
    for i, fr in enumerate(frames):
        down = set()
        for pl in fr["players"]:
            deg = pl.get("fall")
            if type(deg) not in (int, float) or deg <= 0:
                continue
            down.add(pl["id"])
            sp = open_.get(pl["id"])
            if sp is None:
                sp = open_[pl["id"]] = {"i0": i, "deg": [], "pl0": pl, "prev": None}
                if i > 0:
                    sp["prev"] = next((q for q in frames[i - 1]["players"] if q["id"] == pl["id"]), None)
            sp["deg"].append(float(deg))
        for pid in [p for p in open_ if p not in down]:
            out.setdefault(pid, []).append(_plan(open_.pop(pid), frames, fps))
    for pid, sp in open_.items():
        out.setdefault(pid, []).append(_plan(sp, frames, fps))
    return out


def _plan(sp: dict, frames: list[dict], fps: int) -> dict:
    i0, deg = sp["i0"], sp["deg"]
    pl, prev = sp["pl0"], sp["prev"] or sp["pl0"]
    peak = max(deg)
    i_peak = i0 + deg.index(peak)  # the engine's body reaches its deepest
    i_rise = i0 + len(deg) - 1 - deg[::-1].index(peak)  # and leaves it: the get-up
    plan = {"i0": i0, "i1": i0 + len(deg) - 1, "i_rise": i_rise, "peak": peak, "drawn": i0 > 0}
    if not plan["drawn"]:
        return plan
    rng = random.Random(_stable_seed(pl["id"], int(frames[i0].get("frame", i0))))
    way = float(pl.get("fall_dir") or 0.0)
    vx, vy = float(prev.get("vx") or 0.0), float(prev.get("vy") or 0.0)  # his run into the contact
    speed = math.hypot(vx, vy)
    pace = min(speed / FALL_MOMENTUM_MPS, 1.0)
    run = math.atan2(vy, vx) if speed > MOMENTUM_MIN_MPS else way
    w = MOMENTUM_SHARE * pace
    final = _between(way, run, w)
    final += rng.uniform(-FALL_JITTER, FALL_JITTER)
    # One frame in at the contact, as the engine has it; on the grass no later than the get-up.
    first = 1.0 / fps
    latest = max((i_rise - i0 + 1) / fps, (i_peak - i0 + 1) / fps)
    down_s = min(rng.uniform(*FALL_DOWN_S) * (1.0 - FALL_QUICKER * pace), latest)
    on_grass = i0 - 1 + round((max(down_s, first) + GET_UP_AFTER_S) * fps)
    plan.update({
        "i_up": min(plan["i1"], max(on_grass, plan["i1"] + 1 - round(GET_UP_S * fps))),
        "lead": "l" if rng.random() < 0.5 else "r",
        "start_dir": run, "dir": final, "down_s": max(down_s, first),
        "stumble_s": max(down_s, first) * rng.uniform(*STUMBLE_SHARE),
        "stumble": math.radians(rng.uniform(*STUMBLE_DEG) + STUMBLE_PACE_DEG * pace),
        "land": math.radians(peak * rng.uniform(*LAND_SHARE)),
        "spread": (rng.uniform(*SPREAD), rng.uniform(*SPREAD)),
    })
    return plan


def _between(a: float, b: float, w: float) -> float:
    """The direction `w` of the way from `a` to `b` (radians, turning the short way round)."""
    return a + w * ((b - a + math.pi) % (2 * math.pi) - math.pi)


def _smooth(u: float) -> float:
    u = min(max(u, 0.0), 1.0)
    return u * u * (3.0 - 2.0 * u)


def get_up(lie: float, u: float) -> tuple[float, float, float]:
    """(radians over, the arms' weight, the crouch) `u` of the way through getting up from `lie`
    radians over: pushed up on the hands with the knees coming under him, a beat on one knee, then
    up and standing (*design*: no straight-legged pivot back up)."""
    u = min(max(u, 0.0), 1.0)
    a, b = GET_UP_PUSH, GET_UP_PUSH + GET_UP_KNEE
    if u < a:
        v = _smooth(u / a)
        return lie * (1.0 - (1.0 - GET_UP_PUSHED) * v), 1.0, GET_UP_CROUCH * v
    if u < b:
        v = (u - a) / GET_UP_KNEE
        return lie * (GET_UP_PUSHED - (GET_UP_PUSHED - GET_UP_KNELT) * v), 1.0 - _smooth(v), \
            GET_UP_CROUCH + (1.0 - GET_UP_CROUCH) * _smooth(v)
    v = _smooth((u - b) / (1.0 - b))
    return lie * GET_UP_KNELT * (1.0 - v), 0.0, 1.0 - v


def drawn_spell(plan: dict, i: int, engine_deg: float, fps: int) -> tuple[float, float, float, float]:
    """(radians over, direction, the arms' weight, the crouch) at clip frame `i` of a spell."""
    if not plan.get("drawn"):
        return math.radians(engine_deg), None, 0.0, 0.0
    t = (i - plan["i0"] + 1) / fps  # the contact frame is one frame into the fall (engine)
    s_t, d_t, land = plan["stumble_s"], plan["down_s"], plan["land"]
    if i >= plan["i_up"]:
        # The get-up (get_up), ending as the engine has him up: its last frame is short of standing.
        angle, arms, crouch = get_up(land, (i - plan["i_up"] + 1) / (plan["i1"] - plan["i_up"] + 2))
        return angle, plan["dir"], arms, crouch
    if t < s_t:
        u = t / s_t
        angle = plan["stumble"] * math.sin(0.5 * math.pi * u)  # caught off balance, slowing
        way = plan["start_dir"]
    elif t < d_t:
        u = (t - s_t) / max(d_t - s_t, 1e-6)
        angle = plan["stumble"] + (land - plan["stumble"]) * u * u  # the topple gathers pace
        mix = _smooth(u)
        way = _between(plan["start_dir"], plan["dir"], mix)
    else:
        v = (t - d_t) / SETTLE_S
        angle = land - math.radians(SETTLE_DEG) * math.sin(math.pi * min(v, 1.0)) * (1.0 - min(v, 1.0))
        way = plan["dir"]
    arms = _smooth((t / s_t - BRACE_FROM) / (1.0 - BRACE_FROM)) if t < d_t else 1.0
    return angle, way, arms, 0.0


def brace_targets(x: float, y: float, heading: float, height_m: float, angle: float, way: float,
                  spread: tuple[float, float], drop: float = ARM_DROP) -> dict[str, list[float]]:
    """Where each hand reaches, untipped world metres: put so that, once the body is tipped by
    `angle` toward `way`, the hand is ahead of its shoulder and down toward the grass (`drop` of
    the arm's reach below the shoulder; 1 pushes on the grass wherever it reaches)."""
    lx, ly = -math.sin(heading), math.cos(heading)  # his left
    out = {}
    for side, sign, out_by in (("l", 1.0, spread[0]), ("r", -1.0, spread[1])):
        sh = (x + sign * SHOULDER_SIDE_M * lx, y + sign * SHOULDER_SIDE_M * ly, SHOULDER_Z * height_m)
        sx, sy, sz = tip(sh, x, y, angle, way)
        reach = ARM_REACH * ARM_M * height_m
        hz = max(HAND_GRASS_M, sz - reach * drop)
        flat = math.sqrt(max(reach * reach - (sz - hz) ** 2, 0.0))
        # out to his own side of the way he falls: the left hand to the left of it
        across = (sh[0] - x) * -math.sin(way) + (sh[1] - y) * math.cos(way)
        d = way + (out_by if across >= 0 else -out_by)
        hand = (sx + flat * math.cos(d), sy + flat * math.sin(d), hz)
        out[side] = [round(v, 4) for v in tip(hand, x, y, -angle, way)]
    return out


def fall_at(gait, mine: list[dict], player: dict, i: int, fps: int, height_m: float) -> None:
    """The fall this frame on the gait: the engine's spell, drawn (drawn_spell), and the arms out
    (gait.brace). Standing when the engine has him standing; x and y are never moved."""
    angle, way = drawn_fall(player)
    gait.brace = gait.crouch = None
    gait.tip_ahead = 0.0
    plan = next((p for p in mine if p["i0"] <= i <= p["i1"]), None) if angle else None
    if plan is None:
        gait.fall, gait.fall_dir = angle, way
        return
    angle, drawn_way, arms, crouch = drawn_spell(plan, i, player["fall"], fps)
    way = way if drawn_way is None else drawn_way
    gait.fall, gait.fall_dir = angle, way
    if crouch > 0.0:
        gait.crouch = {"w": round(crouch, 4), "lead": plan["lead"]}
        gait.lift = crouch_lift(crouch, plan["lead"], height_m)
    if arms > 0.0 and plan.get("drawn"):
        drop = 1.0 if i >= plan["i_up"] else ARM_DROP  # getting up, he pushes on the grass
        gait.brace = {"w": round(arms, 4), **brace_targets(player["x"], player["y"], gait.heading, height_m,
                                                            angle, way, plan["spread"], drop)}


def tip(point: tuple[float, float, float], x: float, y: float, angle: float, direction: float,
        ahead: float = 0.0):
    """`point` (world metres) tipped over by `angle` about the ground under (x, y), toward `direction`:
    the whole body falls over its feet that way."""
    if not angle:
        return point
    ux, uy = math.cos(direction), math.sin(direction)
    x, y = x + ahead * ux, y + ahead * uy  # over the grass `ahead` metres the way he goes
    along = (point[0] - x) * ux + (point[1] - y) * uy  # ahead of the feet, the way he falls
    side = -(point[0] - x) * uy + (point[1] - y) * ux
    z = point[2]
    c, s = math.cos(angle), math.sin(angle)
    along, z = along * c + z * s, -along * s + z * c
    return (x + along * ux - side * uy, y + along * uy + side * ux, z)


def row(player: dict, angle: float, direction: float | None = None) -> dict:
    """The player's frame row with `fall`, the degrees his drawn body is over, and `fall_dir`, the
    way it is drawn going, while he is down; the row unchanged while he stands (render-check judges
    a lying body's box by it)."""
    if not angle:
        return player
    out = {**player, "fall": round(math.degrees(angle), 1)}
    if direction is not None:
        out["fall_dir"] = round(direction, 4)
    return out


# How the reactions are drawn (*design*, kept short: a beat a viewer reads, not a performance).
REACT_S = 2.0  # the hand stays up, the heads stay turned, this long after the foul frame
REACT_EASE_S = 0.3  # each comes up and goes down over this
LOOKERS = 3  # the fouled side's players nearest him who turn to him
LOOK_MAX = math.radians(70.0)  # as far as a head turns on the neck (*design*)
HAND_UP = 1.12  # the raised hand, as a share of his height: just above his head, within his reach
HAND_SIDE = 0.2  # metres to the side of his body (his right)


def reactions(frames: list[dict], events: list[dict]) -> dict[str, list[dict]]:
    """Per player, his reactions to fouls: {"kind": "signal" | "look", "frame" (the foul's frame index),
    "to" (for a look, who he turns to)}. From the engine's foul events and where everyone stands."""
    index = {fr.get("frame", i): i for i, fr in enumerate(frames)}
    out: dict[str, list[dict]] = {}
    for ev in events:
        i = index.get(ev.get("frame"))
        if ev.get("type") != "foul" or i is None or not ev.get("player"):
            continue
        out.setdefault(ev["player"], []).append({"kind": "signal", "frame": i})
        fouled = ev.get("receiver")
        pos = {p["id"]: p for p in frames[i]["players"]}
        him = pos.get(fouled)
        if him is None:
            continue
        mates = sorted((p for p in frames[i]["players"] if p["team"] == him["team"] and p["id"] != fouled),
                       key=lambda p: math.hypot(p["x"] - him["x"], p["y"] - him["y"]))
        for p in mates[:LOOKERS]:
            out.setdefault(p["id"], []).append({"kind": "look", "frame": i, "to": fouled})
    return out


def _weight(fi: int, start: int, fps: int) -> float:
    """0 before the foul frame, up over REACT_EASE_S, held, down over REACT_EASE_S by REACT_S."""
    u = (fi - start) / fps
    if u < 0 or u > REACT_S:
        return 0.0
    w = min(u / REACT_EASE_S, (REACT_S - u) / REACT_EASE_S, 1.0)
    return 0.5 - 0.5 * math.cos(math.pi * max(w, 0.0))  # eased


def signal_at(gait, mine: list[dict], fi: int, fps: int, x: float, y: float, height_m: float) -> None:
    """The fouler's hand up at frame `fi` (gait.signal), or None."""
    gait.signal = None
    w = max((_weight(fi, r["frame"], fps) for r in mine if r["kind"] == "signal"), default=0.0)
    if w <= 0.0:
        return
    h = gait.heading
    rx, ry = math.sin(h), -math.cos(h)  # his right
    gait.signal = {"side": "r", "at": [round(x + HAND_SIDE * rx, 4), round(y + HAND_SIDE * ry, 4),
                                       round(HAND_UP * height_m, 4)], "w": round(w, 4)}


def look_at(gait, mine: list[dict], fi: int, fps: int, x: float, y: float, frame: dict) -> None:
    """A team-mate's head turned to the fouled player at frame `fi` (gait.look), or None."""
    gait.look = None
    best = None
    for r in mine:
        if r["kind"] != "look":
            continue
        w = _weight(fi, r["frame"], fps)
        if w > 0.0 and (best is None or w > best[0]):
            best = (w, r["to"])
    if best is None:
        return
    him = next((p for p in frame["players"] if p["id"] == best[1]), None)
    if him is None:
        return
    want = math.atan2(him["y"] - y, him["x"] - x)
    yaw = (want - gait.heading + math.pi) % (2 * math.pi) - math.pi
    gait.look = {"yaw": round(max(-LOOK_MAX, min(LOOK_MAX, yaw)), 4), "w": round(best[0], 4)}


# On one knee (meshpose._upper's crouch, *design*): the lead leg's thigh forward and up, its foot
# planted, the other knee down with its shin behind. Thigh and calf angles in the asset's convention
# (a thigh forward is negative, a knee bent positive).
KNEEL_LEAD = (-1.5, 1.6)
KNEEL_BACK = (-0.2, 1.9)


def crouch_lift(w: float, lead: str, height_m: float) -> float:
    """Metres the body is lowered so the crouch's lead foot is on the grass (negative)."""
    from ninety.render.meshpose import _markers, asset, dict_angles, to_world

    def foot_z(c: float) -> float:
        a = dict_angles(asset()["poses"]["stand"])
        a = crouch_angles(a, c, lead)
        return to_world(0.0, 0.0, 0.0, height_m, _markers(a)[f"foot_{lead}"])[2]

    return -round(max(foot_z(w) - foot_z(0.0), 0.0), 4)


def crouch_angles(angles: dict, w: float, lead: str) -> dict:
    """`angles` with the legs `w` of the way into the kneel, `lead` the leg whose foot is planted."""
    back = "r" if lead == "l" else "l"
    out = dict(angles)
    for side, (th, ca) in ((lead, KNEEL_LEAD), (back, KNEEL_BACK)):
        t0, c0 = out.get(f"thigh_{side}", 0.0), out.get(f"calf_{side}", 0.0)
        t0 = t0 if isinstance(t0, float) else 0.0
        c0 = c0 if isinstance(c0, float) else 0.0
        out[f"thigh_{side}"] = t0 + (th - t0) * w
        out[f"calf_{side}"] = c0 + (ca - c0) * w
    return out
