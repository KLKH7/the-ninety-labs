#!/usr/bin/env bash
# Run a command on the shared pod within the core budget (/work/README).
#
#   /work/bin/reserve <cores> <session-name> <command...>
#
# Writes /work/cores/<session>.<pid> with the cores held, runs the command with that many threads at
# most (taskset is not used: the job must size its own workers), and removes the file on exit. It
# waits while the reservation would take the total over the budget: 30 of 32 cores, and engine work
# (anything but the session "render") over 24. When /work/cores/RENDER-EXCLUSIVE exists, only the
# render may start; running jobs are asked to stop by the person who created it.
set -euo pipefail
CORES=${1:?usage: reserve <cores> <session-name> <command...>}
NAME=${2:?usage: reserve <cores> <session-name> <command...>}
shift 2
DIR=/work/cores TOTAL=30 ENGINE=24
mkdir -p "$DIR"
held() {  # cores held by live reservations; a file whose process died is removed
  local sum=0 f pid n
  for f in "$DIR"/*.*; do
    [ -e "$f" ] || continue
    pid=${f##*.}
    if ! kill -0 "$pid" 2>/dev/null; then rm -f "$f"; continue; fi
    n=$(head -1 "$f"); sum=$((sum + n))
  done
  echo "$sum"
}
engine_held() {
  local sum=0 f pid
  for f in "$DIR"/*.*; do
    [ -e "$f" ] || continue
    case "$(basename "$f")" in render.*) continue ;; esac
    pid=${f##*.}; kill -0 "$pid" 2>/dev/null && sum=$((sum + $(head -1 "$f")))
  done
  echo "$sum"
}
while true; do
  exec 9>"$DIR/.lock"; flock 9
  h=$(held); e=$(engine_held); ok=1
  [ $((h + CORES)) -le $TOTAL ] || ok=0
  if [ "$NAME" != render ]; then
    [ $((e + CORES)) -le $ENGINE ] || ok=0
    [ ! -e "$DIR/RENDER-EXCLUSIVE" ] || ok=0
  fi
  if [ $ok = 1 ]; then
    printf '%s\n%s\n%s\n' "$CORES" "$*" "$(date -u +%FT%TZ)" > "$DIR/$NAME.$$"
    flock -u 9; break
  fi
  flock -u 9; sleep 10
done
trap 'rm -f "$DIR/$NAME.$$"' EXIT INT TERM
"$@"
