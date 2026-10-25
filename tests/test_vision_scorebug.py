"""The scorebug reader: the plate found where the renderer draws it, the digits read, and a score
change only for one goal on one side, held for STABLE samples and timed at its first frame.

Frames are drawn here as the renderer draws the bug (web/render/render.js, `drawBug`): the dark
plate, its white underline and the digits, pasted from the committed glyphs (lesson 47). Constants
come from the module (lesson 36).
"""

from __future__ import annotations

import json

import numpy as np
from PIL import Image

from ninety.vision import scorebug as sb

GLYPHS = sb.load_glyphs()


def frame(home, away, goal_w=0, face="arial-bold", h=720, w=1280):
    """A 720-line frame: a mid-grey picture, the plate goal_w px right of its 28 px margin, digits."""
    g = np.full((h, w), 120.0)
    x0 = 28 + goal_w
    top = sb.BUG_TOP
    if goal_w:
        g[top:top + sb.BUG_H, 28:x0] = 244.0  # the GOAL panel
    g[top:top + sb.BUG_H, x0:x0 + sb.PLATE_W] = 14.0
    g[top + sb.UNDERLINE:top + sb.BUG_H, x0:x0 + sb.PLATE_W] = 255.0
    for value, side in ((home, "home"), (away, "away")):
        if value is None:
            continue
        cell = GLYPHS[face][value]
        y, x = top + 20 - sb.CELL_H // 2, x0 + sb.DIGIT_X[side] - 2
        patch = g[y:y + sb.CELL_H, x:x + sb.CELL_W]
        g[y:y + sb.CELL_H, x:x + sb.CELL_W] = np.maximum(patch, cell)
    return g


def test_the_plate_is_found_where_it_is_drawn_and_follows_the_goal_panel():
    assert sb.plate_x(frame(1, 1)) == 28
    assert sb.plate_x(frame(1, 1, goal_w=96)) == 28 + 96
    assert sb.plate_x(np.full((720, 1280), 120.0)) is None  # no bug drawn: nothing to read


def test_every_digit_is_read_in_both_faces():
    for face in GLYPHS:
        for d in range(10):
            got = sb.read_frame(frame(d, (d + 3) % 10, face=face), GLYPHS)
            assert (got["home"][0], got["away"][0]) == (d, (d + 3) % 10), (face, d)


def test_a_blank_cell_is_not_read():
    got = sb.read_frame(frame(2, None), GLYPHS)
    assert got["home"][0] == 2 and got["away"][0] is None


def S(i, h, a, ncc=0.95):
    return sb.Sample(i * sb.SAMPLE_FRAMES, i * 1.0, h, a, {"home": ncc, "away": ncc})


def test_one_goal_held_for_stable_samples_is_one_change():
    samples = [S(0, 1, 1), S(1, 1, 1), S(2, 2, 1), S(3, 2, 1), S(4, 2, 1)]
    found, summary = sb.changes(samples)
    want = [("home", {"home": 2, "away": 1}, 2 * sb.FPS)]
    assert [(c["team"], c["score"], c["frame"]) for c in found] == want
    assert summary["inconsistent"] == 0


def test_a_reading_that_does_not_hold_is_no_change():
    samples = [S(0, 1, 1), S(1, 1, 1), S(2, 2, 1)] + [S(3, 1, 1), S(4, 1, 1)]
    assert sb.changes(samples)[0] == []


def test_anything_but_one_goal_on_one_side_is_counted_not_emitted():
    jump = [S(0, 1, 1), S(1, 1, 1), S(2, 3, 1), S(3, 3, 1)]  # two goals at once: a misread
    found, summary = sb.changes(jump)
    assert found == [] and summary["inconsistent"] == 1
    both = [S(0, 1, 1), S(1, 1, 1), S(2, 2, 2), S(3, 2, 2)]
    assert sb.changes(both)[0] == []
    down = [S(0, 2, 1), S(1, 2, 1), S(2, 1, 1), S(3, 1, 1)]
    assert sb.changes(down)[0] == []


def test_an_unread_sample_breaks_the_run():
    samples = [S(0, 1, 1), S(1, 1, 1), S(2, 2, 1), S(3, None, None), S(4, 2, 1), S(5, 2, 1)]
    found, _ = sb.changes(samples)
    assert [c["frame"] for c in found] == [4 * sb.FPS]


def test_a_staged_clip_gives_a_change_at_its_first_frame(tmp_path):
    clip = tmp_path / "clip"
    (clip / "images").mkdir(parents=True)
    goal = 61  # the first frame showing 2-1
    rows = []
    for f in range(120):
        im = frame(2 if f >= goal else 1, 1, goal_w=96 if goal <= f < goal + 30 else 0)
        name = f"images/{f:05d}.jpg"
        Image.fromarray(im.astype(np.uint8)).save(clip / name, quality=90)
        rows.append({"clip": "c", "frame": 1000 + f, "t": round((1000 + f) / 25, 2), "image": name})
    (clip / "index.jsonl").write_text("".join(json.dumps(r) + "\n" for r in rows))
    found, summary = sb.read_clip(clip)
    assert summary["first_held"] == {"home": 1, "away": 1}
    assert [(e["type"], e["team"], e["frame"], e["score"]) for e in found] == [
        ("score_change", "home", 1000 + goal, {"home": 2, "away": 1})]

    import jsonschema
    schema = json.loads((sb.Path(__file__).parents[1] / "schemas" / "match_event.schema.json").read_text())
    jsonschema.validate(found[0], schema)
