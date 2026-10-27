// The fan's first-run choices (Kian's onboarding, Oct 25): a favourite club, a mode (the brief's
// two personas, casual fan or data-hungry analyst) and what they care about most. Kept in this
// browser only (localStorage, guarded: private windows refuse it), never sent anywhere. The
// choices order Ask's suggested questions (the server's, /api/chips, with their club) and set the
// Story feed's starting filter; they never change a number or add a question.

import { CLUBS, short, type TeamNames } from "../../viewer/src/teams";
import type { Chip } from "./types";

export type Club = "LON" | "LIS";
export type Mode = "casual" | "analyst";
export type Focus = "moments" | "tactics" | "players";
export interface Fan {
  club: Club;
  mode: Mode;
  focus: Focus;
}

export const CHOICES = {
  club: [
    ["LON", CLUBS.LON],
    ["LIS", CLUBS.LIS],
  ],
  mode: [
    ["casual", "Casual fan"],
    ["analyst", "Analyst"],
  ],
  focus: [
    ["moments", "Goals and big moments"],
    ["tactics", "Tactics"],
    ["players", "Players"],
  ],
} as const;

const KEY = "ninety.fan";
const pick = <T extends string>(options: readonly (readonly [T, string])[], v: unknown): T | null =>
  options.some(([k]) => k === v) ? (v as T) : null;

/** The saved choices, "skipped" if the fan said not now, or null on a first visit. */
export function load(): Fan | "skipped" | null {
  try {
    const raw = JSON.parse(localStorage.getItem(KEY) ?? "null") as (Partial<Fan> & { skipped?: boolean }) | null;
    if (!raw || typeof raw !== "object") return null;
    if (raw.skipped === true) return "skipped";
    const club = pick(CHOICES.club, raw.club);
    const mode = pick(CHOICES.mode, raw.mode);
    const focus = pick(CHOICES.focus, raw.focus);
    return club && mode && focus ? { club, mode, focus } : null;
  } catch {
    return null;
  }
}

export function save(f: Fan | "skipped") {
  try {
    localStorage.setItem(KEY, JSON.stringify(f === "skipped" ? { skipped: true } : f));
  } catch {
    // a private window: the choice lasts for this visit only
  }
}

/** The favourite club's short name and its opponent's, from this match's two clubs; a match without
 * the favourite (another clip) keeps home and away. */
export function sides(fan: Fan, teams: TeamNames): { us: string; them: string } {
  const us = short(CLUBS[fan.club]);
  if (teams.home === us) return { us, them: teams.away };
  if (teams.away === us) return { us, them: teams.home };
  return { us: teams.home, them: teams.away };
}

/** The questions Ask offers when /api/chips cannot be reached: only the intent table's rows that code
 * answers from the scorebug or the possession count at any minute (ninety/agents/ask_chips.json, the
 * same words), never a measure that may not exist yet (offside, fastest, distance, shots).
 * tests/test_phone_companion.py checks each one reads as its row. */
export const SAFE_CHIPS: readonly Chip[] = [
  { intent: "score", q: "What's the score?" },
  { intent: "winning", q: "Who's winning?" },
  { intent: "possession", q: "Who has had more of the ball?" },
];

/** What each of the intent table's rows is about, for the fan's focus. */
const GROUP: Record<string, Focus | Mode> = {
  key_moments: "moments",
  why_goal: "moments",
  scorers: "moments",
  shots: "moments",
  on_target: "moments",
  corners: "moments",
  tactics: "tactics",
  on_top: "tactics",
  momentum: "tactics",
  territory: "tactics",
  completion: "tactics",
  passes: "tactics",
  best: "players",
  fastest: "players",
  distance: "players",
  score: "casual",
  winning: "casual",
  possession: "analyst",
  out_of_play: "analyst",
};

/** The order each mode reads the rest in, after the fan's focus: a casual fan the moments and the
 * players first, an analyst the tactics and the numbers. */
const ORDER: Record<Mode, (Focus | Mode)[]> = {
  casual: ["moments", "players", "casual", "analyst", "tactics"],
  analyst: ["tactics", "analyst", "players", "moments", "casual"],
};

/** The server's chips for this fan, best first: their focus, then their mode's order; the server's
 * own order within a group. Only the order changes, never which questions (each one code answers). */
export function ordered(chips: readonly Chip[], fan: Fan | null): Chip[] {
  if (!fan) return [...chips];
  const groups = [fan.focus, ...ORDER[fan.mode].filter((g) => g !== fan.focus)];
  const rank = (c: Chip) => {
    const k = groups.indexOf(GROUP[c.intent] ?? "");
    return k < 0 ? groups.length : k;
  };
  return chips.map((c, i) => [c, i] as const).sort((a, b) => rank(a[0]) - rank(b[0]) || a[1] - b[1]).map(([c]) => c);
}

export type Kind = "moments" | "tactics" | "players" | "numbers";
/** A question's kind, for its glyph on the starter cards: by the words it uses. */
export function kindOf(q: string): Kind {
  if (/missed|shots|moments|corners|goal|score/i.test(q)) return "moments";
  if (/overload|lines|options|shape|compact|ball back|set up|moving/i.test(q)) return "tactics";
  if (/player|run|fastest|linking|speed|far/i.test(q)) return "players";
  return "numbers";
}

/** The Story feed's starting filter: a casual fan opens on the key plays, an analyst on every play. */
export const storyMode = (fan: Fan): "key" | "all" => (fan.mode === "casual" ? "key" : "all");

/** The settings row's summary ("London · Analyst"). */
export function summary(fan: Fan): string {
  const mode = CHOICES.mode.find(([k]) => k === fan.mode)![1];
  return `${short(CLUBS[fan.club])} · ${mode}`;
}
