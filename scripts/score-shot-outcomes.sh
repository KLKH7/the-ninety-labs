#!/bin/bash
# Score goals and saves once, headless, where the shot-outcome set's clips are (docs/eval/shot-outcome-set.md).
#   bash scripts/score-shot-outcomes.sh <split dir of rendered clips> <checkpoint folder> <out dir>
# Each clip runs the live path as the demo does (stage_live: index and images only; live_job: detect,
# observe, events, outcomes), and only then is the answer key read, by ninety.eval.shot_outcomes.
# Run it at the frozen commit; it writes <out>/report.json and each clip's detected.jsonl.
set -euo pipefail
SPLIT=$1; CKPT=$2; OUT=$3
mkdir -p "$OUT/work" "$OUT/detected"
NAME=$(python -c "import json,sys; print(json.load(open(sys.argv[1]))['name'])" "$CKPT/train-manifest.json")
for clip in "$SPLIT"/*/; do
  c=$(basename "$clip")
  [ -s "$OUT/detected/detected-$c.jsonl" ] && continue
  uv run python -m ninety.vision.stage_live "$clip" --from 0 --to 1000000 --checkpoint "$CKPT" --out "$OUT/work/$c"
  uv run --group vision python -m ninety.vision.live_job "$OUT/work/$c/clip" --checkpoint "$NAME" \
    --weights "$OUT/work/$c/checkpoint/checkpoint_best_total.pth" --out "$OUT/live/$c"
  cp "$OUT/live/$c/detected.jsonl" "$OUT/detected/detected-$c.jsonl"
  rm -rf "$OUT/work/$c/clip/images"
done
uv run python -m ninety.eval.shot_outcomes score --clips "$SPLIT"/*/ --detected "$OUT/detected" --out "$OUT/report.json"
