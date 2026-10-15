# Corner scenario report

`uv run python -m ninety.sim.corner_report --seeds 300`: seeds 0 to 299, each a wide attack that play turned into a corner, run on 0.75 minutes after it was given (S9). A report, never a gate (docs/GROUNDING.md, R9).

| Measure | Result | Published |
|---|---|---|
| Clips meeting the data contract | 92 / 300 | all |
| Goals within 10 s of the kick | 36 / 300 (12.0%) | about 2% (R9) |
| Attacking shots within 10 s | 106 / 300 | |
| First contact: attackers / defenders (keeper) / nobody | 173 / 124 (45) / 3 | |
| Lofted deliveries | 296 / 300 | |
| Lofted delivery, kick to first bounce or touch below 0.15 m | 2.2 s (10th to 90th percentile 1.9 to 2.5) | |
| Ready (set-piece event) to kick | 1.1 s (10th to 90th percentile 0.8 to 1.5) | |
| Out of play to kick | 12.2 s (10th to 90th percentile 10.9 to 14.0) | |
| Wide attack to the ball going out for the corner | 3.5 s (10th to 90th percentile 1.8 to 10.7) | |
| Wide attacks played per corner (selection, not a rate) | median 7, most 52 | |
| Distinct delivery end points (to 1 m) | 208 / 300 | |

What sent the ball out for the corner (the opening and the selection shape this mix; it is not how corners arise in matches):

| Cause | Corners |
|---|---|
| a home shot, deflected by a defender | 249 |
| a home pass, deflected by a defender | 32 |
| a defender's pass or clearance | 18 |
| a home pass, touched out by a defender | 1 |

Seeds failing the contract: [0, 4, 5, 6, 7, 8, 9, 12, 14, 15, 17, 18, 19, 21, 23, 24, 25, 26, 27, 28, 31, 32, 35, 36, 37, 38, 39, 40, 43, 47, 48, 52, 53, 54, 56, 57, 58, 59, 60, 61, 62, 64, 65, 66, 67, 68, 69, 71, 72, 73, 74, 76, 77, 80, 81, 82, 83, 85, 86, 87, 88, 89, 92, 93, 94, 96, 99, 100, 102, 103, 104, 105, 106, 107, 108, 110, 112, 113, 114, 115, 116, 118, 119, 120, 121, 123, 124, 125, 126, 128, 129, 130, 131, 132, 133, 134, 135, 136, 137, 138, 140, 142, 144, 145, 146, 148, 149, 151, 152, 157, 158, 161, 162, 163, 164, 166, 167, 169, 170, 171, 173, 174, 176, 177, 179, 180, 181, 182, 184, 188, 190, 191, 194, 195, 197, 198, 199, 201, 202, 203, 204, 206, 207, 208, 209, 212, 213, 216, 217, 218, 219, 221, 222, 223, 224, 226, 228, 230, 231, 232, 233, 235, 239, 240, 241, 242, 243, 244, 245, 246, 247, 248, 249, 251, 252, 254, 255, 256, 257, 258, 259, 261, 262, 263, 265, 266, 267, 270, 271, 272, 273, 276, 277, 278, 279, 280, 281, 283, 285, 287, 288, 289, 290, 293, 294, 295, 297, 298]
