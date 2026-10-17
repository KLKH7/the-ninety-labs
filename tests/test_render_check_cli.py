import json

from ninety.render import cli


def test_determinism_check_leaves_no_copy_next_to_the_clip(tmp_path, monkeypatch):
    # The re-render used to be left as seedN.rerender/ beside the clip, where any tool that walks
    # the dataset (ninety-data-stats) then sees the seed twice.
    clip = tmp_path / "test" / "seed900001"
    clip.mkdir(parents=True)
    (clip / "clip.json").write_text(json.dumps(
        {"clip_id": "seed900001", "seed": 900001, "frames": 2, "fps": 25, "t_start": 0.0, "overrides": {}}
    ))
    report = {
        "projection": {"ball_px": {"max": 0.1, "mean": 0.1, "n": 2}, "keypoint_px": {"max": 0.0},
                       "player_foot_outside_box": 0},
        "labels": {"frames": 2, "problems": []},
        "occlusion": {"ball_visibility_lt_0_5_share": 0.0, "ball_in_frame": 2},
        "passed": {"ok": True},
    }
    rendered = []

    def fake_render(seed, out, **kw):
        out.mkdir(parents=True)
        rendered.append(out)

    monkeypatch.setattr(cli, "check_clip", lambda d: report)
    monkeypatch.setattr(cli, "render_clip", fake_render)
    monkeypatch.setattr(cli, "digest", lambda d: {"frames_jsonl": "a", "events_jsonl": "b", "images": "c",
                                                  "image_count": 2})
    out = tmp_path / "report.json"
    cli.check_main([str(clip), "--determinism", "--report", str(out)])
    assert rendered, "the determinism check must re-render"
    assert sorted(p.name for p in clip.parent.iterdir()) == ["seed900001"]
    assert not rendered[0].exists()
    assert json.loads(out.read_text())["summary"]["determinism"]["images_identical"] is True
