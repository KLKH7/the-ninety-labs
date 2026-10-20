# web/phone: the phone companion

The second screen ([ARCHITECTURE.md](../../docs/ARCHITECTURE.md), stage Personalize). The phone
pairs with the laptop's broadcast, then shows:

- a **minimap** in step with the laptop's clock (within 0.2 s, one frame of the 5 fps feed;
  `src/clock.ts`), with the dots gliding between frames;
- a **player card** for the player tapped (or picked from the list, for a screen reader): speed
  now, top speed, distance and a heat map, each computed by code (`ninety/intel/window.py`);
- a **wind map**: particles drifting through each team's mean velocity over the last 30 s
  (`src/wind.ts`). It is first in the cut order, so it loads only when turned on and stands alone;
- **questions**, suggested or typed, answered by the API (`POST /api/ask`): the question goes as
  data, every number is a cited fact, and each answer's evidence is one tap away.

The laptop side is the viewer's "Connect your phone" panel (`web/viewer/src/companion.ts`): it asks
the API for a 6-character code, shows it with a QR code of `phone/?code=…&clip=…`, and sends its
clock to the room about once a second and on every play, pause and seek.

## Ground truth never reaches the screen

Every positional payload passes `guarded` (`src/feed.ts`): anything not labelled `source: tracked`
throws, and the phone shows only the synced clock and why. The API's stand-in mode serves the
simulator's positions as `source: truth`, so against it the phone draws nothing. That is the
rule (AGENTS.md: the answer key is for training and grading only), and `tests/test_phone.py`
proves it against the API itself and against the mock relabelled as truth.

## Tracked positions for the demo

The phone's real data is the video's own: `tests/fixtures/tracked-seed900001.jsonl`, built from
the M1 clip's observations by `ninety/vision/tracked_frames.py` (tracks, teams, a one-second line
fit against the camera fit's jitter), with no answer key. Graded offline in
[companion-tracked.md](../../docs/eval/companion-tracked.md): speed now within 0.6 km/h (median),
top speed within 1.9 km/h. The tracker reads no shirt numbers, so tracked players are `h-t12`,
shown as "Home player · track 12". The API serves this file once #145 accepts those ids.

## Run it

```bash
npm ci --prefix web/phone
npm run dev --prefix web/phone            # http://localhost:5173/mock-laptop.html, then "Open the phone"
```

`?mock=1` reads the mock feed: positions from a formula in `mock/make_mock.py`, not from the
simulator, so they are nobody's ground truth; the page says "Mock data" on every screen. The mock
laptop page (`mock-laptop.html`) plays a clock and relays it to phones in the same browser.

Against the API (`/api` is proxied to port 8000):

```bash
NINETY_COMPANION=standin uv run uvicorn ninety.api.app:app --port 8000
```

Tests: `npm run build --prefix web/phone && npm run build --prefix web/viewer`, then
`NINETY_REQUIRE_PHONE=1 uv run pytest tests/test_phone.py`.
