#!/usr/bin/env bash
# Who holds cores on the shared pod (/work/README).
for f in /work/cores/*.*; do
  [ -e "$f" ] || continue
  pid=${f##*.}; kill -0 "$pid" 2>/dev/null || continue
  printf '%3s cores  %-24s since %s  %s\n' "$(sed -n 1p "$f")" "$(basename "${f%.*}")" "$(sed -n 3p "$f")" "$(sed -n 2p "$f" | cut -c1-60)"
done
[ -e /work/cores/RENDER-EXCLUSIVE ] && echo "RENDER-EXCLUSIVE: the final render has the pod"
nproc | xargs echo "cores:"; uptime
