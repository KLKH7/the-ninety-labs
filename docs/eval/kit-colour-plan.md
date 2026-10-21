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

## Step 1's diagnosis, and an amendment (before any candidate is scored)

The read kit against the true shirt colour, per track, with crops looked at for seeds 120 and 2043:
- **(b) a pattern's second colour is the main cause.**
  - The renderer draws hoops, stripes, a sash or halves in the kit's second colour: the shorts
    colour, or white when the shorts match the shirt (`web/render/render.js`, kitMaterial).
  - It also draws a yoke of it above about 1.46 m, which lies in the patch `kit_rgb` samples.
  - 120: the blue home kit with white hoops reads near-white.
  - 2043: the white away kit (halves with black) and the dark-green home kit (stripes with black)
    both read near-black.
- **(e) 120's "white read as cyan" is not a misreading.** Those tracks are the away goalkeeper,
  whose kit is cyan; the colour is read correctly.
- **(d) light:** some shirts read darker in shade. Secondary here.
- **(a) grass:** no case found where grass-like shirt pixels were dropped.

R2 (the larger of two colours) cannot fix a half-and-half shirt or a yoked hooped one, where the
second colour can be the larger. So one candidate is added, before any is scored:

| Name | Rule |
|---|---|
| R4 two-colour signature | the shirt patch's pixels, after R1's grass drop, split into two colours (2-means in RGB). The kit is both, ordered by brightness, as one point (the darker's then the lighter's channels). Kits are compared as pairs in the feature track.py chooses (chromaticity or brightness, per colour). A solid shirt gives two close colours |

**R4's colour error:** the distance in chromaticity from the true shirt colour to whichever of its
two colours is nearer. The rule of adoption is unchanged.

## Outcome

### Render run v1's validation clips ([kit-colour.md](kit-colour.md))

| Reader | Sound clips | Side accuracy, track-frames | Pass teams right | Median colour error | Confidence ordering |
|---|---|---|---|---|---|
| R0 (today) | 4 | 0.815 | 11 of 16 | 0.113 | 0.55 |
| R1 measured grass | 4 | 0.744 | 10 of 16 | 0.118 | 0.53 |
| R2 larger colour | 4 | 0.716 | 10 of 15 | 0.142 | 0.52 |
| R3 shading-invariant | 4 | 0.797 | 11 of 15 | 0.142 | 0.61 |
| **R4 two colours (adopted)** | **6** | **0.894** | **12 of 16** | **0.058** | **0.81** |

**R4 is adopted by the rule:** more sound clips, higher side accuracy, lower colour error.
- Seed 120 goes from 0.11 to 1.00, and 2041 becomes sound.
- Seeds 115 (0.64, against R0's 0.73) and 2043 (0.76) are still not sound.

R1 to R3 do worse than today, which agrees with the diagnosis: grass was not the cause.

**The cluster-soundness confidence clears the 0.80 bar on this set: 0.81.** But it rests on 4 wrong
passes against 12 right (48 pairs), so it is predictive by the rule, on a small sample. Two things
follow, both in the plan:
- the reader and the confidence are **confirmed on dataset v2's validation clips** with everything
  frozen;
- only then is the test set scored once and the agents' limit and W6's gate reconsidered.
Until then, neither is lifted.

## Amendment for dataset v2 (written before any v2 clip exists)

W6's dry calibration on R4 (shared notes, r8-possession-design.md) left one clip wrong while
confident: 2043, 15 of 45 right at team_confidence 0.011 to 0.213. Diagnosed on validation, with no
change made:
- the home kit is dark green with black stripes, so R4's "light" colour is arm skin;
- away is white/black halves, so an away player seen from his black half reads (black, skin), the
  home signature;
- the clusters look tight (soundness 0.79), so the mixing is invisible in kit space.

Two non-colour cues tried on the 8 validation clips with events did not separate 2043 from the sound
clips:
- per-frame side balance: sound 108 and 120 are more lopsided;
- frame-level consistency: 2043 0.83, but sound 2041 is 0.79 and 116 is 0.84.

Fixed now, to be judged on **dataset v2's validation clips only**, with everything frozen:

**R5, skin dropped.** R4, with skin-coloured pixels removed from the shirt patch before the
two-colour split. A pixel is skin by the published RGB rule of Kovač, Peer and Solina (2003, *Human
skin colour clustering for face detection*, EUROCON), for daylight:
- R > 95, G > 40, B > 20;
- max − min > 15;
- |R − G| > 15;
- R > G and R > B.
If too few pixels are left (under 4), R4's reading stands. R5 replaces R4 only by the plan's rule:
at least as many sound clips, side accuracy not lower, colour error not higher, on v2's validation
clips. A kit the rule calls skin (orange, salmon) is the known risk, and the per-clip table shows it.

**C, a consistency term (conditional).** Per clip, the share of tracks' per-frame readings that lie
nearer their own cluster's centre than the other's. It enters `team_confidence`'s kit term (the
smaller of soundness and C) **only if, on v2's validation clips, both hold**:
1. it ranks every unsound clip below sound ones in at least 80% of (unsound, sound) clip pairs;
2. with it, the pass-level confidence ordering is higher than without it, and at least 0.80.
Otherwise it is left out, and the outcome says so.

**If neither helps on v2:**
- W6's gate rule stays as W6 pre-registered, with no SURE or SHOW adjustment after seeing data;
- EVALUATION names the failure: a dark kit against a halves kit sharing its dark colour, where a
  player seen from his dark half reads as the other side.

**Order on v2:**
1. The image stage (detect, observe) on v2's validation clips, as slot jobs once the Coordinator
   frees them.
2. R0, R4 and R5 compared; C judged.
3. Everything frozen; then the test set scored once.
