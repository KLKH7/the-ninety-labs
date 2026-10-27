"""The bundle's footage as web video every browser plays: an H.264/AAC MP4 and an HLS ladder.

    write(images, fps, out, audio=None)   # video.mp4, hls/master.m3u8 (+ one rung per size), poster.jpg
    clip(images, first, end, fps, dest)   # one highlight's window as an MP4

Why H.264 and HLS (Oct 26, lesson 272): the VP9 file before this froze in real Chrome. Hardware
VP9 decode failed on the all-keyframe, full-range file, and again on a standard one. H.264 is the
codec every browser and phone decodes in hardware. HLS is meant to let a judge on a slow connection
drop to a smaller rung instead of freezing: planned, as nothing plays the ladder yet (the viewer's
hls.js player is desktop-companion's, in progress); today the viewer and phone play video.mp4.

- **Encoder:** the producer's system ffmpeg, run as an external program on their Mac and never
  shipped (THIRD_PARTY_NOTICES.md, "Tools run, not shipped"), with Apple's VideoToolbox H.264 encoder
  (`h264_videotoolbox`, part of macOS), never libx264, which is GPL (AGENTS.md's licence rule). The
  encode is macOS only: on Linux, CI and the Azure image there is no such encoder, `can_encode` says
  so and e2e ships the JPEG frames.
- **Picture:** high profile, level 4.0, yuv420p. The renderer's full-range BT.601 JPEGs are
  converted to TV-range BT.709 and tagged so (`setparams`: the encoder writes no primaries or
  transfer from the output options alone).
- **Keyframes:** one every 2 s, forced by time on every rung, so the rungs' 4 s segments line up.
  VideoToolbox adds none at a cut (tests/test_footage_encode.py), so `-g` alone holds the grid
  today; the forced times keep it for an encoder that starts a picture group at a scene change.
  fMP4 segments start at time 0: HLS's currentTime is the MP4's, the video time the viewer maps to
  match time (ninety/match/timeline.py).
- **Sound:** any track ffmpeg reads (the render's crowd bed) is muxed into the MP4 and every rung as
  AAC (ffmpeg's own `aac` encoder, not a third-party library), cut to the picture. The frame count
  and duration are the images' own.
"""

from __future__ import annotations

import math
import shutil
import subprocess
from functools import cache
from pathlib import Path

ENCODER = "h264_videotoolbox"
KEY_S = 2  # a keyframe every 2 s (design: a seek lands within 2 s, the common web default)
SEGMENT_S = 4  # HLS segment length: two keyframe intervals (design; Apple's guidance is about 6 s)
MP4_BITRATE = 4_000_000  # design: 720p sport at 25 fps
# The ladder, largest first: (height, width, bitrate). A rung taller than the source is not made.
LADDER = ((1080, 1920, 5_000_000), (720, 1280, 3_000_000), (480, 854, 1_200_000))
AUDIO = ["-c:a", "aac", "-b:a", "128k"]
COLOUR = ("scale=in_range=pc:out_range=tv:in_color_matrix=bt601:out_color_matrix=bt709,"
          "setparams=range=tv:colorspace=bt709:color_primaries=bt709:color_trc=bt709,format=yuv420p")
TAGS = ["-color_range", "tv", "-colorspace", "bt709", "-color_primaries", "bt709", "-color_trc", "bt709"]


def video_args(fps: float) -> list[str]:
    # -g rounded up: at a fractional rate (31.25 images a second) a rounded-down group would put a
    # keyframe just before each forced 2 s one; up, the forced grid is the only one.
    return ["-c:v", ENCODER, "-profile:v", "high", "-level", "4.0", "-g", str(math.ceil(KEY_S * fps)),
            "-force_key_frames", f"expr:gte(t,n_forced*{KEY_S})", *TAGS]


@cache
def can_encode() -> bool:
    """ffmpeg is there and has the H.264 encoder."""
    if not shutil.which("ffmpeg"):
        return False
    out = subprocess.run(["ffmpeg", "-hide_banner", "-encoders"], capture_output=True, text=True).stdout
    return any(line.split()[1:2] == [ENCODER] for line in out.splitlines() if line.strip())


def rungs(height: int, width: int | None = None) -> list[tuple[int, int, int]]:
    """The ladder's rungs no taller than the source; a source smaller than every rung is one rung of
    its own size, at the smallest rung's bitrate."""
    fit = [r for r in LADDER if r[0] <= height]
    return fit or [(height, width or round(height * 16 / 9 / 2) * 2, LADDER[-1][2])]


def _input(images: list[Path], fps: float, first: int = 0) -> list[str]:
    return ["-framerate", f"{fps:g}", "-start_number", str(first), "-i", str(images[0].parent / "%05d.jpg")]


def _length(frames: int, fps: float) -> list[str]:
    return ["-frames:v", str(frames), "-t", f"{frames / fps:.3f}"]


def _sound(timescale: float) -> list[str]:
    """AAC, and the sound sped up with the picture (atempo: the pitch kept)."""
    return [*AUDIO, *(["-af", f"atempo={timescale:g}"] if timescale != 1 else [])]


def write(images: list[Path], fps: int, out: Path, audio: Path | None = None, height: int = 720,
          width: int | None = None, timescale: float = 1.0) -> dict:
    """video.mp4, the HLS ladder under hls/, and poster.jpg in `out`; returns the manifest's footage.
    `timescale` (match seconds a video second, Kian Oct 26: the demo plays 1.25x as its 1x): every
    image is still shown, at fps x timescale a video second, and the sound is sped up with it
    (`footage.timescale` in the manifest; ninety/match/timeline.py maps through it)."""
    n = len(images)
    match_fps, fps = fps, fps * timescale  # images a video second, from here on
    sound = [] if audio is None else ["-i", str(audio)]
    shutil.copyfile(images[0], out / "poster.jpg")
    mp4 = ["ffmpeg", "-y", "-loglevel", "error", *_input(images, fps), *sound, "-map", "0:v",
           *(["-map", "1:a", *_sound(timescale)] if audio else []), "-vf", COLOUR, *video_args(fps),
           "-b:v", str(MP4_BITRATE), *_length(n, fps), "-movflags", "+faststart", str(out / "video.mp4")]
    subprocess.run(mp4, check=True)

    ladder = rungs(height, width)
    split = f"[0:v]{COLOUR},split={len(ladder)}" + "".join(f"[s{i}]" for i in range(len(ladder)))
    scaled = "".join(f";[s{i}]scale={w}:{h}[v{i}]" for i, (h, w, _) in enumerate(ladder))
    maps, rates, streams = [], [], []
    for i, (h, _, bitrate) in enumerate(ladder):
        maps += ["-map", f"[v{i}]"] + (["-map", "1:a"] if audio else [])
        rates += [f"-b:v:{i}", str(bitrate), f"-maxrate:v:{i}", str(bitrate * 4 // 3),
                  f"-bufsize:v:{i}", str(bitrate * 2)]
        streams.append(f"v:{i}" + (f",a:{i}" if audio else "") + f",name:{h}p")
    hls = out / "hls"
    hls.mkdir(exist_ok=True)
    cmd = ["ffmpeg", "-y", "-loglevel", "error", *_input(images, fps), *sound,
           "-filter_complex", split + scaled, *maps, *video_args(fps), *rates,
           *(_sound(timescale) if audio else []),
           # The video at time 0 on every rung: AAC's priming samples sit before it (players drop them),
           # where shifting both up by 23 ms would put the picture off the MP4's clock.
           *_length(n, fps), "-avoid_negative_ts", "disabled",
           "-f", "hls", "-hls_time", str(SEGMENT_S), "-hls_playlist_type", "vod",
           "-hls_segment_type", "fmp4", "-hls_flags", "independent_segments",
           "-master_pl_name", "master.m3u8", "-var_stream_map", " ".join(streams),
           "-hls_segment_filename", str(hls / "%v" / "seg%04d.m4s"), "-hls_fmp4_init_filename", "init.mp4",
           str(hls / "%v" / "index.m3u8")]
    subprocess.run(cmd, check=True)
    return {"kind": "video", "src": "video.mp4", "mp4": "video.mp4", "hls": "hls/master.m3u8",
            "poster": "poster.jpg", "frames": n, "fps": match_fps, "timescale": timescale,
            "duration_s": round(n / fps, 3),
            "segment_s": SEGMENT_S, "audio": "muxed" if audio else None,
            "renditions": [{"height": h, "width": w, "bitrate": b, "playlist": f"hls/{h}p/index.m3u8"}
                           for h, w, b in ladder]}


def clip(images: list[Path], first: int, end: int, fps: int, dest: Path, timescale: float = 1.0) -> None:
    """Images [first, end) as an MP4 with the footage's settings and speed (a highlight's window)."""
    fps = fps * timescale
    cmd = ["ffmpeg", "-y", "-loglevel", "error", *_input(images, fps, first), "-vf", COLOUR, *video_args(fps),
           "-b:v", str(MP4_BITRATE), *_length(end - first, fps), "-movflags", "+faststart", str(dest)]
    subprocess.run(cmd, check=True)
