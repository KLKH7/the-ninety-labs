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

## Read 1, done (before the amendment below was written)

At #342's head (abae7c17), strict, the 80 validation windows: pressure 19 of 66 found (0.29), 19 of
46 right (0.41): **under the bar, so pressure leaves `WRITTEN`**. Tackles 0 of 8 (3 detected),
interceptions 1 of 8 (27 detected): too few to decide, off. Causes, in the order above: of 47 missed
pressures, 4 no spell, 0 not tracked, **23 side read wrong**, 1 outside 1 s, 1 outside 1 m, 3 kept
back by an earlier (false) detection of the side within 8 s, 15 tracked but read at 2 m or more (the
position error against the engine's 2.0 m line). Of 27 false: **8 side wrong**, 4 and 2 a true one
outside 1 s and 1 m, 3 the engine's 8 s memory, 5 no true carrier (a loose ball), 5 the true
nearest opponent at 2 m or more. Why the side is wrong: tracks matched to the truth's players by
place (within `RIVAL_M`, grading only), **24 of the 80 windows have both kits named the wrong way
round** (more than 70% of their tracked frames on the other side), 36 right, 20 mixed; frame-weighted
side accuracy 0.56. `assign_teams` separates the kits, then names them by depth (the deeper kit
defends x = 0); in a 10 s window in one penalty area, attackers stand as deep as defenders.

## Amendment B1: the kits named by the goal their strikes head for (before read 2)

The cause is the naming, not the kits. After `assign_teams`, on the broadcast (not the tactical
views, whose sides `sides.assign` sets), each spell end of an outfield track with a side whose ball
heads for a goal (`heads_for_goal`, tested toward both goals, the shot rule as it stands: between the
widened posts, from within 35 m) is a vote: its kit attacks that goal. When the votes that disagree
with `assign_teams`' naming outnumber those that agree, every outfield track's side is swapped (home
attacks x = 105, the engine's convention); keepers keep the half they stand in. A tie, or no vote,
leaves the naming as it is. No threshold: a strict majority of votes, and the shot rule's own test.

Read 2, once, on the same 80 windows, the same scorer: pressure, tackles, interceptions, and the side
accuracy (frame-weighted, as above). A development number (the windows were read for the breakdown).
Adopted only if: pressure meets 0.5 and 0.5 strict **and** side accuracy does not fall. Then, and only
then, pressure returns to `WRITTEN` with the naming; a naming that changes every broadcast event's
side also needs passes and possession changes re-scored before it reaches main, reported with it.
Tackles and interceptions stay off (8 true events each).
