# Ball height for shots, on target, saves and out of play: a measured negative

**Verdict: no type passes its bar on held-out seed 8080, in either variant. Nothing is turned
on.** The Ask cannot newly count shots, shots on target, saves or out of play from this work.

Pre-registration: [ball-height-events-plan.md](ball-height-events-plan.md). It was committed
before any flight-on number (972a5661), and amendment 1 (variant B) went in before either variant
was scored (c7ec47b4), both on branch `vision/ball-height-events`. Measured on 2026-10-27 from
stored observations on CPU; no vision model was re-run.

- **Variant A:** today's event rules on observations corrected by the flight fit
  (`ninety/vision/flight.py` with PR #410's ball-size and 60 m/s launch checks, applied to main at
  279441fa).
- **Variant B:** "shot by outcome". A strike of at least 10 m/s heading for goal from within 35 m,
  then within 3.5 s one of these: (a) a keeper (vision's flag) gains the ball, (b) the scorebug
  shows a goal within 10 s, or (c) the ball goes over that goal line. On flight-corrected
  observations.
- **Matching:** `event_score.match`, same type and team within 1.0 s, time only. Truth is limited
  to shown frames.
- **Bar, per type, on 8080:** P ≥ 0.80, the Wilson lower bound of P ≥ 0.50, at least 5
  detections, and recall above the off arm.

## Held-out seed 8080 (the verdict)

P and R come with 95% Wilson intervals. Count error is detected minus true, per club. Direction
means sign(home − away) agrees with truth, over the whole cut and per 15-minute window.

| Type (true) | Arm | Det | TP | P [Wilson] | R [Wilson] | Error H / A | Direction: whole, windows | Bar |
|---|---|---|---|---|---|---|---|---|
| shot (16) | off | 9 | 3 | 0.33 [0.12, 0.65] | 0.19 [0.07, 0.43] | −6 / −1 | yes, 3/4 | |
| | A | 13 | 6 | 0.46 [0.23, 0.71] | 0.38 [0.18, 0.61] | −3 / 0 | yes, 3/4 | fail (P) |
| | B | 11 | 7 | 0.64 [0.35, 0.85] | 0.44 [0.23, 0.67] | −4 / −1 | yes, 3/4 | fail (P) |
| on target (7) | off | 4 | 3 | 0.75 [0.30, 0.95] | 0.43 [0.16, 0.75] | −3 / 0 | yes, 3/4 | |
| | A | 5 | 4 | 0.80 [0.38, 0.96] | 0.57 [0.25, 0.84] | −2 / 0 | yes, 3/4 | **fail (Wilson lower 0.38 < 0.50)** |
| | B | 5 | 3 | 0.60 [0.23, 0.88] | 0.43 [0.16, 0.75] | −2 / 0 | yes, 1/4 | fail (P, recall) |
| save (2) | off | 1 | 0 | 0.00 | 0.00 | −1 / 0 | yes, 0/2 | |
| | A | 1 | 0 | 0.00 | 0.00 | −1 / 0 | yes, 0/2 | fail |
| | B (keeper catch) | 1 | 1 | 1.00 [0.21, 1.00] | 0.50 [0.09, 0.91] | −1 / 0 | yes, 1/2 | fail (n < 5, Wilson) |
| out of play (4) | off | 16 | 3 | 0.19 [0.07, 0.43] | 0.75 [0.30, 0.95] | +8 / +4 | no, 2/4 | |
| | A | 11 | 3 | 0.27 [0.10, 0.57] | 0.75 [0.30, 0.95] | +3 / +4 | no, 3/4 | fail (P, recall) |

## Seed 8324 (in-sample for the detector's development; reported, never a verdict)

| Type (true) | Arm | Det | TP | P [Wilson] | R [Wilson] | Error H / A | Direction: whole, windows |
|---|---|---|---|---|---|---|---|
| shot (18) | off | 8 | 4 | 0.50 [0.22, 0.78] | 0.22 [0.09, 0.45] | −4 / −6 | yes, 4/6 |
| | A | 14 | 9 | 0.64 [0.39, 0.84] | 0.50 [0.29, 0.71] | −2 / −2 | yes, 5/6 |
| | B | 18 | 9 | 0.50 [0.29, 0.71] | 0.50 [0.29, 0.71] | −3 / +3 | yes, 6/6 |
| on target (7) | off | 4 | 3 | 0.75 [0.30, 0.95] | 0.43 [0.16, 0.75] | 0 / −3 | yes, 2/4 |
| | A | 5 | 3 | 0.60 [0.23, 0.88] | 0.43 [0.16, 0.75] | 0 / −2 | yes, 2/4 |
| | B | 11 | 4 | 0.36 [0.15, 0.65] | 0.57 [0.25, 0.84] | 0 / +4 | yes, 4/4 |
| save (3) | off | 1 | 0 | 0.00 | 0.00 | 0 / −2 | yes, 1/3 |
| | A | 2 | 0 | 0.00 | 0.00 | 0 / −1 | yes, 1/3 |
| | B (keeper catch) | 0 | 0 | none | 0.00 | 0 / −3 | no, 0/3 |
| out of play (9) | off | 31 | 6 | 0.19 [0.09, 0.36] | 0.67 [0.35, 0.88] | +13 / +9 | yes, 4/5 |
| | A | 22 | 6 | 0.27 [0.13, 0.48] | 0.67 [0.35, 0.88] | +11 / +2 | no, 3/5 |

## What it shows

- **Ball height helps but does not cross a bar.** With the flight fit (A), shot recall roughly
  doubles on both seeds (8080: 0.19 to 0.38; 8324: 0.22 to 0.50), and shot precision rises
  (0.33 to 0.46; 0.50 to 0.64). The out-of-play over-count falls (8080 home +8 to +3; 8324 away
  +9 to +2). The fit's checks hold on this footage: 1,020 ball frames on 8080 and 1,484 on 8324
  were placed in flight.
- **The best candidate is A on target on 8080:** 4 of 5 right, recall up from 0.43 to 0.57. Its
  point estimate meets 0.80, but 5 detections leave a Wilson lower bound of 0.38. On 8324 the same
  rule gets 3 of 5 (0.60), so a bigger sample would not obviously have passed it.
- **Out of play is still mostly false.** Precision 0.27 on both seeds. Why the remaining false
  outs survive the height (ground frames, a ball drawn over a player) was not investigated in the
  timebox.
- **Variant B** finds shots by what happens next. On 8080 it is the most precise shot rule
  (0.64), but on 8324 it falls to 0.50, and its on-target rule (keeper touch or scorebug goal)
  over-counts on 8324 (11 detected, 4 right): keepers also gain crosses and back passes.
- **The sets are small.** 8080 shows 7 shots on target, 2 saves and 4 outs of play. At these
  counts the Wilson bar needs about 8 of 8 detections right, so a pass needs more held-out
  footage, not a different rule.

## Reproducing

The scripts are in the session notes, outside the repo, because the grader reads truth and only
`ninety/eval` may (`run.py`, `varb.py`, `grade.py`, and each arm's `*.grade.json`). `run.py`
re-runs `events.detect(saves=True)` + `restarts` per broadcast segment with or without
`flight.heights`. Its off arm reproduces the stored demo `detected.jsonl` counts on 8080 (9
shots, 16 out of play) and the earlier 8324 baseline (shots P 0.50 / R 0.22, out of play
P 0.19 / R 0.67). The flight-on run takes seconds per segment on two CPU workers.
