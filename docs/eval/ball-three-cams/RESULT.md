# The ball from the broadcast: result

Scored once, on the 30 test clips 900001-900030 of run `tactical1` (renderer 0.5.15, software GL,
every frame), at the frozen commit `81e8865a` ([PLAN.md](PLAN.md), its dated deviations): detection
ours-freeze on the whole broadcast frame and the broadcast's camera fit (#250) made at `e9dcee44`
(byte-identical code), judged with the broadcast band (0.966, 1.121) and gate B3, scored by
`ninety.eval.ball_sources`. Nothing of the test clips was read before. Numbers: `test.json`;
validation: `validation.json`. Wilson 95% in brackets; frames of one clip are not independent, so
the intervals are narrower than the truth.

| Group | Frames | Strict recall (1.0 m) | Strict precision | Lenient recall (2.0 m) | Coverage |
|---|---|---|---|---|---|
| all | 7,221 | **0.763** [0.75, 0.77] | **0.907** [0.90, 0.91] | 0.777 | 0.811 |
| on the ground | 6,921 | 0.796 | 0.973 | 0.810 | 0.818 |
| in the air (above 0.5 m) | 300 | 0.000 | 0.000 | 0.003 | 0.650 |
| near (y < 22.7 m) | 2,376 | 0.779 | 0.943 | 0.791 | 0.826 |
| centre | 2,893 | 0.817 | 0.942 | 0.828 | 0.867 |
| far (y >= 45.3 m) | 1,952 | 0.663 | 0.932 | 0.682 | 0.711 |

Validation, the same code (tactical1's 23 validation clips, GPU-rendered): strict recall 0.590,
precision 0.799, coverage 0.724. Test is higher: its clips are software-rendered (validation's GPU
grain is what #250 had to fix) and are scored once, as they fell.

What it says: a ball on the ground placed by the broadcast is within 1 m of where it is on 80% of
the frames where it is on the pitch, and 97% of the balls it places are right. **A ball in the air
is never placed within 1 m:** every camera places the ball on the ground, so a lofted ball lands
along the line of sight (planned: its height from its flight, PR #226). Coverage is lost far from
the camera and where the broadcast frame does not hold the ball.
