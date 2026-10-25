# Team sides from the tactical views: pre-registered plan

Status: **pre-registered.** Written Oct 23, 19:34 ET (the commit time). The tactical lenses' observations of the
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

### Oct 23, 19:38 ET (the commit time), after T0 was read and before any T1 number was read

T0 was read (docs/eval/sides-tactical/T0-validation.json): outfield accuracy 0.614. The diagnosis
is in the data: the kit is misread on the tactical lenses, which render dark (frame mean RGB about
44–78, against 53–105 on the broadcast of the same clip). A purple shirt reads near-black, and 2-means
splits off one odd track. The renders stay as they are (the Coordinator's decision: ours-tactical
trained on them, and real fixed cameras differ in exposure). The fix is on the vision side. T1
becomes three steps, each scored by the plan's measures and decision rule:

- **T1a:** #202's two-colour reader (R4), re-read from each lens's images (`observe.recolour`),
  today's tracker. Already running when this was written; nothing of it read.
- **T1b:** T1a, with each lens's colours normalised first. Each lens's gain and white balance are
  estimated from that lens's own pixels, with no truth: the grass (the measured pitch colour, #202's
  `grass`) and the white pitch markings (the line pixels the camera fit found). Shirt colour is then
  read in the normalised space. How the normalisation maps colours is written down before T1b is
  run, in the code's docstring and the commit message.
- **Per-track side vote:** a track's side is already decided once per track, from its median kit
  over all its frames (`track.assign_teams`), never per frame. This is checked and kept. If T1b
  still leaves tracks that change identity mid-way (a track whose paired true team is split), that
  is reported, not tuned.

**Fallback (fixed now):** if the best T1 step is still below B, the broadcast's own side accuracy on
the same clips, by Sat Oct 24 12:00 ET, sides come from the broadcast. Each tactical track is
associated with broadcast detections where they overlap on the pitch (the same 1.0 m pairing) and
inherits the side of the broadcast track it overlaps most; positions stay the tactical views'. That
variant is **TB**, scored by the same measures.

The final calibration table goes to the 0.96 gate's owner (the shape-agents session).

### Oct 24 (the commit time): B and TB scored, the rule applied (session C takes the plan over)

B, the broadcast reference the rule compares against, and TB were scored on the same 23 validation
clips, from session D's observations re-judged with today's bands (broadcast (0.966, 1.121), PR
#270; fixed (1.002, 1.151)). Outfield side accuracy, track-frames:

| Variant | Accuracy | Sound clips | Flipped clips |
|---|---|---|---|
| B (broadcast) | 0.578 (56,791) | 8 | 8 |
| T0 | 0.614 | | |
| **T1a** (#202's reader on the lenses) | **0.681** (117,783) | 11 | 4 |
| T1b | 0.574 | | |
| TB (tactical tracks, broadcast sides) | 0.361 (120,702) | 0 | 15 |

TB is right on 0.588 of the track-frames it gives a side to, B's own rate; but 38% of the tactical
track-frames belong to players the broadcast never shows, and get none. By the rule fixed above,
T1a is at least B, so the fallback is not taken: **sides come from the tactical views with #202's
reader (T1a)**, which needs #202 on main. The calibration tables are in each variant's json for the
0.96 gate's owner.

### Oct 25, after review: what the result shows and what it does not

The numbers above stand (the merge queue recomputed them from the json); three things about them
were stated too strongly.

- **The order of writing cannot be shown from git.** The plan, its Oct 23 deviation and every result
  above were committed together (667e4be0, Oct 23 22:16 ET). The plan's header says 19:34 ET, and
  the heading "Oct 24 (the commit time)" above is wrong: that entry is in the same commit and was
  written after B and TB were read. The decision rule (T1 replaces the broadcast if it is at least
  B) is the one fixed in the Oct 23 entry and was not changed, but its pre-registration rests on the
  text, not on git.
- **T1a and B are not compared like for like.** The tactical views track about twice the
  track-frames (117,783 against 56,791), including players the broadcast never shows, and B reads
  the kit with the single median (R0) while T1a uses #202's two-colour reader (R4). "T1a is at least
  B" says the views with R4 told more track-frames right than the broadcast with R0 did; it does not
  separate the camera from the reader.
- **The side confidence barely tells a right side from a wrong one, and that is the headline.**
  T1a: accuracy 0.681; the confidence ranks a right track above a wrong one in 61.8% of pairs (50%
  is chance; B 60.8%); the largest confidence of a wrong track is 0.996 (B 1.0); 8% of right
  tracks are above 0.96 (B 3.6%), and of the 39 tracks above it 0.897 are right (B: 22, 0.636).
  11 of 23 clips are sound and 4 flipped. A wrong side can pass the fact-checker's 0.96 gate
  (`factcheck.side_known`) on either camera, so the gate is unchanged and Law 3 (#308) stands beside
  it as a backstop. The plan promised Hanley–McNeil's 95% interval on the ordering; it is not
  computed here (main has the ordering only).

Nothing here changes the live path. What the live path uses on the views is S (#283: R4 and a
spatial model, outfield accuracy 0.750, calibration error 0.037, SPATIAL-PLAN.md), measured after this.
