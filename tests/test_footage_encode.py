"""The bundle's footage (ninety/footage.py, lesson 272): an H.264/AAC MP4 and an HLS ladder with the
images' own frame count and duration, a keyframe every 2 s on every rung (so their 4 s segments line
up), TV-range BT.709, times from 0 (the clock the phone is synced to), and the sound track kept when
given. Needs ffmpeg with VideoToolbox's H.264 encoder (a Mac): libx264 is GPL (AGENTS.md)."""

from __future__ import annotations

import json
import re
import subprocess
from pathlib import Path

import pytest

from ninety import e2e, footage

pytestmark = pytest.mark.skipif(not footage.can_encode(),
                                reason=f"needs ffmpeg with {footage.ENCODER} (macOS); libx264 is GPL")
FPS, N, W, H = 25, 230, 1280, 720  # 9.2 s: keyframes at 0, 2, 4, 6, 8 s; segments 0-4, 4-8, 8-9.2


def probe(path, *args):
    out = subprocess.run(["ffprobe", "-v", "error", *args, "-of", "json", str(path)],
                         check=True, capture_output=True, text=True).stdout
    return json.loads(out)


def clip_of(tmp_path):
    clip = tmp_path / "clip"
    (clip / "images").mkdir(parents=True)
    # Real JPEGs from ffmpeg's test pattern, full range as the renderer writes them.
    subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-f", "lavfi", "-i",
                    f"testsrc2=size={W}x{H}:rate={FPS}", "-frames:v", str(N), "-pix_fmt", "yuvj420p",
                    str(clip / "images" / "%05d.jpg")], check=True)
    (clip / "clip.json").write_text(json.dumps({"clip_id": "c", "fps": FPS, "frames": N,
                                                "params": {"width": W, "height": H}}))
    return e2e.load_clip(clip)


def keys(path):
    packets = probe(path, "-select_streams", "v", "-show_entries", "packet=pts_time,flags")["packets"]
    return [round(float(p["pts_time"]) * FPS) for p in packets if "K" in p["flags"]]


def video_stream(path):
    (v,) = probe(path, "-select_streams", "v", "-count_frames", "-show_entries",
                 "stream=codec_name,profile,level,pix_fmt,nb_read_frames,color_range,color_space,"
                 "color_primaries,color_transfer,start_time")["streams"]
    return v


@pytest.fixture(scope="module", params=[False, True], ids=["silent", "crowd"])
def bundle(request, tmp_path_factory):
    tmp = tmp_path_factory.mktemp("footage")
    clip = clip_of(tmp)
    audio = None
    if request.param:  # a crowd bed longer than the picture: it is cut to the picture
        audio = tmp / "crowd.wav"
        subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-f", "lavfi", "-i", "sine=f=220:d=12",
                        str(audio)], check=True)
    out = tmp / "bundle"
    out.mkdir()
    return out, e2e.write_footage(clip, out, encode=True, audio=audio), request.param


def test_the_manifest_lists_the_mp4_the_hls_ladder_and_the_poster(bundle):
    out, f, with_audio = bundle
    assert f == {"kind": "video", "src": "video.mp4", "mp4": "video.mp4", "hls": "hls/master.m3u8",
                 "poster": "poster.jpg", "frames": N, "fps": FPS, "timescale": 1.0, "duration_s": N / FPS,
                 "segment_s": 4,
                 "audio": "muxed" if with_audio else None,
                 "renditions": [
                     {"height": 720, "width": 1280, "bitrate": 3_000_000, "playlist": "hls/720p/index.m3u8"},
                     {"height": 480, "width": 854, "bitrate": 1_200_000, "playlist": "hls/480p/index.m3u8"}]}
    assert (out / "poster.jpg").is_file()
    master = (out / "hls" / "master.m3u8").read_text()
    assert "RESOLUTION=1280x720" in master and "RESOLUTION=854x480" in master and "1920x1080" not in master


def test_the_mp4_is_web_h264_with_the_images_frames_duration_and_keyframes(bundle):
    out, _, with_audio = bundle
    mp4 = out / "video.mp4"
    v = video_stream(mp4)
    assert (v["codec_name"], v["profile"], v["level"], v["pix_fmt"]) == ("h264", "High", 40, "yuv420p")
    assert int(v["nb_read_frames"]) == N and float(v["start_time"]) == 0.0
    assert (v["color_range"], v["color_space"], v["color_primaries"], v["color_transfer"]) == (
        "tv", "bt709", "bt709", "bt709")
    assert keys(mp4) == [0, 50, 100, 150, 200]  # one every 2 s, not every frame
    duration = float(probe(mp4, "-show_entries", "format=duration")["format"]["duration"])
    assert abs(duration - N / FPS) <= 1 / FPS
    head = mp4.read_bytes()[:4096]
    assert head.find(b"moov") != -1 and (head.find(b"mdat") == -1 or head.find(b"moov") < head.find(b"mdat"))
    sound = probe(mp4, "-select_streams", "a", "-show_entries", "stream=codec_name")["streams"]
    assert [s["codec_name"] for s in sound] == (["aac"] if with_audio else [])
    # TV range in the pixels, not only the tag: the test pattern's black and white land on 16 and 235.
    first = ["ffmpeg", "-loglevel", "error", "-i", str(mp4), "-frames:v", "1", "-f", "rawvideo",
             "-pix_fmt", "yuv420p", "-"]
    luma = subprocess.run(first, check=True, capture_output=True).stdout[: W * H]
    assert min(luma) >= 14 and max(luma) <= 237 and max(luma) - min(luma) > 180


@pytest.mark.parametrize("rung", ["720p", "480p"])
def test_every_rung_has_the_frames_from_time_0_and_4_s_segments_on_shared_keyframes(bundle, rung):
    out, _, with_audio = bundle
    index = out / "hls" / rung / "index.m3u8"
    lengths = [float(line.split(":")[1].rstrip(",")) for line in index.read_text().splitlines()
               if line.startswith("#EXTINF")]
    assert lengths == pytest.approx([4.0, 4.0, 1.2], abs=1 / FPS)  # segment edges at 4 s and 8 s
    v = video_stream(index)
    assert int(v["nb_read_frames"]) == N and float(v["start_time"]) == 0.0  # the MP4's clock
    assert keys(index) == [0, 50, 100, 150, 200]  # the same keyframes on every rung
    assert v["color_range"] == "tv" and v["color_space"] == "bt709"
    sound = probe(index, "-select_streams", "a", "-show_entries", "stream=codec_name")["streams"]
    assert [s["codec_name"] for s in sound] == (["aac"] if with_audio else [])


def test_a_source_shorter_than_a_rung_gets_no_rung_taller_than_itself():
    assert [h for h, _, _ in footage.rungs(720)] == [720, 480]
    assert [h for h, _, _ in footage.rungs(1080)] == [1080, 720, 480]
    assert [h for h, _, _ in footage.rungs(480)] == [480]
    assert footage.rungs(180, 320) == [(180, 320, 1_200_000)]  # smaller than every rung: its own size


def test_a_hard_cut_keeps_every_rung_on_the_2_s_keyframe_grid(tmp_path):
    # A broadcast cut can make the encoder start a new picture group there; the 2 s grid is forced by
    # time, so every rung still has a keyframe at 2, 4, 6 and 8 s and its segments end at 4 and 8 s.
    clip = tmp_path / "clip"
    (clip / "images").mkdir(parents=True)
    for i, src in enumerate((f"testsrc2=size={W}x{H}:rate={FPS}", f"mandelbrot=size={W}x{H}:rate={FPS}")):
        subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-f", "lavfi", "-i", src, "-frames:v",
                        "37" if i == 0 else str(N - 37), "-start_number", "0" if i == 0 else "37",
                        "-pix_fmt", "yuvj420p", str(clip / "images" / "%05d.jpg")], check=True)
    (clip / "clip.json").write_text(json.dumps({"clip_id": "c", "fps": FPS, "frames": N,
                                                "params": {"width": W, "height": H}}))
    out = tmp_path / "bundle"
    out.mkdir()
    e2e.write_footage(e2e.load_clip(clip), out, encode=True)
    for path in (out / "video.mp4", out / "hls" / "720p" / "index.m3u8", out / "hls" / "480p" / "index.m3u8"):
        assert {0, 50, 100, 150, 200} <= set(keys(path)), path
    for rung in ("720p", "480p"):
        text = (out / "hls" / rung / "index.m3u8").read_text()
        lengths = [float(x.split(":")[1].rstrip(",")) for x in text.splitlines() if x.startswith("#EXTINF")]
        assert lengths == pytest.approx([4.0, 4.0, 1.2], abs=1 / FPS), rung


def r128(path) -> tuple[float, float]:
    """Integrated loudness (LUFS) and true peak (dBFS) of a file's sound, by ffmpeg's ebur128."""
    cmd = ["ffmpeg", "-nostats", "-i", str(path), "-vn", "-af", "ebur128=framelog=quiet:peak=true",
           "-f", "null", "-"]
    err = subprocess.run(cmd, capture_output=True, text=True).stderr
    return (float(re.findall(r"I:\s+(-?[\d.]+) LUFS", err)[-1]),
            float(re.findall(r"Peak:\s+(-?[\d.]+) dBFS", err)[-1]))


def bed_of(tmp_path, expr: str):
    bed = tmp_path / "bed.wav"
    source = ["-f", "lavfi", "-i", f"aevalsrc={expr}:s=48000:d=9.2"]
    subprocess.run(["ffmpeg", "-y", "-loglevel", "error", *source, "-ac", "1", str(bed)], check=True)
    return bed


def test_a_quiet_crowd_bed_is_brought_to_broadcast_loudness(tmp_path):
    # The 8324 bed was rendered at -28.2 LUFS, too quiet to hear on a laptop: one gain to BED_LUFS.
    bed = bed_of(tmp_path, "0.02*(random(0)*2-1)")  # a crowd's hiss, about -33 LUFS
    assert r128(bed)[0] < footage.BED_LUFS - 5
    out = tmp_path / "bundle"
    out.mkdir()
    e2e.write_footage(clip_of(tmp_path), out, encode=True, audio=bed)
    assert r128(out / "video.mp4")[0] == pytest.approx(footage.BED_LUFS, abs=1.0)


def test_the_gain_never_clips_the_whistles(tmp_path, monkeypatch):
    # A whistle near full scale in a bed the gain lifts a long way: the true-peak limiter holds it.
    bed = bed_of(tmp_path, "0.8*sin(2*PI*3200*t)*between(t\\,4\\,4.4)+0.02*(random(0)*2-1)")
    monkeypatch.setattr(footage, "bed_gain", lambda audio, timescale=1.0, **kw: 19.0)  # a long lift
    out = tmp_path / "bundle"
    out.mkdir()
    e2e.write_footage(clip_of(tmp_path), out, encode=True, audio=bed)
    assert r128(out / "video.mp4")[1] <= footage.PEAK_DBTP + 0.5  # AAC's own overshoot: half a dB


def test_the_gain_is_corrected_for_what_the_limiter_takes_off_a_peaky_bed(monkeypatch):
    # The 8324 bed lost about 2 LU in the limiter: one gain from its raw loudness aired at -23.0.
    # Modelled here: the chain gives the raw level plus the gain, less 2 LU once it limits.
    raw, loss = -28.1, 2.0

    def measured(audio, chain=""):
        if not chain:
            return raw
        gain = float(re.search(r"volume=(-?[\d.]+)dB", chain)[1])
        return raw + gain - loss
    monkeypatch.setattr(footage, "loudness", measured)
    gain = footage.bed_gain(Path("bed.wav"), 1.25)
    assert measured(None, footage._chain(1.25, gain)) == pytest.approx(footage.BED_LUFS, abs=0.3)


def test_a_screechy_whistle_is_tamed_but_stays_clear_over_the_crowd(tmp_path):
    # Kian, Oct 27: once the bed was lifted the whistle screeched. A whistle 30+ dB over the crowd in
    # its band is found and its band cut inside it; it stays at least 10 dB over the crowd.
    import numpy as np

    bed = bed_of(tmp_path, "0.05*(random(0)*2-1)+0.6*sin(2*PI*3400*t)*between(t\\,4\\,4.6)")
    tamed = footage.whistles(bed)
    assert len(tamed) == 1 and tamed[0][0] <= 4.0 and tamed[0][1] >= 4.6

    def band(af: str) -> float:
        cut = ["ffmpeg", "-loglevel", "error", "-i", str(bed), "-af", af, "-ac", "1", "-ar", "16000",
               "-f", "s16le", "-"]
        x = np.frombuffer(subprocess.run(cut, capture_output=True, check=True).stdout, dtype=np.int16) / 32768
        n = 800
        f = x[: len(x) // n * n].reshape(-1, n) * np.hanning(n)
        sp, fr = np.abs(np.fft.rfft(f, axis=1)) ** 2, np.fft.rfftfreq(n, 1 / 16000)
        db = 10 * np.log10(sp[:, (fr >= 2500) & (fr <= 4500)].sum(axis=1) + 1e-12)
        return float(db.max() - np.median(db))  # the whistle over the crowd, in its band

    before, after = band("anull"), band(footage._chain(1.0, 0.0, tamed))
    assert before > 30 and 10 <= after <= before - 10
