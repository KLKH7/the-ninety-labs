"""A rendered clip's timeline: which match frame each image shows, across the broadcast's cuts.

A clip's picture may cut away from a dead ball to its restart (ninety/render/edit.py, recorded in
clip.json `segments` and meta.json `cuts`). Anything that shows or schedules by time (the viewer,
the audio description) maps video time to match time through this, not by adding the clip's start.
It reads no ground truth: the segments are the broadcast's own timecode.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class Segment:
    """A run of consecutive match frames shown one after another: image `index` of the clip shows
    match frame `frame`, and the next `frames` - 1 images the frames after it."""

    index: int  # the clip's image index of the segment's first frame
    frame: int  # its match frame
    frames: int

    def as_dict(self) -> dict:
        return {"index": self.index, "frame": self.frame, "frames": self.frames}


def segments(frames: list[int]) -> list[Segment]:
    """The clip's shown frames as runs of consecutive match frames, split at each cut."""
    out: list[Segment] = []
    for i, f in enumerate(frames):
        if out and f == out[-1].frame + out[-1].frames:
            last = out[-1]
            out[-1] = Segment(last.index, last.frame, last.frames + 1)
        else:
            out.append(Segment(i, f, 1))
    return out


class Timeline:
    """Video time against match time, for a clip whose picture cuts: a reader that shows or
    schedules anything by time (the viewer, the audio description) maps through this."""

    @classmethod
    def of_clip(cls, clip: dict) -> Timeline:
        """A rendered clip's timeline from its clip.json: its segments, or for a clip rendered
        before the broadcast cut, one run of frames from its start."""
        fps = clip["fps"]
        whole = {"index": 0, "frame": round(clip["t_start"] * fps), "frames": clip["frames"]}
        segs = clip.get("segments") or [whole]
        return cls(segs, fps)

    def __init__(self, segs: list[Segment] | list[dict], fps: float):
        self.fps = fps
        self.segs = [s if isinstance(s, Segment) else Segment(s["index"], s["frame"], s["frames"])
                     for s in segs]

    def to_match(self, video_t: float) -> float:
        """The match time shown at this video time."""
        i = max(0, int(video_t * self.fps))
        seg = self.segs[0]
        for s in self.segs:
            if s.index <= i:
                seg = s
        return (seg.frame + (video_t * self.fps - seg.index)) / self.fps

    def to_video(self, match_t: float) -> float:
        """When the video shows this match time; a time inside a cut is shown where the cut is."""
        f = match_t * self.fps
        for s in self.segs:
            if f < s.frame:
                return s.index / self.fps
            if f < s.frame + s.frames:
                return (s.index + f - s.frame) / self.fps
        last = self.segs[-1]
        return (last.index + last.frames) / self.fps
