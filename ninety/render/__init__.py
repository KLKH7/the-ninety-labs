"""Broadcast renderer: turns a ninety-sim match into broadcast-style video with exact ground truth.

Python owns the scene (camera path, player bodies, ball) and every label computed from geometry.
The three.js page in `web/render` draws the pixels and an object-id pass, from which visibility
and pixel boxes are counted. See docs/guides/broadcast-render.md and
docs/decisions/0001-synthetic-data.md.
"""

# Bumped whenever the pixels or the labels change, so clip.json says which renderer drew a clip.
# 0.4.0: players drawn on the skinned kit mesh (a3d228e), not the capsules 0.3.x drew; #146's
# turns and touch poses (0.3.3 on its own); the `occlusion=keeper` window; the crowded window
# counting only a live ball. Clips at cca498c and main's clips before the mesh was named both said
# 0.3.2 (docs/LESSONS.md, lesson 102).
# 0.4.1: arms hang standing and swing opposite the legs; a kick swings back and through the ball;
# a lunge recovers over 0.28 s; a keeper's hands hold the ball; the boards behind the goals read
# the right way round; the stands have walls and roofs that close the bowl.
# 0.4.2: the stride plants each foot where the gait has it on the grass and takes and gives back
# the plant over three frames; stand, walk and jog blend by speed; a tackle's poke is drawn as the
# tackler's foot on the ball; no limb jumps in a frame (#150, after 0.4.1's review clips).
RENDERER_VERSION = "0.4.2"
