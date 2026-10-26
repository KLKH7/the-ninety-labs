# Guide: broadcast render

Synthetic images that are worth detecting. Applies to anything that renders the synthetic video
(`web/render`) or generates images.

The renderer turns a `ninety-sim` run into broadcast-style video. Its images are the input to
automatic event detection, and the judges score "creativity and optimized synthetic data
creation". A render is good when (1) a detector trained on real football works on it, (2) its
ground truth is exact, and (3) it can produce hard cases on demand. Pretty is not the bar;
those three are.

Read first: `docs/BRIEF.md`, `docs/ARCHITECTURE.md`, `schemas/frame.schema.json`.

## 1. Ground truth comes out of the renderer, never from guessing

Every frame writes, next to the image:

- the **camera**: position, rotation, focal length / FOV, image size, and the 3x4 projection
  matrix, so any pitch point maps exactly to a pixel;
- per player and the ball: **2D bounding box in pixels**, pitch position in metres, team, player
  id, and **visibility** (fraction of the box not occluded, computed by the renderer, not
  estimated);
- **pitch keypoints in pixels** (line intersections, penalty spots, centre) for camera-to-pitch
  mapping, with a visible flag;
- the seed and every randomized parameter used, so any frame can be regenerated exactly.

A render without this is not usable for scoring. Store it per clip as `frames.jsonl` with one row
per frame; keep the format compact (it was 180 MB for a 90-minute match as plain JSON lines).

**Tactical views.** `--views tactical` also films the clip from two fixed lenses side by side on the
main gantry at halfway (`camera.tactical_views`: one point, nominally 28 m up and 32 m back, each
1920x1080 covering one half of the pitch plus 2.5 m past halfway, the lens solved so the half fits
with a 1% margin; GROUNDING V7). They are vision's input for whole-pitch context; the broadcast stays
the viewer's feed. Each view is written as a complete clip under `views/tac-l/` and `views/tac-r/`
from the same scene and frame spec as the broadcast, in a browser page of its own, with no
graphics and no motion blur (the lens never moves). Asking for views never changes the broadcast:
its images and labels stay byte-identical, and the mount is drawn for every seed after all its
other draws. `ninety-render-check` fails a clip unless every view films the broadcast's world frame
for frame (`checks.streams_agree`).

## 2. Look like television, not a video game

Real broadcast footage has properties detectors depend on. Match them:

| Property | Broadcast reality | Do |
|---|---|---|
| Resolution | 1280x720 or 1920x1080, 25 fps | Render 1280x720 at 25 fps by default |
| Main camera | High in the stand near halfway, about 15 to 25 m up and 30 to 40 m back | Place it there; never a top-down or behind-goal main view |
| Framing | Follows the ball with lag, keeps 8 to 15 players in shot; the pitch fills most of the picture, the stands a band across the top | Aim at the play on the grass (the ball pulled toward the players around it) with a lens 18 m either side; hold still while the ball moves about one area; with play far off, tilt down along the line of sight so the stands stay within the top third; close up on the box without pumping; ease each pan and zoom; at least 85% of live frames well framed and 8 to 15 players in the median frame (`test_render_camera`) |
| Shots | One change of shot every 9 s on average, replays included (SoccerNet-v2, Deliège et al. 2021); live play from one side of the ground; the wide shot through every attack | The gantry in live play, a medium shot from beside it for a throw-in and for the restart after an edit cut, the low angle by the net after a goal; each shot held at least 4 s, none started within 4 s of an edit cut |
| Motion | Fast pans blur the image | Motion blur proportional to pan speed, sharpened after the smear (sharpening the unsmeared picture splits a pan's edges in two) |
| Players | About 30 to 120 px tall in the main view; far side ones small | Keep scale realistic; do not zoom so far that every player is huge |
| Ball | 5 to 15 px, often blurred or hidden | Keep it small; let it be occluded |
| Light | Stadium floodlights cast 2 to 4 soft shadows per player; or daylight with one hard shadow | Both, randomized |
| Grass | Mowing stripes, wear near goals and centre | Striped texture; wear is faint, paler turf that follows the stripes, never brown blotches |
| Image | Compression blocks, slight noise, sharpening halos | Add mild noise and JPEG/H.264-style compression at export |
| Other | Scorebug, crowd, advertising boards | A generic scorebug and boards with **made-up brands only** |
| Fouls | The whistle goes, play stops, the fouler often owns up with a raised hand and team-mates turn to the man down | The engine already stops play (players walk and stand until the restart); the renderer draws the fall (`fall`, `fall_dir`), the fouler's hand up and the fouled side's three nearest turning their heads to him for 2 s from the foul frame (*design*, `ninety/render/fouls.py`; heads only, since a body faces the engine's `heading`), and the mp4 carries a whistle synthesised in `ninety/render/audio.py` at each foul the picture shows |
| Dead balls | The director cuts away from the wait (replays and close-ups, about 7 s a shot) and back to the restart | Broadcast clips only (`ninety-render`; datasets and test sets show every frame): hold the stoppage at least 4 s, cut, come back closed up on the restart 6 s before it and ease out to the wide shot for the kick (`ninety/render/edit.py`); cut only a dead ball whose stoppage and restart the clip shows, record each cut in `meta.json`, never cut over an event |

## 3. Randomize what varies between real matches

Pick per clip from a seeded range (domain randomization). This is what makes a detector trained
on renders work on real footage (SoccerSynth-Detection reports synthetic-only YOLO matching real
datasets and beating them on motion blur).

- kits: primary colour, secondary colour, pattern; the two teams must differ in colour and
  luminance; goalkeepers differ from both; referees in a third colour
- skin tone, hair, height and build across the full human range
- lighting: day, dusk, floodlit night; sun angle; shadow count and softness. **Day only for
  now**: dusk, night and overcast render, but not yet like broadcast footage, so `PLANNED` in
  `ninety/render/params.py` refuses them and every clip is a day clip (sun angle still varies)
- weather: clear, overcast, light rain (streaks and wet grass sheen). **Clear only for now**,
  for the same reason
- grass hue and stripe width; pitch wear
- camera: height, distance, FOV, pan lag, shake; occasional cut to the tighter lens beside the gantry
- stadium: stand colour, crowd density, board colours. `stadium=broadcast` dresses footage a viewer
  watches (the demo clip): a seated crowd in every stand in the teams' colours that jumps for a goal,
  the board ring closed at the corners with varied made-up adverts, a wall under each stand and an
  LED ribbon under each upper tier, grass on to the stands, and softer mowing. No seed draws it, so
  no dataset changes look. The crowd is scenery in the id pass: never labelled, and it hides
  a ball among the fans exactly where the picture does (`tests/test_render_stadium.py`)
- the broadcast look (`web/render/look.js`): a `stadium=broadcast` clip's broadcast stream, and only
  that, is lit and graded as television: a filmic (ACES) tone curve instead of a hard clip, fill light
  from a physical sky (three.js `Sky`), the crowd muted and in the roof's shade, haze on the scenery
  (never on a player or the ball), gentler sharpening and a warm-highlight grade. Light and colour
  only: no label moves, and nothing is drawn from the seed. Training, validation and test renders
  (`stadium=plain`) and the tactical views keep their pixels. Adopted after the vision gate in the
  pull request that added it: our frozen detector's player and ball recall on validation windows
  rendered both ways, within 2 points

Log every choice in the frame metadata. Never randomize something you cannot label.

## 4. Generate hard cases on purpose

The scoring step (`ninety/eval`) reports where detection fails. The renderer must be able to make
more of exactly that, by parameter:

| Failure | Knob |
|---|---|
| Ball lost in crowds | set pieces, corners, goalmouth scrambles: cluster players in the box |
| Missed small players | far-side play, wide FOV |
| ID switches | players crossing, similar positions, similar heights |
| Team confusion | low-contrast kits, floodlit colour cast |
| Blur misses | fast counter-attacks, fast pans, long switches of play |
| Camera-to-pitch mapping errors | tight zoom with few visible lines |

Each targeted round is recorded: which failure, which knob values, how many frames, and the
detector's score before and after on a **fixed, separate test set** (never the frames you just
generated). The before and after table is what goes in the README and the video.

## 5. Rules

- **No real clubs, players, kits, crests, sponsors or Premier League branding.** The rules forbid
  third-party trademarks in the video (rule 4.4) and require synthetic data (rule 4.7).
- **Deterministic by seed.** Same seed and parameters, same pixels and same metadata.
- **No AGPL dependencies** (see `CLAUDE.md`).
- **Assets must be licensed for reuse** (CC0, CC-BY with credit in `docs/ASSETS.md`, or made by us).

## 6. Check a render before calling it done

Run these and report the numbers, not an impression:

1. **Projection check:** project the ground-truth ball and player feet through the saved camera
   matrix; the error against the saved pixel boxes must be under 1 px.
2. **Off-the-shelf detector check:** run the pretrained player and ball detector on 200 frames
   with no fine-tuning. Report player and ball recall. If player recall is far below what the
   same detector gets on real broadcast footage, the render is not realistic enough yet; fix the
   look before training on it.
3. **Occlusion check:** the share of frames where the ball's visibility is under 0.5 should be
   non-zero. A render where the ball is always clearly visible is too easy.
4. **Determinism check:** render the same seed twice and diff the metadata (and a sample of
   images).
5. **Look at it:** export a 10-second clip and compare it side by side with real broadcast
   framing. Note what differs, then fix the biggest difference first.

## If the task is AI image generation instead

For pitch-deck images, thumbnails or the video end card (not training data): use original
scenes with no real clubs, players, kits, crests or stadium names; match the project's visual
style; and never use generated images as ground-truth training data, because they have no exact
labels.
