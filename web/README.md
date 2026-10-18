# web

Viewer and broadcast renderer (three.js). The viewer is planned.

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
