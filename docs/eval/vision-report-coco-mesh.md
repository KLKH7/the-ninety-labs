# Vision report: the off-the-shelf COCO baseline on the mesh test set

This answers how much our training adds over a detector nobody trained on our footage. It uses the
stock COCO-pretrained RF-DETR Small, unchanged: the same pinned size and rfdetr version (1.11.2)
as our checkpoints, run at 640, the resolution our models train and run at.

It is scored on the frozen mesh test set ([test-set-frozen-91d1e3b.json](test-set-frozen-91d1e3b.json)),
every frame, with the same scorer and threshold (0.5) as v3, v4-ctrl and v4
([round1/RESULT.md](round1/RESULT.md)).

## Class mapping, fixed before scoring

The mapping is in `ninety/vision/detect.py` (`COCO_TO_OURS`) and was not changed for this run:
- COCO category 1, *person* → `player`;
- COCO category 37, *sports ball* → `ball`;
- every other COCO class is dropped.

Referees do not appear in our footage, so *person* means players only.

## Results

Precision / recall:

| | Labels | COCO (stock) | ours-v3 | ours-v4-ctrl | ours-v4 |
|---|---|---|---|---|---|
| Players | 11,759 | 0.986 / 0.940 | 0.992 / 0.993 | 0.997 / 0.994 | 0.998 / 0.995 |
| Ball, all labels | 1,249 | 0.879 / **0.175** | 0.978 / 0.909 | 0.991 / 0.932 | 0.991 / 0.931 |
| Ball, at least half visible | 1,167 | 0.883 / 0.187 | 0.985 / 0.937 | 0.994 / 0.956 | 0.993 / 0.956 |
| Ball, partly hidden | 186 | 0.000 / **0.000** | 0.940 / 0.763 | 0.962 / 0.817 | 0.962 / 0.817 |
| Ball, mostly hidden | 82 | 0.000 / **0.000** | 0.837 / 0.500 | 0.923 / 0.585 | 0.940 / 0.573 |
| Players, mostly hidden | 32 | 0.800 / 0.375 | 0.929 / 0.812 | 1.000 / 0.969 | 1.000 / 0.938 |
| False positives, all | | 187 | 125 | 41 | 35 |

What it says:
- **The stock detector finds players** (0.940 recall), as COCO's *person* class would suggest.
- **It barely finds the ball.** Our ball is about 9 px at 640, far smaller than most COCO sports
  balls. The stock model finds 18.7% of balls that are at least half visible and none that are
  partly or mostly hidden.
- **Its 187 false positives** are the most of any model here.
- **Fine-tuning on our synthetic renders** takes ball recall from 0.175 to 0.909 (ours-v3), and to
  about 0.93 with round 1's data. That is the gain synthetic data with exact ground truth buys.

## How to rebuild

The detections are committed in [vision-report-coco-mesh/detections](vision-report-coco-mesh/detections)
(`--checkpoint coco`, every frame, on the Mac). The report rebuilds byte-identical:

    uv run python -m ninety.eval.vision_report --test runs/test-frozen-91d1e3b/test \
        --detections docs/eval/vision-report-coco-mesh/detections \
        --freeze docs/eval/test-set-frozen-91d1e3b.json --out docs/eval/vision-report-coco-mesh.json
