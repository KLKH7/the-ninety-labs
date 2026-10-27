"""Footage played faster as its 1x (Kian, Oct 26: the demo at 1.25): every image is kept and shown at
fps x timescale a video second, and every reader that maps video time to match time maps through
footage.timescale (ninety/match/timeline.py), so nothing on screen or in the ear drifts from the
picture. One image stays one match frame."""

from __future__ import annotations

import json
import subprocess

import pytest

from ninety import e2e, footage
from ninety.match.timeline import Timeline
from ninety.speech import describe as d
from tests.test_describe import BUSY

K = 1.25
SEGS = [{"index": 0, "frame": 1500, "frames": 40}, {"index": 40, "frame": 1550, "frames": 35}]


@pytest.mark.parametrize("image", [0, 10, 39, 40, 45, 74])
def test_an_image_is_one_match_frame_shown_for_1_over_fps_x_timescale_of_video(image):
    t = Timeline(SEGS, 25, K)
    video_t = (image + 0.5) / (25 * K)
    frame = 1500 + image if image < 40 else 1550 + image - 40
    assert t.to_match(video_t) == pytest.approx((frame + 0.5) / 25, abs=1e-9)
    assert t.to_video((frame + 0.5) / 25) == pytest.approx(video_t, abs=1e-9)  # and back, across the cut


def test_a_clip_s_timescale_comes_from_its_meta_and_defaults_to_1():
    meta = {"fps": 25, "t_start": 60.0, "frames": 75, "segments": SEGS}
    assert Timeline.of_clip(meta).timescale == 1.0
    assert Timeline.of_clip({**meta, "timescale": K}).video_fps == 25 * K


def test_the_voice_never_overlaps_itself_on_faster_footage_and_its_lag_is_heard_in_video_seconds():
    # A line spoken for s seconds covers s x timescale of match: scheduled as s, the next line would
    # start while the voice is still speaking.
    plain, _ = d.describe(BUSY, [])
    fast, _ = d.describe(BUSY, [], timescale=K)
    for a, b in zip(fast.said, fast.said[1:], strict=False):
        assert b.t_in >= a.t_in + a.duration_s * K + d.GAP_S * K - 0.011, (a.id, b.id)
    assert all(0 <= s.lag_s <= d.MAX_LAG_S for s in fast.said)
    assert len(fast.said) < len(plain.said)  # less room: more of the busy passage is left unsaid


def test_the_description_captions_last_as_long_as_the_line_is_heard(tmp_path):
    track, refused = d.describe(BUSY, [], timescale=K)
    timeline = Timeline([{"index": 0, "frame": 0, "frames": 400}], 25, K)
    d.write_track(track, refused, tmp_path, 0.0, timeline=timeline)
    first = track.said[0]
    cue = (tmp_path / "description.vtt").read_text().split(first.id + "\n", 1)[1].split(" ")
    start, end = (sum(float(x) * 60 ** i for i, x in enumerate(reversed(c.split(":"))))
                  for c in (cue[0], cue[2]))
    assert start == pytest.approx(first.t_in / K, abs=0.002)
    assert end - start == pytest.approx(first.duration_s, abs=0.002)


@pytest.mark.skipif(not footage.can_encode(), reason=f"needs ffmpeg with {footage.ENCODER} (macOS)")
def test_the_encode_keeps_every_image_at_fps_x_timescale_with_the_sound_sped_up_with_it(tmp_path):
    from tests.test_footage_encode import clip_of, probe, video_stream

    clip = clip_of(tmp_path)  # 230 images at 25 fps: 9.2 s of match
    crowd = tmp_path / "crowd.wav"
    subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-f", "lavfi", "-i", "sine=f=220:d=9.2",
                    str(crowd)], check=True)
    out = tmp_path / "bundle"
    out.mkdir()
    f = footage.write(sorted((clip.dir / "images").glob("*.jpg")), 25, out, crowd, 720, 1280, timescale=K)
    assert (f["fps"], f["timescale"], f["frames"]) == (25, K, 230)
    assert f["duration_s"] == pytest.approx(230 / (25 * K), abs=0.001)  # 7.36 s of video
    for path in (out / "video.mp4", out / "hls" / "720p" / "index.m3u8"):
        v = video_stream(path)
        assert int(v["nb_read_frames"]) == 230 and float(v["start_time"]) == 0.0  # no image dropped
        packets = probe(path, "-select_streams", "v", "-show_entries", "packet=pts_time,flags")["packets"]
        key_s = [float(p["pts_time"]) for p in packets if "K" in p["flags"]]
        # every 2 s of video, on the first image at or after it (1/31.25 s apart), nothing between
        assert key_s == pytest.approx([0.0, 2.0, 4.0, 6.0], abs=1 / (25 * K)), path
    (a,) = probe(out / "video.mp4", "-select_streams", "a", "-show_entries", "stream=duration")["streams"]
    assert float(a["duration"]) == pytest.approx(9.2 / K, abs=0.1)  # the crowd sped with the picture


def test_e2e_sets_the_timescale_only_on_encoded_video(tmp_path):
    from tests.e2e_clip import write_clip

    clip, detections, events = write_clip(tmp_path)
    e2e.main([str(clip), "--out", str(tmp_path / "b"), "--detections", str(detections), "--frames",
              "--events-file", str(events), "--timescale", str(K)])
    manifest = json.loads((tmp_path / "b" / "manifest.json").read_text())
    assert manifest["footage"]["kind"] == "frames"
    assert "timescale" not in manifest["footage"]  # JPEG frames play as made


def test_a_highlight_s_window_is_cut_from_the_images_its_video_times_show(tmp_path):
    from ninety import highlights

    images = []
    (tmp_path / "images").mkdir()
    for i in range(75):
        p = tmp_path / "images" / f"{i:05d}.jpg"
        p.write_bytes(b"\xff\xd8")
        images.append(p)
    reel = {"moments": [{"event": "g1", "t": 62.4, "clip": [60.4, 62.8]}]}
    highlights.record(reel, Timeline(SEGS, 25, K), images, tmp_path / "out", encode=False)
    rec = reel["moments"][0]["recording"]
    # 60.4 s is image 10 and 62.8 s is image 60 (past the cut), at 31.25 images a video second.
    assert rec["images"] == [10, 60] and rec["shot_image"] == 50
    assert rec["video_t"] == [round(10 / (25 * K), 2), round(60 / (25 * K), 2)]
