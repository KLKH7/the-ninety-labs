// The wind map: each team's movement over the last WINDOW_S seconds, drawn as particles drifting
// through its flow field (the API's `flow` message: mean player velocity per cell, computed in
// ninety/intel/window.py). Our own code, no library.
//
// It is the first thing to cut (the plan's cut order), so it stands alone: main.ts loads this
// module only when the viewer turns the wind map on, and nothing else imports it. Deleting this
// file and the `import("./wind")` in main.ts removes it.

import { COLORS, type View, attacksRight, zoneFor } from "./pitch";
import { type Flow, PITCH_X, PITCH_Y, type Team } from "./types";

export const WINDOW_S = 30; // design: about one phase of play
const PER_TEAM = 140; // particles; design: enough to read the flow, few enough to see the dots
const SPEED_UP = 5; // design: real running speeds (1 to 7 m/s) drift too slowly to read at a glance
const LIFE_S = [1.2, 2.6] as const;
const STILL_SPEED = 0.4; // m/s; design: slower than a walk reads as standing, so it draws no streak

interface Particle {
  x: number;
  y: number;
  age: number;
  life: number;
}

/** The velocity at (x, y), blended from the centres of the cells around it that anyone crossed. */
export function sample(f: Flow, x: number, y: number): [number, number] | null {
  const cw = PITCH_X / f.nx;
  const ch = PITCH_Y / f.ny;
  const gx = x / cw - 0.5;
  const gy = y / ch - 0.5;
  const i0 = Math.floor(gx);
  const j0 = Math.floor(gy);
  let vx = 0;
  let vy = 0;
  let wsum = 0;
  for (const [i, j] of [[i0, j0], [i0 + 1, j0], [i0, j0 + 1], [i0 + 1, j0 + 1]]) {
    if (i < 0 || j < 0 || i >= f.nx || j >= f.ny) continue;
    const k = j * f.nx + i;
    const ux = f.vx[k];
    const uy = f.vy[k];
    if (ux === null || uy === null || f.count[k] === 0) continue;
    const w = (1 - Math.abs(gx - i)) * (1 - Math.abs(gy - j));
    vx += ux * w;
    vy += uy * w;
    wsum += w;
  }
  return wsum > 0 ? [vx / wsum, vy / wsum] : null;
}

/** A team's movement in words: forward or back overall, and where it was strongest. */
export function describe(f: Flow): string {
  const name = f.team === "home" ? "Home" : "Away";
  const sign = attacksRight(f.team) ? 1 : -1;
  let forward = 0;
  let n = 0;
  let best = -1;
  let bestSpeed = 0;
  f.count.forEach((c, k) => {
    const ux = f.vx[k];
    const uy = f.vy[k];
    if (!c || ux === null || uy === null) return;
    forward += sign * ux * c;
    n += c;
    const speed = Math.hypot(ux, uy);
    if (speed > bestSpeed && c >= 3) { // design: a cell crossed in under 3 steps is one stride, not a flow
      bestSpeed = speed;
      best = k;
    }
  });
  if (!n) return `${name}: not seen moving in this window.`;
  forward /= n;
  // design: under 0.3 m/s (about a slow walk) a team's average drift is called holding, not moving.
  const overall = Math.abs(forward) < 0.3 ? "holding their line" : forward > 0 ? `pushing forward (${forward.toFixed(1)} m/s)` : `dropping back (${(-forward).toFixed(1)} m/s)`;
  if (best < 0) return `${name}: ${overall}.`;
  const x = ((best % f.nx) + 0.5) * (PITCH_X / f.nx);
  const y = (Math.floor(best / f.nx) + 0.5) * (PITCH_Y / f.ny);
  const ux = f.vx[best]!;
  const way = sign * ux > Math.abs(f.vy[best]!) ? "forward" : sign * ux < -Math.abs(f.vy[best]!) ? "back" : "across";
  return `${name}: ${overall}; fastest in their ${zoneFor(f.team, x, y)}, running ${way} at ${bestSpeed.toFixed(1)} m/s.`;
}

export class WindMap {
  private flows = new Map<Team, Flow>();
  private particles = new Map<Team, Particle[]>();
  private last = 0;

  constructor(
    private readonly canvasView: () => View,
    private readonly random: () => number = Math.random,
  ) {}

  set(flow: Flow) {
    this.flows.set(flow.team, flow);
    if (!this.particles.has(flow.team)) {
      this.particles.set(
        flow.team,
        Array.from({ length: PER_TEAM }, () => this.spawn(flow)),
      );
    }
  }

  /** A new particle in a cell the team crossed, more often where they crossed more. */
  private spawn(f: Flow): Particle {
    const total = f.count.reduce((a, b) => a + b, 0);
    let pick = this.random() * total;
    let k = 0;
    while (k < f.count.length - 1 && pick >= f.count[k]) pick -= f.count[k++];
    const cw = PITCH_X / f.nx;
    const ch = PITCH_Y / f.ny;
    const life = LIFE_S[0] + this.random() * (LIFE_S[1] - LIFE_S[0]);
    return {
      x: ((k % f.nx) + this.random()) * cw,
      y: (Math.floor(k / f.nx) + this.random()) * ch,
      age: this.random() * life,
      life,
    };
  }

  clear() {
    const v = this.canvasView();
    v.ctx.clearRect(0, 0, v.w, v.h);
  }

  /** One animation frame: fade the trails, move every particle, draw its step. */
  step(now: number) {
    const dt = this.last ? Math.min(0.05, (now - this.last) / 1000) : 1 / 60;
    this.last = now;
    const v = this.canvasView();
    const { ctx, sx, sy } = v;
    ctx.globalCompositeOperation = "destination-out";
    ctx.fillStyle = "rgba(0,0,0,0.08)";
    ctx.fillRect(0, 0, v.w, v.h);
    ctx.globalCompositeOperation = "source-over";
    ctx.lineWidth = 1.8;
    ctx.lineCap = "round";
    for (const [team, flow] of this.flows) {
      ctx.strokeStyle = team === "home" ? COLORS.home : COLORS.away;
      const ps = this.particles.get(team)!;
      ctx.beginPath();
      for (let i = 0; i < ps.length; i++) {
        const p = ps[i];
        const vel = sample(flow, p.x, p.y);
        p.age += dt;
        if (!vel || Math.hypot(vel[0], vel[1]) < STILL_SPEED || p.age > p.life || p.x < 0 || p.y < 0 || p.x > PITCH_X || p.y > PITCH_Y) {
          ps[i] = this.spawn(flow);
          continue;
        }
        const nx = p.x + vel[0] * SPEED_UP * dt;
        const ny = p.y + vel[1] * SPEED_UP * dt;
        ctx.moveTo(p.x * sx, p.y * sy);
        ctx.lineTo(nx * sx, ny * sy);
        p.x = nx;
        p.y = ny;
      }
      ctx.stroke();
    }
  }

  /** Reduced motion: one still arrow per crossed cell, its length the cell's speed. */
  still() {
    const v = this.canvasView();
    const { ctx, sx, sy } = v;
    ctx.clearRect(0, 0, v.w, v.h);
    ctx.lineWidth = 1.8;
    for (const [team, f] of this.flows) {
      ctx.strokeStyle = team === "home" ? COLORS.home : COLORS.away;
      const cw = PITCH_X / f.nx;
      const ch = PITCH_Y / f.ny;
      f.count.forEach((c, k) => {
        const ux = f.vx[k];
        const uy = f.vy[k];
        if (!c || ux === null || uy === null) return;
        const cx = ((k % f.nx) + 0.5) * cw;
        const cy = (Math.floor(k / f.nx) + 0.5) * ch;
        const len = Math.min(cw * 0.9, Math.hypot(ux, uy) * 1.4);
        if (len < 0.4) return;
        const a = Math.atan2(uy, ux);
        const x1 = (cx + Math.cos(a) * len) * sx;
        const y1 = (cy + Math.sin(a) * len) * sy;
        ctx.beginPath();
        ctx.moveTo(cx * sx, cy * sy);
        ctx.lineTo(x1, y1);
        ctx.lineTo(x1 - Math.cos(a - 0.5) * 5, y1 - Math.sin(a - 0.5) * 5);
        ctx.moveTo(x1, y1);
        ctx.lineTo(x1 - Math.cos(a + 0.5) * 5, y1 - Math.sin(a + 0.5) * 5);
        ctx.stroke();
      });
    }
  }
}
