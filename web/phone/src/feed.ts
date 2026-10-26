// Where the phone's data comes from: the companion API (ninety/api/companion.py), or the mock
// (mock.ts) until tracked positions exist. Both go through `guarded`, so the UI never holds a
// position, a card or a flow field computed from the ground-truth data (AGENTS.md: the answer key
// is for training and grading only).

import type { AnswerMessage, Flow, InsightCard, Minimap, PlayerCard, Question, RelayMessage, Team } from "./types";

/** Why the relay closed, from the API's close codes (ninety/api/companion.py, relay). */
export type Closed = "unknown-code" | "room-full" | "expired" | "refused" | "lost" | "not-joined";

export function closedBy(code: number): Closed {
  if (code === 4404 || code === 4400) return "unknown-code";
  if (code === 4429) return "room-full";
  if (code === 4410) return "expired";
  if (code === 1007 || code === 1008) return "refused";
  return "lost";
}

export interface Link {
  close(): void;
}

export interface Feed {
  /** True when nothing here comes from a match: the UI says "Mock data" on every screen. */
  readonly mock: boolean;
  /** The clip a pairing code belongs to. */
  clipOf(code: string): Promise<string>;
  /** Listens to the laptop. Resolves once the room accepted the phone; rejects with a Closed. */
  join(code: string, on: (m: RelayMessage) => void, closed: (why: Closed) => void): Promise<Link>;
  minimap(clip: string): Promise<Minimap>;
  card(clip: string, player: string, tTo: number): Promise<PlayerCard>;
  flow(clip: string, team: Team, tFrom: number, tTo: number): Promise<Flow>;
  /** With the demo passcode, the server's agents answer (ninety/api/companion.py, x-ninety-passcode). */
  ask(question: Question, passcode?: string | null): Promise<AnswerMessage>;
  /** The hidden-stat cards pushed so far, up to match time `tTo`. */
  insights(clip: string, tTo: number): Promise<InsightCard[]>;
}

/** A payload computed from the ground-truth data reached the phone; it is never shown. */
export class GroundTruth extends Error {
  constructor(what: string) {
    super(`${what} came from the ground-truth data (source: truth); the phone shows only tracked positions`);
  }
}

/** An API error the phone can say in words. */
export class ApiError extends Error {
  constructor(
    readonly status: number,
    message: string,
  ) {
    super(message);
  }
}

/** The feed with every positional payload checked: from the API, anything not `source: tracked`
 * throws; from the mock, anything not `source: mock`, so made-up data can never pass as tracked. */
export function guarded(feed: Feed, seen: (payload: unknown) => void = () => {}): Feed {
  const allowed = feed.mock ? "mock" : "tracked";
  const onlyTracked = <T extends { source: string }>(what: string, payload: T): T => {
    if (payload.source !== allowed) throw new GroundTruth(what);
    return payload;
  };
  const record = <T>(p: T): T => {
    seen(p);
    return p;
  };
  return {
    mock: feed.mock,
    clipOf: (code) => feed.clipOf(code),
    join: (code, on, closed) => feed.join(code, (m) => on(record(m)), closed),
    minimap: async (clip) => onlyTracked("The minimap", record(await feed.minimap(clip))),
    card: async (clip, player, tTo) => onlyTracked("The player card", record(await feed.card(clip, player, tTo))),
    flow: async (clip, team, tFrom, tTo) => onlyTracked("The wind map", record(await feed.flow(clip, team, tFrom, tTo))),
    // An answer carries no source of its own: the UI asks only once the clip's minimap passed the
    // guard (main.ts), and the API refuses questions about ground-truth clips when deployed (503).
    ask: async (q, pass) => record(await feed.ask(q, pass)),
    // A card carries no positions' source of its own (its `source` is its author, code or model):
    // the Scout builds cards only from tracked facts, and the fact-checker passed each one.
    insights: async (clip, tTo) => (await feed.insights(clip, tTo)).map((c) => record(c)),
  };
}

async function json<T>(response: Response): Promise<T> {
  const body = await response.json().catch(() => ({}));
  if (!response.ok) throw new ApiError(response.status, (body as { error?: string }).error ?? response.statusText);
  return body as T;
}

/** The companion API on this page's own origin (the API serves the phone at /phone/). */
export class HttpFeed implements Feed {
  readonly mock = false;

  constructor(private readonly base = new URL("../", location.href)) {}

  private url(path: string, query: Record<string, number> = {}): string {
    const u = new URL(path, this.base);
    for (const [k, v] of Object.entries(query)) u.searchParams.set(k, String(Math.round(v * 100) / 100));
    return u.toString();
  }

  async clipOf(code: string): Promise<string> {
    const room = await json<{ clip: string }>(await fetch(this.url(`api/pair/${encodeURIComponent(code)}`)));
    return room.clip;
  }

  join(code: string, on: (m: RelayMessage) => void, closed: (why: Closed) => void): Promise<Link> {
    const u = new URL(this.url(`api/pair/${encodeURIComponent(code)}`));
    u.protocol = u.protocol === "https:" ? "wss:" : "ws:";
    u.searchParams.set("role", "phone");
    return new Promise((resolve, reject) => {
      const ws = new WebSocket(u);
      let open = false;
      ws.addEventListener("open", () => {
        open = true;
        resolve({ close: () => ws.close(1000) });
      });
      ws.addEventListener("message", (e) => {
        try {
          on(JSON.parse(String(e.data)) as RelayMessage);
        } catch {
          /* not JSON: the API only sends schema-checked messages, so ignore it */
        }
      });
      ws.addEventListener("close", (e) => {
        if (e.code === 1000 && open) return;
        if (open) closed(closedBy(e.code));
        // A close before the server accepted reaches a browser as 1006 whatever code the server
        // chose, so an unknown code and an unreachable server look the same here.
        else reject(e.code === 1006 ? "not-joined" : closedBy(e.code));
      });
    });
  }

  async minimap(clip: string): Promise<Minimap> {
    return json(await fetch(this.url(`api/minimap/${encodeURIComponent(clip)}`, { fps: 5 })));
  }

  async card(clip: string, player: string, tTo: number): Promise<PlayerCard> {
    return json(await fetch(this.url(`api/card/${encodeURIComponent(clip)}/${encodeURIComponent(player)}`, { t_to: tTo })));
  }

  async flow(clip: string, team: Team, tFrom: number, tTo: number): Promise<Flow> {
    return json(await fetch(this.url(`api/flow/${encodeURIComponent(clip)}/${team}`, { t_from: tFrom, t_to: tTo })));
  }

  async ask(question: Question, passcode?: string | null): Promise<AnswerMessage> {
    // Without a passcode the API answers in code (Replay mode, SECURITY.md); with the demo's, its
    // agents draft and the fact-checker gates. The question is sent as JSON data; the server
    // validates it against viewer_question.schema.json.
    const post = (pass?: string | null) =>
      fetch(this.url("api/ask"), {
        method: "POST",
        headers: { "content-type": "application/json", ...(pass ? { "x-ninety-passcode": pass } : {}) },
        body: JSON.stringify(question),
      });
    const response = await post(passcode);
    // A wrong passcode (401) or a server with no model (503): the code answer, quietly, marked.
    if (passcode && (response.status === 401 || response.status === 503)) return { ...(await json<AnswerMessage>(await post(null))), model_off: true };
    return json(response);
  }

  async insights(clip: string, tTo: number): Promise<InsightCard[]> {
    const body = await json<{ cards: InsightCard[] }>(await fetch(this.url(`api/insights/${encodeURIComponent(clip)}`, { t_to: tTo })));
    return body.cards;
  }
}
