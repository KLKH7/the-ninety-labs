"""One height band per renderer look (ninety/vision/observe.py, BANDS; docs/eval/band-032-plan.md):
each look's band is its own validation measurement, the look is declared (`--look`), and the default
is the demo's."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from ninety.vision import observe
from tests.test_vision_observe import row, wrong_place_row

ROOT = Path(__file__).resolve().parents[1]


def only_032() -> float:
    """A height ratio inside the 0.3.2 band and outside the default's."""
    lo, hi = observe.BANDS["0.3.2"]
    d_lo, d_hi = observe.HEIGHT_BAND
    ratio = (lo + min(hi, d_lo)) / 2 if lo < d_lo else (max(lo, d_hi) + hi) / 2
    assert lo <= ratio <= hi and not d_lo <= ratio <= d_hi  # the two bands differ there
    return ratio


def clip_at(scale: float, frames: int = 11) -> list[dict]:
    """A clip through a right camera whose players come out `scale` times an upright 1.80 m."""
    rows = []
    for f in range(frames):
        r = wrong_place_row(0.0, f)
        r["players"] = row(scale)["players"]
        rows.append(r)
    return rows


def test_the_032_band_is_the_committed_validation_measurement():
    body = json.loads((ROOT / "docs/eval/band-broadcast-032.json").read_text())
    assert list(observe.BANDS["0.3.2"]) == body["broadcast"]["band"]
    assert body["seeds"] == list(range(108, 120))  # validation clips only, never a test seed
    assert body["renderer"] == "0.3.2"


def test_the_default_look_is_the_demos_and_judges_by_270s_band():
    assert observe.DEFAULT_LOOK == "0.5.15"
    assert observe.BANDS[observe.DEFAULT_LOOK] == observe.HEIGHT_BAND == (0.966, 1.121)
    r = only_032()
    assert not observe.place(row(r))["camera"]["ok"]
    assert observe.place(row(r), band=observe.BANDS["0.3.2"])["camera"]["ok"]


def test_the_032_band_holds_its_ends_and_the_markings_must_still_agree():
    lo, hi = observe.BANDS["0.3.2"]
    band = observe.BANDS["0.3.2"]
    assert observe.place(row(lo + 0.002), band=band)["camera"]["ok"]
    assert observe.place(row(hi - 0.002), band=band)["camera"]["ok"]
    assert not observe.place(row(lo - 0.01), band=band)["camera"]["ok"]
    assert not observe.place(row(hi + 0.01), band=band)["camera"]["ok"]
    assert not observe.place(row(only_032(), markings_ok=False), band=band)["camera"]["ok"]  # B3


@pytest.mark.parametrize(("look", "trusted"), [(None, False), ("0.5.15", False), ("0.3.2", True)])
def test_regate_judges_by_the_declared_looks_band(tmp_path, look, trusted):
    src, out = tmp_path / "in.jsonl", tmp_path / "out.jsonl"
    src.write_text("".join(json.dumps(r) + "\n" for r in clip_at(only_032())))
    observe.main(["--regate", str(src), "--out", str(out)] + (["--look", look] if look else []))
    ok = [json.loads(x)["camera"]["ok"] for x in out.read_text().splitlines()]
    assert all(v is trusted for v in ok)


@pytest.mark.parametrize(("look", "trusted"), [(None, False), ("0.3.2", True)])
def test_a_fitted_clip_is_judged_by_the_declared_looks_band(tmp_path, monkeypatch, look, trusted):
    # The fit is not re-run here: observe() returns a clip judged by the default band, as it does.
    (tmp_path / "images").mkdir()
    out = tmp_path / "out.jsonl"
    fitted = observe.agree([observe.place(r) for r in clip_at(only_032())])
    monkeypatch.setattr(observe, "read_detections", lambda p: [])
    monkeypatch.setattr(observe, "observe", lambda images, dets, load, fixed=False: fitted)
    observe.main([str(tmp_path), "--detections", str(tmp_path / "d.jsonl"), "--out", str(out)]
                 + (["--look", look] if look else []))
    ok = [json.loads(x)["camera"]["ok"] for x in out.read_text().splitlines()]
    assert all(v is trusted for v in ok)


def test_an_undeclared_look_is_refused(tmp_path):
    src = tmp_path / "in.jsonl"
    src.write_text("".join(json.dumps(r) + "\n" for r in clip_at(1.0)))
    with pytest.raises(SystemExit):
        observe.main(["--regate", str(src), "--out", str(tmp_path / "o.jsonl"), "--look", "0.4"])
