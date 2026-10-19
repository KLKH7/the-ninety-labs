"""Broadcast renderer: turns a ninety-sim match into broadcast-style video with exact ground truth.

Python owns the scene (camera path, player bodies, ball) and every label computed from geometry.
The three.js page in `web/render` draws the pixels and an object-id pass, from which visibility
and pixel boxes are counted. See docs/guides/broadcast-render.md and
docs/decisions/0001-synthetic-data.md.
"""

# Bumped whenever the pixels or the labels change, so clip.json says which renderer drew a clip.
# 0.4.0: players drawn on the skinned kit mesh (a3d228e), not the capsules 0.3.x drew; and the
# `occlusion=keeper` window. 0.3.2 clips at cca498c and later main clips both said 0.3.2.
RENDERER_VERSION = "0.4.0"
