"""The broadcast's edit: where the picture cuts away from a dead ball and back to the restart.

The engine plays every second of a stoppage, as long as real ones last (GROUNDING R1: about 16 s
for a throw-in, 30 s for a goal kick or corner, 31 to 41 s for a free kick). A broadcast does not
show that wait. It stays on the stoppage a moment (the ball going out, the foul, the goal), then
cuts to the restart being set (design, renderer only: what is shown, never what happened).

A cut leaves out match frames, never changes one: the frames shown are the engine's frames, in
order, and each keeps its match number and time. A cut lies wholly inside a dead ball, from a
stoppage to the restart that ends it, and never over an event, so every event of the clip is on a
frame it shows; and the clip shows the stoppage before it and the restart after it, so the dead ball
is on screen at both ends (docs/DATA_CONTRACT.md; `ninety-validate` checks it, C2).

Only a broadcast clip cuts (`dead_ball_cut`, on in `ninety-render` for the viewer and the demo):
datasets and the test sets show every frame.
"""

from __future__ import annotations

from bisect import bisect_right
from dataclasses import dataclass

from ninety.match.timeline import Segment, Timeline, segments  # noqa: F401  (the clip's timeline)
from ninety.render.camera import CUT_HOLD_S

# Play stops at these events (Laws 9, 10, 11, 12) and starts again at these.
STOPS = ("out_of_play", "foul", "offside", "goal")
RESTARTS = ("set_piece", "kickoff")
# How long the picture stays on a stoppage before the cut, and how long before the restart it comes
# back (design, renderer only). Each hold before a cut is at least the camera's shortest shot
# (CUT_HOLD_S), so no shot flickers: the ball going out or the foul and the players reacting. A goal
# is held for the celebration: the engine's scorer reaches the corner flag about 5 s after a goal
# and his team-mates join him (seed 8001), and the camera follows him (camera.Director, `scorer`).
# The picture comes back on the restart's wide shot as the restart is imminent, the taker seen set,
# so nobody stands still on screen for long (demo v1's critic: 6 s of a frozen close-up). A broadcast
# is away from the live picture for a replay of about 7 s a time (SoccerNet-v2, GROUNDING V1), so a
# wait of more than about 15 s is where a cut stands in for what it shows.
HOLD_AFTER_STOP_S = CUT_HOLD_S
HOLD_AFTER_GOAL_S = 8.0
SHOW_BEFORE_RESTART_S = 2.0
# Each cut is covered by a stinger, as a broadcast covers the cut into and out of a replay with its
# graphic (design: about half a second): `stingers` marks the frames either side of it.
STINGER_S = 0.6
# A cut that would leave out less than this is not made (design): a jump of a second or two in the
# same scene reads as a glitch, not an edit.
MIN_CUT_S = 4.0


@dataclass(frozen=True)
class Cut:
    """Match frames first_frame..last_frame (inclusive) are not shown. `stop` and `restart` are the
    frames of the stoppage and the restart of its dead ball (not recorded: the events are)."""

    first_frame: int
    last_frame: int
    stop: int = -1
    restart: int = -1

    def as_dict(self) -> dict:
        return {"first_frame": self.first_frame, "last_frame": self.last_frame}


def dead_balls(events: list[dict]) -> list[tuple[int, int, str]]:
    """Each dead ball as (stoppage frame, restart frame, stoppage type): from an event that stops
    play to the first restart after it. A stoppage with no restart after it in `events` is left
    open and not returned."""
    out: list[tuple[int, int, str]] = []
    stop: dict | None = None
    for e in sorted(events, key=lambda e: e["frame"]):
        if e["type"] in STOPS and stop is None:
            stop = e
        elif e["type"] in RESTARTS and stop is not None:
            if e["frame"] > stop["frame"]:
                out.append((stop["frame"], e["frame"], stop["type"]))
            stop = None
    return out


def cuts(events: list[dict], fps: int) -> list[Cut]:
    """The cuts through every dead ball long enough to cut, over no event."""
    frames_of = sorted(e["frame"] for e in events)
    out: list[Cut] = []
    for stop, restart, kind in dead_balls(events):
        hold = HOLD_AFTER_GOAL_S if kind == "goal" else HOLD_AFTER_STOP_S
        first = stop + round(hold * fps) + 1
        last = restart - round(SHOW_BEFORE_RESTART_S * fps) - 1
        if last - first + 1 < round(MIN_CUT_S * fps):
            continue
        # Nothing that happened is cut: an event inside would be on no frame of the clip.
        i = bisect_right(frames_of, first - 1)
        if i < len(frames_of) and frames_of[i] <= last:
            continue
        out.append(Cut(first, last, stop, restart))
    return out


def shown(start: int, n: int, cut_list: list[Cut], end: int) -> list[int]:
    """The match frames shown: from `start`, skipping every cut, until `n` are shown or the match
    (frames 0..end-1) runs out. A start inside a cut opens the clip where the cut ends."""
    out: list[int] = []
    f = start
    ordered = sorted(cut_list, key=lambda c: c.first_frame)
    k = 0
    while len(out) < n and f < end:
        while k < len(ordered) and ordered[k].last_frame < f:
            k += 1
        if k < len(ordered) and ordered[k].first_frame <= f <= ordered[k].last_frame:
            f = ordered[k].last_frame + 1
            continue
        out.append(f)
        f += 1
    return out


def plan(start: int, n: int, cut_list: list[Cut], end: int) -> tuple[list[int], list[Cut]]:
    """The match frames a clip of `n` frames from `start` shows, and the cuts it makes: only those
    whose stoppage and restart it shows both, so the dead ball is on screen at each end of the cut.
    Leaving a cut out shows more of the wait, which can push a later restart past the clip's end, so
    the choice is repeated until it holds."""
    chosen = [c for c in cut_list if c.stop >= start]
    while True:
        frames = shown(start, n, chosen, end)
        if not frames:
            return frames, []
        keep = [c for c in chosen if frames[0] <= c.stop and c.restart <= frames[-1]]
        if keep == chosen:
            return frames, used(chosen, frames)
        chosen = keep


def used(cut_list: list[Cut], frames: list[int]) -> list[Cut]:
    """The cuts that fall between two shown frames: the ones the clip actually makes."""
    if not frames:
        return []
    return [c for c in cut_list if frames[0] < c.first_frame and c.last_frame < frames[-1]]


def stingers(frames: list[int], fps: int) -> dict[int, float]:
    """For each picture index near a cut (a jump between two consecutive shown match frames): the
    stinger's progress, from -1 as it starts through 0 at the cut to 1 as it clears. Half of
    STINGER_S each side of the cut; other indices are absent."""
    half = max(1, round(STINGER_S * fps / 2))
    out: dict[int, float] = {}
    for i in range(1, len(frames)):
        if frames[i] == frames[i - 1] + 1:
            continue
        for k in range(half):  # k frames before the cut's last shown frame, and after its first
            if i - 1 - k >= 0:
                out[i - 1 - k] = -(k + 0.5) / half
            if i + k < len(frames):
                out[i + k] = (k + 0.5) / half
    return out
