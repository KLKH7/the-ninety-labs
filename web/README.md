# web

Viewer and broadcast renderer (three.js).

## `web/viewer`: the viewer

Plays one clip with on-screen graphics drawn on the footage from `overlay_cue` records, a persona
switch (casual / analyst) and the agent trace: each claim the Analyst drafted and the
Fact-checker's verdict. It reads only a bundle written by `ninety-e2e`
([ninety/e2e.py](../ninety/e2e.py)), which runs the whole chain on one clip with no Azure:

```bash
uv run ninety-e2e runs/test-frozen-cca498c/test/seed900001 --out runs/e2e/seed900001 --plant \
    --tracked tests/fixtures/tracked-seed900001.json --observations tests/fixtures/observations-seed900001.jsonl
npm ci --prefix web/viewer
npm run dev --prefix web/viewer          # http://localhost:5173, bundle from runs/e2e/seed900001
NINETY_BUNDLE=runs/e2e/other npm run dev --prefix web/viewer    # another bundle
npm run build --prefix web/viewer        # static site in web/viewer/dist; open it with ?bundle=<url>
```

| Stage | In the bundle | Today |
|---|---|---|
| Ingest | `detections.jsonl` | ours-v2's committed run on the frozen test set (`--detect live --weights W` runs RF-DETR) |
| Interpret | `events.jsonl`, `facts.json` | detected events (`ninety/match/detected.py`: source vision, with a confidence; ground truth refused): R3's file for the clip, or until it lands R4's hand-written stand-in, named on screen; `--demo` refuses the stand-in. Stats from `ninety/intel/stats.py` |
| Explain + Render | `trace.json`, `cues.jsonl` | R4's live path (`ninety/agents/live.py`), the one place cues are built: template cues for confident passes and shots, the Analyst → Fact-checker workflow (offline Analyst, or `--replay` a Foundry recording), and the verified claim as an insight cue; unsure detections are held |
| Personalize | persona in each cue | casual, analyst and audio description |
| Radar | `radar.json` | with `--tracked` and `--observations` (vision's `tracked.json` and `observations.jsonl` for the clip, as `ninety/vision/live_job.py` writes them): `ninety/radar.py` adds, per frame, whether vision found the ball and the ground the broadcast picture covers, from vision's own camera fit. Positions not `source: tracked` are refused, here and in the viewer |
| Describe | `audio.json`, `description.vtt`, `audio` cues | the Describer (`ninety/speech/describe.py`): one spoken line per confident pass, shot, goal, tackle or interception, or the verified claim in its event's place; every line passes the fact-checker's code half, starts within 2 s of its event and never overlaps the last; `pan` from the ball's pitch x. Timing is estimated offline; `--speech azure` synthesises each line through Azure AI Speech and measures it (off by default) |

Footage is `video.webm` (VP9, when ffmpeg is installed) or the JPEG frames (`--frames`).

**The radar** beside the video (`src/radar.ts`) draws the whole pitch from above, as the main camera
sees it (its touchline at the bottom): every tracked player in team colours, the ball, and the
broadcast picture's footprint, so a viewer sees what the main feed shows against the whole pitch.
It follows the clip's timeline across cuts (`ninety/match/timeline.py`) and never draws a player
between sightings on either side of a cut. A player or ball not seen in the frame on screen
(placed between sightings at most the tracker's 25-frame gap apart, or a ball the tracked file
filled in) is drawn as a hollow, fainter ring; a footprint held from an earlier frame is dashed.
Shirt numbers are drawn once the tracker reads them; today it does not. <kbd>M</kbd> hides it; it
is described to screen readers at most once a second; the ball's trail and the glide between
frames stop under reduced motion. Today the tracked players are only those the broadcast camera
shows; the whole-pitch tactical camera will fill in the rest.

Accessibility from day one: every control works from the keyboard (<kbd>Space</kbd> play,
<kbd>←</kbd>/<kbd>→</kbd> one second, <kbd>,</kbd>/<kbd>.</kbd> one frame, <kbd>1</kbd>/<kbd>2</kbd>/<kbd>3</kbd>
persona, <kbd>D</kbd> detections, <kbd>M</kbd> radar), the persona switch is an ARIA radio group, what is on air is
announced in a polite live region and named on the graphics canvas, and graphics stop sliding and
fading when the system asks for reduced motion (or the "Reduce motion" box is ticked).


**Audio description** (persona <kbd>3</kbd>) is for blind and low-vision fans. Each line is said
once, as the clock passes its start; a seek or a pause stops the voice, so nothing is said late.
With synthesised audio in the bundle the line itself is placed left to right where the play is;
without it, a short tone placed by `pan` says where, and the browser's own voice says the line.
<kbd>V</kbd> turns the voice off (the live region then speaks the lines to a screen reader
instead; with the voice on it stays quiet, so nothing is said twice), <kbd>R</kbd> repeats the
last line, and the line is drawn as a large caption across the frame where the sound is.
`tests/test_viewer.py` and `tests/test_radar.py` drive all of this in headless Chromium.

## `web/render`: broadcast renderer

`render/index.html` and `render/render.js` draw one frame at a time for `ninety/render/clip.py`,
which drives them through Playwright in headless Chromium. Python sends the camera and every body
part in world metres; the page draws them, then renders an object-id pass to count each player's
and the ball's pixels (alone and in the full scene). Those counts become the boxes and visibility
in `frames.jsonl`. Design and trade-offs: [decision 0001](../docs/decisions/0001-synthetic-data.md);
rules: [render guide](../docs/guides/broadcast-render.md).

```bash
npm ci --prefix web                      # three.js, pinned in package-lock.json
uv run playwright install chromium       # once
uv run ninety-render --seed 7 --seconds 10 --out runs/clip7
uv run ninety-render --seed 7 --out runs/clip7-hard --set kit_contrast=low --set occlusion=crowded
uv run ninety-dataset --split train --count 20   # training clips, seeds 1..20
uv run ninety-dataset --split test               # fixed test set, seeds 900001..900005, no overrides
uv run ninety-render-check runs/clip7            # render guide section 6 checks
```

Knobs (`--set key=value`), all recorded in `clip.json`:

| Knob | Values | Status |
|---|---|---|
| `lighting` | `day` | built; `dusk`, `night` (four floodlight shadows) and `overcast` are drawn but not yet broadcast quality, so they are planned and refused |
| `sun_azimuth_deg`, `sun_elevation_deg` | degrees | built |
| `kit_contrast` | `normal`, `low` (similar luminance: the team-confusion case); drawn `low` for 30% of seeds | built |
| `occlusion` | `natural`, `crowded` (picks the window where a player most often stands between the camera and the ball); drawn `crowded` for 30% of seeds | built |
| `camera.height_m`, `camera.back_m`, `camera.offset_x_m` | gantry position | built |
| `camera.half_width_m`, `camera.box_half_width_m` | zoom in open play and in the box | built |
| `camera.pan_lag_s`, `camera.lead_s`, `camera.shake_m` | follow filter and jitter | built |
| `motion_blur` | shutter fraction; streak follows the pan | built |
| `noise`, `jpeg_quality` | sensor noise and compression | built |
| `grass_hue`, `stripe_width_m`, `wear`, `stand_color`, `crowd_density` | look | built |
| `weather` | `clear` | built; `overcast` and `rain` (wet grass, sheen, streaks) are planned and refused, for the same reason |
| `camera_cut=true` | cut to the far stand, or high behind the goal when the ball is in that penalty area | built |
| `home_pattern`, `away_pattern` | `solid`, `stripes`, `hoops`, `sash`, `halves` (goalkeepers stay solid) | built |

Without `--gpu`, Chromium uses software GL (SwiftShader), so a seed gives the same pixels and
labels on the same Chromium build. That runs at 0.47 to 0.61 s per 720p frame on 4 CPU cores
(sun shadows are the slow part), so about 2 to 2.5 minutes per 10-second clip.
