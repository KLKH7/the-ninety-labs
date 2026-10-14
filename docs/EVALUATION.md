# Evaluation

How every number in the README is produced. A number is published only when the command below
generated it and the output file is committed. Rows marked *planned* have no result yet.

| Measure | Command | Output | Status |
|---|---|---|---|
| Simulator realism: 16 per-match rates against published Premier League averages, ball in play, distance, top speed, no teleports | `uv run python -m ninety.sim.realism` (10 seeds); `uv run pytest tests/test_sim.py` checks the same bands on 3 seeds | `docs/eval/sim-realism.md` | running |
| Event and frame schema validity | CI `smoke` job | CI log | running |
| Render checks (projection error, determinism, ball occlusion share) | planned | `docs/eval/render-checks.json` | planned |
| Detection recall (players, ball) on the fixed test set | planned | `docs/eval/vision-report-v{n}.json` | planned |
| Event precision, recall and F1 per type; possession accuracy; speed error | planned | `docs/eval/vision-report-v{n}.json` | planned |
| Targeted data rounds, before and after | planned | `docs/eval/vision-report-v{n}.json` | planned |
| Fact-checker rules (numbers, players, evidence ids) | `uv run pytest tests/test_factcheck.py` | test assertions | running |
| Fact-checker catch rate on planted false claims, and true claims wrongly rejected | `uv run python -m ninety.eval.factcheck_eval` | `docs/eval/fact-checker.md` | running: 64/64 caught, 0/48 wrongly rejected |
| Recovery from injected failures | planned | `docs/eval/failure-table.md` | planned |
| Ablation: one agent against the full workflow | planned | `docs/eval/ablation.md` | planned |
| Latency to graphic and to speech (p50, p95); cost per match | planned | `docs/eval/latency-cost.md` | planned |

## Real-world calibration

The simulator's rates are tuned to published per-match averages, which are cited per row in
`docs/eval/sim-realism.md`. Only those averages are used: no real match, event or tracking data is
read or committed. A row whose average is not yet cited is marked `to cite`; its band is a working
assumption, not a claim.

## Rules

- **The test set is fixed and separate.** Clips used to score detection are never used to train it,
  and targeted data rounds never add clips to the test set.
- **Every report records its inputs:** git commit, seeds, model versions and the date.
- **Results are reproducible:** each command runs from a clean clone after `uv sync`.
