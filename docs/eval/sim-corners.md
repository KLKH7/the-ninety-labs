# Corner scenario report

`uv run python -m ninety.sim.corner_report --seeds 300`: seeds 0 to 299, each an attack from a moment open play reached (the home side on the ball in its final third) that play turned into a corner, run on 0.75 minutes after it was given (S9). A report, never a gate (docs/GROUNDING.md, R9).

| Measure | Result | Published |
|---|---|---|
| Clips meeting the data contract | 300 / 300 | all |
| Goals within 10 s of the kick | 35 / 300 (11.7%) | about 2% (R9) |
| Attacking shots within 10 s | 130 / 300 | |
| First contact: attackers / defenders (keeper) / nobody | 161 / 133 (30) / 6 | |
| Lofted deliveries | 293 / 300 | |
| Headers within 10 s (P17): attackers / defenders; attackers' headers at goal | 135 / 136; 87 | |
| Lofted delivery, kick to first bounce or touch below 0.15 m | 3.0 s (10th to 90th percentile 1.9 to 4.0) | |
| Ready (set-piece event) to kick | 1.2 s (10th to 90th percentile 0.8 to 1.5) | |
| Out of play to kick | 13.9 s (10th to 90th percentile 11.4 to 16.9) | |
| Opening to the ball going out for the corner | 6.0 s (10th to 90th percentile 2.0 to 13.9) | |
| Attacks played per corner (selection, not a rate) | median 18, most 142 | |
| Distinct delivery end points (to 1 m) | 190 / 300 | |

What sent the ball out for the corner (the opening and the selection shape this mix; it is not how corners arise in matches):

| Cause | Corners |
|---|---|
| a home shot, deflected by a defender | 176 |
| a defender's pass or clearance, kicked, unpressed | 45 |
| a defender's pass or clearance, kicked, pressed | 43 |
| a home pass, deflected by a defender | 24 |
| a defender's pass or clearance, headed, pressed | 6 |
| a defender's pass or clearance, headed, unpressed | 5 |
| a home pass, touched out by a defender | 1 |
