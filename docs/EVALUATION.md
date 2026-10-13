# Evaluation

How every number in the README is produced. A number is published only when the command below
generated it and the output file is committed. Rows marked *planned* have no result yet.

| Measure | Command | Output | Status |
|---|---|---|---|
| Simulator realism (passes, shots, tackles, pass completion per match) | `uv run pytest tests/test_sim.py` | test assertions | running |
| Event and frame schema validity | CI `smoke` job | CI log | running |
| Render checks (projection error, determinism, ball occlusion share) | planned | `docs/eval/render-checks.json` | planned |
| Detection recall (players, ball) on the fixed test set | planned | `docs/eval/vision-report-v{n}.json` | planned |
| Event precision, recall and F1 per type; possession accuracy; speed error | planned | `docs/eval/vision-report-v{n}.json` | planned |
| Targeted data rounds, before and after | planned | `docs/eval/vision-report-v{n}.json` | planned |
| Fact-checker catch rate on planted false claims | planned | `docs/eval/fact-checker.md` | planned |
| Recovery from injected failures | planned | `docs/eval/failure-table.md` | planned |
| Ablation: one agent against the full workflow | planned | `docs/eval/ablation.md` | planned |
| Latency to graphic and to speech (p50, p95); cost per match | planned | `docs/eval/latency-cost.md` | planned |

## Rules

- **The test set is fixed and separate.** Clips used to score detection are never used to train it,
  and targeted data rounds never add clips to the test set.
- **Every report records its inputs:** git commit, seeds, model versions and the date.
- **Results are reproducible:** each command runs from a clean clone after `uv sync`.
