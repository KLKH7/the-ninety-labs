// The picture beside an answer or an insight card, chosen by its `visual.kind`: an overload (a
// shaded zone and "4v2"), a line-breaking pass (an arrow through the defenders it bypassed and
// "6 bypassed"), pass options (the open teammates lit), a team's shape (its lines), or the wind map.
// Every position and number drawn here is the visual's own, from the tool the agent cited; the
// phone only draws it, on the same pitch as the radar (pitch.ts), and never makes a number up.

import { COLORS, type View, drawPitch, zoneFor } from "./pitch";
import {
  PITCH_X,
  PITCH_Y,
  type Point,
  type ScoutPoint,
  type ScoutVisual,
  type Team,
  type Visual,
  type VisualKind,
  type VisualPlayer,
  type VisualRole,
  clock,
  playerName,
  teams,
} from "./types";

export const KINDS: VisualKind[] = ["overload", "line_break", "pass_options", "counter_press", "shape", "wind", "channels", "offside", "counter"];

const other = (side: Team): Team => (side === "home" ? "away" : "home");

/** The agents' picture (schemas/insight_card.schema.json, $defs/visual) as the phone draws it, or
 * null when it lacks what its kind needs: the phone draws nothing rather than fill a gap. `t` is the
 * answer's or card's time when the visual carries none. Counts are the fact's own (geometry `for`
 * and `against`) where it gives them, otherwise the number of points it lists. */
export function fromScout(v: ScoutVisual | null | undefined, t: number | null = null): Visual | null {
  if (!v || !v.geometry || (v.team !== "home" && v.team !== "away")) return null;
  const side = v.team;
  const g = v.geometry;
  const at = v.t ?? t;
  if (at === null || !Number.isFinite(at)) return null;
  const pt = (p: ScoutPoint | null | undefined): Point | null => (Array.isArray(p) && p.length >= 2 ? { x: p[0], y: p[1] } : null);
  const player = (p: ScoutPoint, team: Team, role?: VisualRole): VisualPlayer => ({ x: p[0], y: p[1], id: (p[2] as string | null | undefined) ?? null, team, role });
  const many = (ps: ScoutPoint[] | undefined, team: Team, role?: VisualRole) => (Array.isArray(ps) ? ps.map((p) => player(p, team, role)) : []);
  const base = { t: at, team: side };
  switch (v.kind) {
    case "line_break": {
      const from = pt(g.from);
      const to = pt(g.to);
      if (!from || !to || !Array.isArray(g.bypassed)) return null;
      const players = [player(g.from!, side, "passer"), player(g.to!, side, "receiver"), ...many(g.bypassed, other(side), "bypassed"), ...many(g.players, side)];
      return { ...base, kind: "line_break", players, pass: { from, to }, bypassed: g.bypassed.length };
    }
    case "overload": {
      if (!g.zone || !Array.isArray(g.home) || !Array.isArray(g.away)) return null;
      const own = side === "home" ? g.home : g.away;
      const theirs = side === "home" ? g.away : g.home;
      const players = [...many(own, side, "attacker"), ...many(theirs, other(side), "defender")];
      const count = { for: g.for ?? own.length, against: g.against ?? theirs.length };
      return { ...base, kind: "overload", players, zone: g.zone, count };
    }
    case "pass_options": {
      if (!pt(g.passer)) return null;
      const players = [player(g.passer!, side, "carrier"), ...many(g.open, side, "open"), ...many(g.marked, side, "marked")];
      if (g.target) players.push(player(g.target, side, "receiver"));
      return { ...base, kind: "pass_options", players, radius_m: g.radius_m ?? null };
    }
    case "counter_press": {
      const ball = pt(g.ball);
      if (!ball || !Array.isArray(g.pressers) || !(typeof g.radius_m === "number")) return null;
      return { ...base, kind: "counter_press", players: many(g.pressers, side, "presser"), ball, radius_m: g.radius_m };
    }
    case "shape": {
      // v1 sends only the minute; the picture needs the lines the fact holds (PR B adds them).
      if (!Array.isArray(g.lines) || !g.lines.length) return null;
      const lines = g.lines.map((l) => l.map((p) => ({ x: p[0], y: p[1] })));
      return { ...base, kind: "shape", players: many(g.players, side), lines };
    }
    case "wind_map":
      return { ...base, kind: "wind", players: [], t_from: g.t_from ?? null, t_to: g.t_to ?? null };
    case "channels":
      if (!Array.isArray(g.bands) || g.bands.length !== 3) return null;
      return { ...base, kind: "channels", players: [], bands: g.bands };
    case "offside": {
      if (typeof g.line_x !== "number" || !pt(g.receiver) || !g.verdict) return null;
      const players = [...many(g.attackers, side, "attacker"), ...many(g.defenders, other(side), "defender"), player(g.receiver!, side, "receiver")];
      if (g.second_last) players.push(player(g.second_last, other(side), "second_last"));
      return { ...base, kind: "offside", players, ball: pt(g.ball), line_x: g.line_x, verdict: g.verdict, margin_m: g.margin_m ?? null };
    }
    case "counter": {
      const from = pt(g.from);
      const to = pt(g.to);
      if (!from || !to || typeof g.seconds !== "number") return null;
      return { ...base, kind: "counter", players: [], pass: { from, to }, seconds: g.seconds };
    }
  }
  return null;
}

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
    case "counter_press":
      return onPitch(v.ball) && finite(v.radius_m) && v.radius_m! > 0;
    case "channels":
      return Array.isArray(v.bands) && v.bands.length === 3 && v.bands.every((b) => finite(b.y0) && finite(b.y1) && finite(b.share) && b.share >= 0 && b.share <= 100);
    case "offside":
      return finite(v.line_x) && v.line_x! >= 0 && v.line_x! <= PITCH_X && ["onside", "offside", "too_close"].includes(v.verdict ?? "") && (v.verdict === "too_close" || finite(v.margin_m));
    case "counter":
      return !!v.pass && onPitch(v.pass.from) && onPitch(v.pass.to) && finite(v.seconds) && v.seconds! > 0;
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
  if (v.kind === "counter_press") return `${v.players.filter((p) => p.role === "presser").length} pressing`;
  if (v.kind === "channels") {
    const top = [...v.bands!].sort((a, b) => b.share - a.share)[0];
    return `${Math.round(top.share)}% ${top.channel === "centre" ? "through the middle" : `down the ${top.channel}`}`;
  }
  // "too_close" is within the tracking error: say so, and never call it either way.
  if (v.kind === "offside") return v.verdict === "too_close" ? "Too close to call" : `${v.verdict === "offside" ? "Offside" : "Onside"} by ${v.margin_m!.toFixed(1)} m`;
  if (v.kind === "counter") return `${v.seconds!.toFixed(0)} s, regain to shot`;
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
    case "counter_press": {
      const b = v.ball!;
      ctx.globalAlpha = 0.22;
      ctx.fillStyle = own;
      ctx.beginPath();
      ctx.arc(X(b.x), Y(b.y), v.radius_m! * view.s, 0, Math.PI * 2);
      ctx.fill();
      ctx.globalAlpha = 1;
      ctx.setLineDash([5, 4]);
      ctx.lineWidth = 2;
      ctx.strokeStyle = own;
      ctx.stroke();
      ctx.setLineDash([]);
      for (const p of role("presser")) dot(view, p);
      ball(v, view);
      pill(view, headline(v), X(b.x), Y(b.y) - v.radius_m! * view.s - 16, own);
      break;
    }
    case "channels": {
      // Each lane shaded by its share of the team's passes; its share written at the end it attacks.
      const attackRight = v.team === "home";
      const busiest = Math.max(...v.bands!.map((b) => b.share), 1e-9);
      for (const b of v.bands!) {
        const top = Y(Math.max(b.y0, b.y1));
        const h = Math.abs(Y(b.y1) - Y(b.y0));
        ctx.globalAlpha = 0.06 + 0.5 * (b.share / busiest); // the busiest lane strongest
        ctx.fillStyle = own;
        ctx.fillRect(X(0), top, PITCH_X * view.s, h);
        ctx.globalAlpha = 1;
        ctx.strokeStyle = "rgba(255,255,255,0.5)";
        ctx.lineWidth = 1;
        ctx.strokeRect(X(0), top, PITCH_X * view.s, h);
        pill(view, `${Math.round(b.share)}%`, attackRight ? X(PITCH_X) - 34 : X(0) + 34, top + h / 2, own);
      }
      arrow(view, { x: attackRight ? 40 : 65, y: 34 }, { x: attackRight ? 65 : 40, y: 34 }, "rgba(255,255,255,0.8)", 2);
      break;
    }
    case "offside": {
      // The line across the pitch: solid when called, dashed and labelled when too close to call.
      const sure = v.verdict !== "too_close";
      ctx.setLineDash(sure ? [] : [6, 5]);
      ctx.strokeStyle = sure ? "#fff" : "rgba(255,255,255,0.75)";
      ctx.lineWidth = sure ? 2.5 : 2;
      ctx.beginPath();
      ctx.moveTo(X(v.line_x!), Y(PITCH_Y));
      ctx.lineTo(X(v.line_x!), Y(0));
      ctx.stroke();
      ctx.setLineDash([]);
      for (const p of v.players.filter((q) => q.role === "attacker" || q.role === "defender")) dot(view, p, { dim: true });
      for (const p of v.players.filter((q) => q.role === "second_last" || q.role === "receiver")) dot(view, p, { ring: "#fff" });
      ball(v, view);
      pill(view, headline(v), X(v.line_x!), Y(PITCH_Y) + 14, own);
      break;
    }
    case "counter": {
      arrow(view, v.pass!.from, v.pass!.to, "#fff", 3.5);
      pill(view, headline(v), (X(v.pass!.from.x) + X(v.pass!.to.x)) / 2, (Y(v.pass!.from.y) + Y(v.pass!.to.y)) / 2 - 22, own);
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
  const who = (p: VisualPlayer) => (p.id ? playerName(p.id, names) : `a ${teams[p.team]} player`);
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
    case "channels":
      return `Picture ${at}: ${club}'s passes by lane as they attack: ${v.bands!.map((b) => `${b.channel} ${Math.round(b.share)}%`).join(", ")}.`;
    case "offside": {
      const r = v.players.find((p) => p.role === "receiver")!;
      const call = v.verdict === "too_close" ? "too close to call: within what the tracking can measure" : `${v.verdict} by ${v.margin_m!.toFixed(1)} metres`;
      return `Picture ${at}: a line across the pitch at the second-last defender; ${who(r)} is ${call}.`;
    }
    case "counter":
      return `Picture ${at}: an arrow from where ${club} won the ball to their shot, ${v.seconds!.toFixed(0)} seconds later.`;
    case "counter_press": {
      const n = v.players.filter((p) => p.role === "presser").length;
      return `Picture ${at}: ${n} ${club} player${n === 1 ? "" : "s"} within ${v.radius_m} m of the ball, in a shaded circle.`;
    }
    case "shape":
      return `Picture ${at}: ${club}'s shape, ${v.lines!.length} line${v.lines!.length === 1 ? "" : "s"} drawn through their players.`;
    case "wind":
      return `Picture: how both teams moved from ${clock(v.t_from!)} to ${clock(v.t_to!)}, as arrows.`;
  }
}
