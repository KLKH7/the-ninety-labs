// The bundle `ninety-e2e` writes (ninety/e2e.py), and the one rule for what is on screen.

export type Persona = "casual" | "analyst";

/** schemas/overlay_cue.schema.json */
export interface Cue {
  id: string;
  t_in: number;
  t_out: number;
  kind: "player_tag" | "speed_badge" | "pass_arc" | "shot_speed" | "insight" | "recap" | "audio_description";
  slot: string;
  anchor?: { px: number; py: number } | null;
  persona: string;
  lang: string;
  text: string;
  pan?: number;
  replaces?: string | null;
  verified?: boolean;
  evidence: string[];
}

/** schemas/agent_trace.schema.json (PR #105) */
export interface Step {
  role: string;
  moment: string;
  action: string;
  ms: number;
  detail: string;
}

export interface ClaimTrace {
  id: string;
  minute: number;
  t: number | null;
  status: "accepted" | "held_back";
  drafts: number;
  planted: boolean;
  mode: string;
  text: string;
  evidence: string[];
  steps: Step[];
}

export interface Manifest {
  format: number;
  clip: string;
  fps: number;
  width: number;
  height: number;
  t_start: number;
  footage: { kind: "video" | "frames"; src: string; pattern?: string; frames: number };
  detector: string | null;
  detections: { source: string; frames: number };
  events: { source: string; count: number };
  facts: number;
  agents: { mode: string; planted: boolean; claims: number; accepted: number };
  cues: number;
}

export interface FrameDetections {
  frame: number;
  t: number;
  detections: { cls: "player" | "ball"; bbox: [number, number, number, number]; score: number }[];
}

export interface Bundle {
  base: string;
  manifest: Manifest;
  cues: Cue[];
  claims: ClaimTrace[];
  detections: FrameDetections[];
}

export const BUNDLE_FORMAT = 1;

function jsonl<T>(text: string): T[] {
  return text
    .split("\n")
    .filter((line) => line.trim())
    .map((line) => JSON.parse(line) as T);
}

async function get(base: string, file: string): Promise<string> {
  const res = await fetch(base + file);
  if (!res.ok) throw new Error(`${base}${file}: ${res.status} ${res.statusText}`);
  return res.text();
}

export async function loadBundle(base: string): Promise<Bundle> {
  const manifest = JSON.parse(await get(base, "manifest.json")) as Manifest;
  if (manifest.format !== BUNDLE_FORMAT) {
    throw new Error(`bundle format ${manifest.format}; this viewer reads format ${BUNDLE_FORMAT}`);
  }
  const [cues, trace, detections] = await Promise.all([
    get(base, "cues.jsonl").then((t) => jsonl<Cue>(t)),
    get(base, "trace.json").then((t) => JSON.parse(t) as { claims: ClaimTrace[] }),
    get(base, "detections.jsonl").then((t) => jsonl<FrameDetections>(t)),
  ]);
  return { base, manifest, cues, claims: trace.claims, detections };
}

/**
 * What is on air at match time `t` for `persona`: in each slot, the cue that came in last. A cue
 * that names another in `replaces` takes that one's place even if it came in earlier.
 */
export function onAir(cues: Cue[], persona: Persona, t: number): Cue[] {
  const live = cues.filter((c) => c.persona === persona && c.t_in <= t && t < c.t_out);
  const replaced = new Set(live.map((c) => c.replaces).filter((id): id is string => !!id));
  const bySlot = new Map<string, Cue>();
  for (const cue of live) {
    if (replaced.has(cue.id)) continue;
    const held = bySlot.get(cue.slot);
    if (!held || cue.t_in > held.t_in || (cue.t_in === held.t_in && cue.id > held.id)) bySlot.set(cue.slot, cue);
  }
  return [...bySlot.values()];
}

/** Match clock as mm:ss, the broadcast way. */
export function clock(t: number): string {
  const s = Math.max(0, Math.floor(t));
  return `${String(Math.floor(s / 60)).padStart(2, "0")}:${String(s % 60).padStart(2, "0")}`;
}
