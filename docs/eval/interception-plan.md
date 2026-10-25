# Interceptions from video: the rule and how it is measured (written 2026-10-24, before any run)

Section 2 of [detection-gaps-plan.md](detection-gaps-plan.md) (draft PR #311). Rubric: technological implementation
(one more event type from pixels, measured) and real-world impact (an interception is one of the
events an analyst logs by hand).

Nothing below has been run on any clip when this file is committed. No detected interception, and
no score for any rule here, has been looked at. The answer key of the validation matches has been
read only to see its event format (one rendered clip, seed 920101 from frame 35250).

## What the answer key records

`ninety/sim/engine.py` at the possession set's render commit `65247ba` (main has the same
`ninety/sim`): when an opponent of the passer **controls** a pass, the pass fails and names him
`interceptor`; the engine also writes `interception` (at the point of control, for his side, naming
him) only when `in_the_lane` holds: along the line from the kick to the pass's target
(`pass_target`, where the passer aimed), the point of control is short of `INTERCEPT_SHARE` (0.85,
*design*) of the line's length. A target at the kick's own spot counts as in the lane. A pass
collected beyond that share is a recovery: a `possession_change` only. Every `interception` comes
with a `possession_change` at the same frame.

The target is the passer's intention and is not in the picture, nor in the answer key's events.

## The stand-in for the target

A ground pass is struck so that it still moves at one of the engine's paces when it reaches the
target (`decisions.PASS_PACES`, 6, 10 or 14 m/s, *design*, D1), solved from ball physics
(`ball.ground_pass`: air drag `DRAG_K` and rolling resistance `ROLL_DECEL`, GROUNDING P5 and P8).
So the ball's speed as it leaves the foot says how far the target was, once the pace is known. The
pace is the passer's choice and is not seen, so it is chosen here, from these candidates, fixed now,
in this order (the nearest target first):

| Candidate | Target distance L from the launch speed v0, along the ball's direction of travel |
|---|---|
| `pace14` | how far a ball rolling from v0 goes before it slows to 14 m/s |
| `pace10` | the same, to 10 m/s |
| `pace6` | the same, to 6 m/s (`decisions.ARRIVE_MPS`, the softest pace) |
| `rest` | how far it rolls before it stops |

The roll is the engine's ground model, copied (the live path may not import the engine): each
1/25 s step the speed falls by `DRAG_K` x speed² x dt and by `ROLL_DECEL` x dt. A ball struck at or
below the pace has L = 0, so, as `in_the_lane` treats a target at the kick, any control counts as
in the lane. A lofted pass flies with drag only before it lands; its ground speed is all the
detector sees, so it is treated as a ground pass, and the measurement below includes lofted passes.

v0 and the direction are what the detector already measures at the strike: v0 is the pass's
`ball_speed_kmh` (the median frame-to-frame speed over the first `SHOT_LOOK_S`, 0.3 s), the direction
is from the ball at the strike to the ball at the end of those 0.3 s (`heads_for_goal`'s line). When
either is missing (fewer than two ball points in the 0.3 s) no interception is told.

**The rule (the engine's `in_the_lane`, with the stand-in target).** For a detected failed pass
whose next spell `b` is the other side's (the pass rule's interceptor case): with S the ball at the
strike, u the direction of travel and C the ball at `b`'s first frame, an `interception` is written
when (C − S)·u < `INTERCEPT_SHARE` x L. It is placed at C, at `b`'s first frame, for `b`'s side,
naming `b`'s holder by `attribute` (the interceptor the pass names), with `team_confidence` from
`b`'s track and `confidence` the possession change's at `b` (the ball's score at `b`'s first frame
times min(1, frames / (2 x MIN_SPELL_FRAMES))): one control, one confidence. A score, not a
probability.

Nothing else changes: the pass, its `interceptor` and the possession change are written as now.

## Choosing the candidate, and the bar (on validation truth only)

**M0, the stand-in against the truth.** The 15 validation matches of the possession set (seeds
920101 to 920115), simulated for 35 minutes at `65247ba` (`uv run ninety-sim --seed <S> --minutes
35`), no pixels. For every true pass with an `interceptor`, each candidate is applied to the true
ball path (the ball's x and y in `frames.jsonl` from the pass's frame, with the detector's own speed
and direction code), with C the pass's `end_x`, `end_y`; its verdict is compared with whether the
engine wrote an `interception` at that pass's end. Reported per candidate: disagreements out of
the passes, both directions (an interception called a recovery, and the reverse), with a 95%
Wilson interval, and the same for the two rules that ignore the ball (every one an interception;
none).

- **Chosen:** the candidate with the fewest disagreements; a tie goes to the one listed first.
- **Bar:** it must disagree strictly less often than the better of the two constant rules.
  Otherwise no `interception` is written (the decision of possession-change-plan.md stands) and
  this file says so.

M0 is the stand-in's error with a perfect ball; on video the speed and the spot carry the ball's
position error too, which M1 and M2 include.

## Development measurement on the rule (validation only, labelled as such)

No detector checkpoint is on the machine this is written on, so the validation clips cannot be run
through `detect.py` and `observe.py`. The rule is measured on **stand-in observations** built from
the answer key by `ninety/eval/turnover_standin.py` (evaluation code: it reads the answer key and
nothing on the live path imports it):
- each player seen is a box at his true place plus noise, his kit one of two colours by side;
  the ball the same; the camera ok in every frame. The noise is isotropic Gaussian, drawn fresh per
  frame and object, seeded, with sigma 0.188 m: the players' measured median position error on
  ours-v2's validation clips (0.221 m, docs/eval/attribution-derive.json) over a 2-D Gaussian's
  median radius (1.1774 sigma). Also run with no noise, as the rule's ceiling.
- **M1:** the possession set's 30 validation windows (docs/eval/possession-set.json), cut from the
  M0 matches, every player seen (as a whole-pitch view).
- **M2:** the possession set's validation clips rendered at `65247ba` (the one Track C rendered,
  920101 from frame 35250, and at most three more, the next three in the manifest's order: 920101
  from 47500, 920102 from 21500 and 920102 from 23750), only the players and the ball the broadcast
  shows (visibility above 0), at the rendered clip's own answer key.
- The detector runs unchanged on these rows (`events.detect`); the tracker, teams and spells are its
  own. Graded by `ninety/eval/event_score.py` (same type and team within 1.0 s, one to one, spot
  within 1.0 m strict or 2.0 m lenient of the ball at the detected time), per clip and pooled, with
  Wilson 95% intervals: true, detected, matched, precision, recall. Also: how many detected
  interceptions sit on a true recovery (a true `possession_change` with no `interception`, same side,
  within 1.0 s) and how many true interceptions were detected only as possession changes.

**Bar for writing it by default (development):** on M1 with noise, strict recall and precision of
`interception` both at least 0.5 (design: half found, and no more false than true; a stand-in is
easier than video, so this is a floor, not a claim). A kind that misses it is still built and tested,
but `events.WRITTEN` leaves it out, and this file says so.

Every number from M1 and M2 is a **development number on stand-in observations**, never a vision
result and never a test number. The possession set's test split is not rendered and is not scored
here. The real test number needs the detector checkpoint and the test renders (the pod).

## Outcome

To be written after the runs, below this line, without changing anything above.

### M0 (2026-10-24, 15 validation matches simulated at `65247ba`, 35 minutes each)

The rule ran as written; nothing above was changed after it. 477 true passes an opponent controlled,
all judged (a speed and a direction on every one); the engine called 229 of them interceptions.

| Rule | Disagrees | Rate (95%) | Interception called recovery | Recovery called interception |
|---|---:|---|---:|---:|
| `pace14` | 237 of 477 | 0.50 (0.45 to 0.54) | 95 | 142 |
| `pace10` | 214 | 0.45 (0.40 to 0.49) | 138 | 76 |
| **`pace6`** | **133** | **0.28 (0.24 to 0.32)** | 31 | 102 |
| `rest` | 232 | 0.49 (0.44 to 0.53) | 0 | 232 |
| every one an interception | 248 | 0.52 (0.48 to 0.56) | 0 | 248 |
| none | 229 | 0.48 (0.44 to 0.52) | 229 | 0 |

**Chosen: `pace6`**, which disagrees less often than the better constant rule (133 against 229), so it
clears the bar and `events.TARGET_PACE` is 6 m/s. Its error leans one way: 102 of its 133 are
recoveries it calls interceptions (a ball the passer struck softer than 6 m/s on arrival, or lofted).
So on a perfect ball path about one detected interception in four is a recovery, before any position
error (M1, M2 below).

### M1 and M2 (2026-10-25, [turnovers-dev.json](turnovers-dev.json), from commit `f996285`)

Development numbers on **stand-in observations** built from the answer key, validation only; not a
vision result. Strict matching (lenient gives the same here).

| Run | True | Detected | Found (recall, 95%) | Right (precision, 95%) |
|---|---:|---:|---|---|
| M1, 30 windows, noise 0.188 m | 25 | 86 | 12 (0.48, 0.30 to 0.67) | 12 (0.14, 0.08 to 0.23) |
| M1, no noise | 25 | 61 | 17 (0.68, 0.48 to 0.83) | 17 (0.28, 0.18 to 0.40) |
| M2, 4 rendered clips, noise | 2 | 13 | 2 | 2 |
| M2, no noise | 2 | 7 | 2 | 2 |

**Bar missed** (precision 0.14 against 0.5), so `interception` is not in `events.WRITTEN`: it is built
and tested, and measured with `detect(..., kinds=TURNOVERS)`, but the live path does not write it.
Of the 86 detected on M1 with noise, 32 sit on a true recovery (M0's lean, now with a noisy ball),
and the rest mostly on false failed passes: with fresh noise every frame the spells break (pass
precision falls from 0.64 to 0.35 on the same windows), and every false failed pass to the other side
can carry an interception. 4 of the 25 true ones were detected only as possession changes. The first run drew its noise from the platform's generator, which is not the same on every machine (lesson 46), and gave 13 of 99 right; the committed report is the rerun with portable draws, from the same commit's code. Two draws of the same noise moving a rate this much is the measure's own spread.

**Open, for review:** the noise is drawn fresh each frame. Real position error is mostly a camera
offset that persists over frames, so this stand-in is probably harsher on speeds than the video is;
whether to add a persistent-offset model is a change to what is measured, and would need an
amendment here before any run.
