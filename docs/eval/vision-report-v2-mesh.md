# Vision report v2-mesh: ours-v3 on the mesh test set, beside the capsule test set

This scores the same checkpoint (ours-v3, sha256 `3b2d5cf4…`, [vision-report-v2](vision-report-v2.md))
with the same scorer, threshold (0.5) and detection settings, on a **new frozen test set**. It is
the "before" of targeted round 1 ([round1/PLAN.md](round1/PLAN.md)), so the benchmark change is
on record before any v4 number exists.

**What changed between the two test sets: the picture and the engine, not the seeds.** The seeds
are the same five (900001 to 900005), each drawn with its own parameters.

| | Capsule test set | Mesh test set |
|---|---|---|
| Freeze file | [test-set-frozen.json](test-set-frozen.json) | [test-set-frozen-91d1e3b.json](test-set-frozen-91d1e3b.json) |
| Commit | `cca498c` (engine-v1 plus #118) | `91d1e3b` (main with #136 and #146) |
| Renderer | 0.3.2: capsule players | 0.4.0: skinned kit mesh, #146's turns and touches |
| Engine | engine-v1 | main: adds #58 (kick error) and #90 (foot reach) |
| Ball in shot under half visible | 15.0% (188 of 1,250; 75 mostly hidden, 113 fully) | 6.6% (83 of 1,250; 82 mostly hidden, 1 fully) |

Because the engine also changed, a match on the same seed plays out differently, so the windows
differ. The two test sets are two benchmarks, not one benchmark drawn twice. The capsule set stays
frozen and reported, so v1 and v2 keep their meaning.

## ours-v3 on both

Precision / recall (labels):

| | Capsule (vision-report-v2) | Mesh (this report) |
|---|---|---|
| Players | 0.999 / 0.994 (9,610) | 0.992 / 0.993 (11,759) |
| Ball, all labels | 0.987 / 0.933 (1,137) | 0.978 / 0.909 (1,249) |
| Ball, at least half visible | 0.994 / 0.964 (1,062) | 0.985 / 0.937 (1,167) |
| Ball, partly hidden | 0.968 / 0.916 (167) | 0.940 / **0.763** (186) |
| **Ball, mostly hidden** | 0.841 / 0.493 (75) | 0.837 / **0.500** (82) |
| Players, mostly hidden | 0.985 / 0.893 (75) | 0.929 / 0.812 (32) |
| False positives, all | 27 | **125** |

On the mesh:
- **Partly hidden balls lose the most:** 0.916 to 0.763.
- **False positives rise from 27 to 125.**
- **Mostly hidden balls stay near 0.50.** This is the weakness round 1 targets, and it is unchanged
  by the look.

ours-v3 never saw a mesh player, so this is its baseline on the look the demo shows.

**Small counts.** Mostly hidden players are 32 labels on the mesh set; one standard error of the
recall is about 0.07 there, and 0.055 for mostly hidden balls (82 labels). Differences under twice
that are not measured.

## How to rebuild

The detections are committed in [vision-report-v2-mesh/detections](vision-report-v2-mesh/detections)
(ours-v3, every frame, run locally). The report rebuilds without the checkpoint:

    uv run python -m ninety.eval.vision_report --test runs/test-frozen-91d1e3b/test \
        --detections docs/eval/vision-report-v2-mesh/detections \
        --freeze docs/eval/test-set-frozen-91d1e3b.json --out docs/eval/vision-report-v2-mesh.json

The builder refuses any clip whose labels, events or images differ from the freeze file.
