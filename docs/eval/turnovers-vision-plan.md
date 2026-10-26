# Interceptions, pressure and tackles on real vision (plan, before any number)

Committed before any of these rules is run on a rendered clip's real detector output. The rules are
#342's, unchanged ([pressure-plan.md](pressure-plan.md), [tackle-plan.md](tackle-plan.md),
[interception-plan.md](interception-plan.md)); until now every number for them was on stand-in
observations. Result: [turnovers-vision-result.md](turnovers-vision-result.md).

## Read 1: the rules as built, on real vision

- **Clips:** the shot-outcome set's 80 validation windows (seeds 910001 to 910008, 10 s each,
  [shot-outcome-set.md](shot-outcome-set.md)), from the observations the pod kept of the live path's
  real detector (`runs/onepod-1025b/out/score-val2/observations`, broadcast camera). No test clip
  (910009 to 910016, 900001 to 900030) is read.
- **Code:** #342's head (abae7c17), `events.detect(rows, kinds=TURNOVERS)`.
- **Scorer:** `ninety.eval.event_score.match`, strict (same type and team, within 1.0 s, spot within
  1.0 m: a pressure's spot against the nearest true player of its side, `PLAYER_PLACED`), per kind,
  pooled over the 80 windows, with Wilson 95% intervals. The truth's event counts are what the
  windows hold (66 pressures, 8 tackles, 8 interceptions, counted before this file without any
  detection).
- **Bar, as the plans have it:** strict recall and precision both at least 0.5.
- **Decision:** pressure has 66 true events, enough to decide: if it misses the bar on real vision it
  leaves `events.WRITTEN` (it is written today on a stand-in number only); if it meets it, it stays.
  Tackles and interceptions have 8 each: fewer than 20 true events decides nothing (a 95% interval on
  8 spans about 0.5 either way), so they stay off whatever Read 1 gives, and are reported.

## Then: why they miss

Each missed true event and each false detection is put in one cause, in this order, from the
observations and the truth (grading only): (1) the ball not seen at a holder's feet then (no spell),
(2) the presser or tackler not tracked in that frame (off screen or not detected), (3) the side read
wrong (matched with the team flipped), (4) found but outside 1.0 s, (5) found but outside 1.0 m,
(6) the clip's first 8 s memory (pressure only: the engine's memory ran before the window),
(7) other.

Any change to a rule that follows is written here as an amendment, with its reason and no new fitted
threshold, committed before it is run; it is then scored once on the same 80 windows. That is a
development number (the windows were read for the breakdown), said so wherever it is quoted; a kind
is adopted into `WRITTEN` only if it meets the bar there and has at least 20 true events.
