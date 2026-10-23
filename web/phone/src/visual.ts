// The picture beside an answer or an insight card, chosen by its `visual.kind`: an overload (a
// shaded zone and "4v2"), a line-breaking pass (an arrow through the defenders it bypassed and
// "6 bypassed"), pass options (the open teammates lit), a team's shape (its lines), or the wind map.
// Every position and number drawn here is the visual's own, from the tool the agent cited; the
// phone only draws it, on the same pitch as the radar (pitch.ts), and never makes a number up.

import { COLORS, type View, drawPitch, zoneFor } from "./pitch";
import { PITCH_X, PITCH_Y, type Team, type Visual, type VisualKind, type VisualPlayer, clock, playerName, teams } from "./types";

export const KINDS: VisualKind[] = ["overload", "line_break", "pass_options", "shape", "wind"];

const finite = (n: unknown): n is number => typeof n === "number" && Number.isFinite(n);
// design: a few metres off the pitch is a player by the line or a throw-in taker; past that, a bad fit.
const onPitch = (p: { x: unknown; y: unknown } | null | undefined) =>
  !!p && finite(p.x) && finite(p.y) && p.x >= -5 && p.x <= PITCH_X + 5 && p.y >= -5 && p.y <= PITCH_Y + 5;

/** What a picture of this kind must carry to be drawn; anything less draws nothing rather than
 * a guess (the phone never fills in a missing number). */
export function drawable(v: Visual | null | undefined): v is Visual {
  if (!v || !KINDS.includes(v.kind) || !finite(v.t) || (v.team !== "home" && v.team !== "away")) return false;
  if (!Array.isArray(v.players) || !v.players.every(onPitch)) return false;
  if (v.ball && !onPitch(v.ball)) return false;
  switch (v.kind) {
    case "overload":
      return !!v.zone && [v.zone.x0, v.zone.x1, v.zone.y0, v.zone.y1].every(finite) && !!v.count && finite(v.count.for) && finite(v.count.against);
    case "line_break":
      return !!v.pass && onPitch(v.pass.from) && onPitch(v.pass.to) && finite(v.bypassed);
    case "pass_options":
      return v.players.some((p) => p.role === "carrier");
    case "shape":
      return Array.isArray(v.lines) && v.lines.length > 0 && v.lines.every((l) => l.length >= 2 && l.every(onPitch));
    case "wind":
      return finite(v.t_from) && finite(v.t_to) && v.t_to! > v.t_from!;
  }
}

/** The headline a picture carries, from its own numbers: "4v2", "6 bypassed". */
export function headline(v: Visual): string {
  if (v.kind === "overload" && v.count) return `${v.count.for}v${v.count.against}`;
  if (v.kind === "line_break" && finite(v.bypassed)) return `${v.bypassed} bypassed`;
  if (v.kind === "pass_options") return `${v.players.filter((p) => p.role === "open").length} open`;
  return "";
}

const fill = (side: Team) => (side === "home" ? COLORS.home : COLORS.away);
const ink = (side: Team) => (side === "home" ? COLORS.homeInk : COLORS.awayInk);

function dot(v: View, p: VisualPlayer, o: { r?: number; dim?: boolean; ring?: string; cross?: boolean } = {}) {
  const { ctx, X, Y } = v;
  const r = o.r ?? Math.max(5.5, 1.15 * v.s);
  ctx.globalAlpha = o.dim ? 0.45 : 1;
  ctx.beginPath();
  ctx.arc(X(p.x), Y(p.y), r, 0, Math.PI * 2);
  ctx.fillStyle = fill(p.team);
  ctx.fill();
  ctx.lineWidth = p.team === "home" ? 1 : 2;
  ctx.strokeStyle = p.team === "home" ? "rgba(0,0,0,0.55)" : ink(p.team);
  ctx.stroke();
  ctx.globalAlpha = 1;
  if (o.ring) {
    ctx.lineWidth = 2.5;
    ctx.strokeStyle = o.ring;
    ctx.beginPath();
    ctx.arc(X(p.x), Y(p.y), r + 3.5, 0, Math.PI * 2);
    ctx.stroke();
  }
  if (o.cross) {
    // A defender the pass went past: struck through, so "bypassed" reads without colour.
    ctx.lineWidth = 2;
    ctx.strokeStyle = "#fff";
    ctx.beginPath();
    ctx.moveTo(X(p.x) - r, Y(p.y) - r);
    ctx.lineTo(X(p.x) + r, Y(p.y) + r);
    ctx.stroke();
  }
}

function arrow(v: View, from: { x: number; y: number }, to: { x: number; y: number }, color: string, width: number, dash: number[] = []) {
  const { ctx, X, Y } = v;
  const x0 = X(from.x);
  const y0 = Y(from.y);
  const x1 = X(to.x);
  const y1 = Y(to.y);
  const a = Math.atan2(y1 - y0, x1 - x0);
  const head = 4 + width * 2;
  ctx.strokeStyle = color;
  ctx.fillStyle = color;
  ctx.lineWidth = width;
  ctx.lineCap = "round";
  ctx.setLineDash(dash);
  ctx.beginPath();
  ctx.moveTo(x0, y0);
  ctx.lineTo(x1 - Math.cos(a) * head * 0.8, y1 - Math.sin(a) * head * 0.8);
  ctx.stroke();
  ctx.setLineDash([]);
  ctx.beginPath();
  ctx.moveTo(x1, y1);
  ctx.lineTo(x1 - Math.cos(a - 0.45) * head, y1 - Math.sin(a - 0.45) * head);
  ctx.lineTo(x1 - Math.cos(a + 0.45) * head, y1 - Math.sin(a + 0.45) * head);
  ctx.closePath();
  ctx.fill();
}

/** A label in a pill, kept inside the canvas. */
function pill(v: View, text: string, x: number, y: number, color: string) {
  const { ctx } = v;
  ctx.font = "800 15px system-ui, -apple-system, sans-serif";
  const w = ctx.measureText(text).width + 16;
  const h = 24;
  const left = Math.max(4, Math.min(v.w - w - 4, x - w / 2));
  const top = Math.max(4, Math.min(v.h - h - 4, y - h / 2));
  ctx.fillStyle = "rgba(8, 12, 20, 0.86)";
  ctx.beginPath();
  ctx.roundRect(left, top, w, h, 12);
  ctx.fill();
  ctx.lineWidth = 2;
  ctx.strokeStyle = color;
  ctx.stroke();
  ctx.fillStyle = "#fff";
  ctx.textAlign = "center";
  ctx.textBaseline = "middle";
  ctx.fillText(text, left + w / 2, top + h / 2 + 0.5);
}

function ball(v: Visual, view: View) {
  if (!v.ball) return;
  const { ctx, X, Y } = view;
  ctx.beginPath();
  ctx.arc(X(v.ball.x), Y(v.ball.y), Math.max(3.5, 0.7 * view.s), 0, Math.PI * 2);
  ctx.fillStyle = COLORS.ball;
  ctx.fill();
  ctx.lineWidth = 1.5;
  ctx.strokeStyle = "#000";
  ctx.stroke();
}

/** Draws the picture on a fresh pitch. A wind picture draws the pitch only: its arrows are the
 * flow field the caller fetched for the visual's window (wind.ts, `still`). */
export function drawVisual(view: View, v: Visual) {
  drawPitch(view);
  const { ctx, X, Y } = view;
  const own = fill(v.team);
  const role = (r: string) => v.players.filter((p) => p.role === r);
  const rest = (...roles: string[]) => v.players.filter((p) => !roles.includes(p.role ?? ""));
  switch (v.kind) {
    case "overload": {
      const z = v.zone!;
      const left = X(Math.min(z.x0, z.x1));
      const top = Y(Math.max(z.y0, z.y1));
      const w = Math.abs(X(z.x1) - X(z.x0));
      const h = Math.abs(Y(z.y1) - Y(z.y0));
      ctx.globalAlpha = 0.28;
      ctx.fillStyle = own;
      ctx.fillRect(left, top, w, h);
      ctx.globalAlpha = 1;
      ctx.setLineDash([5, 4]);
      ctx.lineWidth = 2;
      ctx.strokeStyle = own;
      ctx.strokeRect(left, top, w, h);
      ctx.setLineDash([]);
      for (const p of rest("attacker", "defender")) dot(view, p, { dim: true });
      for (const p of [...role("defender"), ...role("attacker")]) dot(view, p);
      ball(v, view);
      pill(view, headline(v), left + w / 2, top - 16, own);
      break;
    }
    case "line_break": {
      for (const p of rest("bypassed", "passer", "receiver")) dot(view, p, { dim: true });
      for (const p of role("bypassed")) dot(view, p, { cross: true });
      arrow(view, v.pass!.from, v.pass!.to, "#fff", 3.5);
      for (const p of [...role("passer"), ...role("receiver")]) dot(view, p, { ring: "#fff" });
      ball(v, view);
      const mid = { x: (X(v.pass!.from.x) + X(v.pass!.to.x)) / 2, y: (Y(v.pass!.from.y) + Y(v.pass!.to.y)) / 2 };
      pill(view, headline(v), mid.x, mid.y - 22, own);
      break;
    }
    case "pass_options": {
      const carrier = role("carrier")[0];
      for (const p of rest("carrier", "open")) dot(view, p, { dim: p.role !== "marked" });
      for (const p of role("open")) arrow(view, carrier, p, "rgba(255,255,255,0.85)", 2, [6, 5]);
      for (const p of role("open")) dot(view, p, { ring: COLORS.ball });
      dot(view, carrier, { ring: own });
      ball(v, view);
      pill(view, headline(v), X(carrier.x), Y(carrier.y) - 26, own);
      break;
    }
    case "shape": {
      for (const p of v.players) dot(view, p, { dim: p.team !== v.team });
      ctx.strokeStyle = own;
      ctx.lineWidth = 3;
      ctx.lineJoin = "round";
      for (const line of v.lines!) {
        ctx.beginPath();
        line.forEach((p, i) => (i ? ctx.lineTo(X(p.x), Y(p.y)) : ctx.moveTo(X(p.x), Y(p.y))));
        ctx.stroke();
      }
      ball(v, view);
      break;
    }
    case "wind":
      break;
  }
}

/** The picture in words, for a screen reader, from the same data the drawing uses. */
export function describeVisual(v: Visual, names?: Record<string, string>): string {
  const club = teams[v.team];
  const who = (p: VisualPlayer) => playerName(p.id, names);
  const at = `at ${clock(v.t)}`;
  switch (v.kind) {
    case "overload": {
      const z = v.zone!;
      const where = zoneFor(v.team, (z.x0 + z.x1) / 2, (z.y0 + z.y1) / 2);
      return `Picture ${at}: ${club} have ${v.count!.for} players against ${v.count!.against} in their ${where}, shaded.`;
    }
    case "line_break": {
      const passer = v.players.find((p) => p.role === "passer");
      const receiver = v.players.find((p) => p.role === "receiver");
      const pass = passer && receiver ? `${who(passer)}'s pass to ${who(receiver)}` : `A ${club} pass`;
      return `Picture ${at}: ${pass}, drawn as an arrow, goes past ${v.bypassed} defenders, each struck through.`;
    }
    case "pass_options": {
      const carrier = v.players.find((p) => p.role === "carrier")!;
      const open = v.players.filter((p) => p.role === "open");
      return open.length
        ? `Picture ${at}: ${who(carrier)} on the ball, with ${open.length} open teammate${open.length === 1 ? "" : "s"} ringed: ${open.map(who).join(", ")}.`
        : `Picture ${at}: ${who(carrier)} on the ball, with no teammate open.`;
    }
    case "shape":
      return `Picture ${at}: ${club}'s shape, ${v.lines!.length} line${v.lines!.length === 1 ? "" : "s"} drawn through their players.`;
    case "wind":
      return `Picture: how both teams moved from ${clock(v.t_from!)} to ${clock(v.t_to!)}, as arrows.`;
  }
}
