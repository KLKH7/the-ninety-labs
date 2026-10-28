// The wind map: each team's movement over the last WINDOW_S seconds, drawn as a field of flow
// lines on a fine lattice, smoothed between the cells of its flow field (the API's `flow` message:
// mean player velocity per cell, computed in ninety/intel/window.py), each line fading in from its
// tail, a light pulse running along it in the direction of play. Our own code, no library.
//
// It is the first thing to cut (the plan's cut order), so it stands alone: main.ts loads this
// module only when the viewer turns the wind map on, and nothing else imports it. Deleting this
// file and the `import("./wind")` in main.ts removes it.

import { COLORS, type View, attacksRight, tint, zoneFor } from "./pitch";
import { type Flow, PITCH_X, PITCH_Y, type Team, teams } from "./types";

export const WINDOW_S = 30; // design: about one phase of play
export const LATTICE_M = 6; // design: one flow line every 6 m, about the gap between two players
const METRES_PER_MS = 1.1; // design: a line's length per m/s, so a sprint (7 m/s) spans about two lattice steps
const STILL_SPEED = 0.4; // m/s; design: slower than a walk reads as standing, so it draws no line
const PULSE_S = 1.6; // design: a pulse runs tail to head in about the time a player covers the line
const FRAME_MS = 33; // design: 30 frames a second is smooth for a pulse and spares a phone's battery

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
  const name = teams[f.team];
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
  private last = 0;

  constructor(private readonly canvasView: () => View) {}

  set(flow: Flow) {
    this.flows.set(flow.team, flow);
  }

  clear() {
    const v = this.canvasView();
    v.ctx.clearRect(0, 0, v.w, v.h);
  }

  /** The flow lines: on a LATTICE_M lattice, the field's velocity blended from the cells around
   * each point (sample), every team in its club's colour lightened to read on the grass. */
  lines(): { team: Team; x: number; y: number; ux: number; uy: number; speed: number }[] {
    const out: { team: Team; x: number; y: number; ux: number; uy: number; speed: number }[] = [];
    for (const [team, f] of this.flows) {
      for (let x = LATTICE_M / 2; x < PITCH_X; x += LATTICE_M) {
        for (let y = LATTICE_M / 2; y < PITCH_Y; y += LATTICE_M) {
          const vel = sample(f, x, y);
          if (!vel) continue;
          const speed = Math.hypot(vel[0], vel[1]);
          if (speed < STILL_SPEED) continue;
          out.push({ team, x, y, ux: vel[0] / speed, uy: vel[1] / speed, speed });
        }
      }
    }
    return out;
  }

  /** One animation frame: the field, with the pulse at this moment's phase. */
  step(now: number) {
    if (this.last && now - this.last < FRAME_MS) return;
    this.last = now;
    this.draw(((now / 1000) % PULSE_S) / PULSE_S, true);
  }

  /** Reduced motion, and an answer's picture: the same field, still. `clear` false draws over what
   * the canvas holds (the pitch). */
  still(clear = true) {
    this.draw(null, clear);
  }

  private draw(phase: number | null, clear: boolean) {
    const v = this.canvasView();
    const { ctx, X, Y } = v;
    if (clear) ctx.clearRect(0, 0, v.w, v.h);
    ctx.lineCap = "round";
    const ink = { home: tint(COLORS.home, 0.45), away: tint(COLORS.away, 0.35) };
    for (const l of this.lines()) {
      const len = Math.min(LATTICE_M * 1.9, l.speed * METRES_PER_MS);
      // Centred on its lattice point, so neighbouring lines read as one stream.
      const x0 = X(l.x - (l.ux * len) / 2);
      const y0 = Y(l.y - (l.uy * len) / 2);
      const x1 = X(l.x + (l.ux * len) / 2);
      const y1 = Y(l.y + (l.uy * len) / 2);
      const strength = Math.min(1, 0.35 + l.speed / 6); // design: faster flow, stronger line (6 m/s full)
      const color = ink[l.team];
      const g = ctx.createLinearGradient(x0, y0, x1, y1);
      g.addColorStop(0, `${color}00`);
      if (phase !== null) {
        const p = Math.min(0.9, Math.max(0.1, phase));
        g.addColorStop(Math.max(0.05, p - 0.15), alpha(color, 0.6 * strength));
        g.addColorStop(p, alpha(tint(color, 0.5), Math.min(1, strength + 0.15)));
        g.addColorStop(Math.min(0.95, p + 0.15), alpha(color, 0.8 * strength));
      }
      g.addColorStop(1, alpha(color, strength));
      ctx.strokeStyle = g;
      ctx.lineWidth = 1.4 + l.speed * 0.25;
      ctx.beginPath();
      ctx.moveTo(x0, y0);
      ctx.lineTo(x1, y1);
      ctx.stroke();
      // A small head, so the way of play reads at a glance.
      const a = Math.atan2(y1 - y0, x1 - x0); // on the canvas, where y runs the other way
      const h = 3 + l.speed * 0.6;
      ctx.fillStyle = alpha(color, strength);
      ctx.beginPath();
      ctx.moveTo(x1 + Math.cos(a) * 1.5, y1 + Math.sin(a) * 1.5);
      ctx.lineTo(x1 - Math.cos(a - 0.45) * h, y1 - Math.sin(a - 0.45) * h);
      ctx.lineTo(x1 - Math.cos(a + 0.45) * h, y1 - Math.sin(a + 0.45) * h);
      ctx.closePath();
      ctx.fill();
    }
  }
}

/** "#rrggbb" with an alpha, as "#rrggbbaa". */
function alpha(hex: string, a: number): string {
  return `${hex}${Math.round(Math.max(0, Math.min(1, a)) * 255).toString(16).padStart(2, "0")}`;
}
