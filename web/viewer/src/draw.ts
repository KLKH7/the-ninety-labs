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

const FONT = '-apple-system, BlinkMacSystemFont, "SF Pro Text", Inter, "Segoe UI", Roboto, sans-serif'; // style.css --g-font
const INK = "#ffffff";
const PANEL = "rgba(0, 0, 0, 0.82)";
/** The scorebug's and the match-stats card's own colours (style.css --g-bug, --g-tab), a touch
 * translucent: white type on them stays above 12:1 over any footage (WCAG AA asks 4.5:1). */
const BUG = "rgba(13, 14, 18, 0.9)";
const BUG_TAB = "rgba(28, 29, 34, 0.94)";
/** Broadcast sizes, in px at a 1920 by 1080 picture (as style.css --v): a slim lower third, the
 * type of a league's on-air graphics, not a subtitle wall (Kian, Oct 27). */
const CAPTION_PX = 28, INSIGHT_PX = 20, LABEL_PX = 13;
/** Title-safe: graphics stay inside the middle 90% of the picture (EBU R 95). */
const TITLE_SAFE = 0.05;
const ACCENT = "#ffffff"; // verified: strict Apple, no accent colour (the words say which)
const TAG = "rgba(235, 235, 245, 0.6)"; // unverified, and the kind label's pill

export interface DrawOptions {
  t: number;
  reduceMotion: boolean;
  /** Every cue on air, when `cues` leaves some to another layer (the big screen's lower third):
   * a fallback among them still gets its badge. */
  onAir?: Cue[];
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

/** A rounded panel with its check down the left edge, as the stats card's side bar, kept inside the corners. */
function panel(ctx: CanvasRenderingContext2D, x: number, y: number, w: number, h: number, r: number, edge: string, ew: number) {
  ctx.save();
  ctx.beginPath();
  ctx.roundRect(x, y, w, h, r);
  ctx.fill();
  ctx.clip();
  ctx.fillStyle = edge;
  ctx.fillRect(x, y, ew, h);
  ctx.restore();
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

/** A lower third reads as a sentence: its first letter capital ("a player plays a pass" → "A player…"). */
const sentence = (text: string) => text.charAt(0).toUpperCase() + text.slice(1);

function drawLowerThird(ctx: CanvasRenderingContext2D, cue: Cue, a: number, W: number, H: number) {
  const u = W / 1920, safe = W * TITLE_SAFE;
  const h = 46 * u, pad = 16 * u, x = safe - (1 - a) * 40 * u, y = H * (1 - TITLE_SAFE) - h - 24 * u;
  ctx.save();
  ctx.globalAlpha = a;
  ctx.font = `700 ${LABEL_PX * u}px ${FONT}`;
  const label = KIND_LABEL[cue.kind] ?? cue.kind.toUpperCase();
  const lw = ctx.measureText(label).width + pad * 2;
  ctx.font = `600 ${22 * u}px ${FONT}`;
  const tw = Math.min(ctx.measureText(cue.text).width, W - 2 * safe - lw - pad * 2) + pad * 2;
  ctx.fillStyle = BUG_TAB; // the kind's label: the bug's tab, its type quiet
  roundRect(ctx, x, y, lw + tw, h, 8 * u);
  ctx.fillStyle = BUG;
  roundRect(ctx, x + lw, y, tw, h, 8 * u);
  ctx.fillStyle = TAG;
  ctx.font = `700 ${LABEL_PX * u}px ${FONT}`;
  ctx.textBaseline = "middle";
  ctx.fillText(label, x + pad, y + h / 2);
  ctx.fillStyle = INK;
  ctx.font = `600 ${22 * u}px ${FONT}`;
  ctx.fillText(sentence(cue.text), x + lw + pad, y + h / 2, tw - pad * 2);
  ctx.restore();
}

/** The fact-checked insight, top right in title-safe, as the match-stats card: a dark header strip
 * (its check) over the line, two lines at most. */
function drawInsight(ctx: CanvasRenderingContext2D, cue: Cue, a: number, W: number, H: number) {
  const u = W / 1920, pad = 16 * u, size = INSIGHT_PX * u, head = 28 * u, lead = size * 1.3;
  ctx.save();
  ctx.globalAlpha = a;
  ctx.font = `600 ${size}px ${FONT}`;
  const lines = wrap(ctx, cue.text, 520 * u);
  const w = Math.max(...lines.map((l) => ctx.measureText(l).width)) + pad * 2;
  const h = head + lines.length * lead + pad;
  const x = W * (1 - TITLE_SAFE) - w + (1 - a) * 40 * u, y = H * (24 / 720); // the bug's own top line (render.js layoutBug)
  ctx.fillStyle = BUG;
  panel(ctx, x, y, w, h, 8 * u, cue.verified ? ACCENT : TAG, 4 * u);
  ctx.save();
  ctx.beginPath();
  ctx.roundRect(x, y, w, h, 8 * u);
  ctx.clip();
  ctx.fillStyle = BUG_TAB;
  ctx.fillRect(x + 4 * u, y, w, head);
  ctx.restore();
  ctx.fillStyle = cue.verified ? ACCENT : TAG;
  ctx.font = `700 ${LABEL_PX * u}px ${FONT}`;
  ctx.textBaseline = "middle";
  const label = cue.verified ? "✓ FACT-CHECKED" : "UNVERIFIED";
  ctx.fillText(cue.fallback ? `${label} · FALLBACK` : label, x + pad, y + head / 2);
  ctx.fillStyle = INK;
  ctx.font = `600 ${size}px ${FONT}`;
  ctx.textBaseline = "top";
  lines.forEach((line, i) => ctx.fillText(line, x + pad, y + head + pad * 0.5 + i * lead));
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

export interface CaptionBox {
  x: number; y: number; w: number; h: number;
  size: number;
  lines: string[];
}

/** Where the spoken description's caption sits: a slim broadcast lower third (CAPTION_PX at 1080
 * lines), one line wherever it fits, across the frame where the sound is (its `pan`), inside
 * title-safe, never off the edge. Read by tests (window.ninetyDraw). */
export function captionBox(measure: (s: string) => number, text: string, pan: number, W: number, H: number): CaptionBox {
  const u = W / 1920, size = CAPTION_PX * u, padX = 20 * u, padY = 10 * u, safe = W * TITLE_SAFE;
  // One line up to about 85 characters (every line the 8324 bundle has); longer wraps, never shrinks or cuts.
  const room = Math.min(W * 0.62, W - 2 * safe - padX * 2);
  const lines: string[] = [];
  let line = "";
  for (const word of text.split(/\s+/).filter(Boolean)) {
    const next = line ? `${line} ${word}` : word;
    if (line && measure(next) > room) {
      lines.push(line);
      line = word;
    } else line = next;
  }
  if (line) lines.push(line);
  const w = Math.min(W - 2 * safe, Math.max(...lines.map(measure), 0) + padX * 2);
  const h = lines.length * size * 1.3 + padY * 2;
  const centre = W / 2 + Math.max(-1, Math.min(1, pan)) * (W / 2 - w / 2 - safe);
  const x = Math.max(safe, Math.min(W - w - safe, centre - w / 2));
  // Bottom of title-safe, lifted clear of the player's scrub bar.
  const y = H * (1 - TITLE_SAFE) - h - 24 * u;
  return { x, y, w, h, size, lines };
}

function drawCaption(ctx: CanvasRenderingContext2D, cue: Cue, a: number, W: number, H: number) {
  ctx.save();
  ctx.globalAlpha = a;
  const u = W / 1920;
  ctx.font = `600 ${CAPTION_PX * u}px ${FONT}`;
  const b = captionBox((s) => ctx.measureText(s).width, sentence(cue.text), cue.pan ?? 0, W, H);
  ctx.fillStyle = BUG;
  panel(ctx, b.x, b.y, b.w, b.h, 8 * u, cue.verified ? ACCENT : TAG, 4 * u);
  ctx.fillStyle = INK;
  ctx.textBaseline = "middle";
  b.lines.forEach((line, i) => ctx.fillText(line, b.x + 20 * u, b.y + 10 * u + (i + 0.5) * b.size * 1.3));
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
    else if (cue.slot === "top_right") drawInsight(ctx, cue, a, W, H);
    else drawLowerThird(ctx, cue, a, W, H);
  }
  const fallback = (o.onAir ?? cues).find((c) => c.fallback && c.kind !== "insight");
  if (fallback) drawFallback(ctx, fallback.fallback!, presence(fallback, o.t, o.reduceMotion));
}
