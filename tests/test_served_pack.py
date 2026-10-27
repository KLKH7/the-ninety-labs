"""infra/served.py: the served match package (NINETY_SERVED_DIR) packs repeatably, unpacks only at its
pinned hash, and never carries the answer key: simulator positions, ground-truth events, clip.json
keys beyond what a served clip reads, or a folder named like a simulator match."""

import importlib.util
import json
from pathlib import Path

import pytest

from ninety.match import tracking

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("served", ROOT / "infra" / "served.py")
served = importlib.util.module_from_spec(spec)
spec.loader.exec_module(served)


def package(root: Path, frame_source="tracked", event_source="vision", **clip_extra) -> Path:
    root.mkdir()
    (root / "tracked.json").write_text(json.dumps({"frames": [{"t": 0.0, "source": frame_source}]}))
    (root / "detected.jsonl").write_text(json.dumps({"id": "s00-v1", "source": event_source}) + "\n")
    clip = {"clip_id": "m", "seed": 8080, "fps": 25, "frames": 1, "t_start": 0.0, "t_end": 0.0,
            "params": {"width": 1280, "height": 720, "home_code": "LON", "away_code": "LIS"}, **clip_extra}
    (root / "clip.json").write_text(json.dumps(clip))
    reading = {"type": "score_read", "score": {"home": 0, "away": 0}}
    (root / "scorebug.jsonl").write_text(json.dumps(reading) + "\n")
    (root / "frames.jsonl").write_text("{}\n")  # the answer key beside it: never taken
    return root


def test_the_package_packs_repeatably_and_unpacks_to_a_served_clip(tmp_path):
    p = package(tmp_path / "pkg")
    a = served.pack(p, "demo-match", tmp_path / "a.tar.gz")
    assert served.pack(p, "demo-match", tmp_path / "b.tar.gz") == a  # byte for byte
    dest = tmp_path / "served"
    served.unpack(tmp_path / "a.tar.gz", dest, a)
    assert sorted(x.name for x in (dest / "demo-match").iterdir()) == [
        "clip.json", "detected.jsonl", "scorebug.jsonl", "tracked.json"]  # no frames.jsonl
    assert tracking.served_clips(str(dest)) == ("demo-match",)
    with pytest.raises(SystemExit, match="sha256"):
        served.unpack(tmp_path / "a.tar.gz", tmp_path / "other", "0" * 64)


@pytest.mark.parametrize("kwargs, why", [
    ({"frame_source": "truth"}, "tracked.json"),
    ({"event_source": "truth"}, "detected.jsonl"),
])
def test_the_answer_key_is_refused(tmp_path, kwargs, why):
    with pytest.raises(SystemExit, match=why):
        served.pack(package(tmp_path / "pkg", **kwargs), "demo-match", tmp_path / "a.tar.gz")


def test_clip_json_is_cut_to_what_a_served_clip_reads(tmp_path):
    p = package(tmp_path / "pkg", roster=[{"id": "h1"}], window={"first_frame": 0})
    sha = served.pack(p, "demo-match", tmp_path / "a.tar.gz")
    served.unpack(tmp_path / "a.tar.gz", tmp_path / "served", sha)
    clip = json.loads((tmp_path / "served" / "demo-match" / "clip.json").read_text())
    assert "roster" not in clip and "window" not in clip and clip["params"]["home_code"] == "LON"


@pytest.mark.parametrize("clip", ["seed8080", "../x", "a/b"])
def test_a_simulator_name_or_a_path_is_not_a_served_clip(tmp_path, clip):
    with pytest.raises(SystemExit):
        served.pack(package(tmp_path / "pkg"), clip, tmp_path / "a.tar.gz")


def test_the_offline_insights_ride_along_only_for_their_own_clip(tmp_path):
    # Built with the Player ID feed and the camera join, which the API cannot rebuild at runtime.
    p = package(tmp_path / "pkg")
    (tmp_path / "insights.json").write_text(json.dumps({"clip": "demo-match", "per_player": {}}))
    sha = served.pack(p, "demo-match", tmp_path / "a.tar.gz", insights=tmp_path / "insights.json")
    served.unpack(tmp_path / "a.tar.gz", tmp_path / "served", sha)
    unpacked = tmp_path / "served" / "demo-match" / "insights.json"
    assert json.loads(unpacked.read_text())["clip"] == "demo-match"
    (tmp_path / "other.json").write_text(json.dumps({"clip": "seed8080-match"}))
    with pytest.raises(SystemExit, match="not this clip's"):
        served.pack(p, "demo-match", tmp_path / "b.tar.gz", insights=tmp_path / "other.json")
