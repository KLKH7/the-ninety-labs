# Ball speed and shot speed from video: the speed error, pre-registered

Status: **scored once** on the 30 test clips (docs/eval/speed-report-freeze.md; the first run's frame half
was invalid, lesson 263, and was rerun after the fix; see Deviations). Written and committed before any
speed number on a dataset v2 clip was computed (R3, docs/TEAM.md, Sat 24: "speed error"; docs/EVALUATION.md, the
event detection row). The detector is ours-freeze, from its one scored test run (below). A change
after this commit is listed under "Deviations" with its date and reason, before any result is read.

**Rubric:** Technological implementation (a measured number behind the speed facts the agents and
the on-screen speed badges show) and UX (a badge is only shown if its error is known).

## What is measured

Vision already writes a ball speed on every pass and shot it detects (`ball_speed_kmh`,
`ninety/vision/events.py`, `_speed_kmh`): the median of the ball's frame-to-frame ground speed over
the 0.3 s after the strike (`SHOT_LOOK_S`), from its place on the pitch (the camera estimated from
the markings, the ball's box centre taken to be on the ground). The detector also has the ball's
velocity at every frame (`_velocity`, positions two frames either side, 0.16 s), which is what a
ball speed badge would show. Neither has been graded. Both are graded here, unchanged, on detected
data only; the answer key is read by the scorer, never by the vision path
(`ninety/eval/speed_score.py`, tested not to be imported by `ninety/vision`).

**1. Event speed, passes and shots** (the number the stats and the agents publish). Detected
passes and shots are paired with true ones by the event scorer's own rule
(`ninety/eval/event_score.py`, `match`, strict: same type and team, within 1.0 s, one to one,
nearest first, spot within 1.0 m at the detected time). For each pair with both speeds:

- error = vision `ball_speed_kmh` − true `ball_speed_kmh`, in km/h. The truth is the engine's
  launch speed, all three components (`ninety/sim/engine.py`, `shot` and `pass_to`);
- absolute error, and relative error (error / true speed);
- passes and shots summarised apart, and each pair listed with its seed, type and whether it was
  lofted.

**2. Frame speed** (a ball speed badge). Every frame where vision has the ball and a velocity
(`ball_path` and `_velocity`, unchanged) is paired with the true ball in the same frame. Error =
vision speed − true speed, km/h, against both the true 3D speed `|(vx, vy, vz)|` and the true flat
speed `|(vx, vy)|`, so the part of the error that is the missing height reads apart from the rest.
A frame the truth does not hold (a broadcast cut) is left out.

**Statistics, for each:** n, median absolute error, 90th percentile absolute error (the order
statistic `pitch_score` uses), mean signed error (bias: vision fast or slow), and median absolute
relative error. Relative error only where the true speed is at least 18 km/h (5 m/s, *design*: a
struck ball; events.py puts a pass at about 10 m/s), since dividing by a ball nearly at rest says
nothing.

**Splits:**

- **on the ground / in the air** (frame speed): EVALUATION.md's groups, defined once in
  `ninety/eval/vision_score.py` (`IN_AIR_Z`, `height_group`: in the air strictly above 0.5 m) and
  imported, never restated (lesson 188);
- **lofted / along the ground** (event speed): lofted when the true ball is in the air by that
  same `height_group` in any frame of the 0.3 s after the true strike (vision's own window);
- **drawn over a player or not** (frame speed; `on_player`: the ball's box inside a player's box,
  so its height and its place are a guess);
- **per clip**, and **pooled**.

## How many before a summary is claimed

A summary statistic (median, p90, bias) is published for a group only with at least **10 pairs**
(*design*, lesson 89: fewer is a list, not a rate). Below that the pairs are listed one by one and
the report says the group is too small. This is set before the number of matched shots is known.

## Expected error before looking (no pass or fail target)

No published accuracy figure for ball speed from a single broadcast camera was found, so there is
**no target and no pass/fail line**: the numbers are reported as measured. What the method can
reach is set down beforehand from committed measurements, not from speeds:

- the ball on the ground was placed to about 0.05 to 0.14 m (median per clip, capsule clips,
  ours-v2, event-report-v2; no measurement on dataset v2 yet). With an independent error σ in each
  of two positions 0.16 s apart, frame speed's noise is about σ√2 / 0.16 s: 0.4 to 1.2 m/s, **about
  1.5 to 4.5 km/h on the ground**. The report publishes the ball-on-ground position error measured
  on these clips (`ninety/eval/pitch_score.py`) beside it, so the floor can be checked;
- a ball in the air is placed too far from the camera (observe.py), so its speed can be wrong by
  much more, either way;
- a flat speed misses the vertical part: for a ball launched at angle θ it reads cos θ of the
  true speed even when placed exactly, **6% low at 20°, 13% at 30°**. Shots and lofted passes are
  expected to read low. 3D speed waits for the ball's height from its flight (draft PR #226,
  `ninety/vision/flight.py`), a follow-up scored by this same rule.

## Clips and detections

- **Clips: dataset v2's test set, 30 clips of 10 s, seeds 900001 to 900030**
  ([finetune-v2freeze/test-set.json](finetune-v2freeze/test-set.json), rendered at `aea01f4`).
  The clips are shared privately and never committed. Each clip is accepted only if its frames,
  events and images match that file's sha256 digests (line endings as committed, `\n`); a clip
  that does not match is not scored and the report says which.
- **Detections: reused, never re-made.** This test set was scored once for detection in PR #210,
  so the detector is **not run on it again**. The speed error reads that run's per-frame
  detections: `finetune-v2freeze-detections.tar.gz` on `pr-assets/finetune-v2freeze-detections`
  (42b2a07), sha256 `1b0e3ac6…c1e0` (finetune-v2freeze/PLAN.md). Before scoring it is checked
  that the archive matches that sha256, that every line names checkpoint `ours-freeze`, and that it
  holds exactly the 30 seeds, one line per frame of each clip. Anything else stops the score.
- **From detections to speeds, at this commit:** `ninety.vision.observe` (the camera from the
  markings in each image, the boxes onto the pitch), then `ninety.vision.events` (the ball's path,
  its velocity, the events). Observe reads the clips' images, never their truth; nothing in it is
  changed for this score. If Kian shares observations made from these detections instead of the
  images, they are used only with the observe code they were made by named, one line per frame of
  each clip, and the report says so.
- **Inputs, not constants:** the clip set, the clips folder, the observations folder and the
  detector's name are arguments of the scorer. Round 2's checkpoint is a re-run with its own
  detections, scored by the same rule and published beside this one, never over it.
- No clip is looked at before the score, and nothing in vision is changed after it.

## Known before the score

- The chosen clips' true events have not been counted for this plan; how many shots there
  are is read from the score, and the 10-pair rule above decides what is claimed.
- Nine of the 30 test clips have a camera cut or a dead-ball cut; cut frames are left out.
- Consecutive frames are not independent: frame-speed n counts frames, not separate balls.

## Deviations

- 2026-10-23, before anything was scored or committed: an earlier draft named the five-clip
  frozen test sets (capsule `cca498c`, mesh `91d1e3b`) and ours-v4. It was replaced on Kian's
  instruction (R1): the clips are now dataset v2's and the detector ours-freeze. The capsule set
  was re-rendered locally: its truth matched the frozen digests, its images did not (rendered on
  Windows), and it was not scored.
- 2026-10-23, before anything was scored or committed: the v2 test set was already scored once
  (PR #210), so the detector is not re-run on it. Two options were weighed (that run's detections,
  or ours-freeze on the validation clips); Carlos chose that run's detections.
- 2026-10-24, before anything was scored: main was merged into this branch (merge 939d7eef, main
  76e91265), so the speed error measures the vision path the demo runs. Since this plan's base
  (0f101db) main changed the camera fit in `observe.py` and `pitch.py` (#229, #250, #270, #285) and
  the ball path's drawn-over-a-player test in `track.py`; `events.py` and the scorers are
  unchanged. Two observation runs started on the old code were stopped and are not used. The
  observations are instead those of the ball height session's run (PR #226), made at main
  a8719457 from the same detections and arguments, whose `observe.py` (d6e065b9), `pitch.py`
  (f7ec71de), `track.py` (cf0be765) and `detections.py` (17ed58cc) are those of this branch after
  the merge. Each file is used only if its sha256 matches the list that run publishes, and it holds
  one line per frame of its clip. Carlos approved both changes.
- 2026-10-24, after the first score, a scorer defect fixed (lesson 263): frame speed read the true
  ball's velocity from fields a rendered clip does not hold, with a default of 0, so every true
  speed was 0 and that half of the first report graded nothing. The true velocity is now the
  central difference of the true places one frame either side (a frame without both neighbours is
  left out), and a missing field is an error. Nothing else changed: the matching, groups,
  thresholds and the event-speed half (which reads the true event's `ball_speed_kmh`) are as
  registered, and the event-speed numbers are the same before and after. The report is rerun once
  with the fix and the first one is not kept.
