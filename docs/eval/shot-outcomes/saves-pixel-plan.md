# Saves from the picture: the ball held in the keeper's box (plan, before any number)

Committed before the rule's code is run on any clip. Result: [saves-pixel-result.md](saves-pixel-result.md).

## Why

At 8ac10a91 saves were found 0 of 50 on validation and 2 of 49 on test ([RESULT.md](RESULT.md)). A ball
in the keeper's hands is above the grass; placed on the ground through the camera it lands 2 to 7 m
behind him, so no spell is his (the ball is not within `CONTROL_M` of his feet) and the catch is not a
turn of the path at him. Its height is unknown. Its **picture** is not: drawn in the image, a caught
ball sits inside the keeper's box. That test needs no height (proposed by tactical cam C).

## The rule (amendment 7 to [shot-outcomes-plan.md](../shot-outcomes-plan.md))

1. **A hold.** `HOLD_FRAMES` ball points running on the ball's path (no cut between them, no point
   missing), each drawn with its box centre inside the box of the same keeper candidate: the
   definition `BallPoint.on_player` already uses, so "overlap" is the centre inside the box. A keeper
   candidate for a goal is `outcomes.keeper_of` for the side defending it (a track marked `keeper`
   standing within the penalty area's 16.5 m of that goal line, Law 1, or that side's player nearest
   the line inside it). `HOLD_FRAMES = events.OUT_FRAMES` (3): the event rules' count for a sustained
   condition, so a ball flying past in front of his body for a frame or two is not a hold.
2. **A save.** A strike (a spell's end, as the event loop has it) whose move contains a hold, before
   the next spell of anyone but that keeper, the next cut or the clip's end, is a shot for the side
   attacking that keeper's goal, outcome `on_target`, when:
   - the striker is not that keeper;
   - the line from the strike to the keeper's foot point at the hold's first frame (on the ground, so
     not bent by the ball's height) crosses that goal line between the posts widened by
     `SHOT_MARGIN_M`, from within `SHOT_MAX_M` (amendment 3's geometry, `ends_at_goal`);
   - it is not a goal: a strike `outcomes.judge` makes a goal stays a goal.
   A strike already read as a shot toward that goal keeps its event and takes outcome `on_target`; a
   strike read as a pass becomes that shot (its pass is not written). Its confidence is the shot rule's
   (the ball's score at the strike, scaled for a short spell).
3. **Nothing else changes**: goals, passes, out of play and possession changes are as at 8ac10a91,
   except a pass that rule 2 turns into a shot.

No new threshold: Law 1, `OUT_FRAMES`, `SHOT_MARGIN_M`, `SHOT_MAX_M` and the `on_player` test are the
rules' own. Known risks, reported and not tuned: a back-pass to the keeper from a defender reads as a
save for the other side (the broadcast cannot tell the passer's side well, side accuracy about 0.58);
a parry (one frame at the keeper) is not a hold.

## The measurement and its bar

- Validation only: the 80 clips of seeds 910001 to 910008 ([shot-outcome-set.md](../shot-outcome-set.md)),
  from the observations the pod kept (`runs/onepod-1025b/out/score-val2/observations`), events re-run
  with `--keep-saves`, scored by `python -m ninety.eval.shot_outcomes score` as before (strict: same
  team, within 1.0 s; gated at 0.5, ungated reported too). **Scored once.** No test clip is read: the
  test split (910009 to 910016, 900001 to 900030) was scored once already for shot outcomes.
- **Bar (gated): saves found at least 0.60 of the validation saves shown (30 of 50), and false saves
  at most 1 per 10 clips (8 on 80).** Goals are reported too; the rule must not lose a goal the
  8ac10a91 code found (12 of 16).
- Not held out, disclosed: validation was read for the earlier diagnosis
  ([shot-outcomes-val-diagnosis] in the notes, the 50 saves' nearest detections), so this is a
  development number, never a test one.
- If the bar is met, `events.SAVES_AIR` turns on and the phone may say "saved"; if not, it stays off,
  the result is written as it is, and nothing is tuned after the read.
