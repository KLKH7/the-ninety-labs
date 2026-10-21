# Reading a kit's colour from the shirt, and a confidence that the two kits are told apart: the plan

Written on branch `vision/kit-colour`, stacked on #200 (`vision/side-decision` at 7a19f1d), before
any of the runs below. Results go under "Outcome" at the end, without editing what is above.
Lesson 179.

## Why

#200 showed that every side error left is a cluster error. The two kit clusters do not each hold one
team, because the colour read from the shirt is wrong: on validation 115, 120, 2041 and 2043, and on
test 900004 and 900005. No confidence predicted those errors (best 0.62).

`observe.kit_rgb` takes the median colour of a box's upper-middle part (20 to 50% down, the middle
60% across), after dropping pixels whose green exceeds red and blue by 10. Seen in #187 and #200,
with causes not yet established:
- a dark green shirt reads grey (2043);
- a green shirt reads yellow in two tracks (108);
- a blue shirt reads near-white (120);
- white shirts read cyan in two tracks (120).

## Data (validation only; no slot jobs)

- **Development:** the 13 observed validation clips of [detector-plan.md](detector-plan.md) (render run
  v1, renderer 0.3.0). The images are on disk with the render run, and the player boxes are in the
  committed observations (`pr-assets/detector-validation-observations`, 4d42fbf). Re-reading the
  colours needs only those, not the camera fit.
- **Confirmation:** dataset v2's validation clips, once rendered (the freeze render). The full
  image stage is run on them, with the rule and every constant frozen beforehand. They are a second
  validation set, never the test set.
- **Test:** the frozen test set (900001 to 900005), scored once at the end.

The render settings (`clip.json`: each kit's shirt colour and pattern) and the truth are read
**offline only**, to diagnose and to score, never by the live path. A test keeps it that way.

## Step 1: diagnose (validation)

For each clip, compare each track's read kit colour with its true team's shirt colour, in
chromaticity and brightness. Record, per failing case, which of these it is:
- (a) grass-like shirt pixels dropped;
- (b) a pattern's second colour mixed in (hoops, stripes, sash, halves);
- (c) background or crowd inside the box;
- (d) light or shading;
- (e) something else.
The diagnosis decides which candidates below are worth building; it cannot add a candidate not
listed.

## Candidates for reading the kit (each from the image and the boxes only: the live path)

| Name | Rule |
|---|---|
| R0 (now) | the median of the upper-middle patch, minus pixels with green more than 10 above red and blue |
| R1 measured grass | per frame, the grass's colour is the median of pitch pixels outside every box (below the horizon the camera gives). A shirt pixel is dropped only if it lies within the grass's own measured spread (its 90th-percentile chroma distance to that median), not by a fixed green rule |
| R2 dominant colour | the shirt patch's pixels are split into two colours (2-means in chromaticity and brightness, after R1's grass drop), and the larger is the kit. A pattern's second colour, or a background strip, is then the smaller |
| R3 shading-invariant | R2, with each pixel's brightness divided by the median brightness of the patch, so light and shade within a shirt do not split it |

## Measures (validation, offline)

- **Cluster soundness,** as in #200: each kit cluster's matched track-frames at least 80% one side,
  the two majorities differing.
- **Side accuracy** by track-frames, and pass teams right on matched passes.
- **Colour error:** per track, the distance in chromaticity between the read kit and the true shirt
  colour, as the median over tracks.

## Adoption rule (validation, render run v1)

A candidate qualifies when, against R0:
- it makes at least as many clips sound;
- side accuracy does not fall;
- the median colour error does not rise.
Among qualifying candidates, the most sound clips wins (ties: the higher side accuracy, then the
earlier in the table). If none qualifies, R0 stays.

The choice is then **confirmed** on dataset v2's validation clips with everything frozen. If it does
worse there than R0 on the sound-clip count, that is reported and R0 stays.

## The cluster-soundness confidence

Its form is fixed now and measured on the adopted reading. Per clip, it is the smaller of:
- the kit separation (centre distance over within-cluster spread, as track.py chooses the feature
  by), mapped through sep / (1 + sep);
- the share of tracks whose kit lies nearer their own cluster's centre than halfway to the other's.
It becomes each event's `team_confidence`, together with the side vote margin as today: the weaker
of the two.

**Bar (fixed now):** it is called predictive only if, on validation, it orders a wrong side below a
right one in at least 80% of (wrong, right) pass pairs, by the same measure as #187's and #200's.
Otherwise it is reported as not predictive, the agents' "no team-level claims" stays, and the
phone's possession gate stays closed.

## Then

- Freeze, and score the test set once:
  - the per-clip side report (`side_decision --test-dir`);
  - `attribution_score`;
  - `event_report`.
- Update EVALUATION, CHALLENGE_MAP, W6's note and the agents' limit (lifted only if predictive).
- Lesson 179.
