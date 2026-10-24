// The mock feed: the companion API's answers, made in the browser from mock/minimap.json (positions
// from a formula, not a match: mock/make_mock.py). It lets the phone be built and tested before
// tracked positions exist. The page says "Mock data" whenever this feed is on.
//
// The numbers follow the API's definitions (ninety/intel/window.py): speed now is the mean over the
// last second, top speed the highest such mean, distance the path length, the heat map the share
// of frames per cell of a 12 x 8 grid, and the flow field each team's mean velocity per cell.

import minimapUrl from "../mock/minimap.json?url";
import type { Closed, Feed, Link } from "./feed";
import { joinMock } from "./mockrelay";
import {
  type AnswerMessage,
  type Flow,
  type InsightCard,
  type Minimap,
  type MinimapFrame,
  PITCH_X,
  PITCH_Y,
  type PlayerCard,
  type Question,
  type RelayMessage,
  type Team,
  type ViewerAnswer,
  type ScoutPoint,
  type ScoutVisual,
  type Visual,
  type VisualKind,
  type VisualPlayer,
  clock,
  playerName,
  teams,
} from "./types";

const NX = 12;
const NY = 8;

// The API's metric words and answer templates (ninety/agents/companion.py), so the mock answers
// the questions the real one does, and refuses the same ones.
const METRIC_WORDS: [string, RegExp][] = [
  ["peak_speed", /\b(?:top|max(?:imum)?|peak|highest|fastest|quickest)\b/],
  ["distance_run", /\b(?:how far|distance|covered|cover|metres|meters|kilomet\w*|kms?(?!\/))\b/],
  ["speed_now", /\b(?:speed|how fast|fast|pace|quick|running at|km\/h|kph)/],
];
const CODE_TEXT: Record<string, (p: string, v: string) => string> = {
  speed_now: (p, v) => `${p} is moving at ${v} km/h right now.`,
  peak_speed: (p, v) => `${p}'s top speed so far is ${v} km/h.`,
  distance_run: (p, v) => `${p} has covered ${v} m so far.`,
};
const ASKABLE = "their speed now, their top speed or how far they have run";

// The mock's stand-ins for the insight tools (the real ones are the agents' MCP tools): each picture
// is computed here from the mock positions at one frame, so its numbers agree with the mock radar.
const VISUAL_WORDS: [VisualKind, RegExp][] = [
  ["overload", /\b(?:overload\w*|outnumber\w*|\d+ ?v ?\d+)\b/],
  ["line_break", /\b(?:line[- ]?break\w*|bypass\w*)\b|\b(?:break|breaks|breaking|broke)\b.*\blines?\b/],
  ["pass_options", /\b(?:pass(?:ing)? options?|options?|open|free man)\b/],
  ["shape", /\b(?:shape|formation|set up|lines?)\b/],
  ["wind", /\b(?:moving|movement|wind|flow|pushing|dropping)\b/],
];
const ZONE_M = 12; // design: half the side of the overload box round the ball (24 m, about a third of the width)
const OPEN_M = 5; // design: a teammate with no opponent within 5 m is "open" in the mock
const INSIGHT_AT: [number, VisualKind, Team][] = [
  [18, "overload", "home"],
  [41, "line_break", "home"],
  [63, "pass_options", "away"],
  [86, "line_break", "away"], // cards carry no shape kind (schemas/insight_card.schema.json)
  [104, "overload", "away"],
];

const round = (v: number, places: number) => Math.round(v * 10 ** places) / 10 ** places;
const cell = (v: number, length: number, n: number) => Math.min(n - 1, Math.max(0, Math.floor((v / length) * n)));

/** The mock's pictures, from the mock frame nearest `t`. */
export function mockVisual(m: Minimap, kind: VisualKind, side: Team, t: number): Visual {
  const f = m.frames.reduce((a, b) => (Math.abs(b.t - t) < Math.abs(a.t - t) ? b : a));
  const sign = side === "home" ? 1 : -1; // home attacks toward x = 105 (pitch.ts, attacksRight)
  const all: VisualPlayer[] = f.players.map(([id, x, y]) => ({ id, team: id.startsWith("h") ? "home" : "away", x, y }));
  const mine = all.filter((p) => p.team === side);
  const theirs = all.filter((p) => p.team !== side);
  const [bx, by] = f.ball;
  const ball = { x: bx, y: by };
  const nearest = (ps: VisualPlayer[], x: number, y: number) => ps.reduce((a, b) => (Math.hypot(b.x - x, b.y - y) < Math.hypot(a.x - x, a.y - y) ? b : a));
  const base = { t: f.t, team: side, ball };
  if (kind === "overload") {
    const zone = { x0: bx - ZONE_M, x1: bx + ZONE_M, y0: Math.max(0, by - ZONE_M), y1: Math.min(PITCH_Y, by + ZONE_M) };
    const inside = (p: VisualPlayer) => p.x >= zone.x0 && p.x <= zone.x1 && p.y >= zone.y0 && p.y <= zone.y1;
    const players = all.map((p) => (inside(p) ? { ...p, role: p.team === side ? ("attacker" as const) : ("defender" as const) } : p));
    return { ...base, kind, players, zone, count: { for: mine.filter(inside).length, against: theirs.filter(inside).length } };
  }
  if (kind === "line_break") {
    const from = nearest(mine, bx, by);
    const to = mine.filter((p) => p.id !== from.id).reduce((a, b) => (sign * b.x > sign * a.x ? b : a)); // a pass goes to someone else
    const lo = Math.min(from.x, to.x);
    const hi = Math.max(from.x, to.x);
    const passed = new Set(theirs.filter((p) => p.x > lo && p.x < hi).map((p) => p.id));
    const players = all.map((p) => (p.id === from.id ? { ...p, role: "passer" as const } : p.id === to.id ? { ...p, role: "receiver" as const } : passed.has(p.id) ? { ...p, role: "bypassed" as const } : p));
    return { ...base, kind, players, pass: { from: { x: from.x, y: from.y }, to: { x: to.x, y: to.y } }, bypassed: passed.size };
  }
  if (kind === "pass_options") {
    const carrier = nearest(mine, bx, by);
    const players = all.map((p): VisualPlayer => {
      if (p.id === carrier.id) return { ...p, role: "carrier" };
      if (p.team !== side) return p;
      const marker = nearest(theirs, p.x, p.y);
      return { ...p, role: Math.hypot(marker.x - p.x, marker.y - p.y) > OPEN_M ? "open" : "marked" };
    });
    return { ...base, kind, players };
  }
  if (kind === "shape") {
    // The mock's 4-3-3 by depth: the deepest player is the keeper, then four, three and three.
    const byDepth = [...mine].sort((a, b) => sign * a.x - sign * b.x).slice(1);
    const lines = [byDepth.slice(0, 4), byDepth.slice(4, 7), byDepth.slice(7)].map((l) => [...l].sort((a, b) => a.y - b.y).map(({ x, y }) => ({ x, y })));
    return { ...base, kind, players: all, lines };
  }
  return { ...base, kind, players: [], t_from: Math.max(0, f.t - 30), t_to: f.t };
}

/** The mock's picture in the agents' shape as committed (schemas/insight_card.schema.json,
 * $defs/visual: points are [x, y]; a shape carries its minute only), so the phone reads the mock
 * exactly as it reads the Scout. Counts are the lengths of the lists. */
export function toScout(v: Visual): ScoutVisual {
  const pt = (p: { x: number; y: number }): ScoutPoint => [p.x, p.y];
  const of = (role: string) => v.players.filter((p) => p.role === role).map(pt);
  const base = { fact: `mock:${v.kind}:${v.t.toFixed(1)}`, t: v.t, team: v.team, club: teams[v.team] };
  switch (v.kind) {
    case "overload": {
      const mine = of("attacker");
      const theirs = of("defender");
      return { ...base, kind: "overload", geometry: { zone: v.zone!, home: v.team === "home" ? mine : theirs, away: v.team === "home" ? theirs : mine } };
    }
    case "line_break":
      return { ...base, kind: "line_break", geometry: { from: of("passer")[0], to: of("receiver")[0], bypassed: of("bypassed") } };
    case "pass_options":
      return { ...base, kind: "pass_options", geometry: { passer: of("carrier")[0], target: null, open: of("open"), marked: of("marked"), radius_m: OPEN_M } };
    case "shape":
      return { ...base, kind: "shape", geometry: { minute: Math.floor(v.t / 60) + 1 } };
    default:
      return { ...base, kind: "wind_map", geometry: { t_from: v.t_from!, t_to: v.t_to! } };
  }
}

/** Why a mock picture matters, from its own numbers: the precomputed "why?" a card carries. */
function mockWhy(v: Visual): string {
  const club = teams[v.team];
  switch (v.kind) {
    case "overload":
      return `With ${v.count!.for} against ${v.count!.against} round the ball, ${club} always had a spare player to pass to.`;
    case "line_break":
      return `A pass that goes past ${v.bypassed} defender${v.bypassed === 1 ? "" : "s"} leaves them behind the ball, so ${club} attack fewer players.`;
    case "pass_options":
      return `${v.players.filter((p) => p.role === "open").length} teammates had no one within ${OPEN_M} m, so the pass was on.`;
    default:
      return `It shows how ${club} were set up at that moment.`;
  }
}

/** What a mock picture says, in a sentence built from its own numbers. */
function mockText(v: Visual, names?: Record<string, string>): { title: string; text: string; value: number | null; unit: string | null } {
  const club = teams[v.team];
  const who = (role: string) => {
    const p = v.players.find((q) => q.role === role);
    return p?.id ? playerName(p.id, names) : `a ${club} player`;
  };
  switch (v.kind) {
    case "overload":
      return { title: `${club} overload`, text: `${club} had ${v.count!.for} player${v.count!.for === 1 ? "" : "s"} against ${v.count!.against} round the ball at ${clock(v.t)}.`, value: v.count!.for, unit: v.count!.for === 1 ? "player" : "players" };
    case "line_break":
      return { title: `${club} break the lines`, text: `${who("passer")}'s pass to ${who("receiver")} went past ${v.bypassed} defender${v.bypassed === 1 ? "" : "s"}.`, value: v.bypassed!, unit: "bypassed" };
    case "pass_options": {
      const open = v.players.filter((p) => p.role === "open").length;
      return { title: `${who("carrier")}'s options`, text: `${who("carrier")} had ${open} teammates with no opponent within ${OPEN_M} m.`, value: open, unit: "open" };
    }
    case "shape":
      return { title: `${club}'s shape`, text: `${club} lined up in ${v.lines!.map((l) => l.length).join("-")} at ${clock(v.t)}.`, value: null, unit: null };
    case "counter_press":
      return { title: `${club} press`, text: `${club} pressed the ball.`, value: null, unit: null };
    case "channels":
    case "offside":
    case "counter":
    case "one_two":
      return { title: club, text: `${club} at ${clock(v.t)}.`, value: null, unit: null }; // the mock makes none of these
    case "wind":
      return { title: "How the teams moved", text: `Both teams' movement from ${clock(v.t_from!)} to ${clock(v.t_to!)}.`, value: null, unit: null };
  }
}

export class MockFeed implements Feed {
  readonly mock = true;
  private data: Promise<Minimap> | null = null;

  private load(): Promise<Minimap> {
    this.data ??= fetch(minimapUrl).then((r) => r.json() as Promise<Minimap>);
    return this.data;
  }

  private async window(tFrom: number, tTo: number): Promise<MinimapFrame[]> {
    const m = await this.load();
    const end = Math.min(tTo, m.frames[m.frames.length - 1].t);
    return m.frames.filter((f) => f.t >= tFrom - 1e-6 && f.t <= end + 1e-6);
  }

  async clipOf(): Promise<string> {
    return "mock";
  }

  async join(code: string, on: (m: RelayMessage) => void): Promise<Link> {
    try {
      return await joinMock(code, on);
    } catch (why) {
      throw why as Closed;
    }
  }

  minimap(): Promise<Minimap> {
    return this.load();
  }

  async card(clip: string, player: string, tTo: number): Promise<PlayerCard> {
    void clip;
    const frames = await this.window(0, tTo);
    const at = frames.map((f) => f.players.find((p) => p[0] === player)!);
    const fps = (await this.load()).fps;
    const steps = at.slice(1).map((p, i) => Math.hypot(p[1] - at[i][1], p[2] - at[i][2]));
    // Speed over each second: the path length of the last fps steps (the API's speed_now).
    const perSecond = steps.map((_, i) => (i + 1 >= fps ? steps.slice(i + 1 - fps, i + 1).reduce((a, b) => a + b, 0) : 0));
    const cells = new Array(NX * NY).fill(0);
    for (const p of at) cells[cell(p[2], PITCH_Y, NY) * NX + cell(p[1], PITCH_X, NX)] += 1;
    return {
      type: "player_card",
      player,
      t_from: 0,
      t_to: frames.length ? frames[frames.length - 1].t : 0,
      heat: { nx: NX, ny: NY, cells: cells.map((c) => round(c / Math.max(1, at.length), 4)) },
      speed_kmh: round((perSecond[perSecond.length - 1] ?? 0) * 3.6, 1),
      peak_kmh: round(Math.max(0, ...perSecond) * 3.6, 1),
      distance_m: round(steps.reduce((a, b) => a + b, 0), 0),
      source: "mock",
    };
  }

  async flow(clip: string, team: Team, tFrom: number, tTo: number): Promise<Flow> {
    void clip;
    const frames = await this.window(tFrom, tTo);
    const prefix = team === "home" ? "h" : "a";
    const sx = new Array(NX * NY).fill(0);
    const sy = new Array(NX * NY).fill(0);
    const count = new Array(NX * NY).fill(0);
    for (let i = 1; i < frames.length; i++) {
      const dt = frames[i].t - frames[i - 1].t;
      const before = new Map(frames[i - 1].players.map((p) => [p[0], p]));
      for (const p of frames[i].players) {
        const q = before.get(p[0]);
        if (!q || !p[0].startsWith(prefix)) continue;
        const k = cell(q[2], PITCH_Y, NY) * NX + cell(q[1], PITCH_X, NX);
        sx[k] += (p[1] - q[1]) / dt;
        sy[k] += (p[2] - q[2]) / dt;
        count[k] += 1;
      }
    }
    return {
      type: "flow",
      team,
      t_from: frames.length ? frames[0].t : tFrom,
      t_to: frames.length ? frames[frames.length - 1].t : tTo,
      nx: NX,
      ny: NY,
      vx: count.map((c, k) => (c ? round(sx[k] / c, 2) : null)),
      vy: count.map((c, k) => (c ? round(sy[k] / c, 2) : null)),
      count,
      source: "mock",
    };
  }

  async insights(clip: string, tTo: number): Promise<InsightCard[]> {
    void clip;
    const m = await this.load();
    return INSIGHT_AT.filter(([t]) => t <= tTo).map(([t, kind, side], i) => {
      const visual = mockVisual(m, kind, side, t);
      const said = mockText(visual);
      const scout = toScout(visual);
      const evidence = [`${kind}:mock_${t}`];
      return {
        id: `mock-insight-${i + 1}`,
        t,
        minute: Math.floor(t / 60) + 1,
        team: side,
        club: teams[side],
        kind,
        headline: said.title.slice(0, 40),
        text: said.text,
        status: "verified",
        source: "code",
        evidence,
        visual: scout,
        why: { question: `Why does that matter at ${clock(t)}?`, answer: { status: "verified", text: mockWhy(visual), evidence, visual: scout } },
      };
    });
  }

  async ask(q: Question): Promise<AnswerMessage> {
    const lowered = q.text.toLowerCase();
    const kind = VISUAL_WORDS.find(([, words]) => words.test(lowered))?.[0];
    if (kind) {
      const m = await this.load();
      const side: Team = new RegExp(`\\b${teams.away.toLowerCase()}\\b`).test(lowered) ? "away" : q.player?.startsWith("a") ? "away" : "home";
      const visual = mockVisual(m, kind, side, q.t);
      const said = mockText(visual);
      return {
        type: "answer",
        source: "code",
        answer: {
          status: "verified",
          text: said.text,
          metric: kind,
          value: said.value,
          unit: said.unit,
          evidence: [`${kind}:mock_${visual.t.toFixed(1)}`],
          t_from: visual.t_from ?? visual.t,
          t_to: visual.t_to ?? visual.t,
          // follow_ups and spoken arrive with the Scout's next schema (PR B); the phone reads them already.
          visual: toScout(visual),
        },
      };
    }
    const metric = METRIC_WORDS.find(([, words]) => words.test(lowered))?.[0] ?? null;
    const none = (text: string, from: number | null = null, to: number | null = null): ViewerAnswer => ({
      status: "unanswerable", text, metric: null, value: null, unit: null, evidence: [], t_from: from, t_to: to,
    });
    if (q.player === null) {
      return { type: "answer", source: "code", answer: none(`Tap a player first, then ask about ${ASKABLE}.`) };
    }
    const card = await this.card("mock", q.player, q.t);
    if (metric === null) {
      return {
        type: "answer",
        source: "code",
        answer: none(`I can only answer about ${q.player}'s speed, top speed and distance run.`, card.t_from, card.t_to),
      };
    }
    const [value, unit] =
      metric === "speed_now" ? [card.speed_kmh, "km/h"] : metric === "peak_speed" ? [card.peak_kmh, "km/h"] : [card.distance_m, "m"];
    const scope = `player_${q.player}_window_${card.t_from.toFixed(2)}-${card.t_to.toFixed(2)}`;
    // A code answer, as the API's without the passcode: it never claims "model", so it is never
    // shown as fact-checked (main.ts, badgeFor).
    return {
      type: "answer",
      source: "code",
      answer: {
        status: "verified",
        text: CODE_TEXT[metric](q.player, String(value)),
        metric,
        value,
        unit,
        evidence: [`${metric}:${scope}`],
        t_from: card.t_from,
        t_to: card.t_to,
      },
    };
  }
}
