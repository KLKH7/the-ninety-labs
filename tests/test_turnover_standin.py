"""The turnover events' validation harness (ninety/eval/turnover_standin.py): the stand-in observations
are the answer key's places as the detector reads them, and M0 counts each stand-in's disagreements
with the engine's interceptions on planted passes whose answer is known before it runs (lesson 8)."""

from __future__ import annotations

import json
import math

from ninety.eval import turnover_standin as ts
from ninety.vision import events as ev
from ninety.vision import track as tr


def frame(f, players, ball, visible=True):
    return {"frame": f, "t": round(f / tr.FPS, 2),
            "players": [{"id": i, "team": team, "x": x, "y": y, "bbox": [0, 0, 5, 5] if visible else None,
                         "visibility": 1.0 if visible else 0.0} for i, team, x, y in players],
            "ball": {"x": ball[0], "y": ball[1], "z": 0.0, "bbox": [0, 0, 2, 2], "visibility": 1.0}}


def test_without_noise_the_stand_in_is_the_answer_keys_places_and_the_broadcast_drops_the_unseen():
    frames = [frame(0, [("h2", "home", 10.0, 20.0)], (11.0, 20.0)),
              frame(1, [("h2", "home", 10.1, 20.0)], (11.1, 20.0), visible=False)]
    whole = ts.observations(frames, 0.0, broadcast=False)
    assert [(p["x"], p["y"], p["rgb"]) for p in whole[1]["players"]] == [(10.1, 20.0, ts.KIT["home"])]
    assert ts.observations(frames, 0.0, broadcast=True)[1]["players"] == []
    noisy = ts.observations(frames, ts.NOISE_M, broadcast=False)
    assert noisy == ts.observations(frames, ts.NOISE_M, broadcast=False)  # seeded
    assert noisy[0]["players"][0]["x"] != 10.0


def planted_match(tmp_path, taken_short: bool):
    """A home pass from (30, 34) along +x at 15 m/s, taken by away player a5 at 10 m or 40 m: the
    engine's answer is written as the test wants it, an interception only for `taken_short`."""
    end = 30.0 + (10.0 if taken_short else 40.0)
    frames = [frame(f, [("h7", "home", 30.0, 34.0), ("a5", "away", end, 34.0)],
                    (min(30.0 + 15.0 * f / tr.FPS, end), 34.0)) for f in range(100)]
    events = [{"id": "e1", "t": 0.0, "frame": 0, "type": "pass", "team": "home", "player": "h7",
               "interceptor": "a5", "end_x": end, "end_y": 34.0, "x": 30.0, "y": 34.0}]
    hit = round((end - 30.0) / 15.0 * tr.FPS)
    if taken_short:
        events.append({"id": "e2", "t": hit / tr.FPS, "frame": hit, "type": "interception", "team": "away",
                       "player": "a5", "x": end, "y": 34.0})
    d = tmp_path / ("short" if taken_short else "long")
    d.mkdir()
    (d / "frames.jsonl").write_text("".join(json.dumps(f) + "\n" for f in frames))
    (d / "events.jsonl").write_text("".join(json.dumps(e) + "\n" for e in events))
    return d


def test_m0_counts_each_rules_disagreements_against_the_engines_interceptions(tmp_path):
    out = ts.m0([planted_match(tmp_path, True), planted_match(tmp_path, False)])
    assert (out["passes"], out["judged"], out["true_interceptions"]) == (2, 2, 1)
    assert out["rules"]["all_interceptions"]["disagree"] == out["rules"]["none"]["disagree"] == 1
    # From 15 m/s the stand-in targets lie 4.0 (pace14), 19.0, 34.3 and 46.6 m (rest) away. Every
    # target but pace14's puts the 10 m take short of 0.85 of it and the 40 m take beyond it; pace14's
    # puts both beyond. Three candidates tie at no disagreement: the first listed is chosen.
    assert 0.85 * ev.roll_distance(15.0, 14.0) < 10.0 < 0.85 * ev.roll_distance(15.0, 10.0)
    assert 0.85 * ev.roll_distance(15.0, 0.0) < 40.0
    assert [out["rules"][n]["disagree"] for n in ev.STAND_INS] == [1, 0, 0, 0]
    assert out["chosen"] == "pace10" and out["beats_constant_rules"]


# Amendment 1: the noise's shares of one offset per clip, one shift per frame, each object's own.


def still_frames(n, players=3):
    return [frame(f, [(f"h{k}", "home", 10.0 + 5 * k, 20.0) for k in range(players)], (50.0, 30.0))
            for f in range(n)]


def errors(rows, frames):
    """Per frame, each object's (dx, dy) from its true place: players in order, then the ball."""
    out = []
    for r, f in zip(rows, frames, strict=True):
        e = [(p["x"] - q["x"], p["y"] - q["y"]) for p, q in zip(r["players"], f["players"], strict=True)]
        out.append(e + [(r["ball"][0]["x"] - f["ball"]["x"], r["ball"][0]["y"] - f["ball"]["y"])])
    return out


def close(a, b):
    return abs(a[0] - b[0]) < 1e-9 and abs(a[1] - b[1]) < 1e-9


def test_a_clips_offset_moves_every_object_in_every_frame_the_same_way():
    frames = still_frames(5)
    err = errors(ts.observations(frames, ts.NOISE_M, False, shares=ts.SHARES["m3"]), frames)
    first = err[0][0]
    assert all(close(e, first) for row in err for e in row) and first != (0.0, 0.0)


def test_a_frames_shift_moves_every_object_in_it_together_and_changes_between_frames():
    frames = still_frames(5)
    err = errors(ts.observations(frames, ts.NOISE_M, False, shares=(0.0, 1.0, 0.0)), frames)
    assert all(close(e, row[0]) for row in err for e in row)
    assert not close(err[0][0], err[1][0])


def test_m1_is_each_objects_own_noise_and_its_rows_are_the_ones_m1_was_run_with():
    frames = still_frames(5)
    rows = ts.observations(frames, ts.NOISE_M, False, shares=ts.SHARES["m1"])
    assert rows == ts.observations(frames, ts.NOISE_M, False)  # the default, as M1 ran
    err = errors(rows, frames)
    assert not close(err[0][0], err[0][1])


def test_every_split_keeps_the_measured_spread():
    # Pooled over many clips (seeds), so the clip's one offset is drawn many times too.
    frames = still_frames(4, players=3)
    for name, shares in ts.SHARES.items():
        assert abs(sum(shares) - 1.0) < 1e-12
        xs = [e[0] for seed in range(600)
              for row in errors(ts.observations(frames, ts.NOISE_M, False, seed=seed, shares=shares), frames)
              for e in row]
        sd = math.sqrt(sum(x * x for x in xs) / len(xs))
        assert abs(sd - ts.NOISE_M) < 0.06 * ts.NOISE_M, (name, sd)


def test_the_shared_parts_take_no_draw_from_the_objects_so_m1s_rows_never_move():
    # M1 was run before amendment 1: its rows are the objects' generator's draws, in order (x then y
    # for each player, then the ball), with nothing drawn between them.
    from ninety.sim import fmath

    frames = still_frames(3, players=2)
    rng = fmath.Random(ts.NOISE_SEED)
    want = [[(rng.gauss(0, ts.NOISE_M), rng.gauss(0, ts.NOISE_M)) for _ in range(3)] for _ in frames]
    got = errors(ts.observations(frames, ts.NOISE_M, False, shares=ts.SHARES["m4"]), frames)
    m1 = errors(ts.observations(frames, ts.NOISE_M, False), frames)
    assert all(close(a, b) for ra, rb in zip(m1, want, strict=True) for a, b in zip(ra, rb, strict=True))
    assert not all(close(a, b) for ra, rb in zip(got, want, strict=True) for a, b in zip(ra, rb, strict=True))
