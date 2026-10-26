"""video.webm is standard web VP9 (ninety/e2e.py, write_footage; highlights.VP9): a keyframe every
2 s, TV-range BT.709, about 4 Mbps, the images' own frame count and duration, and a render's sound
track kept when given. The all-keyframe, full-range file it replaced broke real Chrome's hardware
VP9 decoder intermittently (black at 0.34 s, media error 3)."""

from __future__ import annotations

import json
import shutil
import subprocess

import pytest

from ninety import e2e

pytestmark = pytest.mark.skipif(not shutil.which("ffmpeg") or not shutil.which("ffprobe"),
                                reason="needs ffmpeg and ffprobe")
FPS, N = 25, 130  # 5.2 s: keyframes due at frames 0, 50 and 100


def probe(path, *args):
    out = subprocess.run(["ffprobe", "-v", "error", *args, "-of", "json", str(path)],
                         check=True, capture_output=True, text=True).stdout
    return json.loads(out)


def clip_of(tmp_path):
    clip = tmp_path / "clip"
    (clip / "images").mkdir(parents=True)
    # Real JPEGs from ffmpeg's test pattern, full range as the renderer writes them.
    subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-f", "lavfi", "-i",
                    f"testsrc2=size=320x180:rate={FPS}", "-frames:v", str(N), "-pix_fmt", "yuvj420p",
                    str(clip / "images" / "%05d.jpg")], check=True)
    meta = {"clip_id": "c", "fps": FPS, "frames": N}
    (clip / "clip.json").write_text(json.dumps(meta))
    return e2e.load_clip(clip)


@pytest.mark.parametrize("with_audio", [False, True])
def test_video_webm_is_standard_vp9_with_the_images_frames_and_duration(tmp_path, with_audio):
    clip = clip_of(tmp_path)
    audio = None
    if with_audio:  # a crowd bed longer than the picture: it is cut to the picture
        audio = tmp_path / "crowd.wav"
        subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-f", "lavfi", "-i", "sine=f=220:d=9",
                        str(audio)], check=True)
    out = tmp_path / "bundle"
    out.mkdir()
    footage = e2e.write_footage(clip, out, encode=True, audio=audio)
    video = out / "video.webm"
    assert footage == {"kind": "video", "src": "video.webm", "frames": N, "audio": with_audio}

    (v,) = probe(video, "-select_streams", "v", "-count_frames", "-show_entries",
                 "stream=codec_name,nb_read_frames,color_range,color_space,color_primaries,color_transfer")["streams"]
    assert v["codec_name"] == "vp9" and int(v["nb_read_frames"]) == N
    assert (v["color_range"], v["color_space"], v["color_primaries"], v["color_transfer"]) == (
        "tv", "bt709", "bt709", "bt709")
    packets = probe(video, "-select_streams", "v", "-show_entries", "packet=pts_time,flags")["packets"]
    keys = [round(float(p["pts_time"]) * FPS) for p in packets if "K" in p["flags"]]
    assert keys == [0, 50, 100]  # one every 2 s, not every frame
    duration = float(probe(video, "-show_entries", "format=duration")["format"]["duration"])
    assert abs(duration - N / FPS) <= 1 / FPS
    # TV range in the pixels, not only the tag: the test pattern's black and white land on 16 and 235.
    luma = subprocess.run(["ffmpeg", "-loglevel", "error", "-i", str(video), "-frames:v", "1", "-f", "rawvideo",
                           "-pix_fmt", "yuv420p", "-"], check=True, capture_output=True).stdout[: 320 * 180]
    assert min(luma) >= 14 and max(luma) <= 237 and max(luma) - min(luma) > 180
    sound = probe(video, "-select_streams", "a", "-show_entries", "stream=codec_name")["streams"]
    assert [s["codec_name"] for s in sound] == (["opus"] if with_audio else [])
