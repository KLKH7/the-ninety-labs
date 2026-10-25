# One broadcast gantry per match, and "camera unsure" per shot: the plan (written before any run)

Written on branch `claude/vision-match-gantry-track-h-ff9b34`, based on `origin/main` at
`f455a412`, before any code of this change ran on a clip. Results go under "Outcome" at the end,
without editing what is above. Lessons 159, 230, 231, 242, 244.

## Why

The broadcast fit (`ninety/vision/pitch.py`) finds the gantry (where the main camera stands) once
per clip, from every 25th frame of that clip (`fit_clip`, `find_gantry`), then pan, tilt and zoom
per frame. A clip that only shows one end of the pitch cannot pin the gantry: seen from one end,
distance along the line of sight trades against zoom (`camera-cuts-plan.md`, "a tight lens's own
gantry slides 28 m"). Seen before this was written (observations other sessions wrote, read only):

- The demo match (seed 8080), segment 6, which opens on a corner (813.8 to 822 s): its gantry is
  fitted at (46.7, -42.0, 17.6), about 13 m from the true one; trusted on 77 of 205 frames.
  The same match's open-play window (60 to 64 s) and its throw-in window across a dead-ball cut
  (34 to 70 s) fit the gantry to within 5 cm.
- #330's set-piece validation clips have gantries 15 to 18 m off, and #345 found two more causes on
  some of them (pale turf, hard pans) that this change does not touch.

A broadcast match has one main camera on one gantry for the whole match. So the gantry is fitted
once per match, from frames of all its clips, and each clip only fits pan, tilt and zoom.

Rubric: technological implementation (the live path places players on set-piece clips, where
most goals start) and real-world impact (the graphics and the audio description of a corner rest
on trusted frames).

## (1) One gantry per match

**Which frames count.** For every clip of the match: its frames at every 25th index (today's
anchors, `anchor_every = 25`), each clip's own anchors as today (per shot when `--cuts` is on). An
anchor with fewer than MIN_POINTS marking pixels drops out, as today. If the match holds more than
MATCH_ANCHORS = 64 anchors in all (design: about three of today's longest clips; it bounds the joint
fit's cost on a 17-minute match), each clip's list is thinned evenly to its share,
`ceil(64 / clips)`.

**The search.** `find_gantry`, unchanged in every step, on the pooled anchors, with one
generalisation: the GANTRY_SCORE_FRAMES anchors the finalist gantries are scored on are taken
round-robin across clips (each clip's anchor with most markings, clips in order of that count; then
each clip's second best; and so on), so that a match's scoring sees several views instead of five
frames of whichever end has the most paint. With one clip, the round-robin is that clip's five best
anchors: exactly today's choice. The first ranking still uses the anchor with most markings overall,
and the joint refine still takes every pooled anchor within JOINT_MAX_MEDIAN_PX of the winner.

**Per frame.** Each clip is then fitted as `fit_clip` fits it today, with the gantry fixed at the
match gantry: tracking from the last good frame, a fresh search with the gantry fixed when the
track is lost. Trust (`observe.place`, `observe.agree`) is unchanged.

**What the live path may read.** Only what it reads today: each clip's `images/` and detections.
The match gantry is written to a file by `ninety.vision.match_gantry` from several clips' images
and detections, and `observe --match-gantry <file>` (and `live_job --match-gantry <file>`) read
it. The live path may carry an earlier fit from the same feed between clips (the match gantry, or
the anchors it came from); it never reads the answer key (`frames.jsonl`, `events.jsonl`),
`meta.json`, `clip.json` or the render settings, and the new module joins the
`test_vision_live_path` guard. Which clips are one match is the caller's statement (the clips it
passes together, one feed); nothing infers it from a clip id or a seed.

**Off by default.** Without `--match-gantry`, nothing changes.

## (3) "Camera unsure" per shot

With a match gantry, every shot also gets its own fit, as today (`fit_clip` on the shot alone, its
own gantry). A shot is **camera unsure** when both:

1. its own gantry is more than SHOT_GANTRY_M from the match gantry, and
2. the match gantry explains fewer of the shot's frames than its own gantry does: fewer frames pass
   the marking fit (`FrameFit.ok`: MIN_POINTS and MAX_MEDIAN_PX, today's constants) through the
   match gantry than through the shot's own.

Why both: a shot that shows only one end has a poorly pinned gantry of its own (the problem in
(1)), so distance alone would mark every goal-end shot unsure, which is the opposite of (1). What
says "another camera" is that the shot's own gantry explains markings the match gantry cannot. A tie
goes to the match gantry (no evidence of another camera).

**SHOT_GANTRY_M, measured before any result of this change.** The gantry fit's precision on
validation open-play clips: the largest distance between today's fitted gantry (`fit_clip`, one
shot) and the true one, over every validation clip whose true camera is the main gantry in every
frame (read from `frames.jsonl`, for grading only), rounded up to the next 0.1 m. Clips:

- renderer 0.3.2 (`cca498c`): validation seeds 108 to 119 rendered by #298, whose true camera
  stays on the main gantry; today's fitted gantries are read from the observations #332's session
  wrote with today's fit and the label boxes;
- today's look (0.5.17, `65247ba`, the set-piece clips' render): the first 4 s (kick-off) of each of
  #330's validation seeds 920106, 920108 and 920109, rendered for this plan with #330's flags
  (`stadium=broadcast`, `dead_ball_cut=true`). The window was chosen by rule before rendering: the
  demo's first segment also starts at 0 s, and none of #330's clips covers it.

Both looks are reported; SHOT_GANTRY_M is the larger (lesson 230: a value carries its look). The
demo (seed 8080, a training seed) never sets it.

**What it does.** Every frame of an unsure shot is not trusted (`camera.ok` false, `camera.unsure`
true, positions null), so tracks, events and on-screen graphics on it are held, as for any
untrusted frame. The first observation line lists each shot's gantry and verdict.

## Edge cases

- **A match of one clip** reduces to today: the pooled anchors are the clip's own, the round-robin is
  today's choice, so the match gantry is the clip's gantry; the shot's own fit is the same fit, the
  distance is 0, and no shot is unsure. The observations are the same as without the option
  (tested).
- **Reverse-angle shots** (a camera in the far stand). Law 1's markings are the same after a half
  turn about the centre spot (lesson 244), so the reverse angle draws what the near gantry mirrored,
  at (105 - x, -y') would draw. If the match gantry is within SHOT_GANTRY_M of that mirror (a
  gantry near halfway), check 1 cannot see it and the shot is not marked: a known limit, stated in
  the outcome. Otherwise its own gantry (the mirror) explains its frames and the match gantry does
  not, and it is marked unsure.
- **A shot with no frame of MIN_POINTS marking pixels** has no own gantry. It cannot disagree, so it
  is not marked; its frames have too few markings to pass the fit anyway, and stay untrusted.
- **A clip with no trusted frame at all** still adds its anchors to the pool; anchors that do not fit
  the winning gantry are left out of the joint fit by JOINT_MAX_MEDIAN_PX, as today.

## The bar, set before measuring

Detections are the drawn label boxes (`label_detections`, as #298 and #330 did): no checkpoint is
on this machine, so trusted counts are an upper bound on the detector's.

Validation matches: each of 920106, 920108, 920109 is its own match of two clips (#330's set-piece
clip and the kick-off window). Per clip, before (today, one clip at a time) and after (match
gantry):

1. **Gantry:** the match gantry is within SHOT_GANTRY_M of the true one on every validation match.
2. **Trusted on goal-end clips:** on each set-piece clip, the share of frames trusted after is at
   least 0.8 of the open-play share (frames trusted over frames, today's fit, on the kick-off
   windows together).
3. **No harm:** the worst trusted frame on every validation clip is within MAX_TRUSTED_M (8.5 m,
   `camera-bound-plan.md`), and at least 95% of newly trusted frames are good (ground error within
   1.0 m), as in `camera-cuts-plan.md`.
4. **Check (3) on validation:** no shot whose true camera is the main gantry is marked unsure.
   Reverse-angle shots on validation (seed 117 at 0.3.2, with `--cuts`) are reported: marked or not.
5. **One clip:** the same observations with and without the option (test, and the frozen test set
   below).

If 1 or 2 fails on a clip whose #345 cause (pale turf, a pan beyond the line model) is present,
that is reported as that cause, not tuned around. The option stays off by default until 1 to 4 are
met; turning it on is Kian's call.

Then reported, setting nothing: the demo (seed 8080's three rendered windows, pooled as one match:
the open-play window, the throw-in across a dead-ball cut, the corner of segment 6), per clip.

Then once, at the end, the frozen test set (900001 to 900005, each its own match): with the option,
each clip's observations equal today's (bar 5). Nothing is set from it.
