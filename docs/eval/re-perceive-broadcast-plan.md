# Active perception, "ask the other camera": the plan

Written 2026-10-26, before any of it is built or run. Kian approved the work for 2026-10-27 (timebox 45 minutes). Nothing below changes once a measurement has started; a change after that is an amendment, dated, with its reason.

## Why
Today's re-perception ([re-perceive.md](re-perceive.md)) resolved 0 of 81 held claims. Most were held on their side: a track whose side was told under the gate (`factcheck.MIN_TEAM_CONFIDENCE`, 0.96). Looking again through the same kind of camera gave the same answer. Two things have changed:
- the broadcast now tells sides near-perfectly on the kit-fixed 8080 render;
- #285's association maps each tactical-view track to a broadcast track, with a measured wrong-pair rate.

So a claim held on a view track's side can ask the broadcast what side it saw that player on.

## The rule (`re_perceive` mode `broadcast_side`)
For a claim held because a cited detection's side was not told surely:
1. Take that detection's track (the actor; a receiver or interceptor is someone else, whose side the event did not measure).
2. Find its associated broadcast track in the clip's `association.json`. No association means nothing changes.
3. Read the broadcast track's side the way the gate was measured: its whole-clip side vote and that vote's confidence (lesson 227). A side read at that moment, or from a window, is another reading and decides nothing.
4. **Resolve** only if all three hold:
   - the broadcast vote's confidence is above `MIN_TEAM_CONFIDENCE`;
   - its side is the side the claim names;
   - the association's own confidence is 1.0.

   The claim then goes through the whole fact-checker again with that side, and airs only if it passes.
5. **Contradict** if the broadcast vote clears the gate on the other side: the claim stays held, with that reason.
6. Anything else: still held.

The association is wrong for **4 of 144 pairs (2.8%, 95% interval 1% to 7%; [association.md](association.md))**, and 3 of those 4 have confidence 1.0, so its confidence does not flag them. That is the error this mode can make: a confident broadcast side transferred to the wrong player. It is what the measurement below grades.

## Measured, fixed now
1. **Validation clips only**, graded against the answer key offline: in `ninety/eval/re_perceive_eval.py`, never on the live path.
   - Count held, resolved, contradicted and still held.
   - Grade each resolution: right if the true event's side is the side resolved, wrong otherwise.
   - Report each count with a 95% Wilson interval and list every wrong one.
2. **Then the demo's held claims** (seed 8080). Report resolved and contradicted counts only: the demo is never graded, as it is not a validation clip.

## Rule for enabling it, fixed now
Mode `broadcast_side` goes into the agents' tools (`perceive.MODES`, and the workflow's look) only if, on validation:
- **at least 10 claims are resolved**, and
- **none is resolved wrong**.

Either short, it stays off, and the demo keeps the honest framing: claims on an unsure side stay quiet. With 10 resolved and 0 wrong, the 95% upper bound on the wrong rate is about 28%. The report states that bound, and claims no more than it.

## Outcome (2026-10-26, validation; `re-perceive-broadcast.json`)

Run on the association's validation clips that have a broadcast run (`runs/tactical1/join/runs`:
seeds 108, 109, 110, 113, 114, 115, 116; 112 has none), graded offline against their answer keys:

- Held on their side: **13** claims (all passes).
- Resolved: **0** (right 0, wrong 0). Contradicted: **0**. Still held: 13.
- Why: for 10, no single broadcast track is paired with the actor (he is out of the broadcast's
  picture, or the pairing is ambiguous); for 3, the paired broadcast track's whole-clip vote is not
  above 0.96. Across the 7 clips only 7 broadcast tracks clear 0.96 at all.

**By the rule fixed above it stays off** (needs at least 10 resolved): `broadcast_side` is in
`ninety/agents/perceive.py`, tested, and not in `perceive.MODES`. Claims on an unsure side stay
quiet. The demo's held claims were not run: the mode is not enabled, so it would decide nothing.

**Deviation, stated:** the broadcast's whole-clip vote is read with the join run's own code
(716014c, `runs/tactical1/join/code`), the code that made these observations and the association.
At today's main the two-colour kit reader (R4, #283) needs the second shirt colour these older
observations do not carry, and every broadcast track's confidence reads 0.0; read that way nothing
could resolve either. The track ids agree exactly with the association's under both.

