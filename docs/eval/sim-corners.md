# Corner scenario report

`uv run python -m ninety.sim.corner_report --seeds 200`: seeds 0 to 199, each a wide attack that play turned into a corner, run on 0.75 minutes after it was given (S9). A report, never a gate (docs/GROUNDING.md, R9).

| Measure | Result | Published |
|---|---|---|
| Clips meeting the data contract | 200 / 200 | all |
| Goals within 10 s of the kick | 29 / 200 (14.5%) | about 2% (R9) |
| Attacking shots within 10 s | 78 / 200 | |
| First contact: attackers / defenders (keeper) / nobody | 113 / 86 (29) / 1 | |
| Lofted deliveries | 195 / 200 | |
| Lofted delivery, kick to first bounce or touch below 0.15 m | 2.2 s (10th to 90th percentile 1.9 to 2.5) | |
| Ready (set-piece event) to kick | 1.1 s (10th to 90th percentile 0.8 to 1.5) | |
| Out of play to kick | 12.2 s (10th to 90th percentile 10.8 to 13.8) | |
| Wide attack to the ball going out for the corner | 3.3 s (10th to 90th percentile 1.8 to 9.6) | |
| Wide attacks played per corner (selection, not a rate) | median 5, most 48 | |
| Distinct delivery end points (to 1 m) | 152 / 200 | |

What sent the ball out for the corner (the opening and the selection shape this mix; it is not how corners arise in matches):

| Cause | Corners |
|---|---|
| a home shot, deflected by a defender | 180 |
| a home pass, deflected by a defender | 14 |
| a defender's pass or clearance | 6 |
