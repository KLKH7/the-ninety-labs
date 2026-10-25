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

### Amendment (Oct 23, before any clip of run tactical1 was read)

**Where the clips render.** RunPod had no 48 GB card with 32 or more vCPU. Kian took an RTX PRO 6000 (96 GB VRAM, 13.6
CPUs by the pod's cgroup quota), which is too few CPUs to render the test set in software GL
alongside the GPU renders. So:

- **Training (120) and validation (24)** render on that RTX PRO 6000 (its GL check reports "NVIDIA
  RTX PRO 6000 Blackwell Server Edition" through ANGLE on Vulkan) at GL=gpu, 10 workers. Ten fit
  the 13.6-CPU quota because throughput scaled almost linearly with workers (45.3 clips an hour at
  2 workers, 222.8 at 10, in the pod's run logs): 4.9 times the rate
  for 5 times the workers, so the workers were not contending for CPU. Before
  the first dataset clip, the pod checks that it renders on the GPU and is deterministic: seed 3
  rendered twice in fresh browsers, every file of the clip and its views byte-identical. Every
  image folder is scanned for black frames (an image under a fifth of its folder's median size).
  A clip lost that way is rendered once more, as the plan's checks allow.
- **Test (30)** renders on the maintainer's Mac in software GL (SwiftShader), one clip at a time,
  at the same commit `6ea8e37` with the same driver (sha256 `2ad87ead…`), as every test set so far.

**Reproducibility.** GPU-rendered pixels are reproducible on that pod, not bit-for-bit on another
GPU or driver. Positions, events, the camera matrices and the keypoints are the engine's and the
renderer's arithmetic, so they are exact anywhere. The boxes, visibility and pixel counts are
measured from the same GPU's id pass, so they match that clip's own pixels, which is what a
detector trains on. They are not claimed to match a re-render on other hardware. The test set,
which every number is scored on, stays in software GL and is reproducible on any machine.

**What comes back to the Mac.** The pod keeps the 144 clips and fine-tunes in place, as v2freeze
did. Back to the Mac come:
- the checkpoint and its training manifest, metrics, config, machine record and log;
- the render manifest, with every file's sha256 and size, so the set is reproducible from
  `6ea8e37` plus the seeds, up to the GPU note above;
- the 24 validation clips, for scoring;
- 3 training clips, for contact sheets and the README.

Each file is checked against the pod's `SHA256SUMS`. No credential goes to the pod.

**Clips the checks excluded (the plan's rule: excluded, not replaced).**
- Training seeds 70 and 79, and validation seed 118, all failed `player_feet_in_boxes` in one
  tactical view.
- The cause was the check, not the drawing (lesson 212, PR #244). On a foot touch the foot is drawn
  at the ball, 0.85 to 0.9 m out. From the high lens that falls past a pixel slack sized for a
  side-on camera.
- They stay excluded: the fine-tune started without them (Coordinator). Validation therefore has
  23 seeds.
- Test clips 900004 and 900030 failed the same check in tac-r. Both were re-checked with #244's
  check after it merged (main affc4fe), before any test score was read: both still fail, so both
  stay excluded and the test set is **28 clips**. Their failure is the other kind (a far-side
  runner's box sitting above his ground point). No training clip shows that kind, so it is
  undiagnosed: the test clips' labels were not read.

**The run (Oct 23):**
- **Renders:** 141 of 144 training and validation clips passed. Seeds 70, 79 and 118 are excluded
  above. 28 of 30 test clips passed.
- **Fine-tune:** ours-tactical trained 20:27 to 21:41 UTC. All 8 epochs ran, with no early stop and
  the cap not reached. Training used 118 clips and 39,338 tiles, validated on 23 seeds. The best
  validation effective mAP was 0.626, at epoch 6.
- **Checkpoint:** sha256 `d7b6f0be8a2e3e75015d8545cd10596ac17d9c8b2477eb21aa57556498ac5efb`. It was
  copied back to the Mac and checked against the pod's SHA256SUMS and its training manifest.
- **Render manifest:** sha256 `07e76766…`.
- **Pod:** about 2.6 h, about $6.50. Nothing was scored yet.

**The tile export.** `scripts/finetune-tactical-on-pod.sh` ran #230's `coco_export --tiles` from
the render commit's folder. `python -m` puts the working directory first on the path, so it loaded
the render commit's own `coco_export`, which has no `--tiles`, and stopped before training. On the
pod, and here, it now runs from `$WORK/tiles`. Nothing was trained before the fix.
