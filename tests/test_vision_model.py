"""The detector's name, size and version have one source of truth, and it matches the pin."""

import importlib.metadata
import re
import tomllib
from pathlib import Path

import pytest

from ninety.vision import model as vision_model

ROOT = Path(__file__).resolve().parent.parent


def _pin(pyproject: dict) -> str:
    """The exact rfdetr version in the vision group; refuses anything but a single `==` pin."""
    pins = [d for d in pyproject["dependency-groups"]["vision"] if re.match(r"rfdetr\b", d)]
    if len(pins) != 1:
        raise ValueError(f"expected one rfdetr requirement in the vision group, found {pins}")
    # the train extra (PyTorch Lightning) is allowed; plus, which installs the PML-1.0 sizes, is not
    m = re.fullmatch(r"rfdetr(?:\[train\])?==([0-9][0-9A-Za-z.]*)", pins[0].replace(" ", ""))
    if not m:
        raise ValueError(f"rfdetr must be pinned to an exact version with ==, not {pins[0]!r}")
    return m.group(1)


def _locked(lock: dict, name: str) -> str:
    versions = [p["version"] for p in lock["package"] if p["name"] == name]
    if len(versions) != 1:
        raise ValueError(f"expected one locked {name}, found {versions}")
    return versions[0]


def test_size_is_small():
    assert vision_model.SIZE == "small"
    assert vision_model.model().size == "small"


def test_version_matches_the_pin_and_the_lock():
    pyproject = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    lock = tomllib.loads((ROOT / "uv.lock").read_text(encoding="utf-8"))
    assert _pin(pyproject) == vision_model.VERSION
    assert _locked(lock, "rfdetr") == vision_model.VERSION


def test_version_matches_the_installed_package():
    try:
        installed = importlib.metadata.version("rfdetr")
    except importlib.metadata.PackageNotFoundError:
        pytest.skip("rfdetr is not installed (uv sync --group vision)")
    assert installed == vision_model.VERSION


def test_model_field_is_valid_for_detections_jsonl():
    m = vision_model.model("ours-v1")
    assert (m.name, m.size, m.version, m.checkpoint) == ("rf-detr", "small", vision_model.VERSION, "ours-v1")
    assert vision_model.model().checkpoint == "coco"


@pytest.mark.parametrize(
    "deps",
    [
        ["rfdetr>=1.11.2"],  # a range, not a pin
        ["rfdetr"],  # no version
        ["rfdetr[plus]==1.11.2"],  # the PML-1.0 extra
        ["rfdetr[train,plus]==1.11.2"],  # plus smuggled in beside train
        [],  # missing
        ["rfdetr==1.11.2", "rfdetr==1.11.1"],  # ambiguous
    ],
)
def test_pin_check_refuses_anything_but_one_exact_pin(deps):
    with pytest.raises(ValueError):
        _pin({"dependency-groups": {"vision": deps}})
