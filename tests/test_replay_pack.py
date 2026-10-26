"""infra/replay.py: the Replay bundle packs to the same bytes every time, and only viewer files go in."""

import hashlib
import importlib.util
import json
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
spec = importlib.util.spec_from_file_location("replay", ROOT / "infra" / "replay.py")
replay = importlib.util.module_from_spec(spec)
spec.loader.exec_module(replay)


def bundle(root: Path) -> Path:
    root.mkdir()
    (root / "manifest.json").write_text(json.dumps({"format": 1}))
    for name in ("cues.jsonl", "trace.json", "detections.jsonl", "facts.json", "audio.json",
                 "description.vtt"):
        (root / name).write_text("{}\n")
    (root / "events.jsonl").write_text(json.dumps({"id": "v00001", "source": "vision"}) + "\n")
    (root / "audio").mkdir()
    (root / "audio" / "a1.wav").write_bytes(b"RIFF")
    (root / "frames").mkdir()
    (root / "frames" / "00000.jpg").write_bytes(b"\xff\xd8")
    return root


def test_pack_is_byte_for_byte_repeatable(tmp_path):
    b = bundle(tmp_path / "b")
    first = replay.pack(b, tmp_path / "one.tar.gz")
    (b / "cues.jsonl").touch()  # a new mtime must not change the bytes
    assert replay.pack(b, tmp_path / "two.tar.gz") == first
    assert hashlib.sha256((tmp_path / "one.tar.gz").read_bytes()).hexdigest() == first


ANSWER_KEY_AND_STRAYS = ["frames.jsonl", "clip.json", "meta.json", "images/00000.jpg", "frames/x.json",
                         "audio/a1.json"]


@pytest.mark.parametrize("extra", ANSWER_KEY_AND_STRAYS)
def test_pack_refuses_anything_the_viewer_does_not_read(tmp_path, extra):
    b = bundle(tmp_path / "b")
    (b / extra).parent.mkdir(parents=True, exist_ok=True)
    (b / extra).write_text("the answer key")
    with pytest.raises(SystemExit, match="not a viewer file"):
        replay.pack(b, tmp_path / "out.tar.gz")


def test_unpack_refuses_bytes_that_do_not_match_the_pin(tmp_path):
    digest = replay.pack(bundle(tmp_path / "b"), tmp_path / "r.tar.gz")
    with pytest.raises(SystemExit, match="sha256"):
        replay.unpack(tmp_path / "r.tar.gz", tmp_path / "out", "0" * 64)
    replay.unpack(tmp_path / "r.tar.gz", tmp_path / "out", digest)
    assert json.loads((tmp_path / "out" / "manifest.json").read_text()) == {"format": 1}


@pytest.mark.parametrize("event", [{"id": "e1", "source": "truth"}, {"id": "e1"}])
def test_pack_refuses_events_that_are_not_detected(tmp_path, event):
    # A clip's ground-truth events.jsonl has the bundle's file name; only vision's events may ship.
    b = bundle(tmp_path / "b")
    detected = json.dumps({"id": "v00001", "source": "vision"})
    (b / "events.jsonl").write_text(detected + "\n" + json.dumps(event) + "\n")
    with pytest.raises(SystemExit, match="not a detected event"):
        replay.pack(b, tmp_path / "out.tar.gz")


def test_a_bundle_made_with_the_radar_match_mode_and_live_agents_packs(tmp_path):
    # ninety-e2e --tracked, --match and --agents live write radar.json, match.json and agents.json:
    # all three are viewer files, so a demo bundle made with them can be published.
    b = bundle(tmp_path / "b")
    for name in ("radar.json", "match.json", "agents.json"):
        (b / name).write_text("{}\n")
    names = [p.relative_to(b).as_posix() for p in replay.members(b)]
    assert {"radar.json", "match.json", "agents.json"} <= set(names)


def test_every_file_ninety_e2e_writes_is_one_the_pack_publishes(tmp_path):
    # #328: the bundle gained commentary.json and the image build refused it. A real bundle, as
    # ninety-e2e writes it, must pack, so the next file it adds is caught here, not in the image job.
    from ninety import e2e
    from tests.e2e_clip import write_clip

    clip, detections, events = write_clip(tmp_path)
    out = tmp_path / "bundle"
    e2e.main([str(clip), "--out", str(out), "--detections", str(detections), "--frames",
              "--events-file", str(events)])
    files = set(json.loads((out / "manifest.json").read_text())["files"])
    assert "commentary.json" in files and files <= {p.name for p in replay.members(out)}


def test_every_file_a_manifest_can_list_is_one_the_pack_publishes():
    # Every option's file, not only the default bundle's: the names in ninety-e2e's `files` list
    # (radar.json, match.json, cards.json, agents.json, ...) and the read-aloud step's speech.json.
    import ast

    tree = ast.parse((ROOT / "ninety" / "e2e.py").read_text())
    listed = {node for d in ast.walk(tree) if isinstance(d, ast.Dict)
              for k, v in zip(d.keys, d.values, strict=True)
              if isinstance(k, ast.Constant) and k.value == "files"
              for node in ast.walk(v)}
    names = {n.value for n in listed if isinstance(n, ast.Constant) and isinstance(n.value, str)
             and "." in n.value and " " not in n.value}  # file names, not the mode it compares with
    assert {"cards.json", "commentary.json", "radar.json", "match.json"} <= names  # the list was found
    assert names | {"speech.json"} <= replay.FILES, sorted(names - replay.FILES)


def test_a_bundle_with_every_highlight_recording_packs_and_another_suffix_does_not(tmp_path, monkeypatch):
    # #312: highlights.record writes <event>.jpg and <event>.mp4 under highlights/; the pack refused the
    # folder (the failure #328 hit with commentary.json), so a --match bundle with recordings never shipped.
    from ninety import footage, highlights
    from ninety.match.timeline import Timeline

    images = tmp_path / "images"
    images.mkdir()
    for i in range(50):
        (images / f"{i:05d}.jpg").write_bytes(b"\xff\xd8")
    monkeypatch.setattr(footage, "can_encode", lambda: True)
    monkeypatch.setattr(footage.subprocess, "run", lambda cmd, check: Path(cmd[-1]).write_bytes(b"mp4"))
    timeline = Timeline([{"index": 0, "frame": 1500, "frames": 50}], 25)
    reel = {"moments": [{"event": "v2", "t": 61.0, "clip": [60.4, 61.4]}]}
    b = bundle(tmp_path / "b")
    highlights.record(reel, timeline, sorted(images.glob("*.jpg")), b, encode=True)
    names = [p.relative_to(b).as_posix() for p in replay.members(b)]
    assert "highlights/v2.jpg" in names and "highlights/v2.mp4" in names
    (b / "highlights" / "v2.webm").write_bytes(b"x")  # a suffix the viewer does not read
    with pytest.raises(SystemExit, match="not a viewer file"):
        replay.members(b)
