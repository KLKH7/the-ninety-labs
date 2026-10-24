"""The active-perception evaluation counts what a second look decides and grades it offline."""

import json
from pathlib import Path

from ninety.eval import re_perceive_eval as rpe

ROOT = Path(__file__).resolve().parents[1]


def test_a_clip_whose_other_camera_is_no_surer_leaves_its_team_claims_unresolved(tmp_path):
    # The M1 clip's observations as a second camera: the same reading, no surer, so nothing resolves.
    clip = tmp_path / "seed900001"
    (clip / "views" / "tactical1").mkdir(parents=True)
    (clip / "views" / "tactical1" / "observations.jsonl").write_text(
        (ROOT / "tests/fixtures/observations-seed900001.jsonl").read_text())
    detected = (ROOT / "tests/fixtures/detected-seed900001.jsonl").read_text()
    (clip / "detected.jsonl").write_text(detected)
    first = json.loads(detected.splitlines()[0])
    truth = {**first, "id": "e1", "source": "truth"}  # the answer key, for grading only
    (clip / "events.jsonl").write_text(json.dumps(truth) + "\n")
    rows = rpe.clip_rows(clip)
    assert rows and {r["outcome"] for r in rows} == {"unresolved"}
    assert next(r for r in rows if r["event"] == first["id"])["side_right"] is True


def test_the_summary_counts_a_wrong_resolution_apart():
    rows = [{"outcome": "resolved", "side_right": True, "matched": True},
            {"outcome": "resolved", "side_right": False, "matched": True},
            {"outcome": "resolved", "side_right": None, "matched": False},
            {"outcome": "contradicted", "side_right": False, "matched": True},
            {"outcome": "unresolved", "side_right": None, "matched": False}]
    s = rpe.summary(rows)
    assert (s["held"], s["resolved"], s["resolved_right"], s["resolved_wrong"]) == (5, 3, 1, 1)
    assert (s["resolved_false_event"], s["contradicted_right"], s["unresolved"]) == (1, 1, 1)
