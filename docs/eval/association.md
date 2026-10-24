# Broadcast to tactical player association: plan and results

`ninety/vision/join.py` joins the broadcast's live run and the tactical views' live run of one clip.
The ball and the events come from the broadcast, the players from the views. It also pairs each
broadcast player track with the tactical track of the same man. This page fixes how that pairing's
threshold is set and how the pairing is graded. It was written before either step ran.

## Pre-registered (Oct 24, before any run)

**Clips.** The first 8 validation seeds in order: 108, 109, 110, 112, 113, 114, 115 and 116. 118
is excluded, as in the tactical scoring (`docs/eval/finetune-tactical/PLAN.md`). Each clip is a
10 s window at 25 fps rendered with both cameras (`runs/tactical1/val`). Test seeds are refused.

**Runs.** For each clip, `ninety.vision.live_job` runs twice at origin/main
(`716014c`, recorded in the run folder):
- the broadcast with ours-freeze, untiled;
- the views with ours-tactical, tiled.

**Step 1, the threshold (`association error`).** The views' players' pitch-position error,
measured by the rule that set the broadcast's `RIVAL_M` (`ninety/eval/pitch_score.py`): each
placed detection is paired with the true player whose box in that view it overlaps at IoU ≥ 0.5.
It is pooled over both views of all 8 clips, and its 90th percentile becomes `VIEWS_ERROR_M`. Then
`MATCH_M = hypot(RIVAL_M, VIEWS_ERROR_M)`: two independent errors on one man, added in quadrature.
Nothing is tuned against the association's results.

**The rule.** On every frame both cameras tracked, a broadcast player is paired with the nearest
tactical player only if:
- that player is within `MATCH_M`, and
- the next nearest is more than `MATCH_M` farther away.

Otherwise the frame is unpaired. A broadcast track takes the tactical track that most of its paired
frames chose. Its confidence is that track's share of its paired frames. Teams play no part.

**Step 2, grading (`association grade`).** Each tracked player of each camera is given the true
player nearest it on average over its frames, teams ignored. An association is right when both
tracks have the same true player. The results:
- the rate: associated broadcast tracks over all broadcast tracks, and the same weighted by
  tracked frames;
- the error: wrong associations over associated tracks, by count and by frames.

Each comes with a Wilson 95% interval. The results are reported as measured, with no second run
under another threshold.

## Deviations (recorded before the results were read)

- **The views' runs:** the first views runs placed nothing. `live_job` never passed `fixed=True`
  for a view (lesson 235): seed108 had its camera OK on 0 of 250 frames. They were run again with
  that one-line fix. The runs are at 716014c plus that line, as `code/COMMIT` in the run folder
  records.
- **seed112:** its broadcast run failed. The camera could not be placed on any frame, so `live_job`
  raised. seed112's views run is in step 1, and the clip is reported as not run in step 2.
- **seed115:** its broadcast run finished with the camera OK on 0 frames, so it has no broadcast
  track to pair. Its views are in step 1.

## Results

**Step 1** (`association/error.json`): the views' players' pitch-position error over 42,579
detections on all 8 clips. The median is 0.213 m and the 90th percentile **0.39 m**. The largest,
102 m, is one far outlier on seed113; the p90 is robust to it. So `VIEWS_ERROR_M = 0.39` and
`MATCH_M = hypot(1.26, 0.39) = 1.319 m`.

**Step 2** (`association/grade.json`), on the 7 clips with both runs:

| | Count | Share | Wilson 95% |
|---|---|---|---|
| Broadcast tracks associated | 144 of 179 | 80.4% | 74-86% |
| Their tracked frames | 12,456 of 14,461 | 86.1% | |
| Associations wrong | 4 of 144 | 2.8% | 1-7% |
| Their tracked frames | 176 of 12,456 | 1.4% | |

| Seed | Broadcast tracks | Associated | Wrong | Frame share |
|---|---|---|---|---|
| 108 | 40 | 38 | 0 | 0.93 |
| 109 | 26 | 26 | 0 | 1.00 |
| 110 | 31 | 15 | 1 | 0.72 |
| 113 | 25 | 22 | 3 | 0.80 |
| 114 | 22 | 11 | 0 | 0.79 |
| 115 | 0 | 0 | 0 | (camera never OK) |
| 116 | 35 | 32 | 0 | 0.95 |

- **Unassociated tracks:** most are short. The median is 17 tracked frames, under a second.
- **The 4 wrong pairs:** three have confidence 1.0, so the confidence does not flag them; each is
  20-48 frames long. The fourth has confidence 0.72 over 86 frames.
- **The right pairs:** median confidence 1.0, lowest 0.44.
- **So:** the confidence is reported, not used as a gate. A consumer that needs one man across both
  cameras for longer than a few seconds should prefer long tracks: of the associated tracks of 50 frames or more, 1 of 82 was wrong, against
3 of 62 shorter ones (reported, not a gate chosen here).
