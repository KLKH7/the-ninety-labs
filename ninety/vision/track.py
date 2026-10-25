"""Players and the ball through time, on the pitch: observations -> tracks -> teams.

Input is the observations file `ninety.vision.observe` writes (one line per frame: the estimated
camera's verdict and every detection with its pitch position and kit colour). Nothing here reads
ground truth: this is the live path.

Tracking is in pitch metres, not pixels: the camera pans, so a standing player moves across the
image, but not across the pitch. Each player track predicts its next position from its velocity
and takes the nearest unclaimed detection within GATE_M, nearest pairs first; a detection nobody
claims starts a track. Teams come from kit colour: the two largest colour groups are the two
outfield sides, a track far from both is a goalkeeper (or anyone else in a different colour), and
which side is home follows the engine's one convention, that home attacks toward x = 105 in both
halves (ninety/sim/engine.py): the side whose deepest players stand nearer x = 105 defends that
goal, so it is away.

Pure Python, so CI runs it.
"""

from __future__ import annotations

import json
import math
from dataclasses import dataclass, field
from pathlib import Path

FPS = 25
# The scorer's detection threshold (docs/EVALUATION.md, vision scoring): the same 0.5 everywhere.
SCORE_MIN = 0.5
# Match top speeds are 7.9 to 8.6 m/s (GROUNDING R6); 10 m/s, above that, is 0.4 m a frame, and
# calibration moves a player's foot point by up to about 0.5 m between neighbouring frames. A track
# takes a detection within 1.0 m of where it predicted (design: the two added and rounded up).
GATE_M = 1.0
# A track not seen for this long is closed: a player hidden behind another for a second is
# usually still the same player, longer than that the prediction is a guess (design).
MAX_GAP_FRAMES = 25
# Tracks shorter than this are not used to learn the kit colours: a few frames is often a
# fragment of a crossing or a false detection (design).
MIN_COLOUR_FRAMES = 10
# A track whose kit is farther than this from both outfield colours (as a multiple of the outfield
# tracks' own median distance to their colour) is not an outfield player of either side (design).
OUTLIER_FACTOR = 3.0
PENALTY_AREA_X = 16.5  # Law 1 (GROUNDING L1)
# The least spread two shirts of one kit show in chromaticity (JPEG and sensor noise), so a scene
# of identical shirts still has a scale to measure outliers by (design).
CHROMA_NOISE = 0.01
# The same for brightness, in stops (log2 of the shirt's mean channel): a tenth of a stop (design).
LIGHT_NOISE = 0.1


def read_observations(path: Path | str) -> list[dict]:
    rows = [json.loads(line) for line in Path(path).read_text().splitlines() if line.strip()]
    frames = [r["frame"] for r in rows]
    if frames != sorted(frames) or len(set(frames)) != len(frames):
        raise ValueError(f"{path}: frames are not strictly increasing")
    return rows


@dataclass
class Track:
    id: int
    frames: list[int] = field(default_factory=list)
    xy: list[tuple[float, float]] = field(default_factory=list)
    rgb: list[tuple[float, float, float]] = field(default_factory=list)
    scores: list[float] = field(default_factory=list)
    team: str | None = None  # "home", "away" or None (not known)
    keeper: bool = False
    # How firmly the side was decided, 0 to 1 (`assign_teams`): a score, not a probability.
    side_confidence: float | None = None

    def predict(self, frame: int) -> tuple[float, float]:
        x, y = self.xy[-1]
        if len(self.xy) >= 2 and self.frames[-1] - self.frames[-2] <= 2:
            gap = self.frames[-1] - self.frames[-2]
            vx = (self.xy[-1][0] - self.xy[-2][0]) / gap
            vy = (self.xy[-1][1] - self.xy[-2][1]) / gap
            k = frame - self.frames[-1]
            return x + vx * k, y + vy * k
        return x, y

    def at(self, frame: int) -> tuple[float, float] | None:
        """Where the track was at this frame, if it was seen then."""
        lo, hi = 0, len(self.frames)
        while lo < hi:
            mid = (lo + hi) // 2
            if self.frames[mid] < frame:
                lo = mid + 1
            else:
                hi = mid
        return self.xy[lo] if lo < len(self.frames) and self.frames[lo] == frame else None


def track_players(rows: list[dict]) -> list[Track]:
    """Link player detections across frames. Frames whose camera fit is not ok are skipped:
    their pitch positions are not trusted, and the tracks wait for the next good frame."""
    open_: list[Track] = []
    done: list[Track] = []
    next_id = 1
    for row in rows:
        if not row["camera"]["ok"]:
            continue
        f = row["frame"]
        for t in [t for t in open_ if f - t.frames[-1] > MAX_GAP_FRAMES]:
            open_.remove(t)
            done.append(t)
        dets = [d for d in row["players"] if d["score"] >= SCORE_MIN and d.get("x") is not None]
        pairs = []
        for ti, t in enumerate(open_):
            px, py = t.predict(f)
            for di, d in enumerate(dets):
                dist = math.hypot(d["x"] - px, d["y"] - py)
                if dist <= GATE_M * max(1, f - t.frames[-1]) ** 0.5:
                    pairs.append((dist, ti, di))
        pairs.sort()
        used_t, used_d = set(), set()
        for _, ti, di in pairs:
            if ti in used_t or di in used_d:
                continue
            used_t.add(ti)
            used_d.add(di)
            _add(open_[ti], f, dets[di])
        for di, d in enumerate(dets):
            if di not in used_d:
                t = Track(next_id)
                next_id += 1
                _add(t, f, d)
                open_.append(t)
    return sorted(done + open_, key=lambda t: t.id)


def _add(t: Track, frame: int, d: dict) -> None:
    t.frames.append(frame)
    t.xy.append((d["x"], d["y"]))
    t.rgb.append(tuple(d["rgb"]) if d.get("rgb") else None)
    t.scores.append(d["score"])


def _median_rgb(t: Track) -> tuple[float, ...] | None:
    """Each channel's median over the track's frames: 3 channels for one colour, 6 for a two-colour
    reading (the darker colour's, then the lighter's; observe.py)."""
    cols = [c for c in t.rgb if c is not None]
    if not cols:
        return None
    n = min(len(c) for c in cols)
    return tuple(sorted(c[k] for c in cols)[len(cols) // 2] for k in range(n))


# Two ways to tell kits apart, and each clip uses the one that separates its two kits better
# (`two_colours`). Chromaticity (each channel over their sum) ignores light: sun and shadow scale
# all three channels together, so a kit half in the stand's shadow keeps its chromaticity while its
# raw colour halves (seed 900001: raw colour learned two greys for a maroon and a blue kit). But it
# is blind to brightness, so a white and a black kit are one grey (validation seeds 115 and 121).
# Brightness, in stops, tells those apart; shadow moves it too, which is why it is only chosen when
# the kits differ by more than the light does.
FEATURES = ("chromaticity", "brightness")
NOISE = {"chromaticity": CHROMA_NOISE, "brightness": LIGHT_NOISE}


def kit(t: Track, feature: str) -> tuple[float, ...] | None:
    """The track's kit as a point in `feature`'s space, from its median shirt colour."""
    med = _median_rgb(t)
    if med is None:
        return None
    return _point(med, feature)


def _point(rgb: tuple[float, ...], feature: str) -> tuple[float, ...]:
    """One reading (one colour, or a two-colour reading's both) as a point in `feature`'s space."""
    point: list[float] = []
    for k in range(0, len(rgb) - len(rgb) % 3, 3):
        c = rgb[k:k + 3]
        total = sum(c) + 1e-9
        point += [v / total for v in c] if feature == "chromaticity" else [math.log2(total / 3 + 1e-9)]
    return tuple(point)


def _dist(a, b) -> float:
    return math.dist(a, b)


def _mean(g: list[tuple[tuple, int]]) -> tuple:
    w = sum(w for _, w in g)
    return tuple(sum(c[k] * wt for c, wt in g) / w for k in range(len(g[0][0])))


def _two_means(pts: list[tuple[tuple, int]]) -> tuple[tuple, tuple] | None:
    """2-means on frame-weighted points, started from the two points farthest apart. Deterministic.
    (A split along the main axis was tried on validation and kept seed 120 right only through a
    tied side vote: docs/eval/detector-plan.md, Outcome.)"""
    if len(pts) < 2:
        return None
    a, b = max(((p, q) for p in pts for q in pts), key=lambda pq: _dist(pq[0][0], pq[1][0]))
    ca, cb = a[0], b[0]
    for _ in range(20):
        ga = [(c, w) for c, w in pts if _dist(c, ca) <= _dist(c, cb)]
        gb = [(c, w) for c, w in pts if _dist(c, ca) > _dist(c, cb)]
        if not ga or not gb:
            break
        na, nb = _mean(ga), _mean(gb)
        if na == ca and nb == cb:
            break
        ca, cb = na, nb
    return ca, cb


def separation(pts: list[tuple[tuple, int]], ca: tuple, cb: tuple, noise: float) -> float:
    """How far apart the two centres are, in units of the points' spread about their own centre
    (frame-weighted root mean square, at least `noise`): scale-free, so two features compare."""
    sq = sum(w * min(_dist(c, ca), _dist(c, cb)) ** 2 for c, w in pts) / sum(w for _, w in pts)
    return _dist(ca, cb) / max(math.sqrt(sq), noise)


def two_colours(tracks: list[Track]) -> tuple[str, tuple, tuple] | None:
    """The feature that tells the two outfield kits apart best, and the two kits in it: 2-means on
    the tracks' kits (each weighted by its frames) in each feature, the one whose centres stand
    farther apart for their spread kept. Deterministic."""
    best = None
    for feature in FEATURES:
        pts = [(c, len(t.frames)) for t in tracks if len(t.frames) >= MIN_COLOUR_FRAMES
               and (c := kit(t, feature)) is not None]
        if len(pts) < 2:
            return None
        centres = _two_means(pts)
        if centres is None:
            continue
        ca, cb = centres
        # A goalkeeper or referee in a third colour would drag a centre: drop the far tracks once.
        spread = sorted(min(_dist(c, ca), _dist(c, cb)) for c, _ in pts)
        typical = max(spread[len(spread) // 2], NOISE[feature])
        core = [(c, w) for c, w in pts if min(_dist(c, ca), _dist(c, cb)) <= OUTLIER_FACTOR * typical]
        ga = [(c, w) for c, w in core if _dist(c, ca) <= _dist(c, cb)]
        gb = [(c, w) for c, w in core if _dist(c, ca) > _dist(c, cb)]
        if ga and gb:
            ca, cb = _mean(ga), _mean(gb)
        score = separation(core or pts, ca, cb, NOISE[feature])
        if best is None or score > best[0]:
            best = (score, feature, ca, cb)
    return None if best is None else best[1:]


def soundness(assigned: list[tuple[Track, tuple]], ca: tuple, cb: tuple, feature: str) -> float:
    """How surely the clip's two kit clusters each hold one team (docs/eval/kit-colour-plan.md), 0 to 1:
    the smaller of the kits' separation, mapped through sep / (1 + sep), and the share of the
    clip's assigned tracks whose kit lies nearer its own centre than halfway to the other's."""
    pts = [(c, len(t.frames)) for t, c in assigned if len(t.frames) >= MIN_COLOUR_FRAMES]
    if not pts or not assigned:
        return 0.0
    sep = separation(pts, ca, cb, NOISE[feature])
    half = _dist(ca, cb) / 2
    near = sum(1 for _, c in assigned if min(_dist(c, ca), _dist(c, cb)) < half) / len(assigned)
    return min(sep / (1 + sep), near)


def consistency(assigned: list[tuple[Track, tuple]], ca: tuple, cb: tuple, feature: str) -> float:
    """C (docs/eval/kit-colour-plan.md, amendment for dataset v2): the share of the assigned tracks'
    per-frame kit readings that lie nearer their own cluster's centre than the other's. Measured;
    it enters team_confidence only if dataset v2's validation clips show it separates (USE_CONSISTENCY)."""
    agree = total = 0
    for t, _ in assigned:
        own_is_a = _dist(kit(t, feature) or ca, ca) <= _dist(kit(t, feature) or ca, cb)
        for c in t.rgb:
            if c is None:
                continue
            p = _point(c, feature)
            total += 1
            agree += (_dist(p, ca) < _dist(p, cb)) == own_is_a
    return agree / total if total else 0.0


USE_CONSISTENCY = False  # set only by the amendment's rule on dataset v2's validation clips


# Law 3: a team has at most 11 players on the pitch, its keeper included. More tracks of one side than
# that in one frame cannot all be that side: the kits were not told apart (two kits read as one
# colour, a keeper or referee as a team), and then no side in the clip is sure.
MAX_PER_SIDE = 11


def law3(tracks: list[Track]) -> dict | None:
    """When some frame holds more than MAX_PER_SIDE tracks of one side, every track's side
    confidence becomes 0 (nothing team-named may air) and the evidence is returned; else None."""
    per: dict[int, dict[str, int]] = {}
    for t in tracks:
        if t.team is None:
            continue
        for f in t.frames:
            per.setdefault(f, {}).setdefault(t.team, 0)
            per[f][t.team] += 1
    over = [f for f, c in per.items() if max(c.values()) > MAX_PER_SIDE]
    if not over:
        return None
    for t in tracks:
        if t.team is not None:
            t.side_confidence = 0.0
    return {"frames_over": len(over), "frames": len(per),
            "most": max(max(c.values()) for c in per.values())}


def assign_teams(tracks: list[Track]) -> dict:
    """Give each track a team (or None) and say how: the two kit colours, which one is home and
    why, and how many tracks were left unassigned. The decision is recorded, so a wrong side can
    be seen in the output rather than guessed at."""
    colours = two_colours(tracks)
    if colours is None:
        return {"feature": None, "kits": None, "reason": "fewer than two tracks long enough to learn kits"}
    feature, ca, cb = colours
    meds = [(t, kit(t, feature)) for t in tracks]
    spread = sorted(min(_dist(c, ca), _dist(c, cb)) for t, c in meds if c is not None
                    and len(t.frames) >= MIN_COLOUR_FRAMES)
    typical = max(spread[len(spread) // 2] if spread else 0.0, NOISE[feature])
    side: dict[int, int | None] = {}
    for t, c in meds:
        if c is None:
            side[t.id] = None
        elif min(_dist(c, ca), _dist(c, cb)) > OUTLIER_FACTOR * typical:
            side[t.id] = None
            mx = sum(x for x, _ in t.xy) / len(t.xy)
            t.keeper = mx <= PENALTY_AREA_X or mx >= 105.0 - PENALTY_AREA_X
        else:
            side[t.id] = 0 if _dist(c, ca) <= _dist(c, cb) else 1
    # Which colour defends the right goal (away's, since home attacks toward it): frame by frame,
    # over the frames where both sides are seen, the side whose players stand nearer x = 105 on
    # average. Out of possession a block stays goal-side of the ball (GROUNDING T2) and in
    # possession the back line stays behind it (O6), so the side defending x = 105 is the nearer
    # in either phase. The single deepest player was used before: it needs both defensive lines
    # in the picture, and a view of one half flipped validation seed 2043 (detector-plan.md, A.3).
    votes = 0
    keepers = [t for t in tracks if t.keeper]
    by_frame: dict[int, list[tuple[float, int]]] = {}
    for t in tracks:
        s = side[t.id]
        if s is None:
            continue
        for f, (x, _) in zip(t.frames, t.xy, strict=True):
            by_frame.setdefault(f, []).append((x, s))
    for obs in by_frame.values():
        xs0 = [x for x, s in obs if s == 0]
        xs1 = [x for x, s in obs if s == 1]
        if xs0 and xs1:
            votes += 1 if sum(xs0) / len(xs0) > sum(xs1) / len(xs1) else -1
    away = 0 if votes > 0 else 1
    reason = f"side nearer x = 105 on average: colour {away} in {abs(votes)} more frames"
    names = {away: "away", 1 - away: "home"}
    voting = len([o for o in by_frame.values() if {s for _, s in o} == {0, 1}])
    # An outfield side rests on two decisions, so its confidence is the weaker: whether the two kit
    # clusters are told apart at all (`soundness`), and how one-sided the clip's vote on which
    # colour is home was (0 split, 1 unanimous). The kit term was each track's own colour margin
    # until #200 found every side error left was a cluster error, which a confident track can sit in
    # (docs/eval/kit-colour-plan.md).
    clip_margin = abs(votes) / voting if voting else 0.0
    assigned = [(t, c) for t, c in meds if side[t.id] is not None]
    sound = soundness(assigned, ca, cb, feature)
    agreeing = consistency(assigned, ca, cb, feature)
    if USE_CONSISTENCY:
        sound = min(sound, agreeing)
    for t, _ in meds:
        s = side[t.id]
        if s is not None:
            t.team = names[s]
            t.side_confidence = round(min(sound, clip_margin), 3)
    # A keeper's side is the half he stands in: his confidence is how far from halfway, as a share
    # of the half.
    for k in keepers:
        mx = sum(x for x, _ in k.xy) / len(k.xy)
        k.team = "away" if mx >= 52.5 else "home"
        k.side_confidence = round(min(1.0, abs(mx - 52.5) / 52.5), 3)
    kits = [[round(v, 3) for v in c] for c in (ca, cb)]
    impossible = law3(tracks)
    return {
        "law3": impossible,
        "feature": feature,
        "kits": {"home": kits[1 - away], "away": kits[away]},
        "reason": reason,
        "frames_voting": voting,
        "soundness": round(sound, 3),
        "consistency": round(agreeing, 3),
        "vote_margin": votes if away == 0 else -votes,
        "keepers": len(keepers),
        "unassigned": sum(1 for t in tracks if t.team is None),
    }


@dataclass(frozen=True)
class BallPoint:
    frame: int
    x: float
    y: float
    score: float
    # The ball's box centre lies inside a player's box: it is drawn over his body (at his feet,
    # in his hands, at his head), so its height is unknown and its place on the ground is a guess.
    on_player: bool = False
    u: float | None = None  # the box centre in pixels
    v: float | None = None


def ball_path(rows: list[dict]) -> list[BallPoint]:
    """The ball's pitch position in each good frame where it is detected: the highest-scoring
    ball detection at or above SCORE_MIN that is near the last one (a second ball-sized blob at a
    player's feet is not the ball when the ball was just 20 m away), else the highest-scoring one.
    'Near' is the farthest a ball travels in the frames since, at 40 m/s (144 km/h, a design
    bound above the shots in our clips), plus GATE_M."""
    out: list[BallPoint] = []
    for row in rows:
        if not row["camera"]["ok"]:
            continue
        cands = sorted((b for b in row["ball"] if b["score"] >= SCORE_MIN and b.get("x") is not None),
                       key=lambda b: -b["score"])
        if not cands:
            continue
        pick = cands[0]
        if out:
            reach = 40.0 / FPS * (row["frame"] - out[-1].frame) + GATE_M
            near = [b for b in cands if math.hypot(b["x"] - out[-1].x, b["y"] - out[-1].y) <= reach]
            if near:
                pick = near[0]
        cx, cy = (pick["bbox"][0] + pick["bbox"][2]) / 2, (pick["bbox"][1] + pick["bbox"][3]) / 2
        # Pixels compare only within one picture: on fused lines (ninety.vision.fuse) each box
        # names the view it was drawn in.
        on = any(d["score"] >= SCORE_MIN and d.get("view") == pick.get("view")
                 and d["bbox"][0] <= cx <= d["bbox"][2]
                 and d["bbox"][1] <= cy <= d["bbox"][3] for d in row["players"])
        out.append(BallPoint(row["frame"], pick["x"], pick["y"], pick["score"], on, cx, cy))
    return out
