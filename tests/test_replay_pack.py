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
    for name in ("cues.jsonl", "trace.json", "detections.jsonl", "events.jsonl", "facts.json"):
        (root / name).write_text("{}\n")
    (root / "frames").mkdir()
    (root / "frames" / "00000.jpg").write_bytes(b"\xff\xd8")
    return root


def test_pack_is_byte_for_byte_repeatable(tmp_path):
    b = bundle(tmp_path / "b")
    first = replay.pack(b, tmp_path / "one.tar.gz")
    (b / "cues.jsonl").touch()  # a new mtime must not change the bytes
    assert replay.pack(b, tmp_path / "two.tar.gz") == first
    assert hashlib.sha256((tmp_path / "one.tar.gz").read_bytes()).hexdigest() == first


ANSWER_KEY_AND_STRAYS = ["frames.jsonl", "clip.json", "meta.json", "images/00000.jpg", "frames/x.json"]


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
