"""The fixed tactical views: their lenses, the knob that asks for them, and the check that they film
the same world as the broadcast, frame for frame (ninety/render/camera.py tactical_views, clip.py)."""

import hashlib
import json
import math
import os
import shutil
from pathlib import Path

import pytest

from ninety.render.camera import (
    TACTICAL_HEAD_M,
    TACTICAL_MARGIN,
    TACTICAL_OVERLAP_M,
    TACTICAL_VIEWS,
    pan_tilt,
    tactical_views,
)
from ninety.render.checks import check_clip, digest, streams_agree
from ninety.render.clip import RenderUnavailable, browser_page, render_clip
from ninety.render.params import TacticalParams, sample_params
from ninety.validate import validate as validate_clip

# sample_params(seed).to_dict() at origin/main 0f101db, before the views existed: a seed keeps every
# draw it had, so its broadcast looks the same (sha256 of the sorted JSON, first 16 hex digits).
# The team codes are left out: they are no longer drawn but fixed (params.TEAMS, lesson 234; the
# draw itself is still made), and the test below holds them.
MAIN_PARAMS = {
    1: "f519f64391fd0d30", 7: "cb2cf91406107bae", 42: "b59ab0c991e30d06", 900001: "514ba69ccdd72554",
}
CODES = ("home_code", "away_code")


def _sha(d: dict) -> str:
    return hashlib.sha256(json.dumps(d, sort_keys=True).encode()).hexdigest()[:16]


@pytest.mark.parametrize("seed", sorted(MAIN_PARAMS))
def test_a_seed_keeps_every_draw_it_had_before_the_views(seed):
    drawn = {k: v for k, v in sample_params(seed).to_dict().items() if k not in CODES}
    assert _sha(drawn) == MAIN_PARAMS[seed]


@pytest.mark.parametrize("seed", sorted(MAIN_PARAMS))
def test_every_seed_plays_the_fixed_teams(seed):
    from ninety.render.params import TEAMS

    d = sample_params(seed).to_dict()
    assert (d["home_code"], d["away_code"]) == (TEAMS["home"][0], TEAMS["away"][0])


def test_the_mount_is_drawn_for_every_seed_and_the_views_never_are():
    mounts = [sample_params(s) for s in range(1, 201)]
    assert all(p.views == "none" for p in mounts)
    assert all(24 <= p.tactical.height_m <= 32 and 28 <= p.tactical.back_m <= 38 for p in mounts)
    assert all(abs(p.tactical.offset_x_m) <= 3 for p in mounts)
    assert len({p.tactical for p in mounts}) == len(mounts)
    asked = sample_params(7, views="tactical", **{"tactical.height_m": 30.0})
    assert asked.views == "tactical" and asked.tactical.height_m == 30.0
    assert asked.to_dict()["tactical"]["height_m"] == 30.0
    with pytest.raises(ValueError):
        sample_params(7, views="sideline")


def _corners(x_lo, x_hi):
    return [(x, y, z) for x in (x_lo, x_hi) for y in (0.0, 68.0) for z in (0.0, TACTICAL_HEAD_M)]


HALVES = ((0.0, 52.5 + TACTICAL_OVERLAP_M / 2), (52.5 - TACTICAL_OVERLAP_M / 2, 105.0))


@pytest.mark.parametrize("seed", [None, 7, 21, 900001, 900030])
def test_each_lens_holds_its_half_of_the_pitch_inside_the_margin_and_no_wider(seed):
    mount = TacticalParams() if seed is None else sample_params(seed).tactical
    for cam, (x_lo, x_hi) in zip(tactical_views(mount), HALVES, strict=True):
        w, h = cam.width, cam.height
        assert (w, h) == (1920, 1080)
        slack = []
        for p in _corners(x_lo, x_hi):
            u, v = cam.project(p)
            slack += [u - TACTICAL_MARGIN * w, (1 - TACTICAL_MARGIN) * w - u,
                      v - TACTICAL_MARGIN * h, (1 - TACTICAL_MARGIN) * h - v]
        assert min(slack) >= -1e-6  # every corner inside the margin
        # and the tightest such lens: a corner sits on the margin (within a pixel), on two sides
        assert sorted(slack)[1] < 1.0


def test_the_nominal_lenses_are_the_planned_ones_and_mirror_each_other():
    left, right = tactical_views(TacticalParams())
    (pl, tl), (pr, tr) = pan_tilt(left), pan_tilt(right)
    assert pl == pytest.approx(-pr, abs=1e-3) and tl == pytest.approx(tr, abs=1e-3)
    assert 0.40 < -pl < 0.55 and 0.45 < tl < 0.58  # the plan: pan about 0.47, tilt about 0.52
    hfov = math.degrees(2 * math.atan(left.width / 2 / left.focal_px))
    assert 52 < hfov < 64 and left.fov_v_deg == pytest.approx(right.fov_v_deg, abs=0.01)
    assert left.position == right.position == (52.5, -32.0, 28.0)


def test_a_lens_has_no_roll_and_a_centred_principal_point():
    for cam in tactical_views(sample_params(900001)):
        right = cam.R[0]
        assert right[2] == pytest.approx(0.0, abs=1e-12)  # the image's x axis is level
        K = cam.K
        assert (K[0][2], K[1][2]) == (cam.width / 2, cam.height / 2) and K[0][0] == K[1][1]


# streams_agree on planted clips: the check must fail on each kind of mismatch.


def _row(frame, x, lens):
    return {
        "frame": frame, "t": frame / 25, "clip": "c", "image": f"images/{frame:05d}.jpg",
        "ball": {"x": 50.0, "y": 30.0, "z": 0.0, "bbox": [1, 2, 3, 4], "visibility": 1.0, "pixels": 4,
                 "center_px": [2, 3], "centroid_px": [2, 3]},
        "possessor": "h1",
        "players": [{"id": "h1", "team": "home", "x": x, "y": 30.0, "bbox": [lens, 0, lens + 5, 9],
                     "visibility": 1.0, "pixels": 30, "foot_px": [lens, 9]}],
        "camera": {"P": [[lens, 0, 0, 0], [0, 1, 0, 0], [0, 0, 1, 0]]},
        "blur_px": [0, 0], "keypoints": [],
    }


def _plant(root: Path, views=TACTICAL_VIEWS) -> Path:
    def write(d, rows, extra):
        d.mkdir(parents=True, exist_ok=True)
        (d / "clip.json").write_text(json.dumps({"params": {"views": "tactical"}, **extra}))
        (d / "frames.jsonl").write_text("".join(json.dumps(r) + "\n" for r in rows))
        (d / "events.jsonl").write_text('{"type": "pass", "frame": 1}\n')

    write(root, [_row(f, 40.0 + f, 7 + f) for f in range(3)], {})
    for i, name in enumerate(views):
        lens = 100 + i
        write(root / "views" / name, [_row(f, 40.0 + f, lens) for f in range(3)],
              {"view": {"name": name, "camera": {"P": _row(0, 0, lens)["camera"]["P"]}}})
    return root


def _edit_rows(path: Path, change) -> None:
    rows = [json.loads(line) for line in path.read_text().splitlines()]
    change(rows)
    path.write_text("".join(json.dumps(r) + "\n" for r in rows))


def test_views_that_film_the_same_world_agree(tmp_path):
    assert streams_agree(_plant(tmp_path)) == []


def test_a_player_moved_in_one_view_is_caught(tmp_path):
    clip = _plant(tmp_path)

    def move(rows):
        rows[1]["players"][0]["x"] += 0.001

    _edit_rows(clip / "views" / "tac-r" / "frames.jsonl", move)
    found = streams_agree(clip)
    assert found == ["view tac-r: frame 1: the world differs from the broadcast's (view frame 1)"]


def _left(change):
    return lambda c: _edit_rows(c / "views/tac-l/frames.jsonl", change)


@pytest.mark.parametrize(
    "plant, says",
    [
        (_left(lambda r: r[2]["ball"].update(z=0.5)), "world differs"),
        (_left(lambda r: r.pop()), "2 frames"),
        (_left(lambda r: r[0].update(frame=9)), "world differs"),
        (_left(lambda r: r[0]["camera"]["P"][0].__setitem__(0, 5)), "the lens moved"),
        (lambda c: (c / "views/tac-l/events.jsonl").write_text(""), "events.jsonl differs"),
        (lambda c: shutil.rmtree(c / "views/tac-r"), "tac-r: missing"),
    ],
)
def test_each_kind_of_mismatch_is_caught(tmp_path, plant, says):
    clip = _plant(tmp_path)
    plant(clip)
    found = streams_agree(clip)
    assert found and any(says in f for f in found), found


def test_a_view_checked_on_its_own_has_no_views_to_agree(tmp_path):
    # It copies the clip's params (views=tactical), but a view holds no views of its own.
    view = _plant(tmp_path) / "views" / "tac-l"
    assert streams_agree(view) == []


def _ball_in(clip, name, frames):
    def put(rows):
        for r in rows:
            r["ball"]["bbox"] = [1, 2, 3, 4] if r["frame"] in frames else None

    _edit_rows(clip / "views" / name / "frames.jsonl", put)


def test_the_ball_in_one_half_all_clip_is_seen_by_that_view_alone(tmp_path):
    from ninety.render.checks import ball_unseen

    clip = _plant(tmp_path)
    _ball_in(clip, "tac-l", {0, 1, 2})
    _ball_in(clip, "tac-r", set())
    assert ball_unseen(clip) == []


def test_a_frame_where_neither_view_sees_the_ball_on_the_pitch_is_caught(tmp_path):
    from ninety.render.checks import ball_unseen

    clip = _plant(tmp_path)
    _ball_in(clip, "tac-l", {0})
    _ball_in(clip, "tac-r", {2})
    assert ball_unseen(clip) == [1]
    # off the pitch, or above what a lens is built to hold, nobody need see it
    for change, frame in ((dict(x=-1.0), 1), (dict(z=2.5), 1)):
        for d in (clip, clip / "views/tac-l", clip / "views/tac-r"):
            _edit_rows(d / "frames.jsonl", lambda r, c=change, f=frame: r[f]["ball"].update(c))
        assert ball_unseen(clip) == []
        for d in (clip, clip / "views/tac-l", clip / "views/tac-r"):
            _edit_rows(d / "frames.jsonl", lambda r, f=frame: r[f]["ball"].update(x=50.0, z=0.0))


def test_a_view_nobody_asked_for_is_caught(tmp_path):
    clip = _plant(tmp_path)
    meta = json.loads((clip / "clip.json").read_text())
    (clip / "clip.json").write_text(json.dumps({**meta, "params": {}}))
    assert any("not asked for" in f for f in streams_agree(clip))


# The real thing, in headless Chromium (skipped without it unless NINETY_REQUIRE_RENDER=1).

SECONDS = 1.2


@pytest.fixture(scope="module")
def rendered(tmp_path_factory):
    root = tmp_path_factory.mktemp("views")
    try:
        with browser_page() as (pg, _):
            render_clip(11, root / "plain", seconds=SECONDS, page=pg)
            render_clip(11, root / "views", seconds=SECONDS, page=pg, views="tactical")
    except RenderUnavailable as e:
        if os.environ.get("NINETY_REQUIRE_RENDER") == "1":
            raise
        pytest.skip(str(e))
    return root / "plain", root / "views"


def test_asking_for_views_leaves_the_broadcast_byte_identical(rendered):
    plain, views = rendered
    assert digest(plain) == digest(views)
    a, b = json.loads((plain / "clip.json").read_text()), json.loads((views / "clip.json").read_text())
    assert "views" not in a["params"] and b["params"]["views"] == "tactical"
    assert {k: v for k, v in b["params"].items() if k not in ("views", "tactical")} == a["params"]


def test_each_view_is_a_whole_clip_that_passes_every_check_and_films_the_broadcasts_world(rendered):
    _, views = rendered
    report = check_clip(views)
    assert all(report["passed"].values()), report["passed"]
    assert report["streams_agree"] == []
    for name in TACTICAL_VIEWS:
        d = views / "views" / name
        assert not validate_clip(d)
        alone = check_clip(d)["passed"]
        assert all(alone.values()) and "streams_agree" not in alone, alone
        clip = json.loads((d / "clip.json").read_text())
        assert clip["view"]["name"] == name and clip["scorebug_px"] is None and clip["stinger_frames"] == []
        frames = [json.loads(line) for line in (d / "frames.jsonl").read_text().splitlines()]
        assert len(list((d / "images").glob("*.jpg"))) == len(frames) == round(SECONDS * 25)
        assert {(f["camera"]["width"], f["camera"]["height"]) for f in frames} == {(1920, 1080)}
        assert all(f["blur_px"] == [0.0, 0.0] for f in frames)
        # every player on the pitch is in one view or the other, whole
    seen = {}
    for name in TACTICAL_VIEWS:
        for line in (views / "views" / name / "frames.jsonl").read_text().splitlines():
            f = json.loads(line)
            for pl in f["players"]:
                if pl["bbox"] and pl["visibility"] > 0:
                    seen.setdefault(f["frame"], set()).add(pl["id"])
    assert all(len(ids) == 22 for ids in seen.values()), {k: len(v) for k, v in seen.items()}


def _bare_frame(pg, cam, **spec):
    base = {"index": 3, "camera": {"position": list(cam.position), "R": cam.R, "fov_v_deg": cam.fov_v_deg},
            "objects": [], "keypoints": [], "blur": [0.0, 0.0], "score": [0, 0], "clock": "12:00",
            "goal_age": None, "goal_side": None, "net": None, "stinger": None, "want_image": True}
    return pg.evaluate("s => window.ninety.frame(s)", {**base, **spec})["image"]


@pytest.mark.parametrize("graphics", [True, False])
def test_a_page_without_graphics_draws_no_score_bug_and_no_stinger(graphics):
    # With graphics the score, a goal tag and a stinger change the picture; without, nothing does.
    from ninety.render.clip import _sibling_page

    p = sample_params(11)
    cam = tactical_views(p)[0]
    params = {**p.to_dict(), "width": 640, "height": 360}
    try:
        with browser_page() as (pg, _), _sibling_page(pg) as page:
            cfg = {"seed": 11, "params": params, "objects": []}
            cfg |= {} if graphics else {"graphics": False}
            info = page.evaluate("cfg => window.ninety.init(cfg)", cfg)
            plain = _bare_frame(page, cam)
            dressed = _bare_frame(page, cam, score=[3, 2], goal_age=0.6, goal_side=0)
            wiped = _bare_frame(page, cam, stinger=0.0)
    except RenderUnavailable as e:
        if os.environ.get("NINETY_REQUIRE_RENDER") == "1":
            raise
        pytest.skip(str(e))
    if graphics:
        assert info["bugRect"][2] > 0 and plain != dressed and plain != wiped
    else:
        assert info["bugRect"] == [0, 0, 0, 0] and plain == dressed == wiped


def test_only_a_view_may_have_no_ball_to_measure():
    """projection_ball_lt_1px: a broadcast always frames the ball, so a broadcast clip with no ball
    to measure fails; a fixed half-pitch lens may hold none all clip (views_see_the_ball judges the
    pair), so the same rows pass in a view. A measured error is judged the same in both."""
    from ninety.render.checks import ball_projection_ok

    assert ball_projection_ok(None, is_view=False) is False
    assert ball_projection_ok(None, is_view=True) is True
    for is_view in (False, True):
        assert ball_projection_ok(0.4, is_view) is True
        assert ball_projection_ok(1.2, is_view) is False
