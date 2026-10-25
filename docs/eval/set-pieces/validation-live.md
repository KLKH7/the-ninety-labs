# Restart detection on validation (2026-10-25, `b2e73a0d8ebd88aa4827111dbadbe8da9f965cab`)



| Rule | Type | True | Detected | TP | Precision | Recall | F1 |
|---|---|---:|---:|---:|---:|---:|---:|
| strict | kickoff | 1 | 1 | 0 | 0.00 | 0.00 | 0.00 |
| strict | set_piece | 2 | 1 | 0 | 0.00 | 0.00 | 0.00 |
| lenient | kickoff | 1 | 1 | 0 | 0.00 | 0.00 | 0.00 |
| lenient | set_piece | 2 | 1 | 0 | 0.00 | 0.00 | 0.00 |
| time_only | kickoff | 1 | 1 | 0 | 0.00 | 0.00 | 0.00 |
| time_only | set_piece | 2 | 1 | 0 | 0.00 | 0.00 | 0.00 |

## By kind (strict, with the kind right)

| Kind | True | Right | Time-matched | Kind right of those | No camera |
|---|---:|---:|---:|---:|---:|
| throw_in | 1 | 0 | 0 | 0 | 1 |
| free_kick | 1 | 0 | 0 | 0 | 0 |
| kick_off | 1 | 0 | 0 | 0 | 0 |

## Confusion (true kind by row; matched in time and team)

| True \ found | throw_in | goal_kick | corner | free_kick | penalty_kick | kick_off | missed |
|---|---:|---:|---:|---:|---:|---:|---:|
| throw_in | 0 | 0 | 0 | 0 | 0 | 0 | 1 |
| free_kick | 0 | 0 | 0 | 0 | 0 | 0 | 1 |
| kick_off | 0 | 0 | 0 | 0 | 0 | 0 | 1 |

## Every true restart

| Restart | Kind | Camera | Strict | Found kind | Nearest same-team detection (s) | Nearest of either side (s, side, kind, m) |
|---|---|---|---|---|---:|---|
| seed920101-421/e00011 | throw_in | no camera | no | - | None | - |
| seed920108-1061/e00027 | free_kick | ok | no | - | 1.68 | 1.68, home, free_kick, 0.05 |
| seed920108-1061/e00033 | kick_off | ok | no | - | 2.92 | 2.92, home, kick_off, 0.53 |

False restarts: 2 (1.0 a clip)

- seed920108-1061/r00001: set_piece home free_kick at (15.09, 10.57)
- seed920108-1061/r00002: kickoff home kick_off at (52.01, 33.8)
