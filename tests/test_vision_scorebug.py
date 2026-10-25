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

from ninety.eval.event_score import WINDOW_S  # W's source: the window every detected event is graded in
from ninety.vision import scorebug as sb

GLYPHS = sb.load_glyphs()


def frame(home, away, goal_w=0, face="arial-bold", h=720, w=1280, pop=0.0):
    """A 720-line frame: a mid-grey picture, the plate goal_w px right of its 28 px margin, digits.
    `pop` (0 to 1) lifts and enlarges the home digit as render.js does in a goal's first 0.5 s."""
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
        if side == "home" and pop:
            k = 1 + 0.18 * pop  # render.js: scale 1 + 0.18 pop, lifted 5 pop px
            big = Image.fromarray(cell.astype(np.uint8)).resize((round(sb.CELL_W * k), round(sb.CELL_H * k)))
            cell = np.asarray(big, dtype=float)[: sb.CELL_H, : sb.CELL_W]
            y -= round(5 * pop)
        patch = g[y:y + sb.CELL_H, x:x + sb.CELL_W]
        g[y:y + sb.CELL_H, x:x + sb.CELL_W] = np.maximum(patch, cell)
    return g


def test_the_plate_is_found_where_it_is_drawn_and_follows_the_goal_panel():
    assert sb.plate_x(frame(1, 1)) == 28
    assert sb.plate_x(frame(1, 1, goal_w=96)) == 28 + 96
    assert sb.plate_x(np.full((720, 1280), 120.0)) is None  # no bug drawn: nothing to read


def test_a_dark_band_wider_than_the_plate_is_not_the_plate():
    g = frame(1, 1)
    g[sb.BUG_TOP:sb.BUG_TOP + sb.BUG_H, 28:28 + sb.PLATE_W + 80] = 14.0
    g[sb.BUG_TOP + sb.UNDERLINE:sb.BUG_TOP + sb.BUG_H, 28:28 + sb.PLATE_W + 80] = 255.0
    assert sb.plate_x(g) is None


def test_the_popped_digit_is_still_the_best_reading_though_not_accepted():
    got = sb.read_frame(frame(2, 1, pop=1.0), GLYPHS)
    assert got["home"][3] == 2  # the best digit, which the frame-accurate timing uses
    assert got["home"][0] is None  # but under the acceptance bar: never held as a score


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


def scored(samples):
    """The changes alone: what sb.changes gives, less the first held score (team None)."""
    found, summary = sb.changes(samples)
    return [c for c in found if c["team"]], summary


def test_the_first_held_score_is_read_with_no_side():
    found, _ = sb.changes([S(0, 0, 0), S(1, 0, 0), S(2, 0, 0)])
    assert [(c["team"], c["score"], c["frame"]) for c in found] == [(None, {"home": 0, "away": 0}, 0)]
    assert sb.changes([S(0, 0, 0), S(1, 1, 0)])[0] == []  # nothing held: nothing read


def test_one_goal_held_for_stable_samples_is_one_change():
    samples = [S(0, 1, 1), S(1, 1, 1), S(2, 2, 1), S(3, 2, 1), S(4, 2, 1)]
    found, summary = scored(samples)
    want = [("home", {"home": 2, "away": 1}, 2 * sb.FPS)]
    assert [(c["team"], c["score"], c["frame"]) for c in found] == want
    assert summary["inconsistent"] == 0


def test_a_reading_that_does_not_hold_is_no_change():
    samples = [S(0, 1, 1), S(1, 1, 1), S(2, 2, 1)] + [S(3, 1, 1), S(4, 1, 1)]
    assert scored(samples)[0] == []


def test_anything_but_one_goal_on_one_side_is_counted_not_emitted():
    jump = [S(0, 1, 1), S(1, 1, 1), S(2, 3, 1), S(3, 3, 1)]  # two goals at once: a misread
    found, summary = scored(jump)
    assert found == [] and summary["inconsistent"] == 1
    both = [S(0, 1, 1), S(1, 1, 1), S(2, 2, 2), S(3, 2, 2)]
    assert scored(both)[0] == []
    down = [S(0, 2, 1), S(1, 2, 1), S(2, 1, 1), S(3, 1, 1)]
    assert scored(down)[0] == []


def test_an_unread_sample_breaks_the_run():
    samples = [S(0, 1, 1), S(1, 1, 1), S(2, 2, 1), S(3, None, None), S(4, 2, 1), S(5, 2, 1)]
    found, _ = scored(samples)
    assert [c["frame"] for c in found] == [4 * sb.FPS]


def test_a_staged_clip_gives_a_change_at_its_first_frame(tmp_path):
    clip = tmp_path / "clip"
    (clip / "images").mkdir(parents=True)
    goal = 61  # the first frame showing 2-1
    rows = []
    for f in range(120):
        pop = max(0.0, 1 - (f - goal) / 12) if f >= goal else 0.0  # the pop lasts 0.5 s: 12 frames
        im = frame(2 if f >= goal else 1, 1, goal_w=96 if goal <= f < goal + 30 else 0, pop=pop)
        name = f"images/{f:05d}.jpg"
        Image.fromarray(im.astype(np.uint8)).save(clip / name, quality=90)
        rows.append({"clip": "c", "frame": 1000 + f, "t": round((1000 + f) / 25, 2), "image": name})
    (clip / "index.jsonl").write_text("".join(json.dumps(r) + "\n" for r in rows))
    found, summary = sb.read_clip(clip)
    assert summary["first_held"] == {"home": 1, "away": 1}
    assert [(e["type"], e.get("team"), e["frame"], e["score"]) for e in found] == [
        ("score_read", None, 1000, {"home": 1, "away": 1}),
        ("score_change", "home", 1000 + goal, {"home": 2, "away": 1})]
    assert found[1]["team_confidence"] == found[1]["confidence"]  # the side is a pixel reading

    import jsonschema
    schema = json.loads((sb.Path(__file__).parents[1] / "schemas" / "match_event.schema.json").read_text())
    for e in found:
        jsonschema.validate(e, schema)


def test_the_schema_requires_a_score_exactly_on_score_events_and_a_side_on_all_but_a_read():
    import jsonschema
    import pytest
    schema = json.loads((sb.Path(__file__).parents[1] / "schemas" / "match_event.schema.json").read_text())
    [read, change] = sb.score_events([
        {"frame": 0, "t": 0.0, "team": None, "score": {"home": 0, "away": 0}, "confidence": 0.9},
        {"frame": 9, "t": 0.4, "team": "away", "score": {"home": 0, "away": 1}, "confidence": 0.9}])
    for e in (read, change):
        jsonschema.validate(e, schema)
    bad = [{k: v for k, v in change.items() if k != "score"},  # a change with no score
           {k: v for k, v in change.items() if k != "team"},  # a change with no side
           {"id": "p", "t": 1.0, "type": "pass", "team": "home", "x": 1.0, "y": 1.0, "source": "vision",
            "score": {"home": 0, "away": 0}},  # a score on anything else
           {"id": "p", "t": 1.0, "type": "pass", "x": 1.0, "y": 1.0, "source": "vision"}]  # no side
    for e in bad:
        with pytest.raises(jsonschema.ValidationError):
            jsonschema.validate(e, schema)


def E(i, t, kind, team="home", **kw):
    return {"id": f"v{i}", "t": t, "frame": int(t * 25), "type": kind, "team": team, "x": 90.0, "y": 34.0,
            "source": "vision", "confidence": 0.8} | kw


def change(t, team="home", conf=0.9):
    """The scorebug read 0-0 from the start, then a goal for `team` at t."""
    return sb.score_events([{"frame": 0, "t": 0.0, "team": None, "score": {"home": 0, "away": 0},
                             "confidence": conf},
                            {"frame": int(t * 25), "t": t, "team": team, "score": {"home": 1, "away": 0},
                             "confidence": conf}])


def test_a_vision_goal_the_scorebug_shows_is_confirmed_and_more_confident():
    goal = E(1, 10.0 + WINDOW_S - 0.04, "goal", confidence=0.6)
    out, summary = sb.reconcile([goal], change(10.0))
    [g] = [e for e in out if e["type"] == "goal"]
    assert g["id"] == "v1" and g["confidence"] == round(1 - 0.4 * 0.1, 3)
    assert summary == {"confirmed": 1, "added": 0, "held": []}


def test_a_scorebug_goal_vision_missed_is_added_with_its_scorer_and_assist_by_look_back():
    events = [E(1, 2.0, "pass", player="h-t4", receiver="h-t9", outcome="success"),
              E(2, 5.0, "pass", player="h-t3", receiver="h-t9", outcome="success"),
              E(3, 6.0, "shot", player="h-t9")]
    out, summary = sb.reconcile(events, change(7.5))
    [g] = [e for e in out if e["type"] == "goal"]
    assert (g["player"], g["assist"], g["team"], g["x"]) == ("h-t9", "h-t3", "home", 105.0)
    assert g["team_confidence"] == 0.9  # its side is the reader's pixel reading, not certain
    assert summary["added"] == 1

    import jsonschema
    schema = json.loads((sb.Path(__file__).parents[1] / "schemas" / "match_event.schema.json").read_text())
    jsonschema.validate(g, schema)


def test_look_back_stops_at_the_other_side_and_at_its_horizon():
    took = [E(1, 6.0, "shot", player="h-t9"), E(2, 6.5, "possession_change", team="away")]
    assert [e["player"] for e in sb.reconcile(took, change(7.5))[0] if e["type"] == "goal"] == [None]
    old = [E(1, 7.5 - sb.LOOKBACK_S - 0.5, "shot", player="h-t9")]
    assert [e["player"] for e in sb.reconcile(old, change(7.5))[0] if e["type"] == "goal"] == [None]
    unnamed = [E(1, 2.0, "pass", player="h-t4", receiver="h-t9", outcome="success"),
               E(2, 6.0, "shot", player=None)]
    [g] = [e for e in sb.reconcile(unnamed, change(7.5))[0] if e["type"] == "goal"]
    assert g["player"] is None and g["assist"] is None  # no scorer named: no assist to him either


def test_a_vision_goal_no_score_change_confirms_is_held_back():
    late = E(1, 10.0 + WINDOW_S + 0.2, "goal")  # just outside W of the change
    other = E(2, 10.0, "goal", team="away")  # the other side's
    out, summary = sb.reconcile([late, other], change(10.0))
    assert [e["id"] for e in out if e["type"] == "goal"] == ["g00001"]  # added from the +1 alone
    assert summary["held"] == ["v1", "v2"]


def test_with_no_score_ever_read_the_goals_pass_through():
    goal = E(1, 10.0, "goal")  # a fixed tactical view draws no bug: the scorebug says nothing
    out, summary = sb.reconcile([goal], [])
    assert out == [goal] and summary["scorebug"] == "unread"


def test_an_added_away_goal_is_placed_on_the_goal_line_away_attacks():
    [g] = [e for e in sb.reconcile([], change(5.0, team="away"))[0] if e["type"] == "goal"]
    assert (g["team"], g["x"]) == ("away", 0.0)


def test_the_assist_is_a_completed_pass_to_the_scorer_in_this_attack():
    shot = E(9, 6.0, "shot", player="h-t9")
    for passes, want in (
        ([E(1, 5.0, "pass", player="h-t3", receiver="h-t8", outcome="success")], None),  # to another
        ([E(1, 5.0, "pass", player="h-t3", receiver="h-t9", outcome="fail")], None),  # not completed
        ([E(1, 2.0, "pass", player="h-t3", receiver="h-t9", outcome="success"),
          E(2, 3.0, "possession_change", team="away"), E(3, 4.0, "possession_change", team="home")], None),
    ):
        [g] = [e for e in sb.reconcile(passes + [shot], change(7.0))[0] if e["type"] == "goal"]
        assert g["assist"] == want, passes


def test_a_misread_jump_is_not_adopted_so_the_next_goal_still_counts():
    # 9-0, then "1-0" (a 10 read as 1: two digits are wider than the cell), then really 9-1.
    samples = [S(0, 9, 0), S(1, 9, 0), S(2, 1, 0), S(3, 1, 0), S(4, 9, 1), S(5, 9, 1)]
    found, summary = scored(samples)
    assert [(c["team"], c["score"]) for c in found] == [("away", {"home": 9, "away": 1})]
    assert summary["inconsistent"] == 1


def test_a_change_is_searched_from_the_last_sample_that_read_the_old_score():
    seen = []
    samples = [S(0, 1, 1), S(1, 1, 1), S(2, None, None), S(3, 2, 1), S(4, 2, 1)]
    sb.changes(samples, lambda lo, hi, side, value: seen.append((lo, hi)) or (lo + 1, 0.0))
    assert seen == [(1 * sb.SAMPLE_FRAMES, 3 * sb.SAMPLE_FRAMES)]  # from sample 1, not the unread 2


def test_a_second_goal_is_searched_from_the_first_goal_s_held_score():
    seen = []
    samples = [S(0, 1, 1), S(1, 1, 1), S(2, 2, 1), S(3, 2, 1), S(4, 3, 1), S(5, 3, 1)]
    sb.changes(samples, lambda lo, hi, side, value: seen.append(lo) or (hi, 0.0))
    assert seen == [1 * sb.SAMPLE_FRAMES, 3 * sb.SAMPLE_FRAMES]


def test_a_1080_line_picture_is_read_at_its_own_scale():
    small = frame(3, 7)
    big = np.asarray(Image.fromarray(small.astype(np.uint8)).resize((1920, 1080)), dtype=float)
    got = sb.read_frame(big, GLYPHS)
    assert (got["home"][0], got["away"][0]) == (3, 7)


def test_a_poor_match_is_not_accepted_however_far_ahead():
    g = frame(4, 4)
    for x0 in (28 + sb.DIGIT_X["home"], 28 + sb.DIGIT_X["away"]):  # heavy noise on each digit only
        c = (slice(sb.BUG_TOP + 8, sb.BUG_TOP + 32), slice(x0 - 2, x0 + 14))
        g[c] = np.clip(g[c] + np.random.default_rng(0).normal(0, 75, g[c].shape), 0, 255)
    got = sb.read_frame(g, GLYPHS)
    for k in ("home", "away"):
        digit, ncc, margin, best = got[k]
        assert best == 4 and ncc < sb.MIN_NCC and margin >= sb.MIN_MARGIN  # the premise
        assert digit is None


def test_a_clip_with_a_cut_is_sampled_by_frame_number(tmp_path):
    clip = tmp_path / "clip"
    (clip / "images").mkdir(parents=True)
    rows = []
    frames = list(range(0, 35)) + list(range(45, 130))  # a cut leaves out frames 35 to 44
    for n, f in enumerate(frames):
        name = f"images/{n:05d}.jpg"
        Image.fromarray(frame(0 if f < 45 else 1, 0).astype(np.uint8)).save(clip / name, quality=90)
        rows.append({"clip": "c", "frame": f, "t": f / 25, "image": name})
    (clip / "index.jsonl").write_text("".join(json.dumps(r) + "\n" for r in rows))
    found, summary = sb.read_clip(clip)
    assert [r[0] for r in summary["readings"]] == [0, 25, 45, 70, 95, 120]  # 45: the first after the cut
    assert [(e["type"], e["frame"]) for e in found] == [("score_read", 0), ("score_change", 45)]


def test_the_left_digit_is_home_s_by_the_renderer_s_draw_order():
    got = sb.read_frame(frame(3, 7), GLYPHS)  # frame() draws home at DIGIT_X["home"], left of away
    assert sb.DIGIT_X["home"] < sb.DIGIT_X["away"]
    assert (got["home"][0], got["away"][0]) == (3, 7)


def test_the_grader_tables_refused_reads(tmp_path):
    from ninety.eval import scorebug_score
    clip = tmp_path / "seed920101"
    clip.mkdir()
    (clip / "meta.json").write_text(json.dumps({"seed": 920101}))
    (clip / "frames.jsonl").write_text(json.dumps({"frame": 0, "t": 0.0}) + "\n")
    (clip / "events.jsonl").write_text("")
    (tmp_path / "s.jsonl").write_text("")
    (tmp_path / "s.json").write_text(json.dumps({"inconsistent": 2, "readings": []}))
    report = scorebug_score.score([(clip, tmp_path / "s.jsonl", tmp_path / "s.json", None)])
    assert report["changes"]["refused_reads"] == 2
