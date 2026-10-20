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
# back. Each is at least the camera's shortest shot (CUT_HOLD_S), so no shot flickers: the ball
# going out or the foul and the players reacting; a goal held longer for the scorer and the net.
# The picture comes back on the restart closed up for CUT_HOLD_S (camera.open_on_restart), then
# eases out, so the kick is taken on the wide shot about two seconds later, as a broadcast shows a
# restart. A broadcast is away from the live picture for a replay of about 7 s a time (SoccerNet-v2,
# GROUNDING V1), so a wait of more than about 15 s is where a cut stands in for what it shows.
HOLD_AFTER_STOP_S = CUT_HOLD_S
HOLD_AFTER_GOAL_S = 5.0
SHOW_BEFORE_RESTART_S = CUT_HOLD_S + 2.0
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
