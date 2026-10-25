"""The turnover events' validation harness (ninety/eval/turnover_standin.py): the stand-in observations
are the answer key's places as the detector reads them, and M0 counts each stand-in's disagreements
with the engine's interceptions on planted passes whose answer is known before it runs (lesson 8)."""

from __future__ import annotations

import json

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
