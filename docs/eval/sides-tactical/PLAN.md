# Team sides from the tactical views: pre-registered plan

Status: **pre-registered.** Written Oct 23, 19:40 ET. The tactical lenses' observations of the
validation clips exist (they were made to derive the fixed lens's height band), but no track, side
or confidence has been computed from them. A change after this commit goes under "Deviations",
dated, before any result is read.

**Rubric:** agentic design and real-world impact. The fact-checker holds every claim that names a
team unless each cited event's side was told above 0.96 (PR #249, `MIN_TEAM_CONFIDENCE`). On the
broadcast today, the M1 clip's events score 0.529, so every team claim is held. The two tactical
lenses see all 22 players and both kits all the time. This plan measures whether that makes the
side right, and the confidence earned, and reports the distribution to the gate's owner (the
shape-agents session). It does not set the threshold.

## What runs

The live path, unchanged except for its input: the fused tactical observations (`fuse.fuse` of
`observe --fixed` per lens, with the fixed band of docs/eval/ball-three-cams/band-fixed.json), then
`track.track_players` and `track.assign_teams`, today's code. Side confidence is today's
`side_confidence`: the smaller of the colour margin and the clip's vote margin. Keepers keep theirs
(the half they stand in).

| Variant | Players from | Kit reader |
|---|---|---|
| **B** (reference) | the broadcast's observations (observe on the broadcast images), as the live path runs today | today's (R0) |
| **T0** | the fused tactical views | today's (R0) |
| **T1** (if T0 leaves side errors that are kit-colour errors) | the fused tactical views | #202's two-colour reader (R4), re-read from the lens images by #202's `observe --regate <file> <clip>`. Built on #202, not copied |

## What is measured (validation only: tactical1's 23 validation clips, seed 118 excluded as in the fine-tune)

**Truth matching**, by pitch position, never by pixels, so every camera is judged the same way: in
each frame, a detected player's place is paired one to one with the nearest true player within
1.0 m (the strict radius, `event_score.STRICT_M`). A track's true team is the team of most of its
paired frames. A track with fewer than half its frames paired is "unmatched" and reported, not
scored. Tracks shorter than `tracked_frames.MIN_TRACK_FRAMES` are left out, as the events stage
leaves them out.

- **Side accuracy:** the share of matched track-frames whose track's side is its true team, for
  outfield tracks and keepers separately, with Wilson 95% intervals (k/n). Frames are not
  independent, so the intervals are narrower than the truth.
- **Sound clips:** clips where at least 0.80 of outfield track-frames are right (#200's
  `SOUND_SHARE`). Flipped clips (most wrong) are counted.
- **Confidence:** for each outfield track, its `side_confidence` and whether its side is right:
  - the distribution (min, 10th, 50th, 90th percentile, max) for right and for wrong tracks;
  - the ordering (area under the ROC curve, with Hanley–McNeil's 95% interval, as #200's
    `ordering_95`);
  - **the largest confidence of any wrong track**, and the share of right tracks above 0.96 and
    above that largest wrong value;
  - calibration: accuracy in confidence bins [0, 0.5), [0.5, 0.8), [0.8, 0.9), [0.9, 0.96),
    [0.96, 1].

## Decision (fixed now)

T0 (or T1) replaces the broadcast for players' sides if its outfield side accuracy is at least B's
on the same clips. Whether any claim airs is the gate owner's call, from the distribution above.
T1 is built only if T0's remaining errors are kit-colour errors (the cluster of a wrong track sits
nearer the other kit), and judged by the same rule against T0.

A test-set number for sides is not part of this plan. It would need its own frozen run, and the
plan leaves that to the gate's owner.

## Deviations

None yet.
