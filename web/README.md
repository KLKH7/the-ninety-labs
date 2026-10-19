# web

Viewer and broadcast renderer (three.js).

## `web/viewer`: the viewer

Plays one clip with on-screen graphics drawn on the footage from `overlay_cue` records, a persona
switch (casual / analyst) and the agent trace: each claim the Analyst drafted and the
Fact-checker's verdict. It reads only a bundle written by `ninety-e2e`
([ninety/e2e.py](../ninety/e2e.py)), which runs the whole chain on one clip with no Azure:

```bash
uv run ninety-e2e runs/test-frozen-cca498c/test/seed900001 --out runs/e2e/seed900001 --plant
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
| Personalize | persona in each cue | casual and analyst |

Footage is `video.webm` (VP9, when ffmpeg is installed) or the JPEG frames (`--frames`).

Accessibility from day one: every control works from the keyboard (<kbd>Space</kbd> play,
<kbd>←</kbd>/<kbd>→</kbd> one second, <kbd>,</kbd>/<kbd>.</kbd> one frame, <kbd>1</kbd>/<kbd>2</kbd>
persona, <kbd>D</kbd> detections), the persona switch is an ARIA radio group, what is on air is
announced in a polite live region and named on the graphics canvas, and graphics stop sliding and
fading when the system asks for reduced motion (or the "Reduce motion" box is ticked).
`tests/test_viewer.py` drives all of this in headless Chromium.

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
