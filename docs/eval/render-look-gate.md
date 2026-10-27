# Vision gate for the broadcast look (renderer 0.5.20)

The broadcast look (`web/render/look.js`) changes the light and colour of the footage our frozen
detector watches in the demo. The detector is not retrained for it, so the look had to leave
detection where it was.

**Pre-registered, before any number was seen:** adopt the look only if neither player recall nor
ball recall drops by more than 2 points against the same windows rendered at main. A feature that
breaks it is dropped, never fitted around, and the detector is never retrained for it.

## Method

- **Windows:** validation seeds 910001 and 910002 (never trained on), two 20 s windows each: the
  seed's own window (`a`) and one from 600 s (`b`). 2,000 frames per arm.
- **Render:** both arms with the demo's dressing (`stadium=broadcast`, `kit_contrast=broadcast`, the
  demo kits), software GL (SwiftShader) on one pod. Old = main 6b275a4b; new = 1f5b62d2 (this
  branch; later commits only add metadata, docs and the version, no pixel change). Python was the
  same bytes in both, so the only difference is `web/render`.
- **Detector:** ours-freeze (checkpoint sha256 0fafe959…), `python -m ninety.vision.detect`.
- **Score:** `python -m ninety.eval.vision_score` (threshold 0.5, players IoU 0.5, ball within 5 px).

## Result: passes

| clip | class | old recall | new recall | Δ pts | old precision | new precision | Δ pts |
|---|---|---|---|---|---|---|---|
| v1a | player | 0.995 | 0.997 | +0.2 | 0.999 | 0.999 | +0.1 |
| v1a | ball | 0.570 | 0.556 | -1.4 | 0.993 | 0.945 | -4.8 |
| v1b | player | 0.991 | 0.994 | +0.3 | 0.997 | 0.998 | +0.1 |
| v1b | ball | 0.702 | 0.720 | +1.8 | 0.983 | 0.973 | -1.0 |
| v2a | player | 0.995 | 0.995 | +0.0 | 0.998 | 0.999 | +0.0 |
| v2a | ball | 0.832 | 0.814 | -1.8 | 0.995 | 0.993 | -0.3 |
| v2b | player | 0.985 | 0.985 | +0.0 | 0.998 | 0.998 | -0.0 |
| v2b | ball | 0.796 | 0.810 | +1.4 | 0.985 | 0.978 | -0.7 |
| **pooled** | player | 0.991 | 0.992 | **+0.1** | 0.998 | 0.998 | +0.0 |
| **pooled** | ball | 0.725 | 0.725 | **+0.0** | 0.989 | 0.974 | -1.5 |

Players are unchanged (+0.1 points recall pooled). Ball recall is unchanged pooled (+0.0); no clip
moved more than 1.8 points either way.

**Not in the gate, reported anyway:** ball precision fell 1.5 points pooled (false balls 16 → 38 in
2,000 frames). 18 of the new arm's 38 are in the top third of the picture: blurred lettering on the
advertising boards and fans during fast pans, where the old arm had 5. None is on the pitch near
play. The live path's ball tracking sees these as one-frame strays; this is the cost to watch if the
demo's ball track shows jumps to the boards.

Logs, per-clip score reports and the 15 s before/after are kept outside the repo (the notes of
the session that ran it).
