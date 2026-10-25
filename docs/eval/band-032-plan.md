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

### Identity check (before use)

Fitted here with main's code, every frame's camera matrix and marking verdict equal track B's: seed
110, 0 of 250 differ; test clip 900001, 0 of 250 differ (only the matrices compared). Track B's fits
are used as the amendment says; every input's sha256 is in [band-032/inputs.sha256](band-032/inputs.sha256)
and [band-broadcast-032-observations.sha256](band-broadcast-032-observations.sha256).

### The band (stand-in, label boxes)

`uv run python -m ninety.eval.band_derive --clips <clips> --obs <obs> --seeds 108 ... 119 --out
docs/eval/band-broadcast-032.json`: **(0.901, 0.994)**, renderer 0.3.2, 3,000 frames, 1,508 good,
from 7 clips (108, 109, 110, 113, 114, 116, 118; 111, 112, 115, 117 and 119 have no good frame).
Above the "too few" line (500 frames, 6 clips). For comparison only, renderer 0.3's old band from
ours-v2's boxes on 0.3.0 was (0.901, 1.002).

Candidates on these frames ([band-broadcast-032.json](band-broadcast-032.json)): B1 markings keeps
98.5% of good frames and trusts 354 bad (worst 54.0 m); B2 heights 97.9%, 315 bad (93.9 m); **B3
96.5%, 266 bad (49.0 m)**. B3 keeps more than 90%, so it stays.

### The bar on validation (B3, then `agree`; [band-032/validation.json](band-032/validation.json))

1. Good frames kept: 1,455 of 1,508, **96.5%: met** (bar 90%).
2. Worst trusted frame: **48.96 m: not met** (bar 8.5 m). Clips with trusted frames over 1 m: 117
   (all 250, about 49 m), 112 (3, to 48.8 m), 114 (8, to 1.1 m), 116 (4, to 1.25 m).

Seed 117's true camera is the reverse angle (`frames.jsonl`, `angle: reverse`, in the far stand). It
is fitted as the main gantry turned half a turn about the centre spot, where Law 1's markings are
the same, so markings and heights both pass, and every frame agrees with its neighbours: the failure
track B found on 900003 (lessons 148, 159). It does not depend on the band. Main's band trusts 70 of
its frames too ([band-032/validation-main-band.json](band-032/validation-main-band.json)), and on
these clips keeps 382 of 1,508 good frames (25.3%). By the plan, the bar's miss means **the
proposal recommends against adopting this band as it stands**, on top of the amendment's stand-in
limit.

### Mutation run (before the test set; [band-032/mutation.txt](band-032/mutation.txt))

11 of 11 killed: the 0.3.2 band set to main's, to the old band or moved at its low end; the default
look set to 0.3.2; `place` ignoring its band; `--regate` or the fit path ignoring `--look`; any look
accepted; B3's markings dropped; `band_derive` allowing two looks or not recording the renderer.

### The test set, scored once (an estimate under the box mismatch, not a replacement for 0.25)

Track B's one-shot fits of the frozen five (ours-v2's committed detections), judged by
`observe --regate --look <look>`, graded by [band-032/grade.py](band-032/grade.py) and
`ninety.eval.event_report`:

| Seed | Main (0.5.15 band): trusted (good, bad) | Proposed (0.3.2 band): trusted (good, bad) | Good frames in clip | Proposed: median / p95 / worst |
|---|---|---|---|---|
| 900001 | 115 (61, 54) | 177 (177, 0) | 196 | 0.15 / 0.75 / 0.98 m |
| 900002 | 0 | 101 (101, 0) | 101 | 0.11 / 0.34 / 0.41 m |
| 900003 | 0 | 0 | 0 | - |
| 900004 | 30 (30, 0) | 153 (153, 0) | 160 | 0.18 / 0.72 / 0.91 m |
| 900005 | 9 (9, 0) | 250 (250, 0) | 250 | 0.08 / 0.23 / 0.38 m |
| all | 154 (100, 54), worst 1.77 m | **681 (681, 0), worst 0.98 m** | 707 | 0.11 / 0.60 / 0.98 m |

Passes, strict (lenient the same): main **2 of 13, 1 false, F1 0.25** (reproduces #298); proposed
**5 of 13, 2 false, F1 0.50** (900001: 2 found, 2 false; 900005: 3 found); published (event-report-v2)
7 of 13, 1 false, F1 0.67. Shots: proposed 0 of 1 and 1 false; main 0 of 1. Possession changes: 1 of 5
both, 0 false proposed and 1 false main. Files: [band-032/](band-032/) (`test-camera-look-*.json`,
`test-events-look-*.json`).

**Not adopted, and not adoptable here:** the band is from label boxes (amendment), and it misses
the validation bar on the reverse angle (above). What would make it adoptable: ours-v2 detections of
108 to 119 (the amendment's command), the band re-derived and the bar re-checked; the reverse angle
needs an absolute reference whatever the band (lesson 159).
