# Foundry event check: the rules, stated before any scored run

Written 2026-10-27, committed before any candidate was sent to a model or scored. Approved as a
prototype by Kian (Oct 27, about 10:30 PT); offline only, not wired into the Ask or the bundle.

**The idea.** Event counts from the video are weak (on the 8324 demo vision saw 8 of 18 shots;
restarts have no kind at all), while positions are strong. So code proposes candidate moments from
tracked positions, our own Foundry deployment (`ninety-labs-ai`, `gpt-4.1-mini`) looks at three
frames of each and says what it sees, and code counts. The model only perceives: it never gives a
number, a side or a time.

## Event types

`corner`, `goal_kick`, `throw_in`, `shot`. The model may also answer `none`. Free kicks, penalties
and kick-offs are out of scope.

## Candidates (code, live-path inputs only, no ground truth)

Inputs: the clip's tracked ball and players (`tracked.json`, `ninety/vision/tracked_frames.py`),
the order of shown frames (`observations.jsonl`: line *i* is video frame *i*), the clip's segments
(`clip.json`) and vision's own detected events (`detected.jsonl`). All are live-path outputs.

- **At a line (restart):** a run of tracked ball positions within `events.RIVAL_M` (1.26 m, the
  broadcast camera's measured ground error) of, or beyond, a touchline or goal line. The candidate is
  the run's first frame.
- **Set ball (restart):** a still spell, every tracked ball position within 1.26 m of the spell's
  median for at least 1.0 s (`restarts.MIN_STILL_S`), whose median is within 3 m of a touchline or
  goal line or inside a goal area (5.5 m by 18.32 m). The candidate is the spell's first frame.
- **Fast toward goal (shot):** tracked ball speed over 0.2 s of at least 45 km/h, moving toward a
  goal line it is within 35 m of, on a straight line that crosses that goal line within 8.66 m of
  the goal's centre (the 3.66 m half-width plus 5 m). The candidate is the first frame of the run.
- **Vision's own:** every detected `shot` and `out_of_play` (the first is a shot candidate, the
  second a restart candidate).
- **Merging:** candidates of the same family (restart, shot) within 3 s of video of one another are
  one, at the earliest.

45 km/h, 35 m, 5 m and 3 m are design values, set here before any score: 45 km/h sits under the
slowest shots and above most passes' first touch; 35 m covers long-range shots; 5 m allows for
the camera's error on a fast ball and for a shot just wide; 3 m from a line keeps a throw-in taker
holding the ball. None of them may change after scoring.

## Frames

Three frames per candidate, by video index (what a viewer sees), kept inside the candidate's own
segment: restart candidates at +0 s, +1.5 s and +3.0 s; shot candidates at -0.4 s, +0.4 s and
+1.2 s. Each frame is cropped to 768 x 432 centred on the tracked ball's pixel position when vision
saw it (else the frame's centre), resized to 512 x 288, JPEG quality 80, sent with `detail: low`
(85 input tokens an image). Frames are decoded one clip at a time.

## The prompt

Fixed in `ninety/vision/foundry_check.py` (`INSTRUCTIONS`): three frames of a synthetic broadcast,
in time order; answer only from what is visible; structured JSON
`{"label": corner|goal_kick|throw_in|shot|none, "confidence": 0..1, "seen": <=12 words}`.
Temperature 0. The candidate's own reason is not given to the model.

## Code after the model

A label counts when its confidence is at least 0.6 (design). Accepted events of the same label
within 10 s of video (restarts) or 2 s (shots) are one. The side is code's, from the end the ball is
at (Laws 14, 16, 17, as `ninety/intel/set_pieces.py`): a corner is the attacking club's, a goal kick
the defending club's, a shot the club attacking that goal; a throw-in's side is unknown. Each event
is written with `source: "foundry_check"` and the model's confidence.

## Held-out set

The seed 8080 demo render (engine 65247ba3, the same broadcast look and pipeline as 8324):
24,322 frames, 51 segments, 972.9 s of video, frames from
`runs/demo-8080-bundle-final/hls/720p`, positions and detections from `runs/demo-8080-hunt`.
It is the only clip on disk, other than 8324, with video, tracked positions and an answer key
together (the set-piece and shot-outcome sets' frames stayed on the pod). The answer key
(`~/ninety-notes/footage-hunt/events.jsonl`) is read only by `ninety/eval/foundry_event_score.py`.

Before writing this, only one thing about its key was read: the count of each kind it shows, to
see whether the set can say anything. Shown (the restart's frame or the stoppage's in the video):
shots 16, throw-ins 4, goal kicks 3, corners 1. Nothing else of the key was looked at, and no
candidate was generated.

Caveat in favour of the baseline: the restart detector's rules were developed against 8080
(`docs/eval/restarts-vision-plan.md`); this checker was not.

## Grading (offline, `ninety/eval/foundry_event_score.py`)

- A true restart (kind from `set_piece_set.restarts`) counts if its restart frame or its stoppage
  frame is shown. A detection matches it when its match frame lies from 2 s before the stoppage
  (2 s before the restart if none) to 3 s after the restart; a true shot when within
  `event_score.WINDOW_S` (1.0 s) of its frame. One to one, nearest first.
- Per type: recall and precision with 95% Wilson intervals, every miss and every false positive.
- **Baseline:** vision's detected events on the same clip (`runs/demo-8080-hunt/detected.jsonl`):
  `shot`, and `set_piece` with a `restart` kind, graded the same way.

## The bar

Per type, the checker passes when **all** hold:
1. at least 5 true events of the type are shown (fewer are reported as counts, never as a pass);
2. precision at least 0.8;
3. recall higher than the baseline's on the same clip.

A type that passes may go to the coordinator as a candidate for the Ask; one that fails does not.
8324 is scored only if at least one type passes. On 8080 that means only shots can pass.

## Cost

Hard cap $0.50 for the prototype. The run estimates tokens and cost before any call (85 tokens an
image plus the measured prompt) at the Data Zone price (`latency_cost.PRICES`, the higher of the
two meters), refuses to start above the cap, and stops when the running total reaches it. Every
call's tokens, latency and cost are logged.
