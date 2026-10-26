# Plan: naming the broadcast's tracks directly from the ID feed (pre-registered Oct 26, 2026)

Committed before any number from the direct path is read. The results go in
[identity.json](identity.json) and EVALUATION.md (*Player names from the ID feed*).

## Why

On demo seed 8080, 113 of 345 detected events take a name and a side from the player-ID feed
(#389). Names reach the broadcast's tracks, which events name, only through the camera join to
the tactical camera's tracks, and most broadcast tracks have no join pairing at the gate. Real
broadcasts match the provider's feed to the broadcast camera itself: the calibrated camera puts
each player on the pitch, and the feed is matched there.

## The direct path (fixed now)

1. **Frames.** Each segment's broadcast `tracked.json`: vision's broadcast tracks, already in
   pitch metres through the calibrated camera, only in frames that passed the camera trust test
   (B3; a frame that failed it holds no players). Ids renumbered as the join renumbers them
   (`match_join.renumber`, segments in name order).
2. **Matching.** `identity.assign` as for the tactical tracks (aligned by capture time, 10 s
   windows, Hungarian with a "nobody" column, frames discounted by distance, within GATE_M =
   1.26 m, strict majority, one track per player at a time), with one change: **both sides'
   feed players are candidates**, because the broadcast's side is what the feed is asked to
   supply (5 of 345 events have a sure side from vision). The side a track gets is its feed
   player's.
3. **Events.** An event names a broadcast track by its id; where the event's id letter differs
   from the broadcast track's (the side fix of `sides.json` and the event's own side vote), the
   track is found by its number, which the tracker gives once for both sides in a segment.
4. **Combining with the join.** A broadcast track named by both paths takes the more confident:
   the direct share against the tactical track's share times the association's confidence
   (*design*). Ties go to the direct path (it is that camera's own track).

## What is measured, and the gate

- **Unit:** a detected event's actor (`player`), graded as `identity_eval` grades: the actor's
  broadcast track's true player is the engine player nearest it on average over its frames; a
  name is right when it is the engine player behind the feed id given.
- **Gate (pre-registered):** on the held-out half (odd segments), the combined naming's event
  actor precision must be **at least 0.95** (naming_eval's TARGET). Nothing is tuned: there is no
  grid; GATE_M, the window and the join's association gate (0.75) are as in #389. If the gate is
  missed, the direct path ships off and the result is reported.
- **Reported either way:** precision and coverage on the held-out half and the whole match;
  coverage out of all 345 events; and for every event left unnamed, one reason, in this order:
  (a) vision attributed no player; (b) the actor's broadcast track has no frame that passed the
  camera trust test (calibration withheld); (c) it has frames but no feed player for a strict
  majority of them; (d) its name was given to another track at the same time. Also the number
  of events whose own frame failed the trust test.
- **Side:** events with a sure side (`factcheck.side_known`), without the feed, with #389, and
  with the direct path.
