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

## Results

Pending: the runs are in progress.
