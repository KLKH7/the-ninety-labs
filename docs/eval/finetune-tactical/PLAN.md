# The tactical fine-tune: pre-registered plan

Status: **pre-registered, nothing rendered or trained.** Written Oct 22, before any clip of run
`tactical1` was rendered. A change after this commit is listed under "Deviations" with its date and
reason, before any result is read.

**Rubric:** Technological implementation. Vision watches the two fixed tactical views (renderer
0.5.15, docs/GROUNDING.md V7), not the ball-following broadcast. This run measures whether a
detector fine-tuned on those views finds more players and balls than the demo's detector does with
no tactical training, and where on the pitch.

## The data

[dataset-tactical.json](../dataset-tactical.json), rendered once on one RunPod pod:

| Split | Seeds | GL |
|---|---|---|
| Training (120) | 3–107, 111, 123–132, 2001–2004: the first 120 seeds of dataset v2's training list in its order, less v2's validation seeds, each with its v2 overrides (2001–2004 `occlusion=crowded`) | the pod's GPU |
| Validation (24) | 108–110, 112–122, 2041–2045 (`crowded`), 3041–3045 (`kit_contrast=low`): v2freeze's validation seeds exactly ([validation-set.json](../finetune-v2freeze/validation-set.json)) | the pod's GPU |
| Test (30) | 900001–900030, their own drawn parameters, no overrides | software GL (SwiftShader) on the pod's CPUs |

Every clip is 10 s, every frame, no dead-ball cut, with `--views tactical`. Only the views'
`views/tac-l/` and `views/tac-r/` folders are used here; the broadcast is not. A clip that fails
its checks is excluded and not replaced (dataset-tactical.json, `checks`).

## The run

| | |
|---|---|
| Model | RF-DETR Small (Apache-2.0), rfdetr 1.11.2, as every earlier run |
| Starts from | **ours-freeze**, sha256 `0fafe959ec2e08279e5741261ac4e639f2b87f0c11384a2d0e976dda6ef5d5e5`, the demo's detector |
| Name | **ours-tactical** |
| Images | Every 5th frame of each view, cut into the live path's tiles: `ninety/vision/tiles.py` and `coco_export --tiles` of PR #230 at **`f6254952438eb17181696c9fd76516bc30376266`**, so training sees exactly the tiles inference runs on. That is a 2x2 grid of 1056x594 tiles at x 0 and 864, y 0 and 486, with neighbours sharing 10% of the frame. Each label is clipped to its tile and kept when any part is inside. A tenth of the label-free tiles is kept, chosen by a fixed hash (`--empty-tiles 0.1`, the default). Crops are JPEG q95 with no chroma subsampling. About 120 clips x 2 views x 50 frames x 4 tiles, less most empty tiles |
| Config | [config.json](config.json): `finetune-v2freeze.json`'s settings (resolution 640, batch 4 x 4, lr 5e-5, encoder 7.5e-5, at most 8 epochs, early stopping with patience 3, seed 7, 8 loader workers) with a time cap |
| Time cap | **150 minutes of training.** At the cap the best validation checkpoint so far is the model, and its manifest says it was stopped. Expected 100 to 150 minutes: ours-freeze took 30 minutes for 12,250 images on a 4090, and this run has about 4 times as many |

## Scoring (on the Mac, after the copy-back)

Both models are scored on the same tiles with the same code: the live path's tiled detection and
merge (`tiles.merge` at the commit above). A box cut by an inner tile edge is dropped when an uncut
box of its class from another tile covers half of it; uncut duplicates at IoU 0.5 or more keep the
higher score. The scorer's rule is `vision_score.match` at threshold 0.5.

- **Validation:** the 24 validation clips' views, every 5th frame, ours-freeze and ours-tactical.
  ours-tactical becomes the tactical detector if its recall on balls and on players is each at
  least ours-freeze's.
- **Test set, once:** the 30 test clips' views, every 5th frame, at a commit that freezes the code
  before any detection. Each model is scored once, and every result is reported whatever it shows.
- **By pitch zone:** recall for balls and players, with Wilson 95% intervals, by the object's true
  pitch position. The pitch is cut into thirds along its length (x 0–35, 35–70, 70–105 m) and
  halves across it (near y 0–34, far 34–68 m), six zones; the far corners are the expected weak
  spot (about 27 px a player, 3 px a ball). An object is counted once per frame, in the view whose
  half holds it (`tac-l` for x < 52.5).
- **Coverage:** the share of on-pitch players and balls whose true position is inside some view's
  picture (the renderer's `views_see_the_ball` holds this at 100% for the ball below 2 m).

## Deviations

None yet.
