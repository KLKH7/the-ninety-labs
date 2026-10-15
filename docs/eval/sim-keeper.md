# Keeper report

`uv run python -m ninety.sim.keeper_report --shots 200`: 200 isolated shots per distance, seeds 1000 on. Save rate of shots on target (saved or scored). A report, never a gate (docs/GROUNDING.md, P15).

| Distance | Keeper standing | Keeper moving 2.5 m/s along his line |
|---|---|---|
| 8 m | 5% (10 of 200) | 12% (24 of 200) |
| 11 m | 28% (55 of 200) | 29% (58 of 200) |
| 16 m | 55% (110 of 200) | 48% (95 of 200) |
| 20 m | 78% (157 of 200) | 76% (152 of 200) |
| 25 m | 100% (200 of 200) | 93% (186 of 200) |
