# Corner scenario report

`uv run python -m ninety.sim.corner_report --seeds 200`: seeds 0 to 199, each a wide attack that play turned into a corner, run on 0.75 minutes after it was given (S9). A report, never a gate (docs/GROUNDING.md, R9).

| Measure | Result | Published |
|---|---|---|
| Clips meeting the data contract | 200 / 200 | all |
| Goals within 10 s of the kick | 11 / 200 (5.5%) | about 2% (R9) |
| Attacking shots within 10 s | 29 / 200 | |
| First contact: attackers / defenders (keeper) / nobody | 101 / 98 (29) / 1 | |
| Lofted deliveries | 195 / 200 | |
| Lofted delivery, kick to first bounce or touch below 0.15 m | 2.2 s (10th to 90th percentile 1.8 to 2.5) | |
| Ready (set-piece event) to kick | 1.1 s (10th to 90th percentile 0.8 to 1.4) | |
| Out of play to kick | 12.3 s (10th to 90th percentile 11.0 to 13.8) | |
| Wide attack to the ball going out for the corner | 5.2 s (10th to 90th percentile 2.3 to 14.1) | |
| Wide attacks played per corner (selection, not a rate) | median 11, most 73 | |
| Distinct delivery end points (to 1 m) | 156 / 200 | |
