# Why the broadcast camera fit trusts no frame on some 0.5.17 clips: a diagnosis

Diagnosis only: no threshold, fit or model was changed. It was written on 2026-10-25 for R3, the
round after the freeze. It answers why the live broadcast fit (`ninety/vision/pitch.py`,
`find_gantry` / `fit_clip`, called by `ninety/vision/observe.py`) trusts no frame on some clips of
the set-piece set's look (renderer 0.5.17, `stadium=broadcast`), while it trusts 87–98% of frames
on others of the same look. Lessons 215, 230 and 244 were read first.

Everything below reads the answer key (`frames.jsonl`: each frame's true camera) for diagnosis.
Nothing here is a live number. Detections are the drawn labels, as in draft #330
(`ninety/eval/label_detections.py`).

## The clips

| Clip | Live fit: trusted | Fitted gantry vs true | `sun_azimuth_deg` | Pan range (deg) |
|---|---|---|---|---|
| set-piece seed920101 from 421 | 0 / 352 | 22.4 m off | 105.1 | −12.5 to 7.0 |
| set-piece seed920109 from 3109 | 0 / 352 | 11.4 m off | 67.8 | 28.1 to 52.6 |
| possession seed920101 from 35250 | 0 / 250 (#330) | 16.6 m off | 105.1 | −9.9 to 4.0 |
| set-piece seed920108 from 1061 | 731 / 743 | 0.2 m off | 201.8 | −38.2 to 0.0 |
| set-piece seed920106 from 4570 | 315 / 352 | 2.4 m off | 17.1 | −37.1 to −23.8 |

All five clips show only the main camera (`angle: main` in every frame). The true gantry is fixed
in each clip (sd 0), and it lies inside the search grid. seed920109 has `camera_cut: true` in its
params, but no cut falls inside this window. For possession 35250 no live observations were on
disk, so its row uses #330's figures, and its gantry was re-run with `find_gantry` on the same
anchors for this note (40.5, −33.8, 8.1 against the true 55.5, −35.3, 15.0).

## What separates them: two defects, one on each failing seed

### 1. Pale turf: the marking mask's grass test fails, so most lines are never seen (seed920101)

`line_mask` counts a pixel as marking only if the pixels on both sides of it pass a grass test,
`g > r + 10 and g > b + 10`, after the 3 × 3 blur. On seed920101 the turf is pale and blue-grey,
and its green barely beats its red.

Every 25th frame, on pitch pixels more than 6 px from any marking (through the true camera):

| Clip | Grass test passes (median of frames) | g − r (median) | Mean grass RGB | Marking pixels per frame (median) |
|---|---|---|---|---|
| 920101 / 421 | 0.48 | 10 | (111, 121, 89) | 1,451 |
| 920101 / 35250 | 0.20 | 7 | (121, 129, 94) | 797 |
| 920109 / 3109 | 0.82 | 12 | (117, 129, 88) | 6,829 |
| 920108 / 1061 | 0.98 | 25 | (88, 113, 26) | 16,192 |
| 920106 / 4570 | 0.98 | 30 | (64, 93, 8) | 18,090 |

The pixels the mask does find are right. On seed920101's anchors, 96–100% of them lie within 2 px
of a true marking, and through the true camera the markings test passes on 63 of 71 sampled frames
(421) and 50 of 50 (35250). The mask finds few lines, but not wrong ones: on the 421 opener only an
arc of the centre circle and a few dashes of the far touchline pass (green in the overlay; red
pixels are more than 2 px from a marking).

What breaks is the gantry search. Its first stage ranks all 31,339 grid views per gantry with a
chamfer from model to image: each model point in shot looks up the distance to the nearest marking
pixel (`chamfer_many`). Only the best `COARSE_KEEP = 64` go on to the exact cost and the refine.
Through the true camera, few of the model's points have a marking pixel near them, so the true view
ranks far down:

| Anchor | Model points in shot with a marking pixel within 8 px (true camera) | Chamfer rank of the grid view nearest the truth, gantry fixed at the true one |
|---|---|---|
| 920101 frame 471 | 0.13 | 1,164 |
| 920101 frame 496 | 0.18 | 1,330 |
| 920101 frame 35250 | 0.25 | 1,715 |
| 920101 frame 35300 | 0.14 | 9,102 |
| 920109 frame 3109 | 0.38 | 1,413 |
| 920108 frame 1061 | 0.69 | 42 |
| 920108 frame 1086 | 0.71 | 107 |
| 920106 frame 4570 | 0.66 | 2 |

The views the chamfer prefers are aimed off the pitch (pan −0.8 to −0.9 at 421, tilt 0.05 at
35250). They keep `MIN_IN_SHOT` model points in shot and little else, so they pay for few points
that have no marking pixel. So even with the gantry fixed at the true one, `search` returns a view
costing 17.9 on frame 471 (the true view costs 1.45), and 22.3 on frame 35250 (true view: 1.01).

`find_gantry`'s costs on seed920101 / 421 (mean Cauchy loss, px², on 300 marking pixels; the first
5 anchors by marking count):

| Gantry | Per anchor | Sum |
|---|---|---|
| chosen finalist (37.5, −30, 12.1) | 5.8, 6.7, 4.6, 5.0, 3.5 | **25.5** |
| nearest grid node to the truth (52.5, −40, 16.2), rank 7 of 36 on anchor 1 | 9.5, 8.7, 9.7, 10.9, 9.6 | 48.4 |
| the true gantry, through `search` | 17.9, 8.7, 9.2, 8.6, 9.6 | 54.1 |
| the true camera itself (no search) | 1.45, 1.89, 2.28, 2.34, 2.75 | 10.7 |

The objective would pick the truth. The search never offers it. Each finalist is the gantry
whose best reachable view explains a few arcs least badly. The joint refine then settles there:
(38.5, −49.5, 11.5), 22.4 m off.

All five anchors are the same framing (pan 0.04 to 0.11, a 24° lens on the centre circle and the
halfway line). They add little that the first does not already say.

The grass test's pass rate varies across a frame (0.0 to 0.56 between 421's anchors). In the
opener's overlay, the pieces that survive lie where the turf is darker. That fits mown stripes
deciding it, but it was seen and not measured stripe by stripe.

Why the turf is pale is not proven here, only suggested. Both failing seeds have the sun on the far
side of the pitch, in front of the camera: azimuth 105° and 68°, where 90° is +y, the far
touchline. The working seeds have it behind or to the side (202°, 17°). The pitch shader adds
sun-dependent sheen and mowing highlights (`web/render/render.js`, `decoratePitch`: `sheen` and
`mow`, both green-yellow additions), and `MeshStandardMaterial`'s specular lobe faces a camera
looking into the sun. That is 2 seeds against 2, a correlation and not a test.

### 2. Strong pans: the line model drops a touchline whose far end is behind the camera (seed920109)

The model's straight lines are single long segments: each touchline is one 105 m segment, each goal
line one 68 m segment (`pitch_polylines`). `distances` and `costs_many` keep a segment only if
**both** ends are in front of the camera (`(da > 0) & (db > 0)`), and they do not clip it. With the
camera at x ≈ 50 panned more than about 35° toward a corner, the near touchline's far end is behind
the camera, so the whole near touchline leaves the model. That is usually the brightest and longest
line in the picture.

seed920109 pans 28–53° for its whole window: 68 of 71 sampled frames have a segment like that. At
frame 100 the near touchline is drawn from the corner flag to the bottom-left edge of the picture.
Its pixels sit at the 100 px cap through the **true** camera, and the projected model (magenta in
the overlay) has no line there.

Through the true camera, the markings test (median ≤ 1.5 px on line_points' 800, at least 60
pixels):

| Clip | Model as is | Straight lines cut into 5 m pieces (counterfactual) | Frames with a segment half behind the camera |
|---|---|---|---|
| 920109 / 3109 | 51 / 71 | 70 / 71 | 68 |
| 920101 / 421 | 63 / 71 | 63 / 71 | 0 |
| 920101 / 35250 | 50 / 50 | 50 / 50 | 0 |
| 920108 / 1061 | 149 / 149 | 149 / 149 | 22 |
| 920106 / 4570 | 71 / 71 | 71 / 71 | 3 |

On 920109 the true camera's anchor costs are 12.4 to 24.5. That is as high as the wrong finalists'
(20.7 to 31.1), so the objective cannot prefer the truth. Its mask is also weak: 0.38 of the model
covered on the opener and grass passing 0.82 with g − r 12, the same pale turf as defect 1, though
milder. The fitted gantry (53.9, −20.1, 11.7) is 11.4 m off. On the working clips the segment loss
is rarer and mild: 920108 and 920106 pan to at most 38°, and other lines carry the fit. The
renderer's framing does reach these pans whenever play is near a corner, which is where corners
and throw-ins happen.

The tests in `tests/test_vision_pitch.py` pan between −0.25 and 0.42 rad (−14° to 24°), so none of
them can show this.

### The first anchor's framing, and the stadium dressing

- Off-pitch contamination is small on every clip: 0–2% of anchor marking pixels on the failing
  clips, up to 18% on 920106, which works. The boards, stands and scorebug are not what breaks the
  fit.
- The first anchor (most marking pixels) is a centre-circle view on seed920101 and a corner view on
  920109. Neither is unusual, and both working clips open on similar framings.

## Feasibility (not a chosen fix)

`find_gantry` on each clip's anchors (every 25th frame, drawn-label boxes), with each counterfactual
alone and both together, error to the true gantry in metres. "gate" means the mask's grass test
reduced to `g > b + 10`. That is not a proposed value: it was picked to show the direction, and it
costs precision on the working clips (on-marking share 0.96 to 0.81 on 920108's opener, 0.91 to
0.64 on 920106's). "split" means the model's straight lines cut into 5 m pieces.

| Clip | main | split | gate | gate + split |
|---|---|---|---|---|
| 920101 / 421 (fails live) | 22.42 | 17.19 | **0.04** | 0.93 |
| 920101 / 35250 (fails live) | 16.60 | 16.55 | **0.88** | 0.81 |
| 920109 / 3109 (fails live) | 11.36 | 2.27 | 5.95 | **0.23** |
| 920108 / 1061 (works) | 0.60 | **0.01** | 1.03 | 0.20 |
| 920106 / 4570 (works) | 0.93 | 0.91 | **26.91** | **13.08** |

The "main" column reproduces the live fit's gantries on the failing clips to the centimetre. The
working clips differ slightly from the live run (0.2 m and 2.4 m) because the anchors here have no
ball box and `fit_clip` is not run.

What it says:
- seed920101 is the mask alone: with lines found on the pale turf, the existing search finds the
  gantry to within 0.04–0.9 m. Splitting the model does nothing there (no pan is strong enough).
- seed920109 needs both. Splitting alone brings it from 11.4 m to 2.3 m; with the mask too, 0.23 m.
- The crude gate **breaks a working clip**: 920106 goes from 0.9 m to 26.9 m (13.1 m with the
  split). Its turf is deep green and the extra pixels it admits there are not markings (on-marking
  share 0.91 to 0.64). So the mask fix must keep precision on the look that works, which a fixed,
  looser margin does not.
- Splitting the model harms nothing measured here, and it tightens 920108 (0.60 m to 0.01 m).

## What a fix needs (a plan for R3, not applied)

Two fixes, independent, each with its own validation, in this order:

**A. The model must keep the part of a line that is in front of the camera.** Cut every straight
marking into short pieces, or clip each segment to the camera's near plane, in `distances`,
`costs_many` and `refine`'s model. This is geometry, not a threshold: Law 1's lines are where they
are, and projection only needs them in front of the lens. A test that must fail on main: a view
panned 45° toward a corner, whose near touchline is drawn, fits at ≤ 1.5 px through the true
camera. Check that the coarse `MODEL_SAMPLES` path (already 1 m samples, correct) and the exact path
then agree. Re-run the four validation clips and the frozen test set's committed observations,
because every pan above about 35° changes.

**B. The marking mask must find lines on pale turf.** The grass test is absolute (green 10 levels
above red and above blue), set on older looks. Lesson 230's rule applies: re-derive it on the look
the renderer draws now, by a rule written before any number is seen. One candidate is to judge
grass against the frame's own turf (for example, its dominant pitch colour) rather than a fixed
margin. The bar should be lesson 215's: the most pixels within 2 px of a true marking, keeping at
least 80% of the current mask's on-marking pixels on the clips that work today, and model coverage
through the true camera reported for every clip. Validation clips must include the sun in front of
the camera (azimuth 45–135°) and behind it, which the renderer's `uniform(0, 360)` already samples.
Hold out the test set.

**C. (After A and B, only if the fit still misses.)** The coarse ranking averages model-to-image
distance over the points in shot, so a view aimed mostly off the pitch costs little. A symmetric
chamfer (also image-to-model) would make it pay for marking pixels it leaves unexplained. That is a
change to the search, and needs lesson 21's independent audit like any engine change.

Order and scope: A is small and unambiguous, and on its own it brings 920109 from 11.4 m to 2.3 m.
B is the one that rescues seed920101, and it needs a pre-registered derivation that keeps 920106
working; the feasibility gate above fails that. The lessons for both (a model piece silently dropped
behind the lens; a colour gate set on one turf) go into `docs/LESSONS.md` with the fixes. Neither changes
the trust test (height band or `MAX_MEDIAN_PX`). After them, re-measure #330's set-piece numbers:
#330 currently loses the throw-in and the corner on these clips.

## Reproducing

The scripts (`anchors.py`, `grass.py`, `sweep.py`, `stage.py`, `maskcf.py`, `feas.py`, overlay
images) are in the shared notes folder for this round of sessions (`side-session-notes/local_209d3acf…/broadcast-fit-pale-turf/`, with every output JSON), not in the repo, because they
read the answer key. Each takes a clip folder that holds `frames.jsonl` and `images/`.
