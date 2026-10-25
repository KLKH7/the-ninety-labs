# Restarts on four rendered set-piece validation clips: the detector on main, measured

The restart detector on `main` (`ninety/vision/restarts.py`, #320 and #325) graded by its own
scorer (`ninety/eval/restart_score.py`, #335), unchanged, on four clips of the set-piece set's
**validation** split ([set-piece-set.md](set-piece-set.md)). The test split is not rendered and is
not scored here. Nothing in the detector or the scorer was changed or tuned on these clips. Carried
over from the closed #330, which had first measured them.

Rubric: technological implementation (event detection measured on renders against ground truth).

## The clips

Rendered at the set's render commit `65247ba3`, renderer 0.5.17, `stadium=broadcast`,
`dead_ball_cut=true`, each with `ninety-validate` passing (`uv run python -m ninety.eval.set_commands
docs/eval/set-piece-set.json --out <dir> --split validation`, the lines for these four). Chosen by a
rule fixed before any was rendered (#330's plan): the rendered throw-in sample, then for each of goal
kick, corner and free kick the manifest's validation clip holding it with the earliest start.

| Clip | Restarts it holds |
|---|---|
| seed920101 from 16.84 s (frame 421) | throw-in |
| seed920108 from 42.44 s (frame 1061) | free kick; kick-off after a goal |
| seed920106 from 182.8 s (frame 4570) | goal kick |
| seed920109 from 124.36 s (frame 3109) | corner |

## How they were run

- **Detections:** the drawn labels copied as detections, score 1 (`ninety/eval/label_detections.py`):
  no detector checkpoint was on the machine. So every number here is an upper bound on what the
  detector would give: the camera fit, the tracker, the side naming and the restart rules are
  measured, the detector's own misses are not.
- **Live reading:** `ninety.vision.observe` (main's, no `--cuts`), then `ninety.vision.restarts`.
- **True-camera reading (a diagnostic, never a live number):** the same observations re-placed
  through each frame's true camera (`ninety/eval/true_camera.py`): boxes, scores and kit colours as
  the live path saw them, only the camera replaced. It takes the camera fit out.
- **With #283:** #283's kit reader (`observe.recolour` at its head `56c543b`, which keeps each
  frame's camera and boxes) and `main`'s `restarts.py` with the one change #283 makes there (sides
  from `sides.assign`). #283 is not merged; this measures it, nothing more.
- **Grading:** `uv run python -m ninety.eval.restart_score <clip> <restarts.jsonl> ...`: each true
  restart timed at its kick, its kind by `restart_kind`, matched with its kind and side within 1.0 s.
  The free kick's cause was not run (the detector's command line does not annotate it), so the cause
  table reads "None" and says nothing about `restart_cause`.

## Results (counts: 5 restarts in all)

| Restart | Live | True camera | Live, with #283 | True camera, with #283 |
|---|---|---|---|---|
| kick-off after a goal | found (0.12 s) | found | found | found |
| free kick | found (0.12 s) | found | found | found |
| corner | missed | **found** | missed | missed |
| goal kick | missed | missed | missed | missed |
| throw-in | missed | found, **wrong side** | missed | found, wrong side |

Files: [main-live.json](set-piece-validation/main-live.json),
[main-true-camera.json](set-piece-validation/main-true-camera.json),
[with-283-live.json](set-piece-validation/with-283-live.json),
[with-283-true-camera.json](set-piece-validation/with-283-true-camera.json).
No false restart on the live reading. Through the true camera the one false restart is the throw-in
found under the wrong side (graded with the side asked, it is a miss and a false detection). The kind
is right on every restart found.

## Why each is missed

- **The camera fit** trusts no frame of the throw-in and corner clips on the live reading (its
  gantry 22.4 m and 11.4 m from the true one, each true gantry inside the search grid); it trusts
  731 of 743 and 315 of 352 on the other two. Diagnosed in #345: pale turf hiding the lines on
  920101, a hard pan dropping the near touchline from the line model on 920109.
- **Side naming** (`track.assign_teams`). Through the true camera, the share of tracked player-frames
  with the true player's side ([side-accuracy.json](set-piece-validation/side-accuracy.json)):

  | Clip | Kits | `main` | #283 |
  |---|---|---|---|
  | 920101 | low contrast: black halves against navy halves | 0.596 | 0.605 |
  | 920108 | black sash against white sash | 0.973 | 0.981 |
  | 920106 | black halves with white shorts against white hoops | 0.425 | 0.303 |
  | 920109 | white against dark halves with white shorts | 0.501 | 0.389 |

  On the goal-kick clip two home centre-backs (h3, h4) are sided away, so Law 16's "no opponent in
  the penalty area" refuses the goal kick; on the throw-in clip every side is flipped. Even the better
  of each naming and its flip leaves three clips near 0.6: the kits are not told apart, not only named
  the wrong way round. Kits that share white or black, or low contrast, is a pattern in four clips, not
  a measured cause.

## What it cannot show

Rates (five restarts, one of each kind but the penalty, which validation has none of); the detector's
own recall on a set ball (labels stand in for it; the demo's development check in
[restarts-vision-plan.md](restarts-vision-plan.md) found the ball scored under threshold at a corner);
anything about the test split.
