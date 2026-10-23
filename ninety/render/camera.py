"""Pinhole broadcast camera and the director that points it.

World coordinates are pitch metres: x 0..105 along the pitch, y 0..68 from the near touchline,
z up. Camera coordinates follow OpenCV: x right, y down, z forward. Pixel coordinates have their
origin at the top-left corner of the image, so pixel (i, j) covers [i, i+1] x [j, j+1]; the
principal point is the image centre.
"""

from __future__ import annotations

import math
import random
from dataclasses import dataclass

from ninety.render.params import CameraParams

Vec = tuple[float, float, float]


def _sub(a: Vec, b: Vec) -> Vec:
    return (a[0] - b[0], a[1] - b[1], a[2] - b[2])


def _cross(a: Vec, b: Vec) -> Vec:
    return (a[1] * b[2] - a[2] * b[1], a[2] * b[0] - a[0] * b[2], a[0] * b[1] - a[1] * b[0])


def _norm(a: Vec) -> Vec:
    n = math.sqrt(a[0] ** 2 + a[1] ** 2 + a[2] ** 2)
    return (a[0] / n, a[1] / n, a[2] / n)


def _dot(a: Vec, b: Vec) -> float:
    return a[0] * b[0] + a[1] * b[1] + a[2] * b[2]


@dataclass(frozen=True)
class Camera:
    position: Vec
    target: Vec
    fov_v_deg: float
    width: int
    height: int

    @property
    def focal_px(self) -> float:
        return (self.height / 2) / math.tan(math.radians(self.fov_v_deg) / 2)

    @property
    def K(self) -> list[list[float]]:
        f = self.focal_px
        return [[f, 0.0, self.width / 2], [0.0, f, self.height / 2], [0.0, 0.0, 1.0]]

    @property
    def R(self) -> list[list[float]]:
        """World-to-camera rotation; rows are the camera's right, down and forward axes."""
        fwd = _norm(_sub(self.target, self.position))
        right = _norm(_cross(fwd, (0.0, 0.0, 1.0)))
        down = _cross(fwd, right)
        return [list(right), list(down), list(fwd)]

    @property
    def t(self) -> list[float]:
        return [-_dot(tuple(row), self.position) for row in self.R]  # type: ignore[arg-type]

    @property
    def P(self) -> list[list[float]]:
        """3x4 projection matrix K [R | t]."""
        K, R, t = self.K, self.R, self.t
        Rt = [R[i] + [t[i]] for i in range(3)]
        return [[sum(K[i][k] * Rt[k][j] for k in range(3)) for j in range(4)] for i in range(3)]

    def to_camera(self, X: Vec) -> Vec:
        R, t = self.R, self.t
        return tuple(_dot(tuple(R[i]), X) + t[i] for i in range(3))  # type: ignore[return-value]

    def project(self, X: Vec) -> tuple[float, float] | None:
        """Pixel position of a world point, or None if it is behind the camera."""
        c = self.to_camera(X)
        if c[2] <= 1e-6:
            return None
        f = self.focal_px
        return (f * c[0] / c[2] + self.width / 2, f * c[1] / c[2] + self.height / 2)

    def depth(self, X: Vec) -> float:
        return self.to_camera(X)[2]

    def to_dict(self) -> dict:
        r = lambda m: [[round(v, 6) for v in row] for row in m]  # noqa: E731
        return {
            "width": self.width,
            "height": self.height,
            "fov_v_deg": round(self.fov_v_deg, 6),
            "position": [round(v, 4) for v in self.position],
            "K": r(self.K),
            "R": r(self.R),
            "t": [round(v, 6) for v in self.t],
            "P": r(self.P),
        }


def project_with(P: list[list[float]], X: Vec) -> tuple[float, float] | None:
    """Project with a saved 3x4 matrix, the way any consumer of frames.jsonl would."""
    h = [P[i][0] * X[0] + P[i][1] * X[1] + P[i][2] * X[2] + P[i][3] for i in range(3)]
    if h[2] <= 1e-9:
        return None
    return (h[0] / h[2], h[1] / h[2])


MAX_PAN_MPS = 22.0  # fastest the aim point moves across the ground
# An operator eases a pan in and out instead of starting and stopping it dead (design, after the
# critic's review of 0.5.0: pans went from still to full speed in one frame). The aim point gathers
# speed at most this fast, so a full-speed pan takes about half a second to build up.
PAN_ACCEL_MPS2 = 40.0


def in_box(x: float, y: float, margin: float = 0.0) -> bool:
    """True when (x, y) is inside either penalty area, widened by `margin` metres."""
    return 13.84 - margin <= y <= 54.16 + margin and (x <= 16.5 + margin or x >= 88.5 - margin)


CUT_HOLD_S = 4.0  # a cut stays put this long; shorter than this reads as a flicker
GANTRY_LINE_DEG = 23.0  # handbook: 22-24° from the gantry down to the near touchline
# The widest the gantry goes in open play, against the sampled 17 to 24 m: aimed at the play on the
# grass, the pitch fills the picture and 8 to 15 players are in shot (docs/guides/broadcast-render.md),
# each about 65 px tall. Design: 18 m against 14.5 to 22 m on seeds 7, 21 and 42; test_render_camera
# measures other seeds.
GANTRY_HALF_M = 18.0
# The stands are a band across the top of the picture, at most this share of it. The far side is
# foreshortened, so with play over there the gantry tilts down along its line of sight just enough
# to keep the far edge of the pitch at this line; nearer, it frames the play and the stands are
# what is left above it (design, after the review of 0.4.1: the stands filled 40 to 75% of the
# picture; at 0.25 the line held still and left a third of the picture empty grass below play).
STANDS_MAX = 0.35
# The operator frames the play, not the ball: the aim is pulled from the ball toward the players
# around it (weighted by nearness, out to PLAY_RADIUS_M), PLAY_PULL of the way, and the gantry
# holds still while that stays within HOLD_SHARE of the half-width either side of where it points,
# so a pass inside one area is not a pan (design, after the critic of 0.5.1's first clips: the
# camera was locked to the ball and swung with every pass).
PLAY_RADIUS_M = 20.0
PLAY_PULL = 0.35
HOLD_SHARE = 0.3
# The box's closer lens comes in when the ball is in a penalty area and goes back out only once the
# ball is this far clear of it; the zoom eases like a pan (ZOOM_ACCEL_MPS2: metres of half-width a
# second, a second), so the lens never pumps in and out or reverses in a frame.
BOX_LEAVE_M = 6.0
ZOOM_ACCEL_MPS2 = 6.0
# Live play stays on the gantry through every attack; the tighter lens comes up for a throw-in: a
# medium shot, the taker about a third of the picture high (TIGHT_HALF_M either side of him).
TIGHT_ACTIONS = ("throw",)
TIGHT_HALF_M = 5.0
# After a goal the gantry shows the goal itself this long, then a second camera beside it follows
# the scorer's celebration, a medium shot SCORER_HALF_M either side of him, until the edit cuts to
# the kick-off (design, after demo v1's critic: a fixed low shot beside the net showed the keeper
# and never the scorer). Used when the render says who scored; otherwise the low angle at the net.
GOAL_WIDE_S = 2.0
SCORER_HALF_M = 6.0
# A corner (Law 17): the ball is placed inside the corner arc, 1 m in radius (Law 1). design: while it
# waits, the main camera frames it from the taker inward, the taker near the side of the picture and
# the penalty area filling the rest, so the viewer sees where the ball will go rather than the run-off
# beyond the flag (no source found: a design choice, lesson 177).
CORNER_ARC_M = 1.0
BALL_RADIUS_M = 0.11  # Law 2: a circumference of 68 to 70 cm
# design: the taker kept a tenth of the picture in from each edge, so his run-up and the ball's first
# metres are in shot as well as the ball (set before the corner rule was measured).
CORNER_TAKER_MARGIN = 0.1
NET_SETTLE_S = 2.6  # the mesh is back to rest by here; the angle itself holds CUT_HOLD_S


# How a broadcast frames live play (design, after the Coordinator's review of 0.4.1 and broadcast
# practice): the main camera keeps the play near the middle of the picture with the pitch filling
# most of it, the stands a band across the top. A frame is well framed when the pitch (Law 1) covers
# at least PITCH_SHARE_MIN of the picture and the ball is inside the CENTRAL box (shares of width
# and height: left, right, top, bottom).
PITCH_SHARE_MIN = 0.60
CENTRAL = (0.2, 0.8, 0.15, 0.85)
PITCH_MARGIN = 0.05  # the director keeps the pitch this much over PITCH_SHARE_MIN, for the zoom's lag
#                      (design)
CENTRE_MARGIN = 0.05  # the director aims the ball this far inside the box, so the pan's lag has room (design)


def pitch_share(cam: Camera, step: int = 40) -> float:
    """The share of the picture that is the pitch (105 by 68 m on the ground), from a grid of rays
    through the picture, `step` pixels apart, to the ground."""
    right, down, fwd = cam.R
    f = cam.focal_px
    hit = total = 0
    for v in range(step // 2, cam.height, step):
        for u in range(step // 2, cam.width, step):
            a, b = (u - cam.width / 2) / f, (v - cam.height / 2) / f
            d = [fwd[i] + a * right[i] + b * down[i] for i in range(3)]
            total += 1
            if d[2] >= -1e-9:
                continue  # above the horizon
            s = -cam.position[2] / d[2]
            x, y = cam.position[0] + s * d[0], cam.position[1] + s * d[1]
            hit += 0.0 <= x <= 105.0 and 0.0 <= y <= 68.0
    return hit / total


def well_framed(cam: Camera, ball: Vec) -> bool:
    """The pitch fills at least PITCH_SHARE_MIN of the picture and the ball is in its CENTRAL box."""
    uv = cam.project(ball)
    if uv is None:
        return False
    left, right, top, bottom = CENTRAL
    across = left * cam.width <= uv[0] <= right * cam.width
    down = top * cam.height <= uv[1] <= bottom * cam.height
    return across and down and pitch_share(cam) >= PITCH_SHARE_MIN


def gantry_height(back_m: float, sampled: float) -> float:
    """Height that looks down at the near touchline at 23°. A sample already inside 22-24°
    is kept. The draw itself is not moved, so a seed's stored height stays where it was."""
    if back_m <= 0:
        return sampled
    angle = math.degrees(math.atan2(sampled, back_m))
    if 22.0 <= angle <= 24.0:
        return sampled
    return back_m * math.tan(math.radians(GANTRY_LINE_DEG))


def net_push(age: float, speed: float, y: float, z: float, hit_y: float, hit_z: float) -> float:
    """How far one point of the net gives, in metres, straight out behind the goal line.

    The hit arrives first and the cloth further away follows. The result stays outward.
    `web/render/render.js` applies this same curve. Decor only: it never moves the ball."""
    if age < 0.0 or age > NET_SETTLE_S:
        return 0.0
    dist = math.hypot(y - hit_y, z - hit_z)
    delay = 0.035 * dist
    if age < delay:
        return 0.0
    amp = min(0.85, 0.2 + min(speed, 28.0) * 0.02)
    fall = math.exp(-(dist * dist) / 1.6)
    env = math.exp(-(age - delay) * 2.4)
    ring = 0.7 + 0.3 * (0.5 + 0.5 * math.cos(age * 15.0))
    return amp * fall * env * ring


class Director:
    """Main broadcast camera: fixed gantry position, pans and zooms to follow the ball with lag.

    The gantry is the picture the match is watched from. It aims at the play on the grass, so the
    pitch fills the picture; tilts down along its line of sight when play is far off, so the stands
    stay a band across the top (STANDS_MAX); frames the play rather than the ball and holds still
    while the ball moves about inside that frame (HOLD_SHARE); takes a closer lens in either box;
    and eases each pan and zoom in and out (PAN_ACCEL_MPS2, ZOOM_ACCEL_MPS2).

    With `cuts`, it leaves the gantry for two shots, each held at least CUT_HOLD_S: a tighter lens
    beside the gantry for a throw-in, when that shot still holds the thrower and the ball, and,
    when a goal is scored, a low three-quarter beside that goal, aimed at the mouth the
    event recorded, because the engine has already put the ball back on the centre spot. Live play
    is never shown from across the pitch or from behind a goal: every camera it uses stands on the
    gantry's side, so left and right stay where the viewer has them (the 180-degree rule, as a
    broadcast keeps them; SoccerNet-v2 counts one change of shot every 9 s, replays included).
    The gantry aim keeps updating during a cut, so the return is where it would have been.
    """

    def __init__(
        self, params: CameraParams, width: int, height: int, fps: int, seed: int, cuts: bool = False
    ):
        self.p = params
        self.width, self.height, self.dt = width, height, 1.0 / fps
        self.position: Vec = (
            52.5 + params.offset_x_m,
            -params.back_m,
            gantry_height(params.back_m, params.height_m),
        )
        self.players: list[tuple[float, float, str]] = []
        self.rng = random.Random(f"camera-{seed}")
        self.aim: list[float] | None = None
        self.aim_v = [0.0, 0.0]  # how fast the aim point is moving across the ground (m/s)
        self.tight_aim: list[float] | None = None  # the tighter lens's own aim, while it is up
        self.tight_v = [0.0, 0.0]
        self.zoom_v = 0.0  # how fast the half-width is changing (m/s)
        self._box = False  # the box's closer lens is in (BOX_LEAVE_M)
        self._scorer: tuple[float, float] | None = None  # who scored, while he celebrates (step)
        self._celebrate_from: float | None = None  # when the second camera picks him up
        self.scorer_aim: list[float] | None = None
        self.scorer_v = [0.0, 0.0]
        self._ease_end = -1.0  # the ease out of it ends here, at the wide shot
        self._corner_flag: tuple[float, float] | None = None  # the corner waiting to be taken
        self.half_width = params.half_width_m
        self.prev_ball: tuple[float, float] | None = None
        self.shake_phase = (self.rng.uniform(0, 6.28), self.rng.uniform(0, 6.28))
        self.t = 0.0
        self.cuts = cuts
        self.angle = "main"
        self._cut_until = -1.0
        self._edit_hold_until = -1.0  # the restart's wide shot after an edit cut holds until here
        self._cut_kind = ""  # "", "netL", "netR" or "tight". Empty is the gantry.
        self.net: dict | None = None  # the goal the mesh and the low angle are still showing

    def cut(self) -> None:
        """The edit cuts away from a dead ball to its restart (edit.py): no pan, second angle or goal
        net is carried across the cut, and the camera frames the ball afresh where it is then."""
        self.aim = None
        self.aim_v = [0.0, 0.0]
        self.tight_aim = None
        self.zoom_v = 0.0
        self._box = False
        self.prev_ball = None
        self._scorer = None
        self._celebrate_from = None
        self.scorer_aim = None
        self._cut_kind = ""
        self._cut_until = -1.0
        self.net = None
        self._corner_flag = None

    def open_on_restart(self) -> None:
        """The first frame after a cut: the picture comes back on the gantry's own wide shot of the
        restart, framed afresh where the ball is set, and holds it CUT_HOLD_S with no second angle,
        so the edit reads as one cut into the play. The edit brings it back as the restart is
        imminent (edit.SHOW_BEFORE_RESTART_S), so nobody stands still on screen for long.
        Old (0.5.2 to 0.5.9): it came back closed up on the taker alone for CUT_HOLD_S, then pulled
        out (demo v1's critic, #4 and #15)."""
        self._cut_kind = ""
        self._cut_until = self.t + self.dt + CUT_HOLD_S  # from the restart's first frame
        self._edit_hold_until = self._cut_until
        self.aim = None
        self.zoom_v = 0.0

    def _goal(self, bx: float, by: float, vx: float, vy: float) -> tuple[float, float, float]:
        self._goal_z = 0.0
        corner = self._corner(bx, by)
        if corner is not None:
            return corner
        px, py = self._play(bx, by)
        ax = px + vx * self.p.lead_s
        ay = py + vy * self.p.lead_s
        ay = 34 + (ay - 34) * 0.75  # broadcasters rarely aim right at a touchline
        # Broadcasters rarely aim at a goal line or a touchline, but never short of the ball: when
        # the ball is past these the aim follows it to the line (lesson 175).
        ax = min(max(ax, min(8.0, bx)), max(97.0, bx))
        ay = min(max(ay, min(12.0, by)), max(60.0, by))
        if in_box(bx, by):
            self._box = True
        elif not in_box(bx, by, BOX_LEAVE_M):
            self._box = False
        hw = self.p.box_half_width_m if self._box else min(self.p.half_width_m, GANTRY_HALF_M)
        if self.aim is not None:
            # Held while the play stays near where the gantry points; past that, the play is kept at
            # the edge of the hold as the pan takes it along.
            zone = HOLD_SHARE * hw
            ax = min(max(self.aim[0], ax - zone), ax + zone)
        ax, ay = self._below_stands(ax, ay, hw)
        # The ball in the centre and the pitch filling the picture, solved together: closing in moves
        # the ball across the picture, so they alternate, and the ball has the last word where both
        # cannot hold (a ball on a corner flag): it is never lost to the pitch (lesson 175).
        on_pitch = 0.0 <= bx <= 105.0 and 0.0 <= by <= 68.0  # a ball over a line is play stopped
        wide = self._ball_in_centre(bx, by, vx, vy, ax, ay, hw)
        want = PITCH_SHARE_MIN + PITCH_MARGIN
        if on_pitch and pitch_share(self._shot((*wide, 0.0), hw), step=80) < want:
            cx, cy, chw = ax, ay, hw
            for _ in range(4):  # closing in moves the ball across the picture: settles in 3 or 4
                cx, cy = self._ball_in_centre(bx, by, vx, vy, cx, cy, chw)
                chw = self._pitch_fills(cx, cy, chw)
            cx, cy = self._ball_in_centre(bx, by, vx, vy, cx, cy, chw)
            # Closed in only if that does fill the picture with pitch, the ball in the middle; where
            # no shot does (a ball on a corner flag) the wide shot stays.
            if pitch_share(self._shot((cx, cy, 0.0), chw), step=80) >= PITCH_SHARE_MIN:
                wide, hw = (cx, cy), chw
        ax, ay = wide
        self._goal_z = self._lofted(bx, by, ax, ay, hw)
        return ax, ay, hw

    def _corner(self, bx: float, by: float) -> tuple[float, float, float] | None:
        """The corner framing, while a corner is awarded and waiting to be taken (`step`'s
        `corner`, from the engine's set piece at a flag to the kick: corner_waits). After the kick
        the director frames the play as for any ball (the Reviewer of #201: a hold past the kick
        framed the delivery worse). None when no corner waits."""
        if self._corner_flag is None:
            return None
        fx, fy = self._corner_flag
        cache = self.__dict__.setdefault("_corner_shots", {})  # each corner's own shot
        if (fx, fy) not in cache:
            cache[(fx, fy)] = self._corner_shot(fx, fy)
        best = cache[(fx, fy)]
        if best is None:
            return None
        # The ball waits inside the arc, a metre from the flag, which the shot keeps CORNER_TAKER_MARGIN
        # in from the picture's edges; after the kick the director frames the play as for any ball.
        return best

    def _corner_shot(self, fx: float, fy: float) -> tuple[float, float, float] | None:
        """The shot of a corner from the flag at (fx, fy): of the aims over that corner's quarter of
        the pitch and the lenses from TIGHT_HALF_M to the gantry's own width, the one with the most
        pitch in the picture that keeps the taker (the flag) in the picture, CORNER_TAKER_MARGIN in
        from its edges, and the penalty mark, where the corner is played to, in it too (Law 1, 17).
        A near corner puts the taker at the side of the picture, as a broadcast does: centring him
        would fill the picture with the run-off beside the flag."""
        spot = (11.0 if fx == 0.0 else 94.0, 34.0)
        wide = min(self.p.half_width_m, GANTRY_HALF_M)
        best = None
        for i in range(8):
            x = fx + (spot[0] - fx) * i / 7
            for j in range(12):
                y = fy + (34.0 - fy) * j / 11
                for hw in (TIGHT_HALF_M, 7.0, 9.0, 11.0, 13.0, 15.0, wide):
                    shot = self._shot((x, y, 0.0), hw)
                    flag, mark = shot.project((fx, fy, BALL_RADIUS_M)), shot.project((*spot, 0.0))
                    if flag is None or mark is None:
                        continue
                    m = CORNER_TAKER_MARGIN
                    taker = (m * self.width <= flag[0] <= (1 - m) * self.width
                             and m * self.height <= flag[1] <= (1 - m) * self.height)
                    if taker and 0 <= mark[0] <= self.width and 0 <= mark[1] <= self.height:
                        share = pitch_share(shot, step=80)
                        if best is None or share > best[0]:
                            best = (share, x, y, hw)
        return None if best is None else best[1:]

    def _lofted(self, bx: float, by: float, ax: float, ay: float, hw: float) -> float:
        """How high to aim for a lofted ball: the least height, up to the ball's own, that keeps it
        inside the CENTRAL box (an operator tilts up with a high ball rather than letting it leave
        the top of the picture; lesson 175). Zero for a ball on or near the grass."""
        bz = getattr(self, "ball_z", 0.0)
        if bz < 1.0:
            return 0.0
        left, right, top, bottom = CENTRAL
        m = CENTRE_MARGIN
        ball = (bx, by, bz + 0.11)

        def inside(z: float) -> bool:
            uv = self._shot((ax, ay, z), hw).project(ball)
            return uv is not None and (top + m) * self.height <= uv[1] <= (bottom - m) * self.height

        if inside(0.0):
            return 0.0
        lo, hi = 0.0, bz
        if not inside(hi):
            return hi
        for _ in range(12):
            mid = (lo + hi) / 2
            if inside(mid):
                hi = mid
            else:
                lo = mid
        return hi

    def _pitch_fills(self, ax: float, ay: float, hw: float) -> float:
        """The half-width, closed in only as far as keeps the pitch over PITCH_SHARE_MIN of the
        picture (plus PITCH_MARGIN), never tighter than TIGHT_HALF_M, and only where closing in does
        fill it. Aimed into a corner, a wide shot is mostly run-off and stands; the operator closes
        in on the play there (lesson 175)."""
        want = PITCH_SHARE_MIN + PITCH_MARGIN
        if pitch_share(self._shot((ax, ay, 0.0), hw), step=80) >= want:
            return hw
        lo, hi = TIGHT_HALF_M, hw
        if pitch_share(self._shot((ax, ay, 0.0), lo), step=80) < want:
            # No lens fills the picture with pitch here (a ball on a corner flag): closing in would
            # only show more run-off, so the shot stays as it was (the blind critic of 0.5.5's
            # first cut: a 5-degree close-up held 18 s on a corner, then a whip pan at the kick).
            return hw
        for _ in range(8):
            mid = (lo + hi) / 2
            if pitch_share(self._shot((ax, ay, 0.0), mid), step=80) >= want:
                lo = mid
            else:
                hi = mid
        return lo

    def _play(self, bx: float, by: float) -> tuple[float, float]:
        """Where the play is: the ball, pulled PLAY_PULL of the way toward the players around it,
        each weighted by how near he is, to nothing at PLAY_RADIUS_M."""
        sw = sx = sy = 0.0
        for x, y, _ in self.players:
            w = 1.0 - math.hypot(x - bx, y - by) / PLAY_RADIUS_M
            if w > 0.0:
                sw, sx, sy = sw + w, sx + w * x, sy + w * y
        if sw <= 0.0:
            return bx, by
        return bx + PLAY_PULL * (sx / sw - bx), by + PLAY_PULL * (sy / sw - by)

    def _ball_in_centre(self, bx: float, by: float, vx: float, vy: float, ax: float, ay: float,
                        hw: float) -> tuple[float, float]:
        """The aim, moved toward the ball only as far as keeps the ball inside the CENTRAL box of the
        picture (well_framed's box, shrunk by CENTRE_MARGIN). The pulls, leads, clamps and holds above
        place the play; none of them may leave the ball itself at the edge or out of the picture
        (lesson 175). The main camera follows the ball to the byline (*design*). The ball where it
        will be when the pan has caught up (pan_lag_s ahead, inside the pitch) must fit as well, so a
        ball running to a line is not left behind by the pan's own lag."""
        left, right, top, bottom = CENTRAL
        m = CENTRE_MARGIN
        lag = self.p.pan_lag_s
        z = getattr(self, "ball_z", 0.0) + 0.11
        balls = [(bx, by, z),
                 (min(max(bx + vx * lag, 0.0), 105.0), min(max(by + vy * lag, 0.0), 68.0), z)]

        def inside(t: float) -> bool:
            shot = self._shot((ax + t * (bx - ax), ay + t * (by - ay), 0.0), hw)
            for ball in balls:
                uv = shot.project(ball)
                if not (uv is not None and (left + m) * self.width <= uv[0] <= (right - m) * self.width
                        and (top + m) * self.height <= uv[1] <= (bottom - m) * self.height):
                    return False
            return True

        if inside(0.0):
            return ax, ay
        if not inside(1.0):
            # The ball and where it will be a lag on are too far apart for one shot (a long ball).
            # The aim trails a target moving at the ball's pace by that lag (_ease), so aiming at
            # the ball itself leaves the picture a lag behind it and the ball runs out of shot.
            # Aimed where the ball will be, the trailing aim is on the ball (lesson 205).
            return balls[1][0], balls[1][1]
        lo, hi = 0.0, 1.0  # at t = 1 the ball is at the centre of the picture
        for _ in range(14):
            mid = (lo + hi) / 2
            if inside(mid):
                hi = mid
            else:
                lo = mid
        return ax + hi * (bx - ax), ay + hi * (by - ay)

    def _below_stands(self, ax: float, ay: float, hw: float) -> tuple[float, float]:
        """The aim on the line of sight to (ax, ay), there or nearer the gantry, that keeps the far
        edge of the pitch on that line (the far touchline, or a goal line) in the top STANDS_MAX of
        the picture. Tilting down lifts that edge in the picture and leaves the play where it is
        across it, so the nearest aim that does it is found by halving along the line."""
        gx, gy = self.position[0], self.position[1]
        dx, dy = ax - gx, ay - gy
        if dy <= 0.0:
            return ax, ay
        out = (68.0 - gy) / dy
        if abs(dx) > 1e-9:
            out = min(out, ((105.0 if dx > 0 else 0.0) - gx) / dx)
        edge = (gx + out * dx, gy + out * dy, 0.0)
        line = STANDS_MAX * self.height

        def lifted(t: float) -> bool:
            uv = self._shot((gx + t * dx, gy + t * dy, 0.0), hw).project(edge)
            return uv is None or uv[1] <= line

        if lifted(1.0):
            return ax, ay
        lo, hi = -gy / dy, 1.0  # from the near touchline to the play
        for _ in range(14):
            mid = (lo + hi) / 2
            if lifted(mid):
                lo = mid
            else:
                hi = mid
        return gx + lo * dx, gy + lo * dy

    def step(
        self,
        ball_x: float,
        ball_y: float,
        players: list | None = None,
        goal: tuple | None = None,
        cut_in: float | None = None,
        ball_z: float = 0.0,
        corner: tuple[float, float] | None = None,
        scorer: tuple[float, float] | None = None,
    ) -> Camera:
        """The camera for the next frame. `cut_in` is how long until the edit's next cut, in seconds
        (None when no cut follows): no angle starts or ends that close to one, because the cut is
        itself the change of shot. `ball_z` is the ball's height, so a lofted ball is kept in the
        picture too (lesson 175). `scorer` is where the player who scored is, from the goal until
        the restart (the render passes it): the camera follows his celebration (GOAL_WIDE_S)."""
        self.ball_z = ball_z
        self._corner_flag = corner
        self.players = [(p[0], p[1], p[2]) for p in players] if players else []
        if self.prev_ball is None:
            vx = vy = 0.0
        else:
            vx = (ball_x - self.prev_ball[0]) / self.dt
            vy = (ball_y - self.prev_ball[1]) / self.dt
        self.prev_ball = (ball_x, ball_y)
        gx, gy, ghw = self._goal(ball_x, ball_y, vx, vy)
        if self.aim is None:
            self.aim = [gx, gy]
            self.aim_v = [0.0, 0.0]
            self.aim_z, self.aim_zv = [self._goal_z, 0.0], [0.0, 0.0]
            self.half_width = ghw
        else:
            self._ease(self.aim, self.aim_v, gx, gy)
            self._ease(self.aim_z, self.aim_zv, self._goal_z, 0.0)  # the tilt eases like the pan
            # The zoom is a spring too, slower than the pan, so it gathers and loses pace and never
            # turns round in a frame.
            w = 2.0 / (self.p.pan_lag_s * 2.5)
            acc = w * w * (ghw - self.half_width) - 2 * w * self.zoom_v
            acc = min(max(acc, -ZOOM_ACCEL_MPS2), ZOOM_ACCEL_MPS2)
            self.zoom_v += acc * self.dt
            self.half_width += self.zoom_v * self.dt
        self.t += self.dt
        fresh_goal = False
        if goal:
            side, y, z, speed = goal
            self.net = {
                "side": side,
                "y": float(y),
                "z": float(z),
                "speed": float(speed),
                "t0": self.t,
            }
            fresh_goal = True
            if scorer is not None:
                self._celebrate_from = self.t + GOAL_WIDE_S
        if scorer is None:  # the restart: the celebration is over
            self._celebrate_from = None
        self._scorer = scorer if self._celebrate_from is not None else None
        sx = self.p.shake_m * math.sin(2 * math.pi * 1.3 * self.t + self.shake_phase[0])
        sy = self.p.shake_m * math.sin(2 * math.pi * 0.9 * self.t + self.shake_phase[1])
        target = (self.aim[0] + sx, self.aim[1] + sy, self.aim_z[0])
        self.angle = "main"
        want = self._better(ball_x, ball_y) if self.cuts else ""
        # The hold covers every angle, including the return to the gantry, so an action on the
        # edge of the rule cannot bounce the camera back and forth. A goal starts the low angle at
        # once, even over a hold, except the hold after an edit cut: that cut was itself a change of
        # shot, so a goal soon after the restart is seen on the gantry and the low angle comes up
        # once the hold ends, while the goal is still fresh (_net_due; lesson 205). Near the edit's
        # next cut nothing changes: the cut is the change.
        steady = cut_in is not None and cut_in < CUT_HOLD_S
        due = self.t >= self._cut_until - 1e-9 and want != self._cut_kind and not steady
        after_edit = self.t < self._edit_hold_until - 1e-9
        if (fresh_goal and self.cuts and self._scorer is None and not after_edit) or due:
            self._cut_kind = want
            self._cut_until = self.t + CUT_HOLD_S
        if self._cut_kind == "scorer":
            spot = self._scorer or (ball_x, ball_y)  # held until the next shot, if he is gone
            if self.scorer_aim is None:
                self.scorer_aim, self.scorer_v = list(spot), [0.0, 0.0]
            else:
                self._ease(self.scorer_aim, self.scorer_v, *spot)
        else:
            self.scorer_aim = None
        if self._cut_kind != "tight":
            self.tight_aim = None
        else:
            # The tighter lens has its own operator: framed on the ball when the shot comes up,
            # then following it, eased the same way.
            spot = (min(max(ball_x, 0.0), 105.0), min(max(ball_y, -1.0), 69.0))
            if self.tight_aim is None:
                self.tight_aim, self.tight_v = list(spot), [0.0, 0.0]
            else:
                self._ease(self.tight_aim, self.tight_v, *spot)
        if self._cut_kind:
            return self._second()
        return self._main(target)

    def _ease(self, aim: list[float], vel: list[float], gx: float, gy: float) -> None:
        """Move an aim point toward (gx, gy) like a critically damped spring, gathering and losing
        speed no faster than PAN_ACCEL_MPS2, never faster than MAX_PAN_MPS. Its stiffness, 2 over
        the sampled lag, trails a ball at a steady pace by as much as a plain lag of that time did,
        so the play stays as central as before while each pan eases in and out."""
        w = 2.0 / self.p.pan_lag_s
        ax = w * w * (gx - aim[0]) - 2 * w * vel[0]
        ay = w * w * (gy - aim[1]) - 2 * w * vel[1]
        acc = math.hypot(ax, ay)
        if acc > PAN_ACCEL_MPS2:
            ax, ay = ax * PAN_ACCEL_MPS2 / acc, ay * PAN_ACCEL_MPS2 / acc
        ux, uy = vel[0] + ax * self.dt, vel[1] + ay * self.dt
        speed = math.hypot(ux, uy)
        if speed > MAX_PAN_MPS:  # an operator cannot whip the camera across the pitch
            ux, uy = ux * MAX_PAN_MPS / speed, uy * MAX_PAN_MPS / speed
        vel[0], vel[1] = ux, uy
        aim[0] += ux * self.dt
        aim[1] += uy * self.dt

    def net_view(self) -> dict | None:
        """The hit the mesh is still showing, or None once the cloth has settled."""
        if not self.net:
            return None
        age = self.t - self.net["t0"]
        if age < 0.0 or age > NET_SETTLE_S:
            return None
        return {
            "side": 0 if self.net["side"] == "L" else 1,
            "y": round(self.net["y"], 3),
            "z": round(self.net["z"], 3),
            "speed": round(self.net["speed"], 3),
            "age": round(age, 3),
        }

    def _net_due(self) -> bool:
        return self.net is not None and self.t < self.net["t0"] + CUT_HOLD_S

    def _net_pos(self, side: str) -> Vec:
        left = side == "L"
        line = 0.0 if left else 105.0
        outward = -1.0 if left else 1.0
        # Far enough back that the whole goal reads, and off the near post so the
        # pocket is a three-quarter rather than a flat wall. On the gantry's side of the goal.
        return (line + outward * 7.6, 22.0, 3.6)

    def _better(self, bx: float, by: float) -> str:
        """The angle that frames this moment better than the gantry, or '' to stay on the gantry."""
        if self._scorer is not None:  # the goal on the gantry, then the scorer's celebration
            return "scorer" if self.t >= self._celebrate_from - 1e-9 else ""
        if self._net_due():
            return "net" + self.net["side"]
        if self._tight(bx, by):
            return "tight"
        return ""

    def _main(self, target: Vec) -> Camera:
        return self._shot(target, self.half_width)

    def _shot(self, target: Vec, half_width: float) -> Camera:
        """The gantry aimed at `target`, `half_width` metres of ground either side of it."""
        dist = math.dist(self.position, target)
        hfov = 2 * math.atan(half_width / dist)
        vfov = 2 * math.atan(math.tan(hfov / 2) * self.height / self.width)
        return Camera(self.position, target, math.degrees(vfov), self.width, self.height)

    def _framed(self, position: Vec, target: Vec, half_width: float) -> Camera:
        dist = max(math.dist(position, target), 1.0)
        hfov = 2 * math.atan(half_width / dist)
        vfov = 2 * math.atan(math.tan(hfov / 2) * self.height / self.width)
        # A cut stays a broadcast lens (a box lens zooms to about 1 degree across). Clamping does not
        # move the aim point, so the ball stays centred.
        vfov = min(max(vfov, math.radians(2.0)), math.radians(32.0))
        return Camera(position, target, math.degrees(vfov), self.width, self.height)

    def _tight_pos(self) -> Vec:
        # Beside the gantry, same side and height. Far enough that the jump is a cut.
        return (self.position[0] + 8.0, self.position[1], self.position[2])

    def _tight(self, bx: float, by: float) -> bool:
        """A throw or an aerial touch, when a tighter lens beside the gantry still holds both."""
        actor = None
        best = 3.0
        for px, py, action in self.players:
            if action not in TIGHT_ACTIONS:
                continue
            dist = math.hypot(px - bx, py - by)
            if dist < best:
                best, actor = dist, (px, py)
        if actor is None:
            return False
        shot = self._framed(self._tight_pos(), (bx, by, 0.5), TIGHT_HALF_M)
        ball = shot.project((bx, by, 0.3))
        feet = shot.project((actor[0], actor[1], 0.0))
        head = shot.project((actor[0], actor[1], 1.7))
        if ball is None or feet is None or head is None:
            return False
        pad = 36

        def inside(uv: tuple[float, float]) -> bool:
            return pad <= uv[0] < self.width - pad and pad <= uv[1] < self.height - pad

        return inside(ball) and inside(feet) and 0 <= head[1] < self.height

    def _net_shot(self) -> Camera:
        """Low, off the near post, aimed at the mouth the goal went in by."""
        side = "L" if self._cut_kind == "netL" else "R"
        line = 0.0 if side == "L" else 105.0
        outward = -1.0 if side == "L" else 1.0
        y = min(max(self.net["y"], 31.0), 37.0)
        z = min(max(self.net["z"], 0.4), 2.1)
        return self._framed(self._net_pos(side), (line + outward * 1.0, y, z), 7.0)

    def _second(self) -> Camera:
        if self._cut_kind in ("netL", "netR"):
            self.angle = "net"
            return self._net_shot()
        if self._cut_kind == "scorer":
            self.angle = "scorer"
            aim = (self.scorer_aim[0], self.scorer_aim[1], 1.0)
            return self._framed(self._tight_pos(), aim, SCORER_HALF_M)
        self.angle = "tight"
        return self._framed(self._tight_pos(), (self.tight_aim[0], self.tight_aim[1], 0.8), TIGHT_HALF_M)


def blur_vector(prev: Camera | None, cur: Camera, shutter: float) -> tuple[float, float]:
    """Image-space motion of the scene during the exposure, from the camera pan and zoom.

    The world point at the image centre now is projected through last frame's camera; the
    displacement over one frame interval, times the shutter fraction, is the blur streak.
    """
    if prev is None or shutter <= 0:
        return (0.0, 0.0)
    # A cut changes the gantry. That displacement is not a pan, so it must not streak the frame.
    if math.dist(prev.position, cur.position) > 1.0:
        return (0.0, 0.0)
    p = prev.project(cur.target)
    if p is None:
        return (0.0, 0.0)
    dx, dy = cur.width / 2 - p[0], cur.height / 2 - p[1]
    return (round(dx * shutter, 3), round(dy * shutter, 3))


def corner_waits(events: list[dict]) -> dict[int, tuple[float, float]]:
    """Every frame a corner waits to be taken, with its flag: from the engine's set piece at a corner
    flag (within the corner arc) after the ball went out over a goal line (Law 17: a corner, not a
    throw-in or a free kick near the flag), to the frame before the next touch, the kick."""
    from ninety.render.edit import STOPS  # edit.py imports this module: imported here, not copied

    order = sorted(events, key=lambda e: e["frame"])
    out: dict[int, tuple[float, float]] = {}
    stop = None
    for i, e in enumerate(order):
        if e["type"] in STOPS:
            stop = e
        if e["type"] != "set_piece":
            continue
        over_goal_line = (stop is not None and stop["type"] == "out_of_play"
                          and (stop["x"] <= 0.0 or stop["x"] >= 105.0))
        if not over_goal_line:
            continue
        flag = next(((fx, fy) for fx in (0.0, 105.0) for fy in (0.0, 68.0)
                     if math.hypot(e["x"] - fx, e["y"] - fy) <= CORNER_ARC_M + BALL_RADIUS_M), None)
        if flag is None:
            continue
        kick = next((n["frame"] for n in order[i + 1:] if n["frame"] > e["frame"]), e["frame"] + 1)
        for f in range(e["frame"], kick):
            out[f] = flag
    return out
