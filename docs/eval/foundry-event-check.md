# Foundry event check: measured, and not ready for the Ask

Code proposes candidate moments from tracked positions, our own Foundry deployment
(`ninety-labs-ai`, `gpt-4.1-mini`) looks at three frames of each and labels it, and code counts
(`ninety/vision/foundry_check.py`, graded by `ninety/eval/foundry_event_score.py`). The rules, the
held-out set and the bar were committed before any scored run
([foundry-event-check-plan.md](foundry-event-check-plan.md), commit `79d074b9`; code `3daa953b`).
It is a prototype: nothing on the live path calls it.

**Result.** On the held-out match (seed 8080) shots passed the bar: precision 0.88, recall 0.44,
against the detector's 0.19. On the demo (seed 8324), scored only because 8080 passed, the gain was
not repeated: precision 0.63, recall 0.28 against 0.22. Per club, the checker's shot counts on 8324
are the same as the detector's. Goal kicks are found (recall 0.83 to 1.0) but the precision is
0.23 to 0.39, because the model calls action in the goal area a goal kick. Corners and throw-ins
are too few to say. **Recommendation: do not wire it into the Ask.** Total spend: $0.061.

## Per type

Recall and precision with 95% Wilson intervals. "True" counts the events the video shows (for a
restart, its restart frame or its stoppage frame). The baseline is vision's detected events on the
same clip (`detected.jsonl`), graded by the same rules.

### Seed 8080 (held out, scored once)

| Type | True shown | Checker hits / detected | Recall | Precision | Baseline recall | Bar |
|---|---:|---:|---|---|---|---|
| Shot | 16 | 7 / 8 | 0.44 [0.23, 0.67] | **0.88** [0.53, 0.98] | 0.19 (3 / 9) | **pass** |
| Goal kick | 3 | 3 / 13 | 1.00 [0.44, 1.00] | 0.23 [0.08, 0.50] | 0 (none detected) | fail: n < 5, precision |
| Throw-in | 4 | 1 / 1 | 0.25 [0.05, 0.70] | 1.00 [0.21, 1.00] | 0 | counts only (n < 5) |
| Corner | 1 | 0 / 0 | 0 | none | 0 | counts only (n < 5) |

### Seed 8324 (the demo, scored after 8080 passed)

| Type | True shown | Checker hits / detected | Recall | Precision | Baseline recall | Bar |
|---|---:|---:|---|---|---|---|
| Shot | 18 | 5 / 8 | 0.28 [0.12, 0.51] | 0.63 [0.31, 0.86] | 0.22 (4 / 8) | **fail**: precision |
| Goal kick | 6 | 5 / 13 | 0.83 [0.44, 0.97] | 0.38 [0.18, 0.64] | 0 | fail: precision |
| Throw-in | 7 | 1 / 1 | 0.14 [0.03, 0.51] | 1.00 [0.21, 1.00] | 0.14 (1 / 1) | fail: recall not above |
| Corner | 1 | 0 / 1 | 0 | 0 | 0 | counts only (n < 5) |

The two shot recalls (0.44 and 0.28) have overlapping intervals, and so do both of them with the
baseline's. Across 34 shown shots the checker found 12 at 16 detections (precision 0.75) and the
detector found 7 at 17. That is better, but not by a margin these samples can show.

## What the Ask's counts would become

Shots per club against the answer key. The checker's sides come from code (the end the ball is
at), never from the model.

| | Truth, whole match | Truth, shown | Detector | Checker | Who had more |
|---|---|---|---|---|---|
| 8080 | home 17, away 8 | home 13, away 3 | home 7, away 2 | home 7, away 1 | home in all: right |
| 8324 | home 8, away 23 | home 6, away 12 | home 2, away 6 | home 2, away 6 | away in all: right |

Goal kicks if they went on the Ask: on 8324 the checker would say home 11, away 2, against
home 5, away 1 shown. The direction is right and the totals are double, so they would mislead.

## Misses and false positives

- **The goal area reads as a goal kick.** Of the 26 goal-kick labels over both matches, 8 were
  real goal kicks. Most of the others were shots or saves at the goal mouth. On 8080, the
  candidates at frames 41360, 56093 and 63715 sit 0.1 to 0.6 s from shots the checker missed; the
  model labelled each "ball in goal area, goalkeeper about to kick it". A low-detail 512 x 288
  crop of a goalmouth scramble looks like a placed ball to it. The label set, not the threshold,
  is where this fails: the confidence was 0.9 on every one.
- **Missed shots** (22 over both matches): 7 had a candidate within 1 s labelled `goal_kick`,
  7 one labelled `none` (the ball is a few pixels in the crop), and 9 had no candidate at all
  (one miss had both a `none` and a `goal_kick` candidate). The candidate rule needs the
  tracked ball to be fast toward the goal, and a tracked ball is interpolated over short gaps
  (`tracked_frames.py`), which blunts the speed of a strike.
- **Shot false positives:** 8080 had 1 (a cross from the touchline, 2.5 s before a real shot). 8324
  had 3.
- **Corners:** the broadcast's dead-ball cut hides most restarts (`dead_ball_cut`), and 8080 shows
  a single corner, only its stoppage. Neither match can say anything about corners.
- **Throw-ins:** precise when given (2 of 2) but rarely given (2 of 11): the set-ball rule found 1
  still spell a match, because the picture usually returns after the throw is taken.

## Cost and latency

| Run | Calls | Input tokens | Output tokens | Cost (Data Zone price) | Latency p50 / p95 | Wall |
|---|---:|---:|---:|---:|---|---|
| Smoke (one blank frame) | 1 | 990 | 27 | $0.0005 | 2.7 s | |
| 8080 | 52 | 51,480 | 1,389 | $0.0251 | 1.42 / 2.31 s | 39 s, 4 at a time |
| 8324 | 73 | 72,270 | 1,939 | $0.0352 | 1.39 / 2.48 s | |
| **Total** | 126 | 124,740 | 3,355 | **$0.061** of the $0.50 cap | | |

A call costs about $0.0005 and takes 1.4 s, so a full match of about 60 candidates costs $0.03.
Cost is not the obstacle. The input is 990 tokens a call: 3 images at 85 tokens, and about 600
tokens of schema and framing over the prompt itself. The estimate before the run used that
measured size ($0.026 estimated for 8080, $0.025 spent).

## What it cannot show

- Two matches, 34 shown shots: a rate of 0.75 has a 95% interval of about 0.5 to 0.9 at this n.
- One look: one broadcast style, one engine (65247ba3), the edit's dead-ball cut. The cut hides
  most restarts, so restart kinds were barely tested.
- The model was given low-detail crops to keep the cost down. A high-detail frame (about 1,100
  tokens an image) might separate a scramble from a placed ball. That would be a new plan,
  pre-registered and scored on a match neither of these is.

## Inputs and reproduction

Frames: 8080 from `runs/demo-8080-bundle-final/hls/720p` (ffmpeg, one segment at a time; its
render's frame files are gone), 8324 from `runs/demo-8324-final/images`. Positions and detections
come from `runs/demo-<seed>-*/` (`tracked.json`, `observations.jsonl`, `clip.json`,
`detected.jsonl`). The answer keys are in the footage hunt's notes folder (`events.jsonl`), read only
by the scorer. The raw calls (every candidate, its frames, label, confidence, tokens, latency) are
in [foundry-event-check/](foundry-event-check/).

```bash
uv run python -m ninety.vision.foundry_check runs/demo-8080-hunt --frames runs/demo-8080-bundle-final/hls/720p --dry-run
uv run python -m ninety.eval.foundry_event_score docs/eval/foundry-event-check/seed8080.json --run runs/demo-8080-hunt --truth <events.jsonl>
```
