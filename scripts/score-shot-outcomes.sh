#!/bin/bash
# Score goals and saves once, headless, where the shot-outcome set's clips are (docs/eval/shot-outcome-set.md).
#   JOBS=8 bash scripts/score-shot-outcomes.sh <split dir of rendered clips> <checkpoint folder> <out dir>
#   NO_SCORE=1 ... (the same, without reading the answer key)
# Each clip runs the live path as the demo does (stage_live: index and images only; live_job: detect,
# observe, events, outcomes), JOBS clips at a time (default 1), each in its own process; only then is
# the answer key read, once, by ninety.eval.shot_outcomes. Run it at the frozen commit; it writes
# <out>/report.json, each clip's detected.jsonl and its observations (broadcast) under <out>/observations, so
# a rule changed later can be re-scored from them without the clips. A clip already done is skipped,
# so a rerun resumes.
set -euo pipefail
SPLIT=$1; CKPT=$2; OUT=$3; JOBS=${JOBS:-1}
mkdir -p "$OUT/work" "$OUT/detected" "$OUT/logs" "$OUT/observations"
NAME=$(uv run python -c "import json,sys; print(json.load(open(sys.argv[1]))['name'])" "$CKPT/train-manifest.json")
one() {  # one clip: $1 = its folder
  local c; c=$(basename "$1")
  [ -s "$OUT/detected/detected-$c.jsonl" ] && return 0
  {
    uv run python -m ninety.vision.stage_live "$1" --from 0 --to 1000000 --checkpoint "$CKPT" --out "$OUT/work/$c"
    OMP_NUM_THREADS=${THREADS:-2} uv run --group vision python -m ninety.vision.live_job "$OUT/work/$c/clip" \
      --checkpoint "$NAME" --weights "$OUT/work/$c/checkpoint/checkpoint_best_total.pth" --out "$OUT/live/$c"
    cp "$OUT/live/$c/observations.jsonl" "$OUT/observations/observations-$c.jsonl"
    cp "$OUT/live/$c/detected.jsonl" "$OUT/detected/detected-$c.jsonl"
    rm -rf "$OUT/work/$c/clip/images"
  } > "$OUT/logs/$c.log" 2>&1 || echo "FAILED $c (see $OUT/logs/$c.log)"
}
export -f one; export OUT CKPT NAME
ls -d "$SPLIT"/*/ | xargs -P "$JOBS" -I{} bash -c 'one "$@"' _ {}
# The live path does not write saves (events.SAVES_AIR, lesson 258), so before scoring, each clip's
# events are re-run from its kept observations with the save rule on (--keep-saves); detected/ holds
# those, the measured ones, and live/<clip>/detected.jsonl keeps what the live path wrote.
# NO_SCORE=1 runs the live path only and never reads the answer key (the test split before its freeze:
# it is scored once, later, from <out>/observations at the frozen commit).
for f in "$OUT"/observations/observations-*.jsonl; do
  [ -e "$f" ] || continue
  c=$(basename "$f" .jsonl); c=${c#observations-}
  uv run python -m ninety.vision.events "$f" --keep-saves --out "$OUT/detected/detected-$c.jsonl" >/dev/null
done
[ -n "${NO_SCORE:-}" ] || uv run python -m ninety.eval.shot_outcomes score --clips "$SPLIT"/*/ --detected "$OUT/detected" --out "$OUT/report.json"
