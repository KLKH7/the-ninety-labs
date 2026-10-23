import { DEFAULT_TEAMS, type TeamNames, playerLabel } from "../../viewer/src/teams";

// The shapes the phone reads, mirroring schemas/companion_message.schema.json,
// schemas/minimap.schema.json, schemas/viewer_question.schema.json and viewer_answer.schema.json.
// tests/test_phone.py validates every payload the phone received against those schemas.

/** Where positions come from. "mock" is the phone's own made-up data (mock.ts), never the API's. */
export type Source = "truth" | "tracked" | "mock";
export type Team = "home" | "away";

export interface ClockMessage {
  type: "clock";
  t: number;
  playing: boolean;
}

export interface FocusMessage {
  type: "focus";
  player: string | null;
}

/** What the laptop relays to the phone. */
export type RelayMessage = ClockMessage | FocusMessage;

export interface MinimapFrame {
  t: number;
  ball: [number, number];
  players: [string, number, number][];
}

export interface Minimap {
  clip: string;
  source: Source;
  fps: number;
  roster: string[];
  frames: MinimapFrame[];
}

export interface PlayerCard {
  type: "player_card";
  player: string;
  t_from: number;
  t_to: number;
  heat: { nx: number; ny: number; cells: number[] };
  speed_kmh: number;
  peak_kmh: number;
  distance_m: number;
  source: Source;
}

export interface Flow {
  type: "flow";
  team: Team;
  t_from: number;
  t_to: number;
  nx: number;
  ny: number;
  vx: (number | null)[];
  vy: (number | null)[];
  count: number[];
  source: Source;
}

export interface Question {
  session: string;
  player: string | null;
  text: string;
  t: number;
}

/** What an answer's or a card's picture shows (schemas/viewer_answer.schema.json, `visual`). Every
 * position and number in it comes from the tool the agent cited; the phone only draws it. */
export type VisualKind = "overload" | "line_break" | "pass_options" | "shape" | "wind";
export type VisualRole = "attacker" | "defender" | "passer" | "receiver" | "bypassed" | "open" | "marked" | "carrier";
export interface Point {
  x: number;
  y: number;
}
export interface VisualPlayer extends Point {
  id: string;
  team: Team;
  role?: VisualRole;
}
export interface Visual {
  kind: VisualKind;
  t: number;
  team: Team;
  players: VisualPlayer[];
  ball?: Point | null;
  zone?: { x0: number; x1: number; y0: number; y1: number } | null;
  count?: { for: number; against: number } | null;
  pass?: { from: Point; to: Point } | null;
  bypassed?: number | null;
  lines?: Point[][] | null;
  t_from?: number | null;
  t_to?: number | null;
}

/** A pushed "hidden stat" (schemas/companion_message.schema.json, `insight_card`). */
export interface InsightCard {
  type: "insight_card";
  id: string;
  t: number;
  team: Team;
  title: string;
  text: string;
  metric: string | null;
  value: number | null;
  unit: string | null;
  evidence: string[];
  visual: Visual | null;
  /** What "Why?" asks the Companion. */
  question: string;
  names?: Record<string, string>;
  source: Source;
}

export interface ViewerAnswer {
  status: "verified" | "held" | "rejected" | "unanswerable";
  /** Who wrote the text, copied from the answer message's `source` (main.ts): "model" (the
   * Companion agent, then the code checks and the Judge) or "code" (a template filled from the
   * cited fact, through the code checks only). Missing (an older server) counts as code. */
  source?: "code" | "model";
  text: string;
  metric: string | null;
  value: number | null;
  unit: string | null;
  evidence: string[];
  t_from: number | null;
  t_to: number | null;
  /** The picture the answer's tool data draws, when it has one. */
  visual?: Visual | null;
  /** A label for a player only where the names tool gave one: a name, or a role. */
  names?: Record<string, string>;
  teams?: TeamNames;
}

export interface AnswerMessage {
  type: "answer";
  answer: ViewerAnswer;
  /** schemas/companion_message.schema.json: who wrote the answer. */
  source?: "code" | "model";
}

export const PITCH_X = 105;
export const PITCH_Y = 68;
export const MAX_QUESTION = 200; // viewer_question.schema.json, text.maxLength

export function team(player: string): Team {
  return player.startsWith("h") ? "home" : "away";
}

/** A tracked player (h-t12): the tracker sees no shirt numbers, only a side and a track. */
export function isTrack(player: string): boolean {
  return /^[ha]-t\d+$/.test(player);
}

/** What the dot shows: the shirt number, or the track number. */
export function shirt(player: string): string {
  return isTrack(player) ? player.slice(3) : player.slice(1);
}

/** The clubs on this phone's screen: the bundle's, or the default (viewer/src/teams.ts). */
export const teams: TeamNames = { ...DEFAULT_TEAMS };

/** How a fan reads a player (viewer/src/teams.ts, `playerLabel`): the name or role a payload
 * gives, else the club and shirt, or the club and the tracker's number. */
export function playerName(player: string, names?: Record<string, string>): string {
  return playerLabel(player, teams, names);
}

/** Match time as m:ss. */
export function clock(t: number): string {
  const s = Math.max(0, Math.floor(t));
  return `${Math.floor(s / 60)}:${String(s % 60).padStart(2, "0")}`;
}
