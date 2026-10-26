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

/** A heat map: each cell shaded by its share of the window, the busiest cell at full strength.
 * Cells run row by row from y = 0 (schemas/companion_message.schema.json), so row 0 is drawn at the
 * bottom, along the near touchline. */
export function drawHeat(v: View, heat: { nx: number; ny: number; cells: number[] }, color: string) {
  const { ctx, X, Y } = v;
  const max = Math.max(...heat.cells, 1e-9);
  const cw = PITCH_X / heat.nx;
  const ch = PITCH_Y / heat.ny;
  heat.cells.forEach((share, k) => {
    if (share <= 0) return;
    const col = k % heat.nx;
    const row = Math.floor(k / heat.nx);
    ctx.globalAlpha = 0.15 + 0.75 * (share / max);
    ctx.fillStyle = color;
    const left = X(col * cw);
    const top = Y((row + 1) * ch);
    ctx.fillRect(left + 0.5, top + 0.5, X((col + 1) * cw) - left - 1, Y(row * ch) - top - 1);
  });
  ctx.globalAlpha = 1;
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
