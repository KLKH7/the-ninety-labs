// Drawing the pitch, the players and a heat map onto a canvas. Pitch metres (x 0..105, y 0..68,
// as the frame schema) map onto the canvas with y = 0 at the top.

import { type Minimap, PITCH_X, PITCH_Y, team } from "./types";

export const COLORS = {
  home: "#4ea1ff",
  away: "#ffb02e",
  homeInk: "#04172b",
  awayInk: "#2a1800",
  ball: "#ffffff",
  line: "rgba(255,255,255,0.55)",
  grass: "#1b5434",
  stripe: "#1e5c39",
};

export interface View {
  ctx: CanvasRenderingContext2D;
  w: number; // CSS pixels
  h: number;
  sx: number; // CSS pixels per metre
  sy: number;
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
  return { ctx, w, h, sx: w / PITCH_X, sy: h / PITCH_Y };
}

export function drawPitch(v: View) {
  const { ctx, w, h, sx, sy } = v;
  ctx.fillStyle = COLORS.grass;
  ctx.fillRect(0, 0, w, h);
  ctx.fillStyle = COLORS.stripe;
  for (let i = 0; i < 12; i += 2) ctx.fillRect((i * w) / 12, 0, w / 12, h);
  ctx.strokeStyle = COLORS.line;
  ctx.lineWidth = 1.25;
  const rect = (x: number, y: number, rw: number, rh: number) => ctx.strokeRect(x * sx, y * sy, rw * sx, rh * sy);
  rect(0.4, 0.4, PITCH_X - 0.8, PITCH_Y - 0.8);
  ctx.beginPath();
  ctx.moveTo((PITCH_X / 2) * sx, 0);
  ctx.lineTo((PITCH_X / 2) * sx, h);
  ctx.stroke();
  ctx.beginPath();
  ctx.ellipse((PITCH_X / 2) * sx, (PITCH_Y / 2) * sy, 9.15 * sx, 9.15 * sy, 0, 0, Math.PI * 2);
  ctx.stroke();
  // Penalty and goal areas: 16.5 m by 40.32 m, and 5.5 m by 18.32 m (Law 1).
  for (const left of [true, false]) {
    const x = (d: number) => (left ? 0 : PITCH_X - d);
    rect(x(16.5), (PITCH_Y - 40.32) / 2, 16.5, 40.32);
    rect(x(5.5), (PITCH_Y - 18.32) / 2, 5.5, 18.32);
    ctx.fillStyle = COLORS.line;
    ctx.beginPath();
    ctx.arc((left ? 11 : PITCH_X - 11) * sx, (PITCH_Y / 2) * sy, 1.5, 0, Math.PI * 2);
    ctx.fill();
  }
}

export interface Positions {
  ball: [number, number];
  players: [string, number, number][];
}

/** Positions at match time t, between the two nearest minimap frames, so the dots glide. */
export function positionsAt(m: Minimap, t: number): Positions | null {
  const frames = m.frames;
  if (!frames.length) return null;
  const t0 = frames[0].t;
  const step = 1 / m.fps;
  const i = Math.max(0, Math.min(frames.length - 1, Math.floor((t - t0) / step)));
  const a = frames[i];
  const b = frames[Math.min(frames.length - 1, i + 1)];
  const k = b === a ? 0 : Math.max(0, Math.min(1, (t - a.t) / (b.t - a.t)));
  const at = new Map(b.players.map((p) => [p[0], p]));
  return {
    ball: [a.ball[0] + (b.ball[0] - a.ball[0]) * k, a.ball[1] + (b.ball[1] - a.ball[1]) * k],
    players: a.players.map(([id, x, y]) => {
      const q = at.get(id);
      return q ? [id, x + (q[1] - x) * k, y + (q[2] - y) * k] : [id, x, y];
    }),
  };
}

export const DOT_R = 8; // CSS pixels: a shirt number still reads at 375 px wide

export function drawPlayers(v: View, pos: Positions, selected: string | null, dim = false) {
  const { ctx, sx, sy } = v;
  ctx.globalAlpha = dim ? 0.75 : 1;
  ctx.font = "700 9.5px system-ui, -apple-system, sans-serif";
  ctx.textAlign = "center";
  ctx.textBaseline = "middle";
  const last = (p: [string, number, number]) => (p[0] === selected ? 1 : 0);
  const order = [...pos.players].sort((a, b) => last(a) - last(b)); // the selected player on top
  for (const [id, x, y] of order) {
    const home = team(id) === "home";
    const px = x * sx;
    const py = y * sy;
    const r = id === selected ? DOT_R + 2 : DOT_R;
    ctx.beginPath();
    ctx.arc(px, py, r, 0, Math.PI * 2);
    ctx.fillStyle = home ? COLORS.home : COLORS.away;
    ctx.fill();
    // Away players have a dark outline too, so the two teams differ by more than colour.
    ctx.lineWidth = home ? 1 : 2;
    ctx.strokeStyle = home ? "rgba(0,0,0,0.5)" : COLORS.awayInk;
    ctx.stroke();
    if (id === selected) {
      ctx.lineWidth = 2.5;
      ctx.strokeStyle = "#fff";
      ctx.beginPath();
      ctx.arc(px, py, r + 3, 0, Math.PI * 2);
      ctx.stroke();
    }
    ctx.fillStyle = home ? COLORS.homeInk : COLORS.awayInk;
    ctx.fillText(id.slice(1), px, py + 0.5);
  }
  ctx.globalAlpha = 1;
  const [bx, by] = pos.ball;
  ctx.beginPath();
  ctx.arc(bx * sx, by * sy, 3.5, 0, Math.PI * 2);
  ctx.fillStyle = COLORS.ball;
  ctx.fill();
  ctx.lineWidth = 1.5;
  ctx.strokeStyle = "#000";
  ctx.stroke();
}

/** The players whose dots are within reach of a tap (a 44 px target, WCAG 2.5.5), nearest first. */
export function within(v: View, pos: Positions, x: number, y: number, reach = 22): string[] {
  return pos.players
    .map(([id, px, py]) => [id, Math.hypot(px * v.sx - x, py * v.sy - y)] as const)
    .filter(([, d]) => d < reach)
    .sort((a, b) => a[1] - b[1])
    .map(([id]) => id);
}

/** Which goal each team defends, read off where its players stand: the team further left defends
 * the left goal. The feed carries no attacking direction, so this is inferred, and said as such. */
function leftTeam(pos: Positions): "home" | "away" {
  const mean = (side: string) => {
    const xs = pos.players.filter((p) => team(p[0]) === side).map((p) => p[1]);
    return xs.reduce((a, b) => a + b, 0) / Math.max(1, xs.length);
  };
  return mean("home") <= mean("away") ? "home" : "away";
}

/** One sentence on where the play is, in football words, for a screen reader. */
export function describePlay(pos: Positions, name: (id: string) => string): string {
  const [bx, by] = pos.ball;
  const left = leftTeam(pos) === "home" ? "Home" : "Away";
  const right = left === "Home" ? "Away" : "Home";
  const half = bx < PITCH_X / 2 ? left : right;
  const goalDistance = Math.min(bx, PITCH_X - bx);
  const where = goalDistance < 20 ? `close to ${half}'s goal` : goalDistance < 40 ? `in ${half}'s half` : "around halfway";
  const flank = by < PITCH_Y / 3 ? ", on the top touchline side of the map" : by > (2 * PITCH_Y) / 3 ? ", on the bottom touchline side of the map" : ", in the middle";
  const near = [...pos.players].sort((a, b) => Math.hypot(a[1] - bx, a[2] - by) - Math.hypot(b[1] - bx, b[2] - by))[0];
  return `The ball is ${where}${flank}. ${near ? `${name(near[0])} is nearest it.` : ""}`.trim();
}

/** A heat map: each cell shaded by its share of the window, the busiest cell at full strength. */
export function drawHeat(v: View, heat: { nx: number; ny: number; cells: number[] }, color: string) {
  const { ctx, w, h } = v;
  const max = Math.max(...heat.cells, 1e-9);
  const cw = w / heat.nx;
  const ch = h / heat.ny;
  heat.cells.forEach((share, k) => {
    if (share <= 0) return;
    const col = k % heat.nx;
    const row = Math.floor(k / heat.nx);
    ctx.globalAlpha = 0.15 + 0.75 * (share / max);
    ctx.fillStyle = color;
    ctx.fillRect(col * cw + 0.5, row * ch + 0.5, cw - 1, ch - 1);
  });
  ctx.globalAlpha = 1;
}

/** Where on the pitch a heat map is busiest, in words a screen reader can say. */
export function describeHeat(heat: { nx: number; ny: number; cells: number[] }): string {
  const thirds = [0, 0, 0];
  const bands = [0, 0, 0];
  heat.cells.forEach((share, k) => {
    thirds[Math.min(2, Math.floor(((k % heat.nx) / heat.nx) * 3))] += share;
    bands[Math.min(2, Math.floor((Math.floor(k / heat.nx) / heat.ny) * 3))] += share;
  });
  const total = thirds.reduce((a, b) => a + b, 0);
  if (total <= 0) return "No time on the pitch yet.";
  const t = thirds.indexOf(Math.max(...thirds));
  const b = bands.indexOf(Math.max(...bands));
  const third = ["left third", "middle third", "right third"][t];
  const band = ["top side", "centre", "bottom side"][b];
  return `Mostly in the ${third} of the map, ${band} (${Math.round((thirds[t] / total) * 100)}% of the time in that third).`;
}
