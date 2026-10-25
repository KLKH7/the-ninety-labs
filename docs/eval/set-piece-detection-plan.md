# Set pieces from the video: the plan (written before any of its code runs on a clip)

Section 1 of [detection-gaps-plan.md](detection-gaps-plan.md) (#311). Written on branch
`claude/vision-set-pieces-track-e-a5a8ab`, `origin/main` at `c88fbe6` with #299 (the set-piece set,
`restart_kind`) and #298 (camera cuts, `observe --cuts`, off by default) merged in, before any
detector code was written or run. Results go under "Outcome" at the end, without editing what is
above it. Lessons 8, 41, 202, 207, 227, 230, 231 (the sides one: a rule that leaves cases undecided
is scored over every case), 235, 242/243 (the reverse angle is the main camera's mirror).

Rubric: technological implementation (two more event types from pixels, measured) and real-world
impact (a corner or a throw-in is logged without a human, and the Describer can say which).

## What was seen before this was written

- The engine's restarts at the render commit (`ninety/sim/engine.py`, `stop`, `tick_restart`,
  `restart_ball_spot`, `throw_stand`, `throw_hands`): where each kind's ball is set, and that the
  `set_piece` event is written when the ball is set and its taker is ready, **before** the kick: the
  taker then holds 0.5 to 1.5 s (a free kick, goal kick or kick-off), strikes it as he arrives (a
  corner, off his run-up; a penalty), or throws 0.2 to 0.45 s later (a throw-in, the ball in both
  hands over his head, 1.85 m up, 0.28 m behind the touchline).
- The broadcast's edit at renderer 0.5.17 (`ninety/render/edit.py`, `camera.py`): the picture comes
  back from a cut on the gantry's own wide shot 2 s before the restart and holds it 4 s with no
  second angle. The set-piece set renders `camera_cut=false` (its sample clip's `clip.json`), so it
  has no second angle at all: no reverse angle, behind-goal or tight lens. Its only cuts are the
  edit's, through each dead ball, on the gantry.
- The one rendered validation clip's events (seed 920101 from 16.84 s): an `out_of_play` over the far
  touchline, then a `set_piece` at the same x on that line (a throw-in). No observation of any clip
  was computed, and no detector exists yet.
- `docs/eval/attribution-derive.json`: the players' position error, p90 1.256 m (renderer 0.3,
  ours-v2's validation clips).

## The signal (pixels only)

`ninety/vision/restarts.py` reads the observations (`observe.py`) and the events `events.py` wrote.
It never opens the answer key, the render's settings or its edit list, and goes on the
`test_vision_live_path` guard list.

1. **A dead ball** (a *cue*), any of:
   - an `out_of_play` that `events.py` detected;
   - a `goal` (none is detected on main yet; #271's will count once it lands);
   - a cut: a jump in the observations' frame numbers (the convention `events.py` already uses:
     nothing seen before a cut is linked to after it), or a change of `camera.shot` when the clip
     was observed with `--cuts` (`pitch.shot_starts`);
   - the clip's first frame (the clip may open on a dead ball, such as the match's kick-off).

   Only the fact of a cut is used, **never its length**: the length of the wait the edit leaves out
   follows the engine's restart delays per kind (`RESTART_DELAY_S`), and reading it would copy the
   answer from the edit.
2. **A set ball**: after the cue, the ball seen still (its speed, `events._velocity`, under
   `events.CARRY_MPS`, 4 m/s, the plan's own threshold) on at least `STILL_FRAMES` frames in a row
   (design: 10 frames, 0.4 s; set now and not tuned: a ball rolling past at pass speed is under 4 m/s
   for no frame, and the engine's own wait before a kick is longer), with no detected pass, shot or
   spell of a player carrying it between the cue and that run.
3. **The restart**: the first frame the set ball moves off at more than `CARRY_MPS` with a player
   within `events.CONTROL_M` (1.5 m, P6) of it in the frame before: the taker. A kick-off's two
   players either side of the ball are one taker (the nearer).
   - **Time** is that strike's frame (Laws 8 and 13 to 17: the ball is in play when kicked and
     clearly moves).
   - **Team** is the taker's track's side (`track.assign_teams`), its `team_confidence` the track's.
   - **Spot** is the median of the still run's ball positions (a set ball does not move, so the
     median cuts the noise; nothing is fitted).
   - **Player** is the taker's id (`h-t12`) when `events.attribute` names him, else null.
4. **A throw-in** has no still ball on the ground: it is in the thrower's hands, drawn over his body
   (`on_player`), so its place on the ground is metres wrong (`observe.py`: placed on the ground, a
   ball 1.85 m up lands beyond him by its height times the camera's slope). So: after a cue, the ball
   drawn over one player on at least `HELD_FRAMES` frames in a row (design: 3 frames, as `OUT_FRAMES`:
   one frame is as likely the box overlap of a ball passing him), that player's foot point within
   `LINE_TOL_M` of a touchline or beyond it, then the ball seen off his body inside the field. Time is
   the last held frame, team the thrower's, the spot his foot point's x on that touchline (Law 15:
   the throw is taken from where the ball crossed the line). The ball's height is not used; with
   #226 or #286 it can replace the foot-point test, measured then.

A restart not preceded by a cue is not detected (a ball merely slow in open play is not a restart).
After a restart the next one needs a new cue.

## The kind, from the spot (Laws 1, 13 to 17)

The detector's own spot (never the stoppage) decides the kind, nearest zone first:

| Kind | Zone (Law 1's markings) | Within |
|---|---|---|
| kick-off | the centre spot (52.5, 34) | `BALL_TOL_M` |
| penalty kick | either penalty mark (11 m out, on y = 34) | `BALL_TOL_M` |
| corner | either corner arc (radius 1 m about a corner) | 1 m + `BALL_TOL_M` of the corner |
| goal kick | either goal area (5.5 m deep, 18.32 m wide, centred on y = 34) | `BALL_TOL_M` outside it |
| throw-in | the thrower's rule above (a held ball at a touchline) | `LINE_TOL_M` |
| free kick | a set ball anywhere else | - |

When a spot is within reach of two zones (possible only if `BALL_TOL_M` is over 2.75 m, half the
gap between a goal area's front and its penalty mark) the nearer zone wins.

**Tolerances, from measurement precision.** Set by this rule before any restart is detected:
- `BALL_TOL_M`: the 90th percentile of the ball's ground position error (vision's ball against the
  true ball at the same frame) over the frames whose true ball is on the ground (z at most 0.2 m)
  and whose camera the live path trusts, on the possession set's rendered validation sample (seed
  920101 from 1410 s, 65247ba, renderer 0.5.17: the set-piece clips' look, lesson 230, and none of
  the clips this plan scores), rounded up to the cm. The same rule on the set-piece validation clips
  is reported beside it, per zone where there are frames, not used.
- `LINE_TOL_M`: the same percentile of the players' foot-point error on that clip.
- Both come from observations made with the drawn labels as detections (below), so they are the
  camera fit's error, not the detector's; the scored runs use the same reading (lesson 227).

**Confidence**, a score from 0 to 1, not a probability: the ball detection's mean score over the
still run (for a throw-in, the held run), times `min(1, run / (2 * STILL_FRAMES))`, times 0.5 when the
detector's own last stoppage contradicts the kind (an `out_of_play` it saw over a touchline before
a corner or goal kick; over a goal line before a throw-in). The halving is design, set now.

**Where the kind goes.** `schemas/match_event.schema.json` has `additionalProperties: false` and no
kind field, so the kind is not in the event. It is written beside the events, in a side report
(`restarts.json` in the live job's `--out`: each detected restart's event id, kind, zone distance,
still or held frames, and the cue it followed). Whether to add a `restart` field to the schema from
the engine's `Restart.kind` is R4's and Kian's call; until then the Describer cannot say "corner"
from a detected event.

## Where the detector and `restart_kind` could agree for the wrong reason

Both see the same stoppage, so agreement can be shared structure rather than detection:
- **The cut's length.** It carries the restart delay per kind; the detector never reads it (above).
- **The stoppage.** `restart_kind` names a throw-in from the stopping event's place and a free kick
  from a foul. The detector does not read its stoppage for the kind, only to halve a confidence, so
  a kind it gets right it got from where it saw the ball set.
- **Goal kick against corner.** Both rules read the set ball's place. That is the Law, not a shared
  shortcut, but it means a kind can be right while the spot is several metres wrong. So the kind is
  graded only on restarts matched in time and team, and the spot error is reported for each of them
  whether or not it is within the strict radius.
- **Kick-off.** A clip that opens on the centre spot is a kick-off by both rules because both start
  there; the kick-off at frame 0 of a match is reported apart from the kick-offs after a goal.

## Scoring (offline; the answer key is read only here)

`ninety/eval/restart_score.py`:
- **Type, team, time and spot** with `ninety/eval/event_score.py` unchanged: same type and team
  within 1.0 s, spot strict 1.0 m and lenient 2.0 m at the detected time; `set_piece` and `kickoff`.
- **Kind** against `restart_kind` (`ninety/eval/set_piece_set.py`) on the true restarts matched
  (time and team, no spot radius), with a confusion table of the six kinds and "missed".
- **Time from the true restart**, signed, for every matched restart. The truth writes a set piece
  when the ball is set, up to 1.5 s before the kick the detector sees (above), so some true restarts
  are expected to fall outside event_score's 1.0 s window although the kick was found. That is
  reported as it is; neither the window nor the detected time is moved to fit it. Whether the truth
  should carry the kick's frame, or the scoring the Law's moment of play, is an open question for
  R4 (below).
- **False restarts** per clip, and every miss and false event listed.
- **Coverage** (lesson 231): a true restart whose frames the live path places on no trusted camera
  is a miss, counted in the denominator, and listed as "no camera".

## Clips

- **Measured on validation only.** The test split is not rendered and is not scored here.
- **Detections:** no detector checkpoint is on this laptop, so every clip uses its drawn labels
  copied as detections (score 1, players and ball; as Track B did,
  `docs/eval/camera-cuts-plan.md`). The camera is fitted from the pixels as on the live path. So the
  numbers measure the camera fit and the restart rule, and are an upper bound on what the detector
  would give.
- **Clips:** the rendered set-piece validation clip (seed 920101 from 16.84 s, a throw-in), plus at
  most three more validation clips rendered here at `65247ba` with `set_commands.py`, chosen by this
  rule before any is rendered: for each of goal kick, corner and free kick, in that order, the
  manifest's validation clip holding that kind (by `restart_kind` on the validation matches,
  simulated at `65247ba` only as far as needed) with the earliest start, ties to the shorter, then the
  lower seed; a clip already chosen that holds a later kind covers it; a slot left over goes to the
  shortest kick-off clip. Penalties: validation has none.
- **Camera trust:** observed without `--cuts` (the live default) and with `--cuts`, both reported;
  the headline is the live default. At renderer 0.5.17 with `camera_cut=false` there is no
  reverse-angle shot in these clips. If a later set does have one, its restarts are counted as
  misses ("no camera" or wrong spot), never dropped.

## The bar, set now

- **To merge (off by default):** every planted test passes and each mutant of the new code is
  killed; the live job runs it only with `--restarts`; the live path guard covers the module.
- **On validation (a handful of restarts: counts, not rates):** reported per kind with denominators.
  It decides nothing by itself.
- **To turn `--restarts` on by default** (after the test split is rendered and scored once, at a
  frozen commit): restarts (type and team, strict) with recall's 95% Wilson lower bound at least 0.5
  and precision at least 0.8, and the kind right on at least 80% of the matched restarts of every
  kind with 30 or more in the test split. Below that it stays off, and the challenge map stays
  `planned`.

## Open questions (for R4, R1 and R3)

1. A `restart` field in the schema (the engine's `Restart.kind`), so the kind travels in the event
   and the Describer can say it.
2. The set-piece event's time: the truth's "ball set" against the Law's "ball kicked". Changing
   either is a change of the answer key or of the scoring rule, not of this detector.
3. The cue from a cut is the frame-number jump the index carries. A real broadcast's frames carry no
   match frame number; `--cuts` (pixels) is the honest cue, and it is off by default.

## Amendment 1 (2026-10-24, while writing the code, before it or any observation ran on a clip)

Three holes in the signal above, found by reading it against the engine, not by any result:
- **Still is too loose.** Under `CARRY_MPS` (4 m/s) a ball dribbled at a jog is "still", so after a
  cue a dribble could be read as a set ball. A set ball also stays where it is: every ball position
  of the still run must lie within `BALL_TOL_M` of the run's median (its own measured position error;
  no new constant), as well as under `CARRY_MPS`.
- **A set ball is on the field.** In the hold before the edit's cut the dead ball rolls off and is
  stopped beyond a line; a still ball more than `BALL_TOL_M` outside the lines is never a set ball
  (a throw-in has its own rule).
- **The clip's first frame** is a cue only for a kick-off (a clip opening on the centre spot, as at
  the match's start); a clip that opens in open play must not admit a free kick at its first stop.
- The clause "no detected pass, shot or spell between the cue and the run" is dropped as ill-defined
  (a restart's own strike is a pass). Instead the latest cue before a candidate governs, and one cue
  admits one restart, the first candidate after it.

Known limit, not tested as a pass: where no cut hides the wait, the ball knocked to the spot by
another player and stopped there reads as a restart at the knock, and the real one is missed.

## Amendment 3 (2026-10-25, after the free-kick clip's first run, validation only)

**Seen:** on validation seed 920108 from 42.44 s the kick-off after the goal was missed on both
readings: through the true camera the ball on the centre spot moves between frames by up to 0.1 m
(the ball box's pixel rounding), and amendment 1 required *every* point of the run within
`BALL_TOL_M` of the run's median. `BALL_TOL_M` is a 90th percentile, so by its own definition about
one point in ten lies outside it, and a 10-frame run passes about a third of the time. That was a
mistake in the rule, not a value to tune.

**The rule now:** a point and the run's median each carry up to `BALL_TOL_M` of error, so a point
may lie up to twice it from the median; and, as the tolerance is a 90th percentile, at least 90% of
the run's points must lie within that. No new constant: both follow from the tolerance's definition.
The share is counted as "at most one point in ten further, rounded up", so a run growing frame by
frame may hold one such point from its start (found on a planted scene, before any clip was re-run).
The test split is untouched; the validation clips are re-run with it and both runs are reported.

## Outcome

### The clips (by the rule above)

The validation matches were simulated at `65247ba` for their first 8 minutes, enough to know the
kinds of every validation clip starting before 183 s (seeds 920101 to 920106, 920108 to 920110), and
`set_piece_set.windows` on them gives exactly the manifest's starts and lengths. By the rule:
goal kick seed 920106 from 182.8 s (14.08 s), corner seed 920109 from 124.36 s (14.08 s), free kick
seed 920108 from 42.44 s (29.72 s, which also holds a kick-off after a goal). With the rendered
throw-in (seed 920101 from 16.84 s), that is four clips.

## Amendment 2 (2026-10-24, after the live camera fit was run on two clips, before any restart was detected)

**Seen:** the live path's camera fit, with the drawn labels as detections, trusts **0 of 250** frames
of the possession sample (the tolerance clip) and **0 of 352** of the set-piece throw-in clip. Its
gantries are 15 m and 18 m from the true ones (true: 55.5, -35.3, 15.0 m, inside the search grid),
the marking fit's median 12.7 px off. So on the set-piece set's look (renderer 0.5.17,
`stadium=broadcast`) the live path places nothing, and every restart there is a miss ("no camera").
The fault is the camera fit's, outside this plan (R3, `ninety/vision/pitch.py`); it is not changed here.

**What changes, before any restart is detected:**
- The live measurement stands as the headline and is reported as it is: every restart of these
  clips counts as missed with "no camera" (lesson 231), nothing dropped.
- A diagnostic is added beside it, never a live number: the same observations (boxes, scores, kit
  colours) re-placed through each frame's true camera (`ninety/eval/true_camera.py`), every frame
  trusted. It measures the restart rule with the camera fit taken out, an upper bound.
- `BALL_TOL_M` and `LINE_TOL_M` cannot be measured on the live reading (no trusted frame). They are
  measured by the same rule on the true-camera reading of the possession sample, and the scored
  diagnostic uses that same reading (lesson 227). On the live path they are not yet measured: if the
  fit is fixed, they are re-measured on its reading before any live restart number is read.

### Validation, first two clips (amendment 3's rule; the corner and goal-kick clips are still rendering)

Drawn labels as detections throughout. [validation-live.md](set-pieces/validation-live.md) is the
live path; [validation-true-camera.md](set-pieces/validation-true-camera.md) the diagnostic.

| Clip | Restart | Live camera | Live: found as | Strict match | Why not |
|---|---|---|---|---|---|
| 920101 from 16.84 s | throw-in | 0 of 352 frames trusted | - | no | no camera |
| 920108 from 42.44 s | free kick | 731 of 743 trusted | free kick, home, 0.05 m off | no | 1.68 s after the truth's event |
| 920108 from 42.44 s | kick-off after a goal | (same) | kick-off, home, 0.53 m off its nearest home player | no | 2.92 s after the truth's event |

- **The kind is right on every restart found** (2 of 2 live, 3 of 3 through the true camera), and
  nothing is matched, because every found restart is later than the truth's by more than event_score's
  1.0 s. The detector's time is the kick (the true ball first moves 1.76 s and 3.0 s after the
  truth's events, 2 and 2 frames after the detected ones); the truth's is when the ball is set and its
  taker ready. Neither the window nor the detected time is moved for it (above, "Scoring"): it is
  open question 2.
- **The throw-in, through the true camera,** is found 0.32 s after the truth, 0.06 m away, as a
  throw-in, but under the wrong side: `events.py`'s side naming is flipped on that clip (every pass
  there is `away`, the truth's `home`), and the restart takes its taker's side.
- **False restarts:** live, the two above (late, not false in kind). Through the true camera also a
  free kick on the throw-in clip: `events.py` reads the thrown ball's ground point, metres past the
  far touchline, as out of play; that cue admits the next still ball, a team-mate's first touch.
- **Amendment 3's effect:** with amendment 1's every-point rule, the kick-off was not found on either
  reading (its run kept breaking on the ball box's pixel jitter); everything else is as above.
- **The camera fit is per clip, not per look:** it fails on the throw-in clip and the possession
  sample, and holds on 920108. Live tolerances still cannot be measured by the plan's rule (its
  clip has no trusted frame), so the live run uses the true-camera reading's tolerances, a mismatch
  the plan names (lesson 227).
