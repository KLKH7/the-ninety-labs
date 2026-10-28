// The phone's pitch: the viewer's radar drawing (viewer/src/radar.ts), so the phone and the TV
// picture agree. Pitch metres (x 0..105, y 0..68, as the frame schema) are drawn as the broadcast
// camera sees them: it stands beyond the y = 0 touchline, so that line is at the bottom and x runs
// left to right. Everything the phone draws (radar, heat map, wind map, answer pictures) goes
// through `fit`, so no part of it can be drawn the other way up.

import { COLORS as RADAR, PITCH_X, PITCH_Y, aspect, drawRadar, projection } from "../../viewer/src/radar";
import { type Minimap, playerName, teams, team } from "./types";

export const COLORS = { ...RADAR, line: "rgba(255,255,255,0.55)" };
export { aspect };

export interface View {
  ctx: CanvasRenderingContext2D;
  w: number; // CSS pixels
  h: number;
  s: number; // CSS pixels per metre
  X: (x: number) => number;
  Y: (y: number) => number;
}

/** Sizes the canvas to its box at the screen's pixel density; returns the drawing view. */
export function fit(canvas: HTMLCanvasElement): View {
  const dpr = Math.min(3, window.devicePixelRatio || 1);
  const w = canvas.clientWidth;
  const h = canvas.clientHeight;
  if (canvas.width !== Math.round(w * dpr) || canvas.height !== Math.round(h * dpr)) {
    canvas.width = Math.round(w * dpr);
    canvas.height = Math.round(h * dpr);
  }
  const ctx = canvas.getContext("2d")!;
  ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
  const p = projection(w);
  return { ctx, w, h, s: p.s, X: p.X, Y: p.Y };
}

export function drawPitch(v: View) {
  drawRadar(v.ctx, v.w, v.h, null, { reduceMotion: true, trail: [] });
}

export interface Positions {
  ball: [number, number];
  players: [string, number, number][];
}

/** The minimap feed as the radar's input: one tracked frame per minimap frame, numbered at the
 * feed's own fps. A squad id (h7, the mock's) carries its shirt; a track carries none. */
export function radarFromMinimap(m: Minimap) {
  return {
    format: 1,
    source: m.source,
    clip: m.clip,
    frames: m.frames.map((f) => ({
      frame: Math.round(f.t * m.fps),
      t: f.t,
      source: m.source,
      ball: { x: f.ball[0], y: f.ball[1], z: 0 },
      players: f.players.map(([id, x, y]) => ({
        id,
        team: team(id),
        x,
        y,
        ...(/^[ha]\d+$/.test(id) ? { number: Number(id.slice(1)) } : {}),
      })),
    })),
    views: [],
  };
}

/** The engine's convention, which the tracker's team assignment also follows (ninety/sim/engine.py,
 * ninety/vision/track.py): home attacks toward x = 105 in both halves, away toward x = 0. */
export function attacksRight(side: "home" | "away"): boolean {
  return side === "home";
}

/** Where (x, y) is for a team, in football words: depth (own half, attacking third...) and flank,
 * left and right as the team sees them, facing the goal it attacks. */
export function zoneFor(side: "home" | "away", x: number, y: number): string {
  const forward = attacksRight(side) ? x : PITCH_X - x; // metres from the team's own goal line
  const depth = forward < 35 ? "defensive third" : forward < 70 ? "middle third" : "attacking third"; // thirds of 105 m
  // Facing x = 105, a team's left is toward y = 68 (the engine's home left-back starts at 0.85 of
  // the width, ninety/sim/engine.py); facing x = 0, toward y = 0.
  const leftness = attacksRight(side) ? y : PITCH_Y - y;
  const flank = leftness > (2 * PITCH_Y) / 3 ? "left" : leftness < PITCH_Y / 3 ? "right" : "centre";
  return flank === "centre" ? `${depth}, centrally` : `${depth}, on the ${flank}`;
}

/** One sentence on where the play is, in football words, for a screen reader. */
export function describePlay(pos: Positions, name: (id: string) => string = (id) => playerName(id)): string {
  const [bx, by] = pos.ball;
  const half = bx < PITCH_X / 2 ? teams.home : teams.away;
  const goalDistance = Math.min(bx, PITCH_X - bx);
  // design: within 20 m (a little past the penalty area's 16.5 m) is "close to goal"; within 40 m
  // "in their half"; the 25 m either side of halfway is "around halfway".
  const where = goalDistance < 20 ? `close to ${half}'s goal` : goalDistance < 40 ? `in ${half}'s half` : "around halfway";
  const near = [...pos.players].sort((a, b) => Math.hypot(a[1] - bx, a[2] - by) - Math.hypot(b[1] - bx, b[2] - by))[0];
  if (!near) return `The ball is ${where}.`;
  const side = team(near[0]);
  return `The ball is ${where}. ${name(near[0])} is nearest it, in ${teams[side]}'s ${zoneFor(side, bx, by)}.`;
}

/** Where a player spent most of his time, in football words, for a screen reader. */
export function describeHeat(heat: { nx: number; ny: number; cells: number[] }, side: "home" | "away"): string {
  const total = heat.cells.reduce((a, b) => a + b, 0);
  if (total <= 0) return "No time on the pitch yet.";
  const k = heat.cells.indexOf(Math.max(...heat.cells));
  const x = ((k % heat.nx) + 0.5) * (PITCH_X / heat.nx);
  const y = (Math.floor(k / heat.nx) + 0.5) * (PITCH_Y / heat.ny);
  const ownHalf = heat.cells.reduce((sum, share, i) => {
    const cx = ((i % heat.nx) + 0.5) * (PITCH_X / heat.nx);
    return sum + ((attacksRight(side) ? cx < PITCH_X / 2 : cx > PITCH_X / 2) ? share : 0);
  }, 0);
  return `Most often in his ${zoneFor(side, x, y)}; ${Math.round((ownHalf / total) * 100)}% of the time in his own half.`;
}

/** The smooth heat map's grid: about 2 m a cell (design: fine enough that a player's runs read as
 * a shape, not as a dozen tiles), and the Gaussian blur over it, in cells (design: about 3 m, a
 * stride or two, so one sample is a soft spot and a run is a band). */
export const DENSITY_NX = 52;
export const DENSITY_NY = 34;
const DENSITY_SIGMA = 1.5;

export interface Density {
  nx: number;
  ny: number;
  cells: Float32Array; // row by row from y = 0, as the cards' heat; blurred, the busiest cell 1
  samples: number;
}

/** A density from positions in pitch metres: each counted in its ~2 m cell, then blurred. */
export function densityFromPoints(points: Iterable<[number, number]>): Density {
  const nx = DENSITY_NX;
  const ny = DENSITY_NY;
  const raw = new Float32Array(nx * ny);
  let n = 0;
  for (const [x, y] of points) {
    const cx = Math.min(nx - 1, Math.max(0, Math.floor((x / PITCH_X) * nx)));
    const cy = Math.min(ny - 1, Math.max(0, Math.floor((y / PITCH_Y) * ny)));
    raw[cy * nx + cx] += 1;
    n += 1;
  }
  return { nx, ny, cells: blur(raw, nx, ny), samples: n };
}

/** A density from a coarse heat grid (the card's 12 by 8): each cell's share spread over the fine
 * cells it covers, then blurred, so the server's grid draws as a soft field, not as tiles. */
export function densityFromCells(heat: { nx: number; ny: number; cells: number[] }): Density {
  const nx = DENSITY_NX;
  const ny = DENSITY_NY;
  const raw = new Float32Array(nx * ny);
  for (let j = 0; j < ny; j++) {
    for (let i = 0; i < nx; i++) {
      const ci = Math.min(heat.nx - 1, Math.floor(((i + 0.5) / nx) * heat.nx));
      const cj = Math.min(heat.ny - 1, Math.floor(((j + 0.5) / ny) * heat.ny));
      raw[j * nx + i] = heat.cells[cj * heat.nx + ci] ?? 0;
    }
  }
  return { nx, ny, cells: blur(raw, nx, ny, DENSITY_SIGMA * 2), samples: heat.cells.some((c) => c > 0) ? 1 : 0 };
}

/** A separable Gaussian blur, edges clamped, scaled so the busiest cell is 1. */
function blur(src: Float32Array, nx: number, ny: number, sigma = DENSITY_SIGMA): Float32Array {
  const r = Math.ceil(sigma * 3);
  const k = Array.from({ length: 2 * r + 1 }, (_, i) => Math.exp(-((i - r) ** 2) / (2 * sigma * sigma)));
  const tmp = new Float32Array(nx * ny);
  const out = new Float32Array(nx * ny);
  for (let j = 0; j < ny; j++) {
    for (let i = 0; i < nx; i++) {
      let s = 0;
      for (let d = -r; d <= r; d++) s += k[d + r] * src[j * nx + Math.min(nx - 1, Math.max(0, i + d))];
      tmp[j * nx + i] = s;
    }
  }
  let max = 0;
  for (let j = 0; j < ny; j++) {
    for (let i = 0; i < nx; i++) {
      let s = 0;
      for (let d = -r; d <= r; d++) s += k[d + r] * tmp[Math.min(ny - 1, Math.max(0, j + d)) * nx + i];
      out[j * nx + i] = s;
      if (s > max) max = s;
    }
  }
  if (max > 0) for (let i = 0; i < out.length; i++) out[i] /= max;
  return out;
}

/** "#3a68c0" as [r, g, b]. */
function rgb(hex: string): [number, number, number] {
  const h = hex.replace("#", "");
  return [0, 2, 4].map((i) => parseInt(h.slice(i, i + 2), 16)) as [number, number, number];
}

/** A colour mixed toward white by k (0 the colour, 1 white), as "#rrggbb". */
export function tint(hex: string, k: number): string {
  return `#${rgb(hex).map((c) => Math.round(c + (255 - c) * k).toString(16).padStart(2, "0")).join("")}`;
}

/** Draws a density over the pitch: the club's colour where he passed through, warming toward white
 * where he spent most time, fading to transparent where he barely went (design: below a twentieth
 * of the busiest spot draws nothing, so the pitch stays clean). Smoothed by the browser's own
 * image scaling between the ~2 m cells. */
export function drawDensity(v: View, d: Density, color: string) {
  if (!d.samples) return;
  const img = document.createElement("canvas");
  img.width = d.nx;
  img.height = d.ny;
  const ictx = img.getContext("2d")!;
  const data = ictx.createImageData(d.nx, d.ny);
  const [r0, g0, b0] = rgb(color);
  for (let j = 0; j < d.ny; j++) {
    for (let i = 0; i < d.nx; i++) {
      const val = d.cells[j * d.nx + i];
      const o = ((d.ny - 1 - j) * d.nx + i) * 4; // row 0 (y = 0) at the bottom, the near touchline
      const a = val < 0.05 ? 0 : Math.min(1, (val - 0.05) / 0.95) ** 0.6;
      const warm = Math.max(0, (val - 0.55) / 0.45) * 0.75; // the hottest spots toward white
      data.data[o] = r0 + (255 - r0) * warm;
      data.data[o + 1] = g0 + (255 - g0) * warm;
      data.data[o + 2] = b0 + (255 - b0) * warm;
      data.data[o + 3] = Math.round(a * 0.88 * 255);
    }
  }
  ictx.putImageData(data, 0, 0);
  const { ctx, X, Y } = v;
  ctx.save();
  ctx.imageSmoothingEnabled = true;
  ctx.imageSmoothingQuality = "high";
  ctx.drawImage(img, X(0), Y(PITCH_Y), X(PITCH_X) - X(0), Y(0) - Y(PITCH_Y));
  ctx.restore();
}
