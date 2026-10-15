# Corner scenario report

`uv run python -m ninety.sim.corner_report --seeds 300`: seeds 0 to 299, each a wide attack that play turned into a corner, run on 0.75 minutes after it was given (S9). A report, never a gate (docs/GROUNDING.md, R9).

| Measure | Result | Published |
|---|---|---|
| Clips meeting the data contract | 298 / 300 | all |
| Goals within 10 s of the kick | 50 / 300 (16.7%) | about 2% (R9) |
| Attacking shots within 10 s | 91 / 300 | |
| First contact: attackers / defenders (keeper) / nobody | 171 / 127 (47) / 2 | |
| Lofted deliveries | 295 / 300 | |
| Lofted delivery, kick to first bounce or touch below 0.15 m | 2.2 s (10th to 90th percentile 1.9 to 2.5) | |
| Ready (set-piece event) to kick | 1.1 s (10th to 90th percentile 0.8 to 1.5) | |
| Out of play to kick | 12.6 s (10th to 90th percentile 11.0 to 14.7) | |
| Wide attack to the ball going out for the corner | 4.6 s (10th to 90th percentile 2.0 to 12.5) | |
| Wide attacks played per corner (selection, not a rate) | median 6, most 47 | |
| Distinct delivery end points (to 1 m) | 204 / 300 | |

What sent the ball out for the corner (the opening and the selection shape this mix; it is not how corners arise in matches):

| Cause | Corners |
|---|---|
| a home shot, deflected by a defender | 218 |
| a defender's pass or clearance | 66 |
| a home pass, deflected by a defender | 14 |
| a home shot, touched out by a defender | 1 |
| a home pass, touched out by a defender | 1 |

Seeds failing the contract: [26, 246]
