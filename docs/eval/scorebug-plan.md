# The score from the scorebug: rules stated before any validation score (2026-10-25)

The Coordinator's task, approved by Kian. A scoreline may be shown only from the broadcast's own
scorebug, read from pixels (`ninety/vision/scorebug.py`); a goal the scorebug shows but the shot
detector missed gets its scorer by look-back. Nothing on the live path reads the answer key.

## The reader (live path: pixels only)

- **Where.** The bug is our renderer's (`web/render/render.js`, `drawBug`). The dark plate (196 px,
  white 2 px underline) is found on each frame, because the GOAL panel slides it right. The home
  and away digits sit 62 and 104 px into the plate, at 16 px semi-bold sans-serif, scaled with the
  picture height.
- **Digits.** Normalised cross-correlation against the ten digits rasterised from Helvetica Bold
  (Chromium's `sans-serif` on the Mac) and Arial Bold (whose digits are Liberation Sans Bold's,
  Chromium's `sans-serif` on Linux). Only the 24 x 16 rasters are committed
  (`ninety/vision/scorebug_glyphs.json`), never a font file, and no OCR model is used.
- **Acceptance (design):** best correlation `MIN_NCC` 0.85 or more, and a lead of `MIN_MARGIN`
  0.05 over the best other digit. Two measurements were taken before stating these, neither on
  validation: on 6 pod-rendered training clips (seeds 10, 100 to 104; all 0-0) a 0 reads at 0.99,
  with the next digit at 0.87; on the demo segment (dev check), the goal's "pop" frames read near
  0.79.
- **N (stability), pre-registered:** read every 25 frames (`SAMPLE_FRAMES`, about 1 Hz). A score
  holds after `STABLE` = 2 samples in a row agree, so a reading must last at least 1 s. The
  renderer's two transients are shorter: the scorer's digit pops for 0.5 s and the GOAL panel
  slides in 0.42 s (render.js). The flicker this guards against is measured on validation and
  reported: held scores that change other than by one goal (`inconsistent`), and samples left
  unread.
- **A change** is accepted only as one goal on one side (Law 10). Its frame is the first frame
  showing the new digit, found frame by frame back to the sample before. For timing, the best digit
  counts even under the bar, because the held samples have already settled the score.

## Reconciling with vision's goals (PR #271): W, pre-registered

- **W = 1.0 s** (`event_score.WINDOW_S`, the window every detected event is graded in). The
  renderer shows a goal's new score from the goal's own frame (`ninety/render/clip.py`), and the
  reader is timed to the frame.
- A scorebug +1 with a vision goal of that side within W confirms the goal. Their confidences are
  combined as independent evidence: 1 − (1 − a)(1 − b).
- A +1 with no vision goal adds a goal for that side at that frame. The scorer comes by look-back:
  that side's last detected shot before it, with no event of the other side between, within 10 s
  (*design*: generous beside a shot's flight of 1 to 3 s). The scorer is named only as that shot's
  `player` (already identity-gated), else not at all. The assist is the last completed pass to the
  scorer before the shot.
- A vision goal with no +1 within W is held: it is not shown.

## Measured where

- **Validation only, with goals:** the shot-outcome set's validation clips (seeds 910001 to
  910008), on the pod that holds their frames, or re-rendered on a short pod under Kian's OK.
  `ninety/eval/scorebug_score.py` reports:
  - score-change recall and precision with 95% Wilson intervals, and every timing error;
  - digit accuracy, where the whole match's events are given;
  - the unread share.
- **Test seeds are refused.**
- **Development check, not a result:** demo seed 8080, the 44:06 to 45:09 segment rendered on the
  Mac at 3a27753b. 1 of 1 change found, 0.04 s after the goal; digits 59 of 59 read samples right;
  5 of 64 samples unread.

## Changes after R4's review and an independent audit (2026-10-25, before any validation score)

- **The first score held is a `score_read` event** (no side), so a viewer who joins at any point
  sees the score. It stays in the scorebug's own file: every detected event has a side and it has
  none. `team` is now required on every type but `score_read`, and `score` is required on
  `score_change` and `score_read` and absent elsewhere (schema `allOf`, tested both ways).
- **A change's side is a pixel reading** (which digit changed), so its `team_confidence` is the
  reader's confidence, and so is an added goal's.
- **Shown only once measured.** No screen or voice shows a score from these events until the
  validation measurement above is in: reads right per change, with a Wilson interval. Until then
  the existing pointer ("the scorebug shows the score") stands.
- **Audit fixes:**
  - A held score that changes other than by one goal is never adopted, so a misread does not move
    the count. A two-digit score is wider than the cell, so a 10 can read as 1.
  - The back-scan starts from the last sample that read the old score.
  - Sampling goes by frame number, plus the first frame after each cut.
  - With no score ever read (a fixed tactical view draws no bug), the reconcile changes nothing.
  - The audit's 8 surviving mutants are all killed now.
- **Known limits, stated before measuring:**
  - Scores of 10 or more are not read (the goal from 9 to 10 is lost; later goals still count).
  - The look-back can name an earlier shot's shooter when the scoring shot itself was missed and
    no event of the other side came between.
  - The tactical views have no scorebug.
- **Licence, pending a decision:** the digit templates are rasters of Helvetica Bold and Arial
  Bold (THIRD_PARTY_NOTICES.md). If they are not acceptable, they are replaced by digits cropped
  from our own renders.

## Which digit is home's, and what is refused (R4's N3 and N4, 2026-10-25)

- **Left is home, by the renderer's draw order, not by kit.** `render.js` draws, left to right, the
  home code, the home digit, a dash, the away digit and the away code, from `score = [home, away]`
  (`ninety/render/clip.py`). Tested: a frame drawn with home 3 and away 7 reads home 3, away 7, for
  every digit in both faces.
- **Plausibility.** A held score never decreases, and it changes only by exactly +1 on one side
  (Law 10), held `STABLE` samples before it counts. A held read that goes down or jumps by two is
  refused: not emitted, not adopted, and counted (`inconsistent` in the reader's summary,
  `refused_reads` in the validation table). Tested: down, +2 on one side, +1 on both, and a
  misread jump that must not move the count.
