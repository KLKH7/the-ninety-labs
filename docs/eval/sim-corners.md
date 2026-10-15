# Corner scenario report

`uv run python -m ninety.sim.corner_report --seeds 300`: seeds 0 to 299, each a wide attack that play turned into a corner, run on 0.75 minutes after it was given (S9). A report, never a gate (docs/GROUNDING.md, R9).

| Measure | Result | Published |
|---|---|---|
| Clips meeting the data contract | 298 / 300 | all |
| Goals within 10 s of the kick | 42 / 300 (14.0%) | about 2% (R9) |
| Attacking shots within 10 s | 106 / 300 | |
| First contact: attackers / defenders (keeper) / nobody | 167 / 132 (42) / 1 | |
| Lofted deliveries | 292 / 300 | |
| Lofted delivery, kick to first bounce or touch below 0.15 m | 2.2 s (10th to 90th percentile 1.9 to 2.5) | |
| Ready (set-piece event) to kick | 1.1 s (10th to 90th percentile 0.8 to 1.4) | |
| Out of play to kick | 12.2 s (10th to 90th percentile 10.6 to 14.0) | |
| Wide attack to the ball going out for the corner | 3.6 s (10th to 90th percentile 1.9 to 11.4) | |
| Wide attacks played per corner (selection, not a rate) | median 7, most 52 | |
| Distinct delivery end points (to 1 m) | 208 / 300 | |

What sent the ball out for the corner (the opening and the selection shape this mix; it is not how corners arise in matches):

| Cause | Corners |
|---|---|
| a home shot, deflected by a defender | 242 |
| a home pass, deflected by a defender | 32 |
| a defender's pass or clearance | 23 |
| a home pass, touched out by a defender | 3 |

Seeds failing the contract: [57, 246]
