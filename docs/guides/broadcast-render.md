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

## 2. Look like television, not a video game

Real broadcast footage has properties detectors depend on. Match them:

| Property | Broadcast reality | Do |
|---|---|---|
| Resolution | 1280x720 or 1920x1080, 25 fps | Render 1280x720 at 25 fps by default |
| Main camera | High in the stand near halfway, about 15 to 25 m up and 30 to 40 m back | Place it there; never a top-down or behind-goal main view |
| Framing | Follows the ball with lag, keeps 8 to 15 players in shot | Smooth pan with a lag filter; zoom in on set pieces and the box |
| Motion | Fast pans blur the image | Motion blur proportional to pan speed |
| Players | About 30 to 120 px tall in the main view; far side ones small | Keep scale realistic; do not zoom so far that every player is huge |
| Ball | 5 to 15 px, often blurred or hidden | Keep it small; let it be occluded |
| Light | Stadium floodlights cast 2 to 4 soft shadows per player; or daylight with one hard shadow | Both, randomized |
| Grass | Mowing stripes, wear near goals and centre | Striped texture, wear map |
| Image | Compression blocks, slight noise, sharpening halos | Add mild noise and JPEG/H.264-style compression at export |
| Other | Scorebug, crowd, advertising boards | A generic scorebug and boards with **made-up brands only** |
| Dead balls | The director cuts away from the wait and back to the restart | Hold the stoppage, then cut to the restart being set (`ninety/render/edit.py`); record each cut in `meta.json`, never cut over an event |

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
- camera: height, distance, FOV, pan lag, shake; occasional cut to a second angle
- stadium: stand colour, crowd density, board colours

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
