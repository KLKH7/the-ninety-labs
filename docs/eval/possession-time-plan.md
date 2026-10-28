# Plan: possession as time on the ball, from the video (pre-registered Oct 27, 2026)

Committed before the method's possession is compared with the answer key on any match. Results in
[possession-time.json](possession-time.json) and EVALUATION.md (*Possession, time on the ball*).

## Why

The Stats tab's possession was each club's share of the detected passes, stated only when every
pass's side was told surely (I17). On the demo almost no window qualified, so it read "unsure" all
match. Time in possession is the other broadcast standard (GROUNDING I17b): the seconds each team
had the ball, dead and contested time excluded.

## The method (fixed now; `ninety/intel/ball_share.py`)

On the tactical camera's tracked frames (vision's ball and players, 25 fps):

1. **Control.** In a frame, a player has the ball when it is within `CONTROL_M` = 1.5 m of him (P6),
   the nearest such player, moving with him within `CARRY_MPS` = 4 m/s (the detector's own
   possession, `ninety/vision/events`), and the ball is in play (not beyond a line by more than
   its radius, Law 9). His side is his track's, as vision reads it.
2. **Gaining it.** A side gains possession when its players have the ball for `MIN_SPELL_FRAMES` =
   2 frames running (the detector's).
3. **Keeping it.** It keeps it until the other side gains it, while the ball is in play, and for at
   most `HOLD_S` = 4 s after its last touch (the phone's possession layer's design). A dead ball, a
   cut in the footage (frames more than `SPELL_GAP_FRAMES` apart) and a ball loose longer than
   HOLD_S belong to nobody until a side gains it again.
4. **Share.** Each side's seconds over both sides' seconds in the window, rounded so the two make
   100. Stated once both sides together had at least `MIN_POSSESSION_S` = 60 s of possession in the
   window (*design*); before that the screen shows "—". Never "unsure".

## The measurement (offline; `ninety/eval/possession_time.py`)

- **Truth.** The answer key's `possessor` each frame, carried to the next possessor, over the same
  frames the footage shows; dead-ball time excluded (from an `out_of_play`, `goal`, `foul`,
  `offside` or `half_time` event to the next `set_piece` or `kickoff`, and whenever the true ball is
  beyond a line). The true share is each side's frames over both sides'.
- **Matches.** Seed 8080 (held out) and seed 8324 (the demo; its live 50% / 50% for the whole match
  was printed once while the code was written, never compared with the answer key).
- **Windows.** The ones the screen shows as headline numbers: first half, second half, full match,
  on each match (six values).
- **Gate.** Mean absolute error of the home share over the six windows **≤ 5 points**. Reported
  beside it: the largest error, and the MAE of the Stats tab's "so far" values at every 5-minute bin
  once stated.
- **If it misses.** Published as missed; the screen keeps the number with the measured error
  beside it in How we know, and the row is labelled with it. No parameter is changed after the score.
- **Scored once**, the commit recorded in the json.
