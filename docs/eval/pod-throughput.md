# Render throughput on the RunPod CPU pod (dry run, nothing counts)

Measured Oct 21 at #188's merge commit `86e03a5`, on a RunPod `cpu3g` pod: 32 vCPU of an AMD EPYC
7702P host shared with other tenants (host load average 110–210 throughout), Ubuntu 24.04,
software GL (SwiftShader), as `infra/pod/setup.sh` sets it up.

| Measure | Result |
|---|---|
| `setup.sh` from a clean pod, unattended | 38 min, of which the 60 s smoke render is 26 min |
| Smoke checks | validate and render-check pass, 0 feet outside their boxes; the determinism re-render of a 10 s clip is identical on frames, events and all images |
| One render alone | about 1.2 s a frame (the maintainer's Mac: about 0.43 s) |
| 2 s clips (100 frames with warm-up) | 1 worker 120 s a clip; 4 workers 163 s; 16 workers 402 s (137 clips an hour) |
| 10 s clips, 8 workers | 16 of 16 passed; median 944 s a clip, 30 clips an hour |
| Chromium throttling flags (`--disable-background-timer-throttling` and two more) | no change in speed; output byte-identical |

A render waits rather than computes: with 16 workers our 32 CPUs were about 63% idle and steal was
0, yet each render slowed threefold. Each frame draws the scene about 26 times (one solo draw per
object for the visibility labels, the id pass, the main pass, the post pass and the overlay), most
followed by a synchronous pixel read-back from the GPU process. The likely limit is memory bandwidth
and cache shared with the host's other tenants, not our core count.

At about 16 workers a 10 s clip runs at roughly 50 an hour, so the 310 clips of dataset v2 take
about 6 hours on one pod, or about 3 on two. Pod-hours, and so cost, are about the same either way.
