"""The height band's derivation (ninety/eval/band_derive.py) runs on validation clips only."""

import pytest

from ninety.eval import band_derive


@pytest.mark.parametrize("seed", [900004, 910009])
def test_a_test_seed_is_refused_before_anything_is_read(seed, tmp_path):
    with pytest.raises(SystemExit):
        band_derive.derive(tmp_path, tmp_path, [108, seed])
