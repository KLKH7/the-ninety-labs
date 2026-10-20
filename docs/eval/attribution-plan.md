# #168: re-deriving the attribution constants on non-test clips (written 2026-10-20T14:41Z, before any run)

Why: the Coordinator pointed out that the track-break rule was shaped on seed 900004 (a frozen test
clip). RIVAL_M = 1.44 m was also measured on seed 900001, which is a test clip too.

Clips: the ours-v2 validation seeds that have no camera cut, from render run v1 (renderer 0.3.0;
the detector never trained on them; none is a test seed):
108 109 114 115 116 120 121 122 2041 2042 2043 2045 3041 3042 3045 (15 clips).
Source: render run v1, train split (runs/azure/v1/train/seed<N> on the training machine). Checkpoint ours-v2, sha256 ef478f09... (matches
the train manifest).

Pipeline, unchanged from the test clips: detect (ours-v2) -> observe -> track -> events.

Fixed now, before looking:
1. RIVAL_M := the p90 of player pitch-position error pooled over these 15 clips (pitch_score's rule:
   IoU 0.5 pairing, score >= 0.5, camera-trusted frames). Same statistic as before, now on
   non-test clips. Rounded to cm. This value is final whatever it is.
2. Track-break rule: its form and its other constants (REACH_MPS 10 m/s from track.py / GROUNDING
   R6; MAX_GAP_FRAMES from the tracker) stay as they are. On the validation clips, with the rule on
   and off, count (a) detected passes whose passer and receiver tracks are the same true player
   (self-passes), and (b) true passes matched. The rule stays only if (a) occurs on validation
   without it and it removes those without losing (b). If (a) never occurs on validation, the rule
   is reported as unvalidated and stays out (it is not evidenced on non-test data).
3. Attribution on validation (team, names) is reported as development numbers.
4. Then the test clips are scored once with the final constants and rule. Seed 900004 is still
   reported as having been seen when the rule was first written.

## Amendment, 2026-10-20T17:01:43Z, on the Reviewer's audit (before any validation number was looked at)

State at amendment: detection and observe have run on seeds 108, 114, 116 and 121 (the rest are running).
The only thing looked at so far: seed 108's camera trusted 195 of 250 frames (a sanity check that the
file is valid). No error, pass, self-pass or attribution number from any validation clip has been seen.

1. Keep-or-drop limit for the track-break rule, exact: **keep it only if, on the 15 validation clips,
   it removes at least 1 self-pass and suppresses 0 passes between two different true players. A
   removed pass whose players cannot be checked counts as a suppressed real pass.** Otherwise
   drop it (code and lesson text updated to say so).
2. The rule's form (never seen together, starts within MAX_GAP_FRAMES, within reach) was chosen on
   test seed 900004. That is stated in the PR and the report. Nothing about it is tuned on
   validation: the only outcome is keep or drop.
3. REACH_MPS: re-sourced to GROUNDING R6 (match top speeds 7.9 to 8.6 m/s; 10 m/s is a design bound
   above them). Not "track.py's bound": track.py has no such constant (Reviewer's point, lesson 69).
   Its value is unchanged: it is not tuned.
4. RIVAL_M is reported per clip as well as pooled (renderer 0.3.0 on validation vs 0.3.2 on test).
   The pooled p90 is the value used, as planned.
5. Committed with the result: the derivation JSON and .md, the exact commands (detect, observe,
   derive, and the observe commands for 900002 to 900005), the checkpoint sha, and a test that
   events.RIVAL_M equals the committed pooled p90.
6. Both kinds of error are reported: names left empty, and names on false events (dev and test).
7. Then the test clips are scored once, with the final constants. Commit order against this plan
   is what's claimed, not "pushed before scoring" for a58ef3e (its three commits went in one push).
