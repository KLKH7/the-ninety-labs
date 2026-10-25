// On-screen graphics drawn on the footage: detections, the lower third, the fact-checked insight.

import type { Cue, FrameDetections } from "./bundle";

const EASE_S = 0.3; // graphics slide and fade in over this long, unless motion is reduced
// Draw what the scorer counts as a detection: its 0.5 threshold (docs/eval/vision-report-v1.md).
const MIN_SCORE = 0.5;

const KIND_LABEL: Record<string, string> = {
  pass_arc: "PASS",
  shot_speed: "SHOT",
  speed_badge: "SPEED",
  player_tag: "PLAYER",
  insight: "INSIGHT",
  recap: "RECAP",
  audio_description: "DESCRIBED",
};

const FONT = 'system-ui, -apple-system, "Segoe UI", Roboto, sans-serif';
const INK = "#ffffff";
const PANEL = "rgba(0, 0, 0, 0.82)";
const ACCENT = "#ffffff"; // verified: strict Apple, no accent colour (the words say which)
const TAG = "rgba(235, 235, 245, 0.6)"; // unverified, and the kind label's pill

export interface DrawOptions {
  t: number;
  reduceMotion: boolean;
}

/** 0 -> 1 as a cue comes in, 1 -> 0 as it goes out; always 1 with reduced motion. */
function presence(cue: Cue, t: number, reduceMotion: boolean): number {
  if (reduceMotion) return 1;
  const p = Math.min(1, (t - cue.t_in) / EASE_S, (cue.t_out - t) / EASE_S);
  return Math.max(0, p);
}

function roundRect(ctx: CanvasRenderingContext2D, x: number, y: number, w: number, h: number, r: number) {
  ctx.beginPath();
  ctx.roundRect(x, y, w, h, r);
  ctx.fill();
}

function wrap(ctx: CanvasRenderingContext2D, text: string, width: number): string[] {
  const lines: string[] = [];
  let line = "";
  for (const word of text.split(/\s+/)) {
    const next = line ? `${line} ${word}` : word;
    if (line && ctx.measureText(next).width > width) {
      lines.push(line);
      line = word;
    } else line = next;
  }
  if (line) lines.push(line);
  return lines;
}

export function drawDetections(ctx: CanvasRenderingContext2D, frame: FrameDetections | undefined) {
  if (!frame) return;
  ctx.save();
  ctx.lineWidth = 2;
  for (const d of frame.detections) {
    const [x0, y0, x1, y1] = d.bbox;
    if (d.cls === "player" && d.score >= MIN_SCORE) {
      // Corner brackets: they mark a player without boxing the footage in.
      const w = x1 - x0, h = y1 - y0, c = Math.min(8, w / 3, h / 3);
      ctx.strokeStyle = "rgba(255,255,255,0.75)";
      ctx.beginPath();
      for (const [x, y, dx, dy] of [[x0, y0, 1, 1], [x1, y0, -1, 1], [x0, y1, 1, -1], [x1, y1, -1, -1]]) {
        ctx.moveTo(x + dx * c, y);
        ctx.lineTo(x, y);
        ctx.lineTo(x, y + dy * c);
      }
      ctx.stroke();
    } else if (d.cls === "ball" && d.score >= MIN_SCORE) {
      ctx.strokeStyle = TAG;
      ctx.beginPath();
      ctx.arc((x0 + x1) / 2, (y0 + y1) / 2, Math.max(9, (x1 - x0) * 0.9), 0, Math.PI * 2);
      ctx.stroke();
    }
  }
  ctx.restore();
}

function drawLowerThird(ctx: CanvasRenderingContext2D, cue: Cue, a: number, W: number, H: number) {
  const x = 56 - (1 - a) * 40, y = H - 128, h = 64, pad = 20;
  ctx.save();
  ctx.globalAlpha = a;
  ctx.font = `700 18px ${FONT}`;
  const label = KIND_LABEL[cue.kind] ?? cue.kind.toUpperCase();
  const lw = ctx.measureText(label).width + pad * 2;
  ctx.font = `600 28px ${FONT}`;
  const tw = Math.min(ctx.measureText(cue.text).width, W - x - lw - 120) + pad * 2;
  ctx.fillStyle = INK; // the kind's label: a white pill, black type
  roundRect(ctx, x, y, lw, h, 6);
  ctx.fillStyle = PANEL;
  roundRect(ctx, x + lw, y, tw, h, 6);
  ctx.fillStyle = "#000";
  ctx.font = `700 18px ${FONT}`;
  ctx.textBaseline = "middle";
  ctx.fillText(label, x + pad, y + h / 2);
  ctx.fillStyle = INK;
  ctx.font = `600 28px ${FONT}`;
  ctx.fillText(cue.text, x + lw + pad, y + h / 2, tw - pad * 2);
  ctx.restore();
}

function drawInsight(ctx: CanvasRenderingContext2D, cue: Cue, a: number, W: number) {
  const w = 440, pad = 22, x = W - w - 40 + (1 - a) * 40, y = 40;
  ctx.save();
  ctx.globalAlpha = a;
  ctx.font = `600 26px ${FONT}`;
  const lines = wrap(ctx, cue.text, w - pad * 2);
  const h = 58 + lines.length * 34 + pad;
  ctx.fillStyle = PANEL;
  roundRect(ctx, x, y, w, h, 10);
  ctx.fillStyle = cue.verified ? ACCENT : TAG;
  roundRect(ctx, x, y, 6, h, 3);
  ctx.font = `700 16px ${FONT}`;
  ctx.textBaseline = "top";
  const label = cue.verified ? "✓ FACT-CHECKED" : "UNVERIFIED";
  ctx.fillText(cue.fallback ? `${label} · FALLBACK` : label, x + pad, y + pad);
  ctx.fillStyle = INK;
  ctx.font = `600 26px ${FONT}`;
  lines.forEach((line, i) => ctx.fillText(line, x + pad, y + 54 + i * 34));
  ctx.restore();
}

function drawTag(ctx: CanvasRenderingContext2D, cue: Cue, a: number) {
  if (!cue.anchor) return;
  const { px, py } = cue.anchor;
  ctx.save();
  ctx.globalAlpha = a;
  ctx.font = `700 20px ${FONT}`;
  const w = ctx.measureText(cue.text).width + 20;
  ctx.fillStyle = PANEL;
  roundRect(ctx, px - w / 2, py - 46, w, 30, 6);
  ctx.fillStyle = INK;
  ctx.textBaseline = "middle";
  ctx.fillText(cue.text, px - w / 2 + 10, py - 31);
  ctx.restore();
}

/** The spoken description as a large caption for low-vision fans, sitting across the frame
 * where the sound is (its `pan`), never off the edge. */
function drawCaption(ctx: CanvasRenderingContext2D, cue: Cue, a: number, W: number, H: number) {
  const pad = 24, size = Math.round(H / 18);
  ctx.save();
  ctx.globalAlpha = a;
  ctx.font = `700 ${size}px ${FONT}`;
  const lines = wrap(ctx, cue.text, W * 0.6);
  const w = Math.max(...lines.map((l) => ctx.measureText(l).width)) + pad * 2;
  const h = lines.length * size * 1.25 + pad * 1.5;
  const centre = W / 2 + (cue.pan ?? 0) * (W / 2 - w / 2 - 40);
  const x = Math.max(40, Math.min(W - w - 40, centre - w / 2));
  const y = H - h - 48;
  ctx.fillStyle = "rgba(0, 0, 0, 0.9)";
  roundRect(ctx, x, y, w, h, 10);
  ctx.fillStyle = cue.verified ? ACCENT : TAG;
  roundRect(ctx, x, y, w, 6, 3);
  ctx.fillStyle = INK;
  ctx.textBaseline = "top";
  lines.forEach((line, i) => ctx.fillText(line, x + pad, y + pad * 0.9 + i * size * 1.25));
  ctx.restore();
}

/** A small badge, top left, while a cue on air is a fallback: says what failed, so a viewer knows
 * the template graphic is standing in for an explanation that did not pass, or come. */
function drawFallback(ctx: CanvasRenderingContext2D, why: string, a: number) {
  const text = `FALLBACK · ${why.toUpperCase()}`;
  ctx.save();
  ctx.globalAlpha = a;
  ctx.font = `700 16px ${FONT}`;
  const w = ctx.measureText(text).width + 24;
  ctx.fillStyle = PANEL;
  roundRect(ctx, 40, 40, w, 30, 6);
  ctx.fillStyle = TAG;
  roundRect(ctx, 40, 40, 5, 30, 3);
  ctx.textBaseline = "middle";
  ctx.fillText(text, 54, 55);
  ctx.restore();
}

export function drawCues(ctx: CanvasRenderingContext2D, cues: Cue[], o: DrawOptions) {
  const { width: W, height: H } = ctx.canvas;
  for (const cue of cues) {
    const a = presence(cue, o.t, o.reduceMotion);
    if (cue.anchor) drawTag(ctx, cue, a);
    else if (cue.kind === "audio_description") drawCaption(ctx, cue, a, W, H);
    else if (cue.slot === "top_right") drawInsight(ctx, cue, a, W);
    else drawLowerThird(ctx, cue, a, W, H);
  }
  const fallback = cues.find((c) => c.fallback && c.kind !== "insight");
  if (fallback) drawFallback(ctx, fallback.fallback!, presence(fallback, o.t, o.reduceMotion));
}
