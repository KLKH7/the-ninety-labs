# The phone's numbers from tracked positions (seed900001, M1 clip)

The companion's minimap, player cards and wind map read `tests/fixtures/tracked-seed900001.json`.
It is built from the video's observations by `ninety/vision/tracked_frames.py`, with no answer key
(`tests/test_tracked_frames.py` watches it run). This report grades those numbers against the
ground truth, offline, which is the answer key's only allowed use.

```bash
uv run python -m ninety.eval.tracked_speed tests/fixtures/observations-seed900001.jsonl \
    runs/test-frozen-cca498c/test/seed900001/frames.jsonl --clip seed900001 \
    --out docs/eval/companion-tracked.json
```

**Method.**
- Each track the phone shows is paired with the true player of its side who stands nearest it on
  average over the frames it was seen.
- The companion's own window facts (`ninety/intel/window.py`) are computed on both, over the same
  frames:
  - speed now at every whole second of the track (60 readings);
  - top speed and distance over the whole track (16 tracks).
- The errors are tracked minus true. The report is about the committed file: `graded_sha256`
  equals its digest, and a test holds the two equal.

## The clip

- Ten seconds (frames 1650 to 1899).
- The broadcast camera sees 0 to 10 players a frame, 7.3 on average.
- The tracker makes 21 tracks. 16 last a phone frame (0.2 s) or longer and are shown: 4 home and
  12 away.
- The tracker sees no shirt numbers, so each player is his side and his track (`h-t12`), not a
  squad number.

## Results

| Smoothing | Speed now, median (p90) | Top speed, median (p90) | Distance, median (p90) |
|---|---|---|---|
| none: positions as the camera fit gives them | 4.35 km/h (8.6) | **55.6 km/h** (67.2) | 6 m (11) |
| shipped: a line through each second (25 frames) | **0.6 km/h** (2.0) | **1.9 km/h** (4.2) | **1 m** (3) |

Mean signed errors with the shipped smoothing: speed now +0.02 km/h, top speed +0.17 km/h,
distance +0.12 m. So the smoothing adds no lag: a fit over each second follows a moving player.

**Why the smoothing is needed.** Without it, the camera fit's frame-to-frame jitter (up to about
0.5 m) is summed as running: every track's "top speed" reads 53 to 89 km/h. The one-second width
comes from the phone's own one-second speed and was set before this report was run. It was not
tuned to these numbers. The one change after measuring was to fix a cause the unit test found: a
plain average lagged at a track's ends (it read a straight 18 km/h run as 13.9), so the average
became a line fit, which equals it inside a track.

## What this does not show

- **Ten seconds is too short for a heat map.** A player crosses 2 or 3 of the 12 x 8 cells. Speed
  now is meaningful; top speed and distance cover at most ten seconds and say so. A longer
  tracked clip is needed before the heat map means anything.
- **Some tracks are not one player.**
  - `h-t3` is on average 11 m from the nearest home player, so it is likely a fragment of someone
    else (a referee, or a kit misread).
  - `a-t10` (1.6 m) and `a-t15` (2.6 m) probably switch between players during a crossing.
  - Several true players are split over two tracks (`h10` over three).
- **One clip, so the result is not general.**
- **Kickoffs.** A reset inside a tracked clip would be read as running; the tracker does not
  detect kickoffs (`restarts` is empty).
