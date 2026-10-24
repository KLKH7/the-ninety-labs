"""The join of the broadcast's and the views' live runs (ninety/vision/join.py): one clock, each
camera for what it sees best, the association only where it is unambiguous, and no ground truth."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from ninety.vision import join as jn
from ninety.vision import tracked_frames as tf
from tests.test_vision_live_path import TRUTH_FILES, run_audited, truth_reads

M = jn.MATCH_M
FRAMES = list(range(100, 130))
RGB = {"home": [200.0, 20.0, 20.0], "away": [20.0, 20.0, 200.0]}
B_PLAYERS = [("home", 50.0, 30.0), ("away", 60.0, 40.0)]
V_PLAYERS = [("home", 50.3, 30.2), ("away", 60.2, 39.9), ("home", 20.0, 10.0), ("away", 90.0, 60.0)]
B_BALL = range(105, 125)  # the broadcast follows the ball from frame 105 to 124
V_BALL = range(100, 110)  # the views find it only on 100 to 109


def _player(pid, team, x, y):
    return {"id": pid, "team": team, "x": x, "y": y}


def _frame(f, ball, players, clip="c"):
    return {"frame": f, "t": round(f / 25, 2), "source": "tracked", "clip": clip,
            "ball": {"x": ball[0], "y": ball[1], "z": 0.0}, "players": players}


def _obs(frames, times, players, ball):
    rows = []
    for f, t in zip(frames, times, strict=True):
        bx = ball(f)
        rows.append({
            "frame": f, "t": t, "camera": {"ok": True, "P": None},
            "players": [{"bbox": [0, 0, 10, 20], "score": 0.9, "x": x, "y": y, "rgb": RGB[team]}
                        for team, x, y in players],
            "ball": [] if bx is None else [{"bbox": [0, 0, 2, 2], "score": 0.9, "x": bx, "y": 30.0}],
        })
    return rows


def _write_run(where: Path, views: list[str], players, ball, events=(), clip="c", frames=FRAMES,
               times=None):
    where.mkdir(parents=True)
    times = times or [round(f / 25, 2) for f in frames]
    obs = _obs(frames, times, players, ball)
    (where / "run.json").write_text(json.dumps({"clip": clip, "frames": len(frames), "views": views}))
    (where / "detected.jsonl").write_text("".join(json.dumps(e) + "\n" for e in events))
    (where / "observations.jsonl").write_text("".join(json.dumps(r) + "\n" for r in obs))
    (where / "tracked.json").write_text(tf.text(tf.build(obs, clip)))
    return where


def _runs(tmp_path, **kw):
    """A broadcast run of two players, the ball on frames 105-124; a views run of four players,
    two of them where the broadcast's are, the ball on 100-109 only."""
    events = [{"type": "pass", "frame": 110, "player": "h-t1"}]
    b = _write_run(tmp_path / "b", [], B_PLAYERS, lambda f: 50.0 + 0.1 * (f - 100) if f in B_BALL else None,
                   events, **kw.get("b", {}))
    v = _write_run(tmp_path / "v", ["tac-l", "tac-r"], V_PLAYERS, lambda f: 49.0 if f in V_BALL else None,
                   **kw.get("v", {}))
    return b, v


def test_the_join_takes_events_and_ball_from_the_broadcast_and_players_from_the_views(tmp_path):
    b, v = _runs(tmp_path)
    report = jn.join(b, v, tmp_path / "out")
    out = tmp_path / "out"
    assert sorted(p.name for p in out.iterdir()) == [
        "association.json", "detected.jsonl", "join.json", "observations.jsonl", "tracked.json"]
    assert (out / "detected.jsonl").read_text() == (b / "detected.jsonl").read_text()
    assert (out / "observations.jsonl").read_text() == (b / "observations.jsonl").read_text()
    frames = json.loads((out / "tracked.json").read_text())["frames"]
    # every frame either camera has the ball on, not only the 10 the views' own tracked.json holds
    assert [f["frame"] for f in frames] == list(range(100, 125))
    assert all(len(f["players"]) == 4 for f in frames)  # the views' four, not the broadcast's two
    assert [f["ball"]["x"] for f in frames[:5]] == [49.0] * 5  # the views' ball before 105
    assert [f["ball"]["x"] for f in frames[5:]] == [round(50.0 + 0.1 * k, 2) for k in range(5, 25)]
    assert report["tracked"] == {"frames": 25, "ball_from_broadcast": 20, "ball_from_views": 5,
                                 "views_tracked_frames": 10}
    assert report["events"] == 1 and report["clip"] == "c"
    assert report["association"]["broadcast_tracks"] == 2 and report["association"]["matched"] == 2


def test_the_joined_tracked_frames_meet_the_frame_schema(tmp_path):
    from jsonschema import validate

    schema = json.loads((Path(__file__).resolve().parents[1] / "schemas/frame.schema.json").read_text())
    b, v = _runs(tmp_path)
    jn.join(b, v, tmp_path / "out")
    for f in json.loads((tmp_path / "out" / "tracked.json").read_text())["frames"]:
        validate(f, schema)


@pytest.mark.parametrize("change, message", [
    ({"b": {"clip": "other"}}, "two clips"),
    ({"v": {"frames": FRAMES[:-1] + [130]}}, "same frames"),
    ({"v": {"times": [round(f / 25, 2) for f in FRAMES[:-1]] + [5.2]}}, "same frames"),  # 129 at another time
    ({"v": {"frames": FRAMES[:20]}}, "same frames"),
])
def test_runs_on_two_clocks_are_refused(tmp_path, change, message):
    b, v = _runs(tmp_path, **change)
    with pytest.raises(SystemExit, match=message):
        jn.join(b, v, tmp_path / "out")
    assert not (tmp_path / "out").exists()


def test_the_cameras_must_be_the_right_way_round(tmp_path):
    b, v = _runs(tmp_path)
    with pytest.raises(SystemExit, match="not the broadcast"):
        jn.join(v, b, tmp_path / "out")
    (v / "run.json").write_text(json.dumps({"clip": "c", "frames": 30, "views": ["tac-l"]}))
    with pytest.raises(SystemExit, match="not of the tactical camera"):
        jn.join(b, v, tmp_path / "out")


def test_a_tracked_frame_neither_run_observed_is_refused(tmp_path):
    b, v = _runs(tmp_path)
    (v / "tracked.json").write_text(json.dumps({"restarts": [], "frames": [_frame(999, (1.0, 1.0), [])]}))
    with pytest.raises(SystemExit, match="999"):
        jn.join(b, v, tmp_path / "out")


def test_a_run_missing_a_file_is_refused(tmp_path):
    b, v = _runs(tmp_path)
    (v / "tracked.json").unlink()
    with pytest.raises(SystemExit, match="tracked.json"):
        jn.join(b, v, tmp_path / "out")


def test_the_nearest_pair_is_taken_only_when_unambiguous():
    me = [_player("b1", "home", 0.0, 0.0)]
    near = 0.4 * M
    # the nearest within MATCH_M, the next one far away: paired
    assert jn.pair_frame(me, [_player("t1", "home", near, 0.0), _player("t2", "home", 0.0, 3 * M)], M) == {
        "b1": ("t1", near)}
    # nothing within MATCH_M: none
    assert jn.pair_frame(me, [_player("t1", "home", 1.01 * M, 0.0)], M) == {}
    # a second man within the gap (here 1.3 M away against 0.4 M): none, not a guess
    t1 = _player("t1", "home", near, 0.0)
    assert jn.pair_frame(me, [t1, _player("t2", "home", -1.3 * M, 0.0)], M) == {}
    # the second just past the gap: paired
    far = near + 1.01 * M
    assert jn.pair_frame(me, [t1, _player("t2", "home", -far, 0.0)], M)["b1"][0] == "t1"
    # the teams play no part: each camera reads the kits on its own
    assert jn.pair_frame(me, [_player("t1", "away", near, 0.0)], M)["b1"][0] == "t1"


def test_each_broadcast_track_takes_the_tactical_track_most_of_its_frames_chose(tmp_path):
    # b h-t1 sits on t7 for three frames and on t9 for one; a-t2 is between two men on every frame
    frames = FRAMES[:4]
    b = {"tracked": {"frames": [_frame(f, (50.0, 30.0), [_player("h-t1", "home", 50.0, 30.0),
                                                         _player("a-t2", "away", 70.0, 40.0)])
                                for f in frames]}}
    joined = [_frame(f, (49.0, 29.0), [_player("h-t7" if k < 3 else "h-t9", "home", 50.2, 30.0),
                                       _player("a-t8", "away", 70.0, 40.0 + 0.3 * M),
                                       _player("a-t3", "away", 70.0, 40.0 - 0.3 * M)])
              for k, f in enumerate(frames)]
    got = jn.associate(b, joined)
    assert got["h-t1"]["track"] == "h-t7"
    assert got["h-t1"]["confidence"] == 0.75
    assert got["h-t1"]["paired"] == 4 and got["h-t1"]["agree"] == 3
    assert got["a-t2"] == {"track": None, "confidence": 0.0, "frames": 4, "paired": 0}


def test_frames_only_the_broadcast_tracked_are_not_used_to_pair():
    b = {"tracked": {"frames": [_frame(f, (50.0, 30.0), [_player("h-t1", "home", 50.0, 30.0)])
                                for f in FRAMES[:4]]}}
    joined = [_frame(103, (49.0, 29.0), [_player("h-t7", "home", 50.0, 30.0)])]
    assert jn.associate(b, joined)["h-t1"]["frames"] == 1


def test_the_association_file_names_its_threshold(tmp_path):
    b, v = _runs(tmp_path)
    jn.join(b, v, tmp_path / "out")
    got = json.loads((tmp_path / "out" / "association.json").read_text())
    assert got["match_m"] == round(M, 3) and got["broadcast_error_m"] == jn.BROADCAST_ERROR_M
    assert {a["track"] for a in got["tracks"].values()} == {"h-t1", "a-t2"}  # the views' ids for the two


def test_the_join_opens_no_truth_file(tmp_path):
    """Run in a fresh interpreter under the audit hook, with the answer key's file names planted in
    both runs and beside them: only the runs' own four files are opened."""
    b, v = _runs(tmp_path)
    for d in (b, v, tmp_path):
        for name in TRUTH_FILES:
            (d / name).write_text("{}\n")
    out = tmp_path / "out"
    run = run_audited(f"""
        from ninety.vision import join
        r = join.join({str(b)!r}, {str(v)!r}, {str(out)!r})
        OUT = {{"frames": r["tracked"]["frames"], "matched": r["association"]["matched"]}}
    """)
    assert run["out"] == {"frames": 25, "matched": 2}  # it did the work
    assert truth_reads(run) == []
    read = {Path(o).name for o in run["opened"] if str(tmp_path) in o and not o.startswith(str(out))}
    assert read == set(jn.RUN_FILES)


def test_the_joined_folder_draws_a_radar(tmp_path, monkeypatch):
    """ninety-e2e reads the joined tracked.json and observations.jsonl as it reads one run's."""
    from ninety import radar

    monkeypatch.setattr(radar, "footprint", lambda P, w, h: None)  # these rows carry no camera matrix
    b, v = _runs(tmp_path)
    out = tmp_path / "out"
    jn.join(b, v, out)
    body = radar.write(out / "tracked.json", out / "observations.jsonl", 1280, 720, tmp_path / "radar.json")
    assert len(body["frames"]) == 25
