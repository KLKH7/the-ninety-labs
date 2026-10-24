"""The join of the broadcast's and the views' live runs (ninety/vision/join.py): one clock, each
camera for what it sees best, the association only where it is unambiguous, and no ground truth."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from ninety.vision import join as jn
from tests.test_vision_live_path import TRUTH_FILES, run_audited, truth_reads

M = jn.MATCH_M
FRAMES = [100, 101, 102, 103]


def _player(pid, team, x, y):
    return {"id": pid, "team": team, "x": x, "y": y}


def _frame(f, ball, players, clip="c"):
    return {"frame": f, "t": round(f / 25, 2), "source": "tracked", "clip": clip,
            "ball": {"x": ball[0], "y": ball[1], "z": 0.0}, "players": players}


def _write_run(where: Path, views: list[str], tracked: list[dict], events=(), clip="c", frames=FRAMES,
               times=None):
    where.mkdir(parents=True)
    times = times or [round(f / 25, 2) for f in frames]
    (where / "run.json").write_text(json.dumps({"clip": clip, "frames": len(frames), "views": views}))
    (where / "detected.jsonl").write_text("".join(json.dumps(e) + "\n" for e in events))
    (where / "observations.jsonl").write_text("".join(
        json.dumps({"frame": f, "t": t, "camera": {"ok": False}, "players": [], "ball": []}) + "\n"
        for f, t in zip(frames, times, strict=True)))
    (where / "tracked.json").write_text(json.dumps({"restarts": [], "frames": tracked}))
    return where


def _runs(tmp_path, b_tracked=None, v_tracked=None, **kw):
    """A broadcast run that sees the ball on frames 100-102 and two players near it; a views run
    that sees four players on every frame, and the ball on all of them."""
    b_tracked = b_tracked if b_tracked is not None else [
        _frame(f, (50.0 + f - 100, 30.0), [_player("h-t1", "home", 50.0, 30.0),
                                            _player("a-t2", "away", 60.0, 40.0)])
        for f in FRAMES[:3]]
    v_tracked = v_tracked if v_tracked is not None else [
        _frame(f, (49.0, 29.0), [_player("h-t7", "home", 50.3, 30.2), _player("a-t8", "away", 60.2, 39.9),
                                 _player("h-t9", "home", 20.0, 10.0), _player("a-t3", "away", 90.0, 60.0)])
        for f in FRAMES]
    events = [{"type": "pass", "frame": 101, "player": "h-t1"}]
    b = _write_run(tmp_path / "b", [], b_tracked, events, **kw.get("b", {}))
    v = _write_run(tmp_path / "v", ["tac-l", "tac-r"], v_tracked, **kw.get("v", {}))
    return b, v


def test_the_join_takes_events_and_ball_from_the_broadcast_and_players_from_the_views(tmp_path):
    b, v = _runs(tmp_path)
    report = jn.join(b, v, tmp_path / "out")
    out = tmp_path / "out"
    assert sorted(p.name for p in out.iterdir()) == [
        "association.json", "detected.jsonl", "join.json", "observations.jsonl", "tracked.json"]
    assert (out / "detected.jsonl").read_text() == (b / "detected.jsonl").read_text()
    assert [json.loads(x)["frame"] for x in (out / "observations.jsonl").read_text().splitlines()] == FRAMES
    frames = json.loads((out / "tracked.json").read_text())["frames"]
    assert [f["frame"] for f in frames] == FRAMES  # every frame the views tracked
    assert all({p["id"] for p in f["players"]} == {"h-t7", "a-t8", "h-t9", "a-t3"} for f in frames)
    assert [f["ball"]["x"] for f in frames] == [50.0, 51.0, 52.0, 49.0]  # the broadcast's, then the views'
    assert report["tracked"] == {"frames": 4, "ball_from_broadcast": 3, "ball_from_views": 1}
    assert report["events"] == 1 and report["clip"] == "c"


def test_the_joined_tracked_frames_meet_the_frame_schema(tmp_path):
    from jsonschema import validate

    schema = json.loads((Path(__file__).resolve().parents[1] / "schemas/frame.schema.json").read_text())
    b, v = _runs(tmp_path)
    jn.join(b, v, tmp_path / "out")
    for f in json.loads((tmp_path / "out" / "tracked.json").read_text())["frames"]:
        validate(f, schema)


@pytest.mark.parametrize("change, message", [
    ({"b": {"clip": "other"}}, "two clips"),
    ({"v": {"frames": [100, 101, 102, 104]}}, "same frames"),
    ({"v": {"times": [4.0, 4.04, 4.08, 4.16]}}, "same frames"),  # frame 103 at another time
    ({"v": {"frames": FRAMES[:3]}}, "same frames"),
])
def test_runs_on_two_clocks_are_refused(tmp_path, change, message):
    b, v = _runs(tmp_path, v_tracked=[], **change)
    with pytest.raises(SystemExit, match=message):
        jn.join(b, v, tmp_path / "out")
    assert not (tmp_path / "out").exists()


def test_the_cameras_must_be_the_right_way_round(tmp_path):
    b, v = _runs(tmp_path)
    with pytest.raises(SystemExit, match="not the broadcast"):
        jn.join(v, b, tmp_path / "out")
    (b / "run.json").write_text(json.dumps({"clip": "c", "frames": 4, "views": []}))
    (v / "run.json").write_text(json.dumps({"clip": "c", "frames": 4, "views": ["tac-l"]}))
    with pytest.raises(SystemExit, match="not of the tactical camera"):
        jn.join(b, v, tmp_path / "out")


def test_a_tracked_frame_neither_run_observed_is_refused(tmp_path):
    b, v = _runs(tmp_path, v_tracked=[_frame(999, (1.0, 1.0), [])])
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
    b_tracked = [_frame(f, (50.0, 30.0), [_player("h-t1", "home", 50.0, 30.0),
                                          _player("a-t2", "away", 70.0, 40.0)]) for f in FRAMES]
    v_tracked = []
    for k, f in enumerate(FRAMES):
        here = "h-t7" if k < 3 else "h-t9"
        v_tracked.append(_frame(f, (49.0, 29.0), [_player(here, "home", 50.2, 30.0),
                                                  _player("a-t8", "away", 70.0, 40.0 + 0.3 * M),
                                                  _player("a-t3", "away", 70.0, 40.0 - 0.3 * M)]))
    b, v = _runs(tmp_path, b_tracked=b_tracked, v_tracked=v_tracked)
    jn.join(b, v, tmp_path / "out")
    got = json.loads((tmp_path / "out" / "association.json").read_text())
    assert got["match_m"] == round(M, 3)
    assert got["tracks"]["h-t1"]["track"] == "h-t7"
    assert got["tracks"]["h-t1"]["confidence"] == 0.75
    assert got["tracks"]["h-t1"]["paired"] == 4 and got["tracks"]["h-t1"]["agree"] == 3
    assert got["tracks"]["a-t2"] == {"track": None, "confidence": 0.0, "frames": 4, "paired": 0}
    assert json.loads((tmp_path / "out" / "join.json").read_text())["association"]["matched"] == 1


def test_frames_only_the_broadcast_tracked_are_not_used_to_pair(tmp_path):
    b_tracked = [_frame(f, (50.0, 30.0), [_player("h-t1", "home", 50.0, 30.0)]) for f in FRAMES]
    v_tracked = [_frame(103, (49.0, 29.0), [_player("h-t7", "home", 50.0, 30.0)])]
    b, v = _runs(tmp_path, b_tracked=b_tracked, v_tracked=v_tracked)
    assert jn.associate(jn.read_run(b), jn.read_run(v))["h-t1"]["frames"] == 1


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
    assert run["out"] == {"frames": 4, "matched": 2}  # it did the work
    assert truth_reads(run) == []
    read = {Path(o).name for o in run["opened"] if str(tmp_path) in o and not o.startswith(str(out))}
    assert read == set(jn.RUN_FILES)


def test_the_joined_folder_draws_a_radar(tmp_path):
    """ninety-e2e reads the joined tracked.json and observations.jsonl as it reads one run's."""
    from ninety import radar

    b, v = _runs(tmp_path)
    out = tmp_path / "out"
    jn.join(b, v, out)
    body = radar.write(out / "tracked.json", out / "observations.jsonl", 1280, 720, tmp_path / "radar.json")
    assert len(body["frames"]) == 4
