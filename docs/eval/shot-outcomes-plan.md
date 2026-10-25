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

## Amendment 2 (Oct 24, evening, before any number of the shot-outcome set was read): the restart decides

Kian's call, relayed by the Coordinator: the restart after a shot is evidence of its own, from the
Laws. After a detected shot, the **first restart seen before the next strike** (across a broadcast cut
too) decides:

- **kick-off** (GROUNDING L4, Law 8): the ball still within `E_C` of the centre spot on 3 frames running
  (moving under `CARRY_MPS`), with the players who have a side in their own halves (rule 4's test).
  Then the shot is a **goal** for the shooter's side. Its confidence is `1 - (1 - line)(1 - kickoff)`,
  `line` 0 when the net was not seen; its time is the crossing frame when the line was seen, else the
  ball's last point nearest the goal line before the restart.
- **goal kick** (L8, Law 16): the ball still inside the goal area of the goal the shot attacked (no more
  than 5.5 m + `E_X` from the goal line, within 9.16 m + `E_Y` of the centre of the goal). Then
  **not a goal**: `on_target` if the keeper rule saw a save, else `off_target`.
- **corner** (L9, Law 17): the ball still within 1 m + `E_Y` of a corner of the end the shot attacked.
  Then **not a goal**: `on_target` (a save) if the shot was on target, else `blocked`.
- **none seen:** rules 1 to 5 as before.

A restart seen overrides the line evidence (the Laws say what happened; the net is a pixel judgement).
Thresholds are Law 1's geometry and the errors already measured on validation (`E_X`, `E_Y`, `E_C`,
`docs/eval/shot-outcomes.json`); nothing is fitted.

## Amendment 3 (Oct 25, after the validation score at 523f0074 and before any re-score; validation only)

Validation at 523f0074 (`runs/onepod-1025/out/score-val/report.json`, the pod's): goals found 12 of
16 ungated, 6 false, **0 above the 0.5 gate**; saves **0 of 50**. Diagnosed from the validation clips'
truth and the detected events only (the test split not opened):

- **Goal confidence:** all 18 detected goals score 0.153 to 0.434. Rule 6 halves the line evidence
  where no height is known (on the broadcast that is nearly every frame) and again near a post, and
  the kick-off is almost never inside a 10 s clip, so a goal's confidence cannot reach the gate the
  other events are judged by. Reliability (detected goals, share true): 0.15 to 0.2, 5 of 9; 0.2 to
  0.3, 2 of 2; 0.3 to 0.4, 4 of 5; 0.4 to 0.5, 1 of 2.
- **False goals:** 4 of 6 are saves: a ball in the keeper's hands, placed on the ground, lands
  behind the line by its height times the camera's slope. `events.out_of_play` already passes over a
  ball drawn over a player for this reason; the net rule did not. The other 2 are true goals timed
  1.2 and 2.6 s late (not changed here: the observations needed to see why are not on hand).
- **Saves:** of the 50, 39 are read as passes and 5 as nothing. About half carry the wrong side:
  a shot is tested only toward the goal the striker's side attacks, so a side read wrong (the
  broadcast's side accuracy on validation is about 0.58) makes a shot a pass. Most of the rest are
  lofted: the first 0.3 s of ground track meets the goal line 4 to 24 m wide of the centre while the
  keeper takes the ball by it (measured speeds 120 to 230 km/h against 65 to 120 true).

Four changes, none a fitted threshold:

1. **The net ignores a ball drawn over a player** (`on_player`), as `out_of_play` does.
2. **A shot's side is the side attacking the goal it heads for** (the engine's convention, the one
   `assign_teams` names sides by: home attacks x = 105), and a strike is tested toward both goals.
   Its `team_confidence` is the striker's track's when the two agree, else none (the kit says the
   other side).
3. **A strike is also a shot when its move ends at that goal**: the line from the strike to where the
   move ends crosses the goal line between the widened posts (`SHOT_MARGIN_M`) from within
   `SHOT_MAX_M`, and the move ends with a keeper's spell (`Track.keeper`) inside that goal's penalty
   area (16.5 m, Law 1), or with the ball over that goal line. The end of a move is on the ground or
   in the keeper's hands, so a lofted ball's height bends it far less than the strike's first 0.3 s.
   The same line counts for rule 5's "on target": a shot is on target when either line (the first
   0.3 s carried on, or the strike to the move's end) meets the goal line within the posts by `E_Y`.
4. **A goal's line evidence is the mean ball score over the in-net frames**, without the two halvings
   (they were design weights, and the reliability above shows they put every goal under the gate);
   a goal's confidence stays `1 - (1 - line)(1 - kickoff)`, the gate stays 0.5.

The validation clips are re-scored with this, the reliability table reported again, and then the
commit is frozen and the test split scored once.
