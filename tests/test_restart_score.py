"""The restart scorer on a planted clip: the answers are known from the plant, not from the scorer
(lesson 8). A throw-in found with its kind, a free kick found at its spot read as a corner, a false
goal kick, a kick-off missed on a frame with no trusted camera."""

from __future__ import annotations

import json

from ninety.eval import restart_score as rsc


def ev(i, frame, kind, team, x, y, source="truth"):
    return {"id": f"{'e' if source == 'truth' else 'r'}{i}", "t": round(frame / 25, 2), "frame": frame,
            "type": kind, "team": team, "player": None, "x": x, "y": y, "source": source}


def plant(tmp_path):
    clip, run = tmp_path / "seed1-100", tmp_path / "run"
    clip.mkdir()
    run.mkdir()
    truth = [ev(1, 110, "out_of_play", "home", 40.0, 68.0), ev(2, 150, "set_piece", "away", 40.0, 68.0),
             ev(3, 160, "foul", "away", 60.0, 20.0), ev(4, 180, "set_piece", "home", 60.0, 20.0),
             ev(5, 190, "goal", "home", 105.0, 34.0), ev(6, 230, "kickoff", "away", 52.5, 34.0)]
    frames = []
    for f in range(100, 241):
        ball = (40.0, 68.0) if f < 156 else (60.0, 20.0) if f < 200 else (52.5, 34.0)
        frames.append({"frame": f, "t": round(f / 25, 2), "ball": {"x": ball[0], "y": ball[1], "z": 0.0},
                       "players": [{"id": "a1", "team": "away", "x": 52.0, "y": 34.3},
                                   {"id": "h1", "team": "home", "x": 60.5, "y": 20.0}]})
    (clip / "events.jsonl").write_text("".join(json.dumps(e) + "\n" for e in truth))
    (clip / "frames.jsonl").write_text("".join(json.dumps(f) + "\n" for f in frames))
    (clip / "meta.json").write_text(json.dumps({"cuts": []}))
    found = [ev(1, 120, "set_piece", "home", 5.5, 34.0, "vision"),
             ev(2, 152, "set_piece", "away", 40.0, 68.0, "vision"),
             ev(3, 181, "set_piece", "home", 60.0, 20.0, "vision")]
    (run / "detected.jsonl").write_text("".join(json.dumps(e) + "\n" for e in found))
    (run / "restarts.json").write_text(json.dumps({"restarts": [
        {"id": "r1", "kind": "goal_kick"}, {"id": "r2", "kind": "throw_in"},
        {"id": "r3", "kind": "corner"}]}))
    (run / "observations.jsonl").write_text("".join(
        json.dumps({"frame": f, "camera": {"ok": f < 200}}) + "\n" for f in range(100, 241)))
    return clip, run


def test_the_scorer_grades_type_spot_and_kind_and_counts_a_restart_with_no_camera_as_a_miss(tmp_path):
    body = rsc.pooled([rsc.clip(*plant(tmp_path))])
    sp = body["per_type"]["strict"]["set_piece"]
    assert (sp["true"], sp["detected"], sp["tp"], sp["fp"], sp["fn"]) == (2, 3, 2, 1, 0)
    assert body["per_type"]["strict"]["kickoff"]["fn"] == 1
    assert body["confusion"]["throw_in"]["throw_in"] == 1
    assert body["confusion"]["free_kick"]["corner"] == 1
    assert body["confusion"]["kick_off"]["missed"] == 1
    assert body["by_kind"]["throw_in"]["strict_and_kind_right"] == 1
    assert body["by_kind"]["free_kick"]["strict_and_kind_right"] == 0
    assert body["by_kind"]["kick_off"] == {"true": 1, "strict_and_kind_right": 0, "time_only": 0,
                                           "kind_right_of_time_matched": 0, "no_camera": 1, "rate": 0.0,
                                           "wilson95": [0.0, 0.79]}
    assert [f["kind"] for f in body["false"]] == ["goal_kick"] and body["false_per_clip"] == 1.0
    assert [r["nearest_dt_s"] for r in body["restarts"]] == [0.08, 0.04, -3.12]
    assert body["restarts"][2]["either_side"] == {"dt_s": -1.96, "team": "home", "kind": "corner",
                                                  "distance_m": 15.88}


def test_the_cli_writes_json_and_markdown(tmp_path):
    clip, run = plant(tmp_path)
    rsc.main(["--clip", str(clip), "--run", str(run), "--out", str(tmp_path / "out" / "validation")])
    body = json.loads((tmp_path / "out" / "validation.json").read_text())
    assert body["clips"] == ["seed1-100"]
    assert "| free_kick | 0 | 0 | 1 | 0 | 0 | 0 | 0 |" in (tmp_path / "out" / "validation.md").read_text()
