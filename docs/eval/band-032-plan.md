# A broadcast height band for the frozen test set's look (renderer 0.3.2): the plan

Status: **proposal, for @KLKH7 to choose (option (a) on #270), written before any derivation.**
Written 2026-10-24 on branch `claude/vision-band-032-track-f-522f8d`, from `origin/main` at
f54e9efa. Results go to the end of this file, under "Outcome", without editing what is above.
Lessons 148, 149, 159, 227, 230, 242.

## Why

#270 re-derived the broadcast trust test's height band, (0.966, 1.121), on renderer 0.5.15, the
demo's look, and added gate B3 (heights and markings). The frozen test set
(`test-set-frozen.json`, engine `cca498c`) is renderer 0.3.2. On it the new band rejects most frames
whose camera is right: trusted frames on 900001/900004/900005 fell from 238/194/248 to 115/30/9 and
strict pass F1 from the published 0.67 to 0.25 (#298, `docs/eval/camera-cuts-plan.md`, Outcome).
Lesson 230's rule says a band carries the look it was measured on. Option (a) is one band per look,
each derived by the same rule on that look's own validation clips. The old band (0.901, 1.002) is
not put back: it predates B3, the grain blur in `pitch.py` (#250) and today's camera fit.

Rubric: technological implementation (the published event numbers are measured on main's code, on
the test set's own look).

## Seen before this was written

- #298's tables of the test set re-judged three ways (old band, #270's band, #270's band and B3),
  and its remark that a right camera's ratio with label boxes is about 0.94 to 0.96 on 0.3.2
  validation seeds 110 and 118. No observation of mine has been made or read on a test clip.
- That the 12 validation clips below exist and are renderer 0.3.2 (each clip's `clip.json`,
  `renderer.version`; read offline, never by the live path).
- Image statistics, for the look question below: frame size, and a grain measure (the median of
  |grey - its 3x3 median|) on every 25th frame of 0.3.2 seeds 108, 109, 110, 117 and two 0.5.17
  validation clips of track C's sets (seed 920101). Nothing else.

## Data

- **Validation (derivation):** ours-v2's bulk validation seeds 108 to 119
  (`vision-report-v1/train-manifest.json`, `val_seeds`; never trained on, never test), rendered by
  track B at `cca498c`, the test set's renderer, 0.3.2 (checked in each `clip.json`). 12 clips,
  3,000 frames. 120 to 122 were not rendered. Never a test seed (`band_derive` refuses them).
- **Detections on validation: the drawn label boxes, score 1, as stand-ins.** The ours-v2
  checkpoint is not on this machine, so validation cannot be detected with the detector the test
  set is scored with. This is a different reading (lesson 227): a label box is exact, and a
  detector's box is noisier. Per frame the ratio is a median over players, which damps that noise,
  but the band's 1st and 99th percentiles may come out narrower than ours-v2's boxes need. This is
  the proposal's main limit and is stated with every number. If ours-v2 detections of 108 to 119
  become available (the pod), the same command re-derives the band on them and that band replaces
  this one before anything is adopted.
- **Observations:** main's `observe.observe` at f54e9efa (#250's `pitch.py`, one shot, no cuts) on
  each validation clip's images and stand-in boxes. The band does not change the fit or the ratio,
  so one run serves every band.
- **Test (scored once, at the end):** the frozen five, 900001 to 900005, track B's local re-render
  at `cca498c` (byte-identical to the frozen digests), ours-v2's committed detections
  (`docs/eval/vision-report-v1/detections`). Their camera fits are made with main's code at
  f54e9efa; they may run before the band is committed (the band does not enter the fit), but no test
  observation is judged, read or scored before the band, the selection code and its tests are
  committed.

## 1. The band

The same function and rule as #270: `ninety.eval.band_derive` (which calls
`detector_derive.gates`), broadcast kind. Every frame with an estimated camera gets its ground
mapping error against the true camera (a 5 m grid of pitch points, median distance); a frame is
**good** when that is within 1.0 m. The band is the 1st to the 99th percentile of the frames' height
ratio over the good frames, rounded to 3 decimals. Committed as `docs/eval/band-broadcast-032.json`
with the observation files' sha256.

**Too few to derive:** if fewer than 500 good frames, or good frames from fewer than 6 of the 12
clips, the band is not set and the proposal asks for more clips instead.

## 2. How a clip's look is known

**No live-path signal is established that tells 0.3.2 from 0.5.x.** Both looks are 1280 x 720. The
grain measure overlaps: 0.3.2 seeds 108 and 110 read 3.0 and 2.5, but 109 and 117 read 1.0, the same
as the two 0.5.17 clips (1.0 and 0.98); 0.3.2 draws its grain per clip from its render parameters.
The other difference known, the height ratio itself, is what the band judges, so choosing the band
from it would be circular (a wrong camera scales heights too). A pixel classifier of the look would
need its own validation of both looks, which is not possible before the freeze.

So the look is **declared, not detected**: `observe` takes the band by name, `--look`, and its
default is the demo's look (0.5.15, #270's band). The evaluation passes `--look 0.3.2` for the frozen
test set, from the test set's own record (`test-set-frozen.json`, "renderer 0.3.2"), offline. The
live path never reads `meta.json`, `clip.json` or any render setting, and `live_job` is unchanged:
it always runs at the default. **Limit:** a clip of an undeclared look is judged by the default
band; the band can only be chosen per test set, offline, by whoever runs the evaluation.

## 3. With B3

Unchanged: on the broadcast a frame is trusted when its ratio lies in its look's band **and** its
marking fit holds (B3), then `agree`. Only the band changes with the look. `gates` also reports B1,
B2 and B3 on 0.3.2 validation; if B3 keeps fewer than 90% of good frames there (step B's floor,
`detector-plan.md`), that is reported and B2 for this look is offered as an alternative for Kian to
choose, not adopted here.

## 4. The bar, set before measuring

On the 12 validation clips, with the derived band, B3 and `agree`:

1. good frames kept: at least 90% (step B's floor);
2. the worst trusted frame's ground error: at most 8.5 m (`camera-bound-plan.md`'s value; observed,
   not a bound, lesson 159), with every clip that has trusted frames over 1 m listed.

If either fails, the proposal says so and recommends against adopting it. The test set has no bar:
it is scored once and reported whatever it shows.

## 5. The test set, once

With the band, the selection and the tests committed: each test clip's observations re-judged
(`observe --regate --look 0.3.2`), then

- trusted frames per clip, split good and bad by the same 1.0 m truth measure, with the median,
  p95 and worst ground error of the trusted frames;
- events by `ninety.eval.event_report` (strict and lenient), passes pooled over the five clips;

reported beside main today (#270's band, `--look 0.5.15`: pass F1 0.25, 2 of 13) and the published
figure (event-report-v2: 0.67, 7 of 13), with the denominators.

## 6. Code and tests

- `ninety/vision/observe.py`: `BANDS` (look name to band, each citing its measurement),
  `HEIGHT_BAND` stays the default's, `place(..., band=)`, and `--look` for a fit or a `--regate`.
  `observe()` and `agree` are not touched (#298 edits them).
- Tests: the 0.3.2 band is the committed measurement and from validation seeds only; the default is
  #270's; `--look 0.3.2` judges a frame by its band end to end (the CLI on a written file); an unknown
  look is refused. A mutation run on the new code (band values, the default, the selection, the
  refusal), each mutant expected to fail a test.
- EVALUATION and the challenge map: the numbers as a **proposal**; main's current figure stays
  #298's 0.25 unless this merges.

## Outcome

### Amendment (2026-10-24, before any derivation: no band, ratio or validation error has been computed)

**This band is not adoptable as derived here.** It measures each box's height against an upright
1.80 m. The label boxes are tight around the drawn body; ours-v2's boxes have their own systematic
size error, of unknown sign and size at this look. A band from label boxes applied to ours-v2's test
detections mixes two box sources, which can bias it either way. So:

- the band derived below is a **stand-in band**, and the proposal can only be adopted once it is
  re-derived, by the same command, on ours-v2 detections of the 12 validation clips;
- the test-set numbers below are an **estimate under that mismatch**, never a replacement for main's
  0.25 or a published figure;
- the gap between label and detector boxes is **not measured on any test clip**.

**Searched first, for ours-v2 detections or observations at the 0.3.2 look:** the repo, `docs/eval/`,
`tests/fixtures/`, every remote branch's history and the PRs. The only ours-v2 validation
observations are #187's (commit 7448d3d8: seeds 108, 109, 114 to 116, 120 to 122, 2041 to 2043,
3041, 3042). They are render run v1, renderer 0.3.0, before #102 redrew the players' bodies as their
labelled capsules (0.3.1; 0.3.1 to 0.3.2 changed labels only), and from other 10 s windows (seed 108:
frames 3286 to 3535 there, 4258 to 4507 here). Their boxes are of another picture of the players, the
very thing the ratio measures, so they cannot stand in for 0.3.2. `tests/fixtures/broadcast-seed108`
holds 2 frames. None is used.

**What finishes it:** ours-v2's checkpoint (`checkpoint_best_total.pth`, train manifest
`docs/eval/vision-report-v1/train-manifest.json`) on a machine holding the 12 clips, then for each
seed N in 108 to 119:

    uv run --group vision python -m ninety.vision.detect <clips>/seedN --checkpoint ours-v2 \
        --weights <ours-v2>/checkpoint_best_total.pth --out <dets>/seedN.jsonl
    uv run --group vision python -m ninety.vision.observe <clips>/seedN \
        --detections <dets>/seedN.jsonl --out <obs>/broadcast/seedN.jsonl

and `uv run python -m ninety.eval.band_derive --clips <clips> --obs <obs> --seeds 108 ... 119
--out docs/eval/band-broadcast-032.json`, then BANDS["0.3.2"] set from it and the test set scored
again (section 5). The clips are track B's local renders at `cca498c` (about 1 GB), or
`uv run ninety-dataset` at `cca498c` for those seeds.

### Amendment (2026-10-24, 22:00, before any derivation)

The laptop's load (230 on 8 cores) gives each fit about 13% of a core: after an hour no clip had
finished. So the one-shot fits track B already made from the same stand-in boxes are used for seeds
111, 112, 113, 117, 118 and 119 (its `before` observations: `pitch.fit_shots` with one shot, which
its branch tests to be exactly main's `fit_clip`), and its one-shot test fits for 900001 to 900005
(ours-v2's committed detections). Both are copied, never moved, and their sha256 recorded. Seeds 108,
109, 114, 115 and 116 are fitted here with main's code. **Identity check, before use:** seed 110 and
test clip 900001 are also fitted here with main's code, and every frame's camera matrix must equal
track B's; only the matrices are compared, nothing on the test clip is judged or read. If any
differs, track B's fits are not used and the derivation waits for this machine's.
