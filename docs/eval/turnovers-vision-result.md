# Interceptions, pressure and tackles on real vision: the result

Plan, each part committed and pushed before the read it governs:
[turnovers-vision-plan.md](turnovers-vision-plan.md) (read 1: d39da586; amendment B1: 17a30cbc, its
code 8aad0754). The first numbers for these rules on the detector's **real output** (until now every
one was on stand-in observations): the shot-outcome set's 80 validation windows (seeds 910001 to
910008, 10 s each, broadcast), strict (same type and team, within 1.0 s and 1.0 m). No test clip was
read. [turnovers-vision.json](turnovers-vision.json).

| Read | Kind | True | Detected | Found (recall, 95%) | Right (precision, 95%) | Bar (0.5 and 0.5) |
|---|---|---:|---:|---|---|---|
| 1, #342 as built (abae7c17) | pressure | 66 | 46 | 19 (0.29, 0.19 to 0.41) | 19 (0.41, 0.28 to 0.56) | missed |
| | tackle | 8 | 3 | 0 (0.0) | 0 (0.0) | too few to decide |
| | interception | 8 | 27 | 1 (0.13) | 1 (0.04) | too few to decide |
| 2, amendment B1 (8aad0754) | pressure | 66 | 46 | 19 (0.29, 0.19 to 0.41) | 19 (0.41, 0.28 to 0.56) | missed |
| | tackle | 8 | 3 | 1 (0.13) | 1 (0.33) | too few to decide |
| | interception | 8 | 25 | 0 (0.0) | 0 (0.0) | too few to decide |

**Decision, as pre-registered: pressure leaves `events.WRITTEN`** (it was written on a stand-in number
only); **amendment B1 is not adopted** (pressure did not meet the bar) and its code is not in this
branch's live path; tackles and interceptions stay off. `WRITTEN` is empty, so the live path writes
what main writes, and the M1 fixture is main's again.

## Why they miss (read 1)

**Pressure**, 47 missed: 23 the side read wrong; 15 tracked, but the holder and the nearest opponent
read at 2 m or more (the players' position error, p90 1.26 m, against the engine's 2.0 m line); 4 no
spell (the ball not seen at a holder's feet); 3 kept back by an earlier false detection of the side
within 8 s (the engine's once-in-8-s memory); 1 outside 1 s; 1 outside 1 m; none for a presser or
carrier not tracked. 27 false: 8 the side wrong; 4 and 2 a true pressure outside 1 s and 1 m; 5 no
true carrier then (a loose ball near two players); 5 the true nearest opponent at 2 m or more; 3 the
engine's 8 s memory (a true one shortly before, or the window's first 8 s, which the engine's memory
covers and the clip cannot see).

**The side** is the largest cause. Tracks matched to the truth's players by place (within `RIVAL_M`,
grading only): in 24 of the 80 windows both kits are named the wrong way round (more than 70% of
their tracked frames on the other side), 36 right, 20 mixed; frame-weighted side accuracy 0.56.
`assign_teams` separates the two kits, then names them by depth (the deeper kit defends x = 0); in a
10 s window around one penalty area, attackers stand as deep as defenders.

**Amendment B1** named the kits by the goal their strikes head for. It renamed 20 windows; 53 had no
strike that headed for a goal, 7 kept their naming by the votes. Side accuracy rose from 0.56 to 0.615
(right 36 to 40, wrong way round 24 to 20): it renamed about as many windows wrongly as rightly
(a pass that heads for a goal, a clearance toward one's own). Pressure did not move.

**Interceptions**, 26 false: 9 by a true shot (the keeper or a blocker taking a shot is a possession
change, not an interception of a pass), 6 by a true pass (its receiver or side misread), 4 a true
possession change by that side (a recovery the engine does not call an interception), 3 a true
deflection, 4 nothing true within 1 s. **Tackles**: 3 detected (2 by a true tackle, outside the side
or the 1 m), 8 missed, 7 with only a pass or possession change detected near them.

## What would fix them (not done here)

- **The side** is upstream of every event on the broadcast, passes and possession changes included:
  better naming needs evidence the broadcast holds over more than 10 s (the kick-off, or the whole
  match's kit-to-goal record), a change to `assign_teams` with its own plan and its own split.
- **The 2.0 m line** against a 1.26 m position error loses a quarter of true pressures. The line is the
  engine's definition; widening it would be fitting a threshold, so it is not done.
- Tackles and interceptions need a set with at least 20 of each (these windows were chosen around
  shots).
