"""Tiled detection (ninety/vision/tiles.py): the grid covers the frame with the stated overlap, boxes
come back in full-image pixels, and only what tiling duplicated is merged.

Boxes are planted where tiling goes wrong: on the seams, in the shared band, cut by a tile edge.
Each "must merge" case has a "must not merge" twin a few pixels away.
"""

from __future__ import annotations

import pytest

from ninety.vision.detections import Detection
from ninety.vision.tiles import CUT_COVER, SAME_IOU, Tile, grid, iou, is_cut, merge, to_image

W, H = 1920, 1080
TL, TR, BL, BR = grid(W, H)


def det(box, score=0.9, cls="player"):
    return Detection(cls, tuple(float(v) for v in box), score)


def local(tile: Tile, box):
    """A box given in image pixels, as the model would return it from `tile`."""
    x0, y0, x1, y1 = box
    return (x0 - tile.x0, y0 - tile.y0, x1 - tile.x0, y1 - tile.y0)


def test_the_tactical_grid_is_four_tiles_sharing_a_tenth_of_the_frame():
    assert [(t.x0, t.y0, t.x1, t.y1) for t in grid(W, H)] == [
        (0, 0, 1056, 594), (864, 0, 1920, 594), (0, 486, 1056, 1080), (864, 486, 1920, 1080)]
    assert TL.x1 - TR.x0 == 192 and TL.y1 - BL.y0 == 108  # 10% of 1920 and of 1080


@pytest.mark.parametrize("w,h,c,r", [(1920, 1080, 2, 2), (1280, 720, 3, 2), (1001, 777, 2, 3),
                                     (640, 360, 1, 1)])
def test_every_pixel_is_in_a_tile_and_no_tile_leaves_the_image(w, h, c, r):
    tiles = grid(w, h, c, r)
    assert len(tiles) == c * r
    assert all(0 <= t.x0 < t.x1 <= w and 0 <= t.y0 < t.y1 <= h for t in tiles)
    for x in (0, w // 3, w // 2, w - 1):
        for y in (0, h // 3, h // 2, h - 1):
            assert any(t.x0 <= x < t.x1 and t.y0 <= y < t.y1 for t in tiles), (x, y)


def test_a_box_from_a_tile_comes_back_in_image_pixels():
    assert to_image(BR, (10, 20, 30, 60)) == (874, 506, 894, 546)


def test_a_box_at_the_image_border_is_not_cut_but_one_at_an_inner_tile_edge_is():
    assert not is_cut(TL, (0, 0, 20, 50), W, H)  # the frame's own edge
    assert is_cut(TL, (1040, 100, 1056, 150), W, H)  # TL's right edge is inside the frame
    assert is_cut(TR, (864, 100, 880, 150), W, H)
    assert not is_cut(TR, (868, 100, 880, 150), W, H)  # 4 px in from the edge


def test_a_player_whole_in_both_tiles_of_the_vertical_seam_is_one_detection():
    box = (950, 200, 980, 270)  # inside the shared band x 864..1056
    out = merge([(TL, [det(local(TL, box), 0.8)]), (TR, [det(local(TR, box), 0.9)])], W, H)
    assert [(d.bbox, d.score) for d in out] == [(box, 0.9)]


def test_a_ball_on_the_crossing_of_both_seams_seen_by_all_four_tiles_is_one_detection():
    box = (958, 538, 962, 542)
    per = [(t, [det(local(t, box), 0.5 + k / 10, "ball")]) for k, t in enumerate(grid(W, H))]
    out = merge(per, W, H)
    assert len(out) == 1 and out[0].bbox == box and out[0].score == 0.8


def test_two_players_side_by_side_on_the_seam_stay_two():
    a, b = (940, 200, 970, 270), (962, 200, 992, 270)  # IoU 8/52: touching, not the same
    assert iou(a, b) < SAME_IOU
    both = [det(local(TL, a)), det(local(TL, b))], [det(local(TR, a)), det(local(TR, b))]
    out = merge([(TL, both[0]), (TR, both[1])], W, H)
    assert sorted(d.bbox for d in out) == [a, b]


def test_a_player_and_the_ball_at_his_feet_are_never_merged():
    p, ball = (950, 200, 980, 270), (962, 262, 970, 270)
    out = merge([(TL, [det(local(TL, p))]), (TR, [det(local(TR, ball), cls="ball")])], W, H)
    assert sorted(d.cls for d in out) == ["ball", "player"]


def test_two_overlapping_players_from_one_tile_are_the_model_s_and_are_kept():
    a, b = (300, 200, 330, 270), (303, 202, 333, 272)  # IoU above SAME_IOU, one tile: not tiling's
    assert iou(a, b) >= SAME_IOU
    assert len(merge([(TL, [det(a, 0.9), det(b, 0.6)])], W, H)) == 2


def test_a_player_cut_by_the_horizontal_seam_gives_way_to_the_tile_that_holds_him_whole():
    whole = (400, 560, 430, 640)  # under TL's bottom edge (594) and inside BL from 486
    cut = (400, 560, 430, 594)  # what TL sees of him
    out = merge([(TL, [det(local(TL, cut), 0.95)]), (BL, [det(local(BL, whole), 0.7)])], W, H)
    assert [d.bbox for d in out] == [whole]


def test_a_cut_box_nothing_covers_is_kept():
    cut = (1040, 100, 1056, 160)
    out = merge([(TL, [det(local(TL, cut))]), (TR, [])], W, H)
    assert [d.bbox for d in out] == [cut]


def test_a_cut_box_beside_another_player_is_not_swallowed_by_him():
    cut = (1040, 100, 1056, 160)  # cut by TL's right edge
    other = (1000, 100, 1030, 160)  # a different whole player 10 px to the left
    assert CUT_COVER > 0 and iou(cut, other) == 0
    out = merge([(TL, [det(local(TL, cut))]), (TR, [det(local(TR, other))])], W, H)
    assert sorted(d.bbox for d in out) == [other, cut]


def test_a_duplicate_just_below_the_same_object_rule_stays_two():
    a = (950.0, 200.0, 980.0, 270.0)
    b = (962.0, 200.0, 992.0, 270.0)  # IoU 18/42 = 0.43
    assert iou(a, b) < SAME_IOU
    assert len(merge([(TL, [det(local(TL, a))]), (TR, [det(local(TR, b))])], W, H)) == 2
    c = (956.0, 200.0, 986.0, 270.0)  # IoU 24/36 = 0.67
    assert iou(a, c) >= SAME_IOU
    assert len(merge([(TL, [det(local(TL, a))]), (TR, [det(local(TR, c))])], W, H)) == 1


def test_a_bad_grid_is_refused():
    with pytest.raises(ValueError):
        grid(1920, 1080, overlap=1.0)
    with pytest.raises(ValueError):
        grid(0, 1080)


class SeamModel:
    """Stands in for RF-DETR: in every crop it is given, finds one player whose image box is
    PLAYER (on the vertical seam, whole in both top tiles), at the crop's own pixels, and records
    the crop sizes."""

    class_names = ["player", "ball"]
    PLAYER = (950.0, 200.0, 980.0, 270.0)

    def __init__(self):
        self.sizes = []

    def predict(self, images, **kw):
        import numpy as np

        out = []
        for im in images:
            self.sizes.append(im.size)
            # Which tile this crop is: its size is the same for all four, so it is told by order.
            t = grid(W, H)[(len(self.sizes) - 1) % 4]
            x0, y0, x1, y1 = self.PLAYER
            inside = t.x0 <= x0 and x1 <= t.x1 and t.y0 <= y0 and y1 <= t.y1
            boxes = np.array([local(t, self.PLAYER)]) if inside else np.zeros((0, 4))
            n = len(boxes)
            out.append(type("P", (), {"xyxy": boxes, "confidence": np.full(n, 0.9),
                                      "class_id": np.zeros(n, dtype=int)})())
        return out


def test_tiled_detection_runs_each_tile_and_writes_one_merged_box_in_image_pixels(tmp_path):
    from PIL import Image

    from ninety.vision.detect import detect_rows, labels_for
    from ninety.vision.model import model

    rows = []
    for k in range(3):
        p = tmp_path / f"{k:05d}.jpg"
        Image.new("RGB", (W, H), (40, 120, 40)).save(p)
        rows.append({"clip": "c", "frame": k, "t": k / 25, "image": p})
    m = SeamModel()
    out = detect_rows(m, rows, labels_for("ours-x", m.class_names), model("ours-x"), batch=2, tiles=True)
    assert m.sizes == [(1056, 594)] * 12  # four tiles a frame, three frames
    assert [f.frame for f in out] == [0, 1, 2]
    assert all([d.bbox for d in f.detections] == [SeamModel.PLAYER] for f in out)
