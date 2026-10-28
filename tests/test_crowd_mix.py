"""The recorded crowd (ninety/render/crowd_mix.py): the same mix from the same seed, a limiter that
holds, seamless bed joins, reactions that do not stack, and only allow-listed licences used."""

from __future__ import annotations

import hashlib
import json

import numpy as np
import pytest

from ninety.render import crowd_mix as cm

R = cm.RATE


def noise(seconds: float, seed: int, level: float = 0.1) -> np.ndarray:
    return (np.random.default_rng(seed).standard_normal(int(seconds * R)) * level).astype(np.float32)


def clips() -> dict:
    return {"bed": [noise(8, 1), noise(9, 2, 0.3), noise(7, 3, 0.05)],
            "roar": [(noise(10, 4, 0.5), 1.0), (noise(9, 5, 0.6), 1.2)],
            "ooh": [(noise(6, 6, 0.3), 1.5)], "lift": [(noise(4, 7), 1.0)]}


CUES = [(3.0, "lift"), (8.0, "ooh"), (12.0, "ooh"), (12.5, "roar"), (25.0, "lift")]
CALLS = [(1.0, "kickoff"), (12.6, "foul"), (29.0, "full_time")]


def test_same_seed_same_mix_and_another_seed_differs():
    a = cm.mix(32, CUES, CALLS, clips(), seed=7)
    b = cm.mix(32, CUES, CALLS, clips(), seed=7)
    c = cm.mix(32, CUES, CALLS, clips(), seed=8)
    assert len(a) == 32 * R
    assert np.array_equal(a, b)
    assert not np.array_equal(a, c)


def test_limiter_holds_on_a_track_far_over_full_scale():
    x = noise(5, 9, 3.0)  # peaks around 12x full scale
    y = cm.limit(x)
    assert float(np.abs(y).max()) <= cm.CEILING + 1e-6
    quiet = noise(5, 10, 0.01)  # well under the ceiling: untouched
    assert np.allclose(cm.limit(quiet), quiet, atol=1e-7)


def test_mix_holds_the_ceiling_with_roars_and_whistles_over_a_loud_bed():
    loud = {**clips(), "bed": [noise(8, 11, 0.9)]}
    y = cm.mix(30, CUES + [(14.0, "roar")], CALLS + [(14.0, "foul")], loud, seed=0)
    assert float(np.abs(y).max()) <= cm.CEILING + 1e-6


def test_bed_has_no_seam_jumps():
    # Pieces at very different levels are brought to one RMS and crossfaded: the short-term level
    # never steps by more than 3 dB a quarter second.
    y = cm.bed(60, clips()["bed"], seed=3)
    q = R // 4
    rms = np.sqrt((y[: len(y) // q * q].reshape(-1, q) ** 2).mean(axis=1))
    db = 20 * np.log10(rms)
    assert np.abs(np.diff(db)).max() < 3.0
    assert abs(float(np.median(db)) - cm.BED_DBFS) < 1.0


def test_a_shot_inside_a_goal_roar_is_dropped_and_a_goal_never_is():
    kept = cm.schedule([(12.0, "ooh"), (12.5, "roar"), (13.0, "ooh"), (13.5, "roar"), (40.0, "ooh")], clips())
    assert kept == [(12.0, "ooh"), (12.5, "roar"), (13.5, "roar"), (40.0, "ooh")]


def manifest(tmp_path, licence: str, data: bytes = b"RIFF fake", digest: str | None = None):
    (tmp_path / "x.wav").write_bytes(data)
    m = tmp_path / "m.json"
    m.write_text(json.dumps({"sources": [{"name": "x", "file": "x.wav", "licence": licence,
                                          "sha256": digest or hashlib.sha256(data).hexdigest(),
                                          "bed": [[0, 1]]}]}))
    return m


@pytest.mark.parametrize("licence", ["CC-BY-NC-4.0", "CC-BY-NC-SA-4.0", "CC-BY-ND-4.0", None, "cc0"])
def test_a_licence_off_the_allow_list_is_refused(tmp_path, licence):
    with pytest.raises(cm.LicenceRefused):
        cm.load(tmp_path, manifest(tmp_path, licence))


def test_a_source_whose_bytes_changed_is_refused(tmp_path):
    with pytest.raises(ValueError, match="sha256"):
        cm.load(tmp_path, manifest(tmp_path, "CC0-1.0", digest="0" * 64))


def test_the_shipped_sources_are_all_cc0_and_pinned():
    spec = json.loads(cm.MANIFEST.read_text())
    assert spec["sources"]
    for src in spec["sources"]:
        cm.check_licence(src)
        assert src["licence"] == "CC0-1.0" and len(src["sha256"]) == 64 and src["url"].startswith("https://freesound.org/")
        for a, onset, b in (c for cuts in src.get("reactions", {}).values() for c in cuts):
            assert a < onset < b
            for x0, x1, _ in src.get("excluded", []):
                assert b <= x0 or a >= x1, f"{src['name']}: reaction {a}-{b} overlaps excluded {x0}-{x1}"
        for a, b in src.get("bed", []):
            for x0, x1, _ in src.get("excluded", []):
                assert b <= x0 or a >= x1
