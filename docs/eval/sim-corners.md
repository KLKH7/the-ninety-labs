# Corner scenario report

`uv run python -m ninety.sim.corner_report --seeds 300`: seeds 0 to 299, each a wide attack that play turned into a corner, run on 0.75 minutes after it was given (S9). A report, never a gate (docs/GROUNDING.md, R9).

| Measure | Result | Published |
|---|---|---|
| Clips meeting the data contract | 298 / 300 | all |
| Goals within 10 s of the kick | 29 / 300 (9.7%) | about 2% (R9) |
| Attacking shots within 10 s | 106 / 300 | |
| First contact: attackers / defenders (keeper) / nobody | 127 / 164 (37) / 9 | |
| Lofted deliveries | 296 / 300 | |
| Headers within 10 s (P17): attackers / defenders; attackers' headers at goal | 124 / 159; 76 | |
| Lofted delivery, kick to first bounce or touch below 0.15 m | 3.1 s (10th to 90th percentile 2.0 to 4.1) | |
| Ready (set-piece event) to kick | 1.1 s (10th to 90th percentile 0.8 to 1.4) | |
| Out of play to kick | 12.4 s (10th to 90th percentile 10.8 to 14.2) | |
| Wide attack to the ball going out for the corner | 3.6 s (10th to 90th percentile 1.9 to 9.3) | |
| Wide attacks played per corner (selection, not a rate) | median 8, most 106 | |
| Distinct delivery end points (to 1 m) | 193 / 300 | |

What sent the ball out for the corner (the opening and the selection shape this mix; it is not how corners arise in matches):

| Cause | Corners |
|---|---|
| a home shot, deflected by a defender | 239 |
| a defender's pass or clearance | 49 |
| a home pass, deflected by a defender | 10 |
| a home pass, touched out by a defender | 2 |

Seeds failing the contract: [26, 277]
