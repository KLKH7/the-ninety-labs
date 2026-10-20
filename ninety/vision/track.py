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


def _median_rgb(t: Track) -> tuple[float, float, float] | None:
    """The track's kit as chromaticity (each channel over their sum) of its median shirt colour.
    Sun and shadow scale all three channels together, so a kit half in the stand's shadow keeps
    its chromaticity while its raw colour halves; clustering raw colour split the players by
    light, not by side (seed 900001: two greys learned for a maroon and a blue kit)."""
    cols = [c for c in t.rgb if c is not None]
    if not cols:
        return None
    med = [sorted(c[k] for c in cols)[len(cols) // 2] for k in range(3)]
    total = sum(med) + 1e-9
    return tuple(v / total for v in med)


def _dist(a, b) -> float:
    return math.dist(a, b)


def two_colours(tracks: list[Track]) -> tuple[tuple, tuple] | None:
    """The two outfield kit colours: 2-means on the tracks' median colours, each track weighted
    by how many frames it has, started from the two tracks farthest apart. Deterministic."""
    pts = [(c, len(t.frames)) for t in tracks if len(t.frames) >= MIN_COLOUR_FRAMES
           and (c := _median_rgb(t)) is not None]
    if len(pts) < 2:
        return None
    a, b = max(((p, q) for p in pts for q in pts), key=lambda pq: _dist(pq[0][0], pq[1][0]))
    ca, cb = a[0], b[0]
    for _ in range(20):
        ga = [(c, w) for c, w in pts if _dist(c, ca) <= _dist(c, cb)]
        gb = [(c, w) for c, w in pts if _dist(c, ca) > _dist(c, cb)]
        if not ga or not gb:
            break
        mean = lambda g: tuple(sum(c[k] * w for c, w in g) / sum(w for _, w in g) for k in range(3))  # noqa: E731
        na, nb = mean(ga), mean(gb)
        if na == ca and nb == cb:
            break
        ca, cb = na, nb
    # A goalkeeper or referee in a third colour would drag a centre: drop the far tracks once.
    spread = sorted(min(_dist(c, ca), _dist(c, cb)) for c, _ in pts)
    typical = max(spread[len(spread) // 2], CHROMA_NOISE)
    core = [(c, w) for c, w in pts if min(_dist(c, ca), _dist(c, cb)) <= OUTLIER_FACTOR * typical]
    ga = [(c, w) for c, w in core if _dist(c, ca) <= _dist(c, cb)]
    gb = [(c, w) for c, w in core if _dist(c, ca) > _dist(c, cb)]
    if ga and gb:
        mean = lambda g: tuple(sum(c[k] * w for c, w in g) / sum(w for _, w in g) for k in range(3))  # noqa: E731
        ca, cb = mean(ga), mean(gb)
    return ca, cb


def assign_teams(tracks: list[Track]) -> dict:
    """Give each track a team (or None) and say how: the two kit colours, which one is home and
    why, and how many tracks were left unassigned. The decision is recorded, so a wrong side can
    be seen in the output rather than guessed at."""
    colours = two_colours(tracks)
    if colours is None:
        return {"chromaticity": None, "reason": "fewer than two tracks long enough to learn kits"}
    ca, cb = colours
    meds = [(t, _median_rgb(t)) for t in tracks]
    spread = sorted(min(_dist(c, ca), _dist(c, cb)) for t, c in meds if c is not None
                    and len(t.frames) >= MIN_COLOUR_FRAMES)
    typical = max(spread[len(spread) // 2] if spread else 0.0, CHROMA_NOISE)
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
    # Which colour defends the right goal: compare each side's deepest players toward x = 105,
    # frame by frame, over the frames where both sides are seen. A keeper standing in a penalty
    # area settles it outright: the keeper at x = 105 is away's (home attacks toward it).
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
        xs0 = sorted((x for x, s in obs if s == 0), reverse=True)
        xs1 = sorted((x for x, s in obs if s == 1), reverse=True)
        if xs0 and xs1:
            votes += 1 if xs0[0] > xs1[0] else -1
    away = 0 if votes > 0 else 1
    reason = f"deepest outfield player toward x = 105: colour {away} in {abs(votes)} more frames"
    names = {away: "away", 1 - away: "home"}
    voting = len([o for o in by_frame.values() if {s for _, s in o} == {0, 1}])
    # An outfield side rests on two decisions, so its confidence is the weaker: how much nearer the
    # track's kit is to its own colour than to the other (0 halfway between, 1 on its own centre),
    # and how one-sided the clip's vote on which colour is home was (0 split, 1 unanimous).
    clip_margin = abs(votes) / voting if voting else 0.0
    for t, c in meds:
        s = side[t.id]
        if s is not None:
            t.team = names[s]
            own, other = (ca, cb) if s == 0 else (cb, ca)
            d_own, d_other = _dist(c, own), _dist(c, other)
            colour_margin = (d_other - d_own) / (d_other + d_own) if d_other + d_own else 0.0
            t.side_confidence = round(min(colour_margin, clip_margin), 3)
    # A keeper's side is the half he stands in: his confidence is how far from halfway, as a share
    # of the half.
    for k in keepers:
        mx = sum(x for x, _ in k.xy) / len(k.xy)
        k.team = "away" if mx >= 52.5 else "home"
        k.side_confidence = round(min(1.0, abs(mx - 52.5) / 52.5), 3)
    chroma = [[round(v, 3) for v in c] for c in (ca, cb)]
    return {
        "chromaticity": {"home": chroma[1 - away], "away": chroma[away]},
        "reason": reason,
        "frames_voting": voting,
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
        on = any(d["score"] >= SCORE_MIN and d["bbox"][0] <= cx <= d["bbox"][2]
                 and d["bbox"][1] <= cy <= d["bbox"][3] for d in row["players"])
        out.append(BallPoint(row["frame"], pick["x"], pick["y"], pick["score"], on, cx, cy))
    return out
