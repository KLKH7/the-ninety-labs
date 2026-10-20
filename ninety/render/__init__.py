"""Broadcast renderer: turns a ninety-sim match into broadcast-style video with exact ground truth.

Python owns the scene (camera path, player bodies, ball) and every label computed from geometry.
The three.js page in `web/render` draws the pixels and an object-id pass, from which visibility
and pixel boxes are counted. See docs/guides/broadcast-render.md and
docs/decisions/0001-synthetic-data.md.
"""

RENDERER_VERSION = "0.3.3"
