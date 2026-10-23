// The radar beside the broadcast video: the whole pitch from above, every tracked player, the ball,
// and the part of the pitch the broadcast picture shows. Drawn from radar.json (ninety/radar.py):
// vision's tracked positions and its own camera fit, never the answer key.
//
// Synced to the video through the clip's segments (ninety/match/timeline.py): the picture may cut
// from a dead ball to its restart, and nothing is ever drawn between two tracked frames on either
// side of a cut.

import type { Manifest } from "./bundle";

/** One tracked frame: schemas/frame.schema.json with `source: tracked` (ninety/vision/tracked_frames.py). */
export interface TrackedFrame {
  frame: number;
  t: number;
  source: string;
  ball: { x: number; y: number; z: number };
  /** `number` once the tracker reads shirts; today it does not, and none is drawn. */
  players: { id: string; team: "home" | "away"; x: number; y: number; number?: number }[];
}

export interface View {
  frame: number;
  ball_seen: boolean;
  footprint: [number, number][] | null;
}

export interface RadarData {
  format: number;
  source: string;
  clip: string | null;
  frames: TrackedFrame[];
  views: View[];
}

export type Segment = NonNullable<Manifest["segments"]>[number];

export interface Mark {
  x: number;
  y: number;
  /** Not seen in the frame on screen: placed between the sightings either side of it. */
  estimated: boolean;
}

export interface RadarPlayer extends Mark {
  id: string;
  team: "home" | "away";
  number?: number;
}

export interface RadarState {
  /** The match frame on screen. */
  frame: number;
  players: RadarPlayer[];
  ball: Mark | null;
  footprint: { points: [number, number][]; estimated: boolean } | null;
}

export const PITCH_X = 105; // Law 1 as the engine plays it (docs/GROUNDING.md, L1)
export const PITCH_Y = 68;
const RUNOFF = 3; // metres of grass drawn round the lines, so a player on the line is not cut (design)
/** The tracker's own: a track unseen for longer than this is closed, its prediction a guess
 * (ninety/vision/track.py, MAX_GAP_FRAMES). The radar draws nothing across a longer gap either. */
export const MAX_GAP_FRAMES = 25;

export const COLORS = {
  home: "#4ea1ff", // the phone minimap's (web/phone/src/pitch.ts), so the two read the same
  away: "#ffb02e",
  homeInk: "#04172b",
  awayInk: "#2a1800",
  ball: "#ffffff",
  grass: "#123d2b",
  stripe: "#15442f",
  line: "rgba(255,255,255,0.6)",
  view: "rgba(255,255,255,0.09)",
  viewLine: "rgba(255,255,255,0.7)",
};

/** The style a mark is drawn with: filled when seen, a hollow, fainter ring when estimated. */
export function markStyle(estimated: boolean): { filled: boolean; alpha: number } {
  return estimated ? { filled: false, alpha: 0.75 } : { filled: true, alpha: 1 };
}

interface Sighting {
  frame: number;
  x: number;
  y: number;
  number?: number;
}

/** The last sighting at or before `f`, by binary search. */
function before(s: Sighting[], f: number): number {
  let lo = 0;
  let hi = s.length - 1;
  if (hi < 0 || s[0].frame > f) return -1;
  while (lo < hi) {
    const mid = (lo + hi + 1) >> 1;
    if (s[mid].frame <= f) lo = mid;
    else hi = mid - 1;
  }
  return lo;
}

/** Where a mark is at continuous match frame `f`, from its sightings, inside [lo, hi) (the segment
 * on screen): between the sightings either side when they are at most MAX_GAP_FRAMES apart, at the
 * sighting itself when `f` is on it; estimated unless the frame on screen is one it was seen in. */
function place(s: Sighting[], f: number, lo: number, hi: number, smooth: boolean): (Mark & { at: Sighting }) | null {
  const k = Math.floor(f);
  const i = before(s, f);
  const a = i >= 0 && s[i].frame >= lo ? s[i] : null;
  const b = i + 1 < s.length && s[i + 1].frame < hi ? s[i + 1] : null;
  if (a && a.frame === k) {
    // Seen in the frame on screen; between it and the next frame's sighting while the video is between.
    if (smooth && b && b.frame === k + 1) {
      const w = f - k;
      return { x: a.x + (b.x - a.x) * w, y: a.y + (b.y - a.y) * w, estimated: false, at: a };
    }
    return { x: a.x, y: a.y, estimated: false, at: a };
  }
  if (!a || !b || b.frame - a.frame > MAX_GAP_FRAMES) return null;
  const w = ((smooth ? f : k) - a.frame) / (b.frame - a.frame);
  return { x: a.x + (b.x - a.x) * w, y: a.y + (b.y - a.y) * w, estimated: true, at: a };
}

/** Video time against match time across the broadcast's cuts (ninety/match/timeline.py): a bundle
 * without segments is one run of frames from its start. */
export function timeline(m: Pick<Manifest, "segments" | "t_start" | "fps" | "footage">) {
  const segs: Segment[] = m.segments?.length
    ? m.segments
    : [{ index: 0, frame: Math.round(m.t_start * m.fps), frames: m.footage.frames }];
  const matchTime = (v: number) => {
    const i = Math.max(0, Math.floor(v * m.fps));
    let seg = segs[0];
    for (const s of segs) if (s.index <= i) seg = s;
    return (seg.frame + (v * m.fps - seg.index)) / m.fps;
  };
  const videoTime = (t: number) => {
    const f = t * m.fps;
    for (const s of segs) {
      if (f < s.frame) return s.index / m.fps; // inside a cut: shown where the cut is
      if (f < s.frame + s.frames) return (s.index + f - s.frame) / m.fps;
    }
    const last = segs[segs.length - 1];
    return (last.index + last.frames) / m.fps;
  };
  /** The run of match frames [lo, hi) that holds match frame `k`. */
  const segmentOf = (k: number): [number, number] => {
    let seg = segs[0];
    for (const s of segs) if (s.frame <= k) seg = s;
    return [seg.frame, seg.frame + seg.frames];
  };
  return { matchTime, videoTime, segmentOf };
}

export class RadarModel {
  private players = new Map<string, { team: "home" | "away"; s: Sighting[] }>();
  private ball: Sighting[] = [];
  private views = new Map<number, View>();
  private viewFrames: Sighting[] = []; // frames with a footprint, for the nearest one

  constructor(
    data: RadarData,
    private fps: number,
    private segmentOf: (k: number) => [number, number],
  ) {
    if (data.source !== "tracked" || data.frames.some((f) => f.source !== "tracked")) {
      // The answer key never reaches the screen (AGENTS.md); ninety/radar.py refuses it too.
      throw new Error("radar.json holds positions that are not vision's tracked output");
    }
    const frames = [...data.frames].sort((a, b) => a.frame - b.frame);
    for (const f of frames) {
      this.ball.push({ frame: f.frame, x: f.ball.x, y: f.ball.y });
      for (const p of f.players) {
        let track = this.players.get(p.id);
        if (!track) this.players.set(p.id, (track = { team: p.team, s: [] }));
        track.s.push({ frame: f.frame, x: p.x, y: p.y, number: p.number });
      }
    }
    for (const v of data.views) {
      this.views.set(v.frame, v);
      if (v.footprint) this.viewFrames.push({ frame: v.frame, x: 0, y: 0 });
    }
    this.viewFrames.sort((a, b) => a.frame - b.frame);
  }

  /** What the radar shows at match time `t`. `smooth` glides between frames; without it (reduced
   * motion) every mark holds its frame's place. */
  at(t: number, smooth = true): RadarState {
    const f = t * this.fps;
    const k = Math.floor(f);
    const [lo, hi] = this.segmentOf(k);
    const players: RadarPlayer[] = [];
    for (const [id, track] of this.players) {
      const m = place(track.s, f, lo, hi, smooth);
      if (m) players.push({ id, team: track.team, x: m.x, y: m.y, estimated: m.estimated, number: m.at.number });
    }
    const b = place(this.ball, f, lo, hi, smooth);
    // The tracked file fills a short gap in the ball on a straight line; vision did not see it there.
    const ball = b ? { x: b.x, y: b.y, estimated: b.estimated || this.views.get(k)?.ball_seen === false } : null;
    let footprint: RadarState["footprint"] = null;
    const own = this.views.get(k)?.footprint;
    if (own) footprint = { points: own, estimated: false };
    else {
      const i = before(this.viewFrames, k);
      const near = i >= 0 ? this.viewFrames[i].frame : null;
      if (near !== null && near >= lo && k - near <= MAX_GAP_FRAMES)
        footprint = { points: this.views.get(near)!.footprint!, estimated: true };
    }
    return { frame: k, players, ball, footprint };
  }
}

/** Pitch metres onto the canvas, seen as the broadcast sees it: the main camera stands beyond the
 * y = 0 touchline (vision's camera fit puts it there), so that line is at the bottom, the far one at
 * the top, and x runs left to right as it does on the TV picture. */
export interface Projection {
  s: number; // canvas pixels per metre
  X: (x: number) => number;
  Y: (y: number) => number;
}

export function aspect(): number {
  return (PITCH_X + 2 * RUNOFF) / (PITCH_Y + 2 * RUNOFF);
}

export function projection(w: number): Projection {
  const s = w / (PITCH_X + 2 * RUNOFF);
  return { s, X: (x) => (RUNOFF + x) * s, Y: (y) => (RUNOFF + PITCH_Y - y) * s };
}

function drawPitch(ctx: CanvasRenderingContext2D, p: Projection, w: number, h: number) {
  const { s, X, Y } = p;
  const top = Y(PITCH_Y);
  ctx.fillStyle = COLORS.grass;
  ctx.fillRect(0, 0, w, h);
  ctx.fillStyle = COLORS.stripe;
  for (let i = 0; i < 12; i += 2) ctx.fillRect(X((i * PITCH_X) / 12), top, (PITCH_X / 12) * s, PITCH_Y * s);
  ctx.strokeStyle = COLORS.line;
  ctx.lineWidth = 1;
  ctx.setLineDash([]);
  ctx.strokeRect(X(0), top, PITCH_X * s, PITCH_Y * s);
  ctx.beginPath();
  ctx.moveTo(X(PITCH_X / 2), Y(0));
  ctx.lineTo(X(PITCH_X / 2), top);
  ctx.stroke();
  // Law 1: centre circle 9.15 m; penalty area 16.5 by 40.32 m, its mark 11 m out and its arc 9.15 m
  // from the mark; goal area 5.5 by 18.32 m; goal 7.32 m; corner arcs 1 m.
  ctx.beginPath();
  ctx.arc(X(PITCH_X / 2), Y(PITCH_Y / 2), 9.15 * s, 0, Math.PI * 2);
  ctx.stroke();
  ctx.fillStyle = COLORS.line;
  const spot = (x: number, y: number) => {
    ctx.beginPath();
    ctx.arc(X(x), Y(y), Math.max(1.2, 0.25 * s), 0, Math.PI * 2);
    ctx.fill();
  };
  spot(PITCH_X / 2, PITCH_Y / 2);
  for (const left of [true, false]) {
    const box = (depth: number, width: number) =>
      ctx.strokeRect(X(left ? 0 : PITCH_X - depth), Y((PITCH_Y + width) / 2), depth * s, width * s);
    box(16.5, 40.32);
    box(5.5, 18.32);
    spot(left ? 11 : PITCH_X - 11, PITCH_Y / 2);
    // The arc: the part of the 9.15 m circle round the mark that lies outside the area.
    const a = Math.acos((16.5 - 11) / 9.15);
    ctx.beginPath();
    if (left) ctx.arc(X(11), Y(PITCH_Y / 2), 9.15 * s, -a, a);
    else ctx.arc(X(PITCH_X - 11), Y(PITCH_Y / 2), 9.15 * s, Math.PI - a, Math.PI + a);
    ctx.stroke();
    // The goal, drawn outside the line.
    ctx.strokeRect(X(left ? -1.5 : PITCH_X), Y((PITCH_Y + 7.32) / 2), 1.5 * s, 7.32 * s);
  }
  // Corner arcs, each a quarter circle into the pitch from its canvas corner.
  const corners: [number, number, number][] = [
    [X(0), top, 0],
    [X(PITCH_X), top, Math.PI / 2],
    [X(PITCH_X), Y(0), Math.PI],
    [X(0), Y(0), (3 * Math.PI) / 2],
  ];
  for (const [cx, cy, start] of corners) {
    ctx.beginPath();
    ctx.arc(cx, cy, 1 * s, start, start + Math.PI / 2);
    ctx.stroke();
  }
}

export interface DrawOptions {
  reduceMotion: boolean;
  trail: { x: number; y: number }[]; // the ball's last places, oldest first
}

/** Marks never shrink below these, so a dot reads at phone width (CSS pixels). */
const PLAYER_R = 1.15; // metres
const PLAYER_MIN_PX = 5.5;
const BALL_MIN_PX = 3.5;

export function drawRadar(ctx: CanvasRenderingContext2D, w: number, h: number, state: RadarState | null, o: DrawOptions) {
  const p = projection(w);
  const { X, Y } = p;
  drawPitch(ctx, p, w, h);
  if (!state) return;

  // What the broadcast picture shows, inside the lines: the rest is pitch the main feed does not.
  if (state.footprint) {
    ctx.save();
    ctx.beginPath();
    ctx.rect(X(0), Y(PITCH_Y), PITCH_X * p.s, PITCH_Y * p.s);
    ctx.clip();
    ctx.beginPath();
    state.footprint.points.forEach(([x, y], i) => (i ? ctx.lineTo(X(x), Y(y)) : ctx.moveTo(X(x), Y(y))));
    ctx.closePath();
    ctx.fillStyle = COLORS.view;
    ctx.fill();
    ctx.setLineDash(state.footprint.estimated ? [4, 4] : []);
    ctx.strokeStyle = COLORS.viewLine;
    ctx.lineWidth = 1.5;
    ctx.stroke();
    ctx.restore();
    ctx.setLineDash([]);
  }

  const r = Math.max(PLAYER_MIN_PX, PLAYER_R * p.s);
  ctx.font = `700 ${Math.round(r * 1.15)}px system-ui, -apple-system, sans-serif`;
  ctx.textAlign = "center";
  ctx.textBaseline = "middle";
  // Seen players over estimated ones, so a hollow ring never hides a filled dot.
  const order = [...state.players].sort((a, b) => Number(b.estimated) - Number(a.estimated));
  for (const pl of order) {
    const st = markStyle(pl.estimated);
    const home = pl.team === "home";
    const fill = home ? COLORS.home : COLORS.away;
    const ink = home ? COLORS.homeInk : COLORS.awayInk;
    ctx.globalAlpha = st.alpha;
    ctx.beginPath();
    ctx.arc(X(pl.x), Y(pl.y), st.filled ? r : r - 1, 0, Math.PI * 2);
    if (st.filled) {
      ctx.fillStyle = fill;
      ctx.fill();
      // Away players carry a heavier dark outline, so the teams differ by more than colour.
      ctx.lineWidth = home ? 1 : 2;
      ctx.strokeStyle = home ? "rgba(0,0,0,0.55)" : ink;
      ctx.stroke();
      if (pl.number !== undefined) {
        ctx.fillStyle = ink;
        ctx.fillText(String(pl.number), X(pl.x), Y(pl.y) + 0.5);
      }
    } else {
      ctx.lineWidth = 2;
      ctx.strokeStyle = fill;
      ctx.stroke();
    }
  }
  ctx.globalAlpha = 1;

  if (state.ball) {
    const b = state.ball;
    const br = Math.max(BALL_MIN_PX, 0.7 * p.s);
    if (!o.reduceMotion && o.trail.length > 1) {
      ctx.lineCap = "round";
      for (let i = 1; i < o.trail.length; i++) {
        ctx.strokeStyle = `rgba(255,255,255,${(0.45 * i) / o.trail.length})`;
        ctx.lineWidth = Math.max(1, br * (i / o.trail.length));
        ctx.beginPath();
        ctx.moveTo(X(o.trail[i - 1].x), Y(o.trail[i - 1].y));
        ctx.lineTo(X(o.trail[i].x), Y(o.trail[i].y));
        ctx.stroke();
      }
    }
    const st = markStyle(b.estimated);
    ctx.globalAlpha = st.alpha;
    ctx.beginPath();
    ctx.arc(X(b.x), Y(b.y), br + 3, 0, Math.PI * 2);
    ctx.fillStyle = "rgba(255,255,255,0.18)"; // a halo, so the ball is the first thing the eye finds
    if (st.filled) ctx.fill();
    ctx.beginPath();
    ctx.arc(X(b.x), Y(b.y), br, 0, Math.PI * 2);
    if (st.filled) {
      ctx.fillStyle = COLORS.ball;
      ctx.fill();
      ctx.lineWidth = 1.5;
      ctx.strokeStyle = "#000";
      ctx.stroke();
    } else {
      ctx.lineWidth = 2;
      ctx.strokeStyle = COLORS.ball;
      ctx.stroke();
    }
    ctx.globalAlpha = 1;
  }
}

/** Words for a screen reader: what the radar shows, in the pitch's thirds. */
export function describe(state: RadarState | null): string {
  if (!state || (!state.players.length && !state.ball)) return "Radar: no tracked positions at this moment.";
  const home = state.players.filter((p) => p.team === "home").length;
  const away = state.players.length - home;
  const guessed = state.players.filter((p) => p.estimated).length;
  const third = (x: number) => (x < PITCH_X / 3 ? "home's defensive third" : x < (2 * PITCH_X) / 3 ? "the middle third" : "home's attacking third");
  const parts = [`Radar: ${home} home and ${away} away players tracked${guessed ? `, ${guessed} placed between sightings` : ""}`];
  if (state.ball) parts.push(`the ball in ${third(state.ball.x)}${state.ball.estimated ? ", estimated" : ""}`);
  if (state.footprint) {
    const xs = state.footprint.points.map(([x]) => Math.min(PITCH_X, Math.max(0, x)));
    parts.push(`the broadcast camera shows ${Math.round(Math.min(...xs))} to ${Math.round(Math.max(...xs))} metres along the pitch`);
  }
  return `${parts.join("; ")}.`;
}
