# Rendering the set-piece and possession sets

How the clips of [set-piece-set.md](set-piece-set.md) and [possession-set.md](possession-set.md) are
rendered, validated and frozen. Both sets are chosen already (`docs/eval/set-piece-set.json`,
`docs/eval/possession-set.json`); rendering changes nothing in them. Every clip is rendered at the
render commit `65247ba36343c640fe7673c772a1cbc0ac19c07e` and nowhere else: each command line checks
`git rev-parse HEAD` first and stops if it differs.

## Cost

Measured on the maintainer's laptop (8 cores, shared with two other sessions, load 55 to 85): a
4 s clip took 12 minutes and a 14 s clip about 2 to 3 hours, the simulation up to the window
included. On the Azure render job (2 vCPU, nothing else running) a 10 s clip took 365 to 660 s
(`infra/README.md`). The sets are about 300 clips of 10 to 30 s; on a CPU machine with 32 cores
running 16 at a time, that is a few hours. Only synthetic renders and this public repo go to the
machine; no credential does.

## 1. The command lists (on the Mac, from this branch)

```bash
uv run python -m ninety.eval.set_commands docs/eval/set-piece-set.json --out runs/event-sets/set-piece-set > set-piece.sh
uv run python -m ninety.eval.set_commands docs/eval/possession-set.json --out runs/event-sets/possession-set > possession.sh
```

One line per clip: render it with the set's settings into
`runs/event-sets/<set>/<split>/seed<N>-<start frame>/`, then `ninety-validate` it; it prints
`ok <dir>` or `FAILED <dir>` (the log is `<dir>.log`). A clip already rendered and valid is
skipped, so a list can be run again after an interruption. Add `--split validation` or
`--split test` to render one split.

## 2. The machine (a Linux CPU machine reached over SSH)

```bash
ssh -p <port> <user>@<host> 'bash -s' <<'EOF'
set -e
apt-get update -qq && apt-get install -y -qq git curl python3-pip nodejs npm tmux >/dev/null
pip install --quiet --break-system-packages uv==0.12.23
git clone -q https://github.com/KLKH7/the-ninety-labs.git ninety && cd ninety
git checkout -q 65247ba36343c640fe7673c772a1cbc0ac19c07e
uv sync --quiet && (cd web && npm ci --silent)
uv run playwright install --with-deps chromium >/dev/null
EOF
scp -P <port> set-piece.sh possession.sh <user>@<host>:ninety/
ssh -p <port> <user>@<host> "cd ninety && tmux new -d -s sets \
  'cat set-piece.sh possession.sh | tr \"\\n\" \"\\0\" | xargs -0 -n 1 -P 16 sh -c > sets.log 2>&1'"
```

`-P 16` runs 16 clips at a time; use about half the machine's cores (each render runs Chromium
and the engine). Progress: `ssh ... 'grep -c ^ok ninety/sets.log; grep FAILED ninety/sets.log'`.

## 3. Back to the Mac, validated again

```bash
rsync -a -e 'ssh -p <port>' <user>@<host>:ninety/runs/event-sets/ runs/event-sets/
for d in runs/event-sets/*/*/seed*/; do uv run ninety-validate "$d" >/dev/null || echo "FAILED $d"; done
```

Then delete the machine. A clip that fails its render checks or the contract is listed with its
log, never re-rendered with other settings or replaced by another window.

## 4. Freeze the test splits

```bash
uv run python -m ninety.eval.set_commands docs/eval/set-piece-set.json --out runs/event-sets/set-piece-set \
    --split test --freeze docs/eval/set-piece-set-test-frozen.json
uv run python -m ninety.eval.set_commands docs/eval/possession-set.json --out runs/event-sets/possession-set \
    --split test --freeze docs/eval/possession-set-test-frozen.json
```

Each clip gets the hashes of its `frames.jsonl`, `events.jsonl`, images and `meta.json`, and its
renderer; `rendered` counts the clips done. Commit only these two JSON files. The images, and the
test split's answer key (`frames.jsonl`, `events.jsonl`, `meta.json`), are never committed: the
answer key goes to the `truth-test` container (as the frozen test set's, `test-set-frozen.json`),
the images to `renders/<set>/test/`, uploaded by the maintainer with their own login.
