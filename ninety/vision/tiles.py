"""Detect on overlapping tiles of a frame, so small far players and the ball keep their pixels.

On the fixed tactical camera (two 1920 x 1080 lenses, each covering half the pitch) a player at the
far corner is about 27 px tall and the ball about 3.3 px. The detector shrinks its input to its
trained size (640 for ours), so a whole frame loses two thirds of those pixels; a 2 x 2 grid of
overlapping tiles loses about 40%.

    grid(1920, 1080)  ->  4 tiles of 1056 x 594, origins x in {0, 864}, y in {0, 486}

Each tile is the image's size over the grid, plus OVERLAP of the image's size shared with its
neighbour: 192 px across and 108 px down on a 1920 x 1080 frame. The overlap is sized so a whole
player fits in it (design: the tallest player near the horizontal seam, in the middle of the
picture, is about 78 px, under the 108 px shared there), so every player is whole in at least one
tile.

Boxes are mapped back to full-image pixels and merged across tiles (`merge`). Only what tiling
made is merged; boxes from one tile are the model's own output and stay as they are:

- a box that touches a tile edge inside the image is cut by the tile; another tile holds the
  whole object, so a cut box is dropped when a box of the same class from another tile covers
  at least CUT_COVER of it;
- two uncut boxes of one class from different tiles with IoU at least SAME_IOU are one object
  seen twice; the higher score is kept (greedy NMS, highest score first).

A cut box nothing covers is kept: an object larger than the overlap is cut in both tiles, and a
part of it is better than nothing. Pure Python, so CI runs it.
"""

from __future__ import annotations

import math
from dataclasses import dataclass

from ninety.vision.detections import Detection

COLS, ROWS = 2, 2
# Share of the image's width (height) two neighbouring tiles have in common (design; see above).
OVERLAP = 0.10
# A box edge within this of a tile's inner edge is cut by it. Design: the model places a box edge
# at the object's edge to a pixel or two, so 2 px catches a cut object without catching one that
# merely stands near the seam.
EDGE_PX = 2.0
# Two uncut boxes from different tiles at or above this IoU are the same object: the COCO
# matching rule's 0.5 (Lin et al. 2014, "Microsoft COCO"), as the scorer matches a box to a label.
SAME_IOU = 0.5
# A cut box is the part of an object another tile holds whole: drop it when an uncut box of its
# class covers at least half of its area (design: the same 0.5, measured over the smaller box).
CUT_COVER = 0.5


@dataclass(frozen=True)
class Tile:
    """A window of the image in full-image pixels: [x0, x1) x [y0, y1)."""

    x0: int
    y0: int
    x1: int
    y1: int

    @property
    def size(self) -> tuple[int, int]:
        return self.x1 - self.x0, self.y1 - self.y0


def _starts(length: int, n: int, overlap: float) -> tuple[int, list[int]]:
    side = min(length, math.ceil((length + overlap * length * (n - 1)) / n))
    if n == 1:
        return side, [0]
    step = (length - side) / (n - 1)
    return side, [round(i * step) for i in range(n)]


def grid(width: int, height: int, cols: int = COLS, rows: int = ROWS, overlap: float = OVERLAP) -> list[Tile]:
    """`cols` x `rows` tiles covering the image, neighbours sharing `overlap` of its size, row by
    row from the top left."""
    if width < 1 or height < 1 or cols < 1 or rows < 1 or not 0 <= overlap < 1:
        raise ValueError(f"no grid of {cols} x {rows} tiles with overlap {overlap} on {width} x {height}")
    tw, xs = _starts(width, cols, overlap)
    th, ys = _starts(height, rows, overlap)
    return [Tile(x, y, x + tw, y + th) for y in ys for x in xs]


def to_image(tile: Tile, box) -> tuple[float, float, float, float]:
    """A box in the tile's pixels -> the same box in the full image's."""
    x0, y0, x1, y1 = box
    return (x0 + tile.x0, y0 + tile.y0, x1 + tile.x0, y1 + tile.y0)


def is_cut(tile: Tile, box, width: int, height: int, edge: float = EDGE_PX) -> bool:
    """Whether a box (full-image pixels) touches an edge of the tile that lies inside the image:
    such a box may be only the part of its object that falls in this tile."""
    x0, y0, x1, y1 = box
    return ((tile.x0 > 0 and x0 <= tile.x0 + edge) or (tile.x1 < width and x1 >= tile.x1 - edge)
            or (tile.y0 > 0 and y0 <= tile.y0 + edge) or (tile.y1 < height and y1 >= tile.y1 - edge))


def _area(b) -> float:
    return max(0.0, b[2] - b[0]) * max(0.0, b[3] - b[1])


def _inter(a, b) -> float:
    return _area((max(a[0], b[0]), max(a[1], b[1]), min(a[2], b[2]), min(a[3], b[3])))


def iou(a, b) -> float:
    i = _inter(a, b)
    u = _area(a) + _area(b) - i
    return i / u if u > 0 else 0.0


def cover(part, whole) -> float:
    """How much of `part`'s area `whole` covers, 0 to 1."""
    a = _area(part)
    return _inter(part, whole) / a if a > 0 else 0.0


def merge(per_tile: list[tuple[Tile, list[Detection]]], width: int, height: int) -> list[Detection]:
    """Every tile's detections (boxes in that tile's pixels) as one frame's, in full-image pixels,
    with what tiling duplicated removed (see the module's docstring). Highest score first."""
    found = []  # (score, tile index, cut, Detection in image pixels)
    for k, (tile, dets) in enumerate(per_tile):
        for d in dets:
            box = tuple(round(v, 2) for v in to_image(tile, d.bbox))
            found.append((k, is_cut(tile, box, width, height), Detection(d.cls, box, d.score)))
    whole = [(k, d) for k, cut, d in found if not cut]
    kept: list[tuple[int, Detection]] = []
    for k, d in sorted(whole, key=lambda kd: -kd[1].score):
        if not any(j != k and e.cls == d.cls and iou(e.bbox, d.bbox) >= SAME_IOU for j, e in kept):
            kept.append((k, d))
    for k, cut, d in found:
        if cut and not any(j != k and e.cls == d.cls and cover(d.bbox, e.bbox) >= CUT_COVER
                           for j, e in whole):
            kept.append((k, d))
    return sorted((d for _, d in kept), key=lambda d: -d.score)
