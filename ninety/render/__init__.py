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
# 0.4.3: while a foot plays the ball the other one stands and steps after the body; a planted foot
# left beyond the leg's reach steps at once; a lowered leg that cannot reach its plant stays above
# the grass; a keeper stoops less on the move (render-check feet in boxes, seeds 7 and 11).
# 0.4.4: a foot that has played the ball comes back to the grass from where the touch drew it.
# 0.4.5: a touch keeps its foot's plant within the leg's reach and lets the foot go from where it
# is drawn; a foot a touch catches in the air lands within three frames. A touch on the move keeps
# a foot on the grass (render-check feet in boxes, seed 7: 7 checks at 0.4.3, 1 at 0.4.4).
# 0.5.0: the broadcast cuts from a stoppage to its restart instead of showing the whole dead ball
# (ninety/render/edit.py; meta.json `cuts`, clip.json `segments`), and the match is simulated to a
# fixed horizon, so a clip's events no longer depend on how its start was found.
# 0.5.1: the gantry aims at the play on the grass with a wider lens (18 m), so the pitch fills the
# picture with 8 to 15 players in shot; with play far off it tilts down its line of sight so the
# stands stay at most a third of the picture; it frames the play rather than the ball and holds
# still while the ball moves about one area; pans and zooms ease in and out, and the box's lens
# does not pump; live play keeps to the gantry's side (no far stand, no camera behind a goal) and
# cuts closer only for a throw-in, as a medium shot; no shot is shorter than 4 s; a pan smears
# instead of splitting every edge in two (the sharpening read the unsmeared picture); the
# goalmouth and centre wear is faint, pale turf in the mowing stripes.
# 0.5.2: players are drawn at their own height (the body mesh stands 1.684 m, not 1.84 m, so every
# player was 91.5% of his height), with proportions measured against Drillis and Contini; walking
# and running, a foot is planted for its stance and carried on an arc through its swing, never
# dragged along the grass; the stride lengthens and the swing lifts with speed.
RENDERER_VERSION = "0.5.2"
