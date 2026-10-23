# web/phone: the phone companion

The second screen ([ARCHITECTURE.md](../../docs/ARCHITECTURE.md), stage Personalize), and the
product's main surface: the big screen shows only the broadcast, its graphics, the score and a QR
code; everything else is here. The phone pairs with the big screen, then has three tabs:

- **Radar**: the viewer's own radar (`web/viewer/src/radar.ts`): every tracked player, the ball,
  the TV camera's footprint, estimated positions hollow, drawn the way up the TV shows it, within
  0.2 s of the big screen's clock (`src/clock.ts`) and across its cuts (it reads the bundle's
  segments, named by the QR code). Tap a player for a **player card**: speed now, top speed,
  distance and a heat map, each computed by code (`ninety/intel/window.py`). The **wind map**
  (`src/wind.ts`) is first in the cut order, so it loads only when turned on and stands alone;
- **Ask**: questions, suggested or typed, answered by the API (`POST /api/ask`): the question goes
  as data, every number is a cited fact, the evidence is one tap away, and an answer with a
  `visual` draws its picture (`src/visual.ts`): an overload, a line-breaking pass, pass options,
  a team's shape or the wind map, from the visual's own positions and numbers, or nothing when one
  is missing;
- **Insights**: hidden-stat cards (`GET /api/insights/{clip}?t_to=`) up to the big screen's clock,
  newest first, each with its picture and "Why?", which asks the Companion.

Clubs are named from the codes on the clip's scorebug (`web/viewer/src/teams.ts`); a player by the
name or role an answer carries, otherwise by club and shirt or track ("Fenwick player 12").

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

The phone's real data is the video's own: `tests/fixtures/tracked-seed900001.json`, built from
the M1 clip's observations by `ninety/vision/tracked_frames.py` (tracks, teams, a one-second line
fit against the camera fit's jitter), with no answer key. Graded offline in
[companion-tracked.md](../../docs/eval/companion-tracked.md): speed now within 0.6 km/h (median),
top speed within 1.5 km/h. The tracker reads no shirt numbers, so tracked players are `h-t12`,
shown as "Home player · track 12". The API serves this file once #145 accepts those ids.

## Run it

```bash
npm ci --prefix web/phone
npm run dev --prefix web/phone            # http://localhost:5173/mock-laptop.html, then "Open the phone"
```

The mock is in the dev server and the dev bundle only (`npm run build:mock`, into `dist-mock/`);
`npm run build`, what ships, leaves it out. There, `?mock=1` reads the mock feed: positions from a formula in `mock/make_mock.py`, not from the
simulator, so they are nobody's ground truth. They are labelled `source: mock`, which the phone accepts only from the mock feed, and the page says "Mock data" on every screen. The mock
laptop page (`mock-laptop.html`) plays a clock and relays it to phones in the same browser.

Against the API (`/api` is proxied to port 8000):

```bash
NINETY_COMPANION=standin uv run uvicorn ninety.api.app:app --port 8000
```

Tests: `npm run build --prefix web/phone && npm run build:mock --prefix web/phone && npm run build --prefix web/viewer`, then
`NINETY_REQUIRE_PHONE=1 uv run pytest tests/test_phone.py tests/test_phone_companion.py`.
