"""The height band's derivation (ninety/eval/band_derive.py) runs on validation clips only."""

import json

import pytest

from ninety.eval import band_derive


@pytest.mark.parametrize("seed", [900004, 910009])
def test_a_test_seed_is_refused_before_anything_is_read(seed, tmp_path):
    with pytest.raises(SystemExit):
        band_derive.derive(tmp_path, tmp_path, [108, seed])


def test_clips_of_two_looks_are_refused_before_a_band_is_made(tmp_path):
    for seed, version in ((108, "0.3.2"), (109, "0.5.15")):
        (tmp_path / f"seed{seed}").mkdir()
        (tmp_path / f"seed{seed}" / "clip.json").write_text(json.dumps({"renderer": {"version": version}}))
    with pytest.raises(SystemExit, match="one band per look"):
        band_derive.derive(tmp_path, tmp_path, [108, 109])
    assert band_derive.derive(tmp_path, tmp_path, [108])["renderer"] == "0.3.2"
