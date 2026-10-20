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
  type Minimap,
  type MinimapFrame,
  PITCH_X,
  PITCH_Y,
  type PlayerCard,
  type Question,
  type RelayMessage,
  type Team,
  type ViewerAnswer,
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

const round = (v: number, places: number) => Math.round(v * 10 ** places) / 10 ** places;
const cell = (v: number, length: number, n: number) => Math.min(n - 1, Math.max(0, Math.floor((v / length) * n)));

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
      source: "tracked",
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
      source: "tracked",
    };
  }

  async ask(q: Question): Promise<AnswerMessage> {
    const lowered = q.text.toLowerCase();
    const metric = METRIC_WORDS.find(([, words]) => words.test(lowered))?.[0] ?? null;
    const none = (text: string, from: number | null = null, to: number | null = null): ViewerAnswer => ({
      status: "unanswerable", text, metric: null, value: null, unit: null, evidence: [], t_from: from, t_to: to,
    });
    if (q.player === null) return { type: "answer", answer: none(`Tap a player first, then ask about ${ASKABLE}.`) };
    const card = await this.card("mock", q.player, q.t);
    if (metric === null) {
      return {
        type: "answer",
        answer: none(`I can only answer about ${q.player}'s speed, top speed and distance run.`, card.t_from, card.t_to),
      };
    }
    const [value, unit] =
      metric === "speed_now" ? [card.speed_kmh, "km/h"] : metric === "peak_speed" ? [card.peak_kmh, "km/h"] : [card.distance_m, "m"];
    const scope = `player_${q.player}_window_${card.t_from.toFixed(2)}-${card.t_to.toFixed(2)}`;
    return {
      type: "answer",
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
