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
