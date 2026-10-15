# Corner scenario report

`uv run python -m ninety.sim.corner_report --seeds 200`: seeds 0 to 199, 0.75 minutes each. A report, never a gate (docs/GROUNDING.md, R9).

| Measure | Result | Published |
|---|---|---|
| Clips meeting the data contract | 200 / 200 | all |
| Goals within 10 s of the kick | 14 / 200 (7.0%) | about 2% (R9) |
| Attacking shots within 10 s | 31 / 200 | |
| First contact: attackers / defenders (keeper) / nobody | 96 / 104 (29) / 0 | |
| Lofted deliveries | 197 / 200 | |
| Lofted delivery, kick to first bounce or touch below 0.15 m | 2.1 s (10th to 90th percentile 1.9 to 2.4) | |
| Ready (set-piece event) to kick | 1.1 s (10th to 90th percentile 0.8 to 1.4) | |
| Out of play to kick | 12.2 s (10th to 90th percentile 11.4 to 13.2) | |
| Distinct delivery end points (to 1 m) | 154 / 200 | |
