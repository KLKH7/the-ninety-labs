import { DEFAULT_TEAMS, type TeamNames, playerLabel, sideUnsure } from "../../viewer/src/teams";

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

/** A picture as the agents send it (schemas/insight_card.schema.json, $defs/visual): pitch metres,
 * home attacking x = 105, a point as [x, y] or [x, y, player id or null]. Every position and count
 * comes from the cited fact; `visual.ts` turns it into the `Visual` the phone draws, or nothing. */
export type ScoutKind = "line_break" | "overload" | "pass_options" | "counter_press" | "shape" | "wind_map" | "channels" | "offside" | "counter" | "one_two";
export type ScoutPoint = [number, number] | [number, number, string | null];
export interface ScoutVisual {
  kind: ScoutKind;
  fact: string;
  t: number | null;
  team: Team | null;
  club: string | null;
  geometry: {
    from?: ScoutPoint;
    to?: ScoutPoint;
    bypassed?: ScoutPoint[];
    zone?: { x0: number; x1: number; y0: number; y1: number };
    home?: ScoutPoint[];
    away?: ScoutPoint[];
    for?: number;
    against?: number;
    passer?: ScoutPoint;
    target?: ScoutPoint | null;
    open?: ScoutPoint[];
    marked?: ScoutPoint[];
    radius_m?: number;
    ball?: ScoutPoint;
    pressers?: ScoutPoint[];
    minute?: number;
    lines?: ScoutPoint[][];
    players?: ScoutPoint[];
    t_from?: number;
    t_to?: number;
    // channels: three lanes along the team's attack, each lane's share of its passes
    bands?: { channel: "left" | "centre" | "right"; y0: number; y1: number; share: number }[];
    minute_from?: number;
    minute_to?: number;
    // offside: a line across the pitch at the second-last defender
    line_x?: number;
    receiver?: ScoutPoint;
    second_last?: ScoutPoint;
    attackers?: ScoutPoint[];
    defenders?: ScoutPoint[];
    verdict?: "onside" | "offside" | "too_close" | "unsure" | "restart";
    margin_m?: number;
    // counter: from the regain to the shot
    seconds?: number;
    // one_two: from, via the wall player, back to (from and to above)
    via?: ScoutPoint;
  };
}

/** What the phone draws (visual.ts), made from a ScoutVisual. */
export type VisualKind = "overload" | "line_break" | "pass_options" | "counter_press" | "shape" | "wind" | "channels" | "offside" | "counter" | "one_two";
export type VisualRole = "attacker" | "defender" | "passer" | "receiver" | "bypassed" | "open" | "marked" | "carrier" | "presser" | "second_last";
export interface Point {
  x: number;
  y: number;
}
export interface VisualPlayer extends Point {
  id: string | null;
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
  radius_m?: number | null;
  lines?: Point[][] | null;
  bands?: { channel: "left" | "centre" | "right"; y0: number; y1: number; share: number }[] | null;
  line_x?: number | null;
  verdict?: "onside" | "offside" | "too_close" | "unsure" | "restart" | null;
  margin_m?: number | null;
  seconds?: number | null;
  via?: Point | null;
  t_from?: number | null;
  t_to?: number | null;
}

/** A pushed "hidden stat" (schemas/insight_card.schema.json): cards.json beside the bundle, oldest
 * first. Only verified cards are written; `why.answer` is precomputed and fact-checked. */
export interface InsightCard {
  id: string;
  t: number;
  minute: number;
  team: Team;
  club: string;
  kind: string;
  headline: string;
  text: string;
  status: "verified";
  source: "code" | "model";
  evidence: string[];
  visual: ScoutVisual | null;
  why: { question: string; answer: { status: "verified"; text: string; evidence: string[]; visual: ScoutVisual | null } } | null;
  names?: Record<string, string>;
  /** A plain sentence for screen readers and the Describer, with no reference to the picture. */
  spoken?: string;
  follow_ups?: string[];
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
  visual?: ScoutVisual | null;
  spoken?: string;
  follow_ups?: string[];
  /** The direct answer in a few words, computed by code from the question's kind (a name, a number
   * with its unit, a place); null when code has none (viewer_answer.schema.json, #294). */
  headline?: string | null;
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

/** The team sheet the bundle carries (match.json `lineup`, from the line-up tool): a player's name,
 * shirt and position, for the players it is confident of. Empty until a bundle brings one. */
export interface SheetEntry {
  name?: string;
  number?: number;
  position?: string;
}
export const teamSheet: Record<string, SheetEntry> = {};
/** The same feed's rows for TACTICAL track ids (match.json `lineup_tactical`): the radar's dots, the
 * player card and answers. Kept apart from `teamSheet`: a string in one id space is another man in the
 * other (lesson 259). Names come from the player-ID feed, never from vision (`identity`). */
export const tacticalSheet: Record<string, SheetEntry> = {};

/** A tracked player nothing names: the tracker's number is all we have, and it is not a shirt, so it
 * is never shown (video-prep, Oct 25: "Player 7240"). `events`: the id is a BROADCAST track (an
 * event's or a highlight's), the only id space the team sheet's line-up names (names-by-role). */
export function unnamedTrack(player: string, names?: Record<string, string>, events = false): boolean {
  return isTrack(player) && !names?.[player] && !(events ? teamSheet : tacticalSheet)[player]?.name;
}

/** A tracked player nothing names: his club's player, or "A player" on a side not told surely. */
const unnamed = (player: string) => (sideUnsure(player) ? "A player" : `${teams[team(player)]} player`);

/** How a fan reads a player on the radar, a player card or an answer (TACTICAL track ids): the name
 * or role a payload gives, else the club and shirt; a tracked player nobody names is his club's
 * ("London player"), or "A player" on a side not told surely: never the tracker's number. Never the
 * team sheet's line-up, which names broadcast tracks: the same string can be another man here. */
export function playerName(player: string, names?: Record<string, string>): string {
  if (unnamedTrack(player, names)) return unnamed(player);
  if (isTrack(player) && !names?.[player]) return tacticalSheet[player]!.name!; // the ID feed's name
  return playerLabel(player, teams, names);
}

/** A player in a detected event or a highlight (BROADCAST track ids): the team sheet's name where
 * the line-up names the track, else as playerName says him. */
export function eventName(player: string): string {
  const sheet = teamSheet[player]?.name;
  if (sheet) return sheet;
  return isTrack(player) ? unnamed(player) : playerLabel(player, teams); // never the tactical feed's row
}

/** Match time as m:ss. */
export function clock(t: number): string {
  const s = Math.max(0, Math.floor(t));
  return `${Math.floor(s / 60)}:${String(s % 60).padStart(2, "0")}`;
}
