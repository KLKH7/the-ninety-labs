# Shot outcomes from video: plan (set before any measurement or result)

*Status: planned. The detector (`ninety/vision/outcomes.py`) and its scorer
(`ninety/eval/shot_outcomes.py`) are on branch `claude/shot-outcomes`; nothing here is measured yet.*

Automatic event detection finds shots (`ninety/vision/events.py`) but leaves their outcome empty,
so no goal or save ever reaches the viewer. `ninety/vision/outcomes.py` reads the ball's path after
each detected shot, on the live path (pixels only), and writes the outcome in the answer key's own
words (`docs/DATA_CONTRACT.md`, the engine's `close_shot`): `goal` (plus a `goal` event),
`on_target` (the keeper stopped a ball going in: a save), `blocked` (an outfield defender got to
it), `off_target`.

## The rules (design, written before any number below is measured)

The ball is the broadcast's (one ball per frame, `track.ball_path`), on the pitch through the
broadcast camera's fitted matrix; where the ball's height from its flight is known (PR #226 writes
`z` and its standard error `se` on the ball), it is used, else the ball is taken to be on the
ground. Constants marked `E…` are measured below, never chosen.

1. **The ball over the goal line** (Law 9 and Law 10): its centre beyond the goal line the shooter
   attacks by more than its radius plus `E_X` (the ball's along-the-pitch position error near the
   goals).
2. **In the goal mouth**: at that frame, the centre within the posts by its radius
   (`|y - 34| <= 3.66 - 0.11`), and, where the height is known, under the bar by its radius plus
   two standard errors (`z + 2 se <= 2.44 - 0.11`). A centre within `E_Y` (the across error) of a
   post's inner edge is in, at half the line evidence (rule 6).
3. **In the net**: the ball then stays inside the goal's footprint, behind the line and no deeper
   than the net (`NET_DEPTH_M`, 2.0 m, plus `E_X`), between the posts (plus `E_Y`), on
   `IN_NET_FRAMES` = 3 frames (the out-of-play rule's count, `events.OUT_FRAMES`) before anything
   else happens to it. A ball over the bar lands beyond the net, and one wide in the side netting
   is outside the posts: neither passes.
4. **Kick-off after it** (Law 8): later in the clip, after a cut or not, the ball still on the
   centre spot (within `E_C`, the position error there) on `IN_NET_FRAMES` frames running,
   moving under `events.CARRY_MPS`. Where players are seen (the tactical views' fused positions
   when given, else the broadcast's), at least 90% (design) of those with a side are in their own
   half, within `events.RIVAL_M` (the players' position error).
5. **A save**: the shot was on target (its line, carried on, crosses the goal line in the mouth,
   rule 2, within `E_Y`), and before the line the ball's path turns (its direction changes by more
   than 30 degrees or its speed falls by half between the `SPEED_FRAMES` either side; design)
   within `events.CONTROL_M` of a keeper (`Track.keeper`, or the defending side's player nearest
   its goal line inside its penalty area). Then either he keeps it (the next spell is his), or it
   goes out over the goal line (a corner). **Blocked**: the same turn near any other defending
   player. **Off target**: anything else that is not a goal.
6. **Confidence** (a score, not a calibrated probability, as every detected event's): the line
   evidence (rules 1 to 3) is the mean ball detection score over the in-net frames, halved for a
   centre within `E_Y` of a post, and halved again when the height is not known; the kick-off
   evidence (rule 4) is the same mean over its frames. A goal's confidence is
   `1 - (1 - line)(1 - kickoff)`. The fact-checker's `MIN_CONFIDENCE` (0.5) gates what airs.

## The precision (to be measured on validation clips only)

On the 24 validation clips of dataset v2 at the look freeze (no test clip; seeds in
`docs/eval/fuse-gate.md`), with the demo detector's (ours-freeze) detections, the live path's
observations, graded against the clip's own ground truth (offline):

- `E_X`, `E_Y`: the 95th percentile of the ball's absolute position error along and across the
  pitch, on frames whose true centre is on the ground (`z <= 0.5`, the scorers' cut-off) and within
  25 m of a goal line. If fewer than 200 such frames are matched, all on-ground frames are pooled,
  and that is reported.
- `E_C`: the same 95th percentile, in distance, within 15 m of the centre spot.

## What is scored, once, at a frozen commit

Goal precision and recall, save precision and recall, with 95% Wilson intervals, and each failure
listed, on the test split of the shot-outcome set ([shot-outcome-set.md](shot-outcome-set.md)),
rendered for this because the frozen test set shows no goal and one save, and the 24 validation
clips hold no shot. False goals and false saves are also counted on the frozen 30-clip test set.

## Amendment (Oct 24, before any clip of the shot-outcome set was rendered or scored)

Found on the demo clip (seed 8001, development only, never a measurement): its goal was read as out
of play and a second, false goal 2.3 s later. Three rule fixes, none of them a threshold:

- **A goal no detected shot led to is still a goal.** A lofted strike's ground track bends wide of
  the posts as the ball rises, so no shot is read at it (events.py's known limit). Rules 1 to 3 are now
  also applied to every run of the ball over a goal line (`events.out_of_play`): at rest in the net,
  it is a goal for the side attacking that goal (an own goal counts for it too, Law 10), with the
  kick-off evidence as before; the last spell of that side before it becomes the shot, outcome goal.
- **A strike from behind a goal line is no shot.** A player rolling the ball out of the net toward
  the pitch had his path "cross the goal line between the posts" (the shot rule's test) and, the ball
  still in the net, a second goal.
- **The goal's time is when the ball crossed the line** (Law 10), the first frame of the unbroken
  stretch over the line that ends at rest in the net, not the first frame at rest: on the demo the
  ball sat beyond the net's depth for a second first, which put the goal 1.2 s late, outside the
  scorer's 1.0 s window.

On the demo clip afterwards: one shot (0.3 s from the true strike) and one goal (one frame from the
true goal), confidence 0.865 with the kick-off seen after the cut.
