// The shapes the phone reads, mirroring schemas/companion_message.schema.json,
// schemas/minimap.schema.json, schemas/viewer_question.schema.json and viewer_answer.schema.json.
// tests/test_phone.py validates every payload the phone received against those schemas.

export type Source = "truth" | "tracked";
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

export interface ViewerAnswer {
  status: "verified" | "held" | "rejected" | "unanswerable";
  text: string;
  metric: string | null;
  value: number | null;
  unit: string | null;
  evidence: string[];
  t_from: number | null;
  t_to: number | null;
}

export interface AnswerMessage {
  type: "answer";
  answer: ViewerAnswer;
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

/** "Home 7" for h7, "Home player 12" for the tracked h-t12: synthetic teams have no names. */
export function playerName(player: string): string {
  const side = team(player) === "home" ? "Home" : "Away";
  return isTrack(player) ? `${side} player ${shirt(player)}` : `${side} ${shirt(player)}`;
}

/** Match time as m:ss. */
export function clock(t: number): string {
  const s = Math.max(0, Math.floor(t));
  return `${Math.floor(s / 60)}:${String(s % 60).padStart(2, "0")}`;
}
