// The fan's first-run choices (Kian's onboarding, Oct 25): a favourite club, a mode (the brief's
// two personas, casual fan or data-hungry analyst) and what they care about most. Kept in this
// browser only (localStorage, guarded: private windows refuse it), never sent anywhere. The
// choices shape Ask's suggested questions and the Story feed's starting filter; they never change
// a number, only which questions come first.

import { CLUBS, short, type TeamNames } from "../../viewer/src/teams";

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

// Every question here reaches one of the Companion's tools (ninety/agents/companion_match.py,
// `route`); tests/test_phone_onboarding.py checks each one with {us} and {them} filled in.
const BANK: Record<Focus | "casual" | "analyst", string[]> = {
  moments: [
    "What have I missed?",
    "How many shots have {us} had?",
    "What were the key moments?",
    "How many corners have {us} had?",
  ],
  tactics: [
    "Where are {us} overloading?",
    "Which pass broke {them}'s lines?",
    "What are {us}'s passing options?",
    "What shape are {them} in?",
    "How do {us} win the ball back?",
    "How compact are {us}?",
  ],
  players: [
    "Who's been {us}'s best player?",
    "Who has run the furthest?",
    "Who is the fastest on the pitch?",
    "Who is linking up for {us}?",
  ],
  casual: ["Who has more of the ball?", "Where has the ball been?"],
  analyst: ["How do the halves compare?", "Who has more of the ball?"],
};

/** The order each mode reads the rest in, after the fan's focus: a casual fan the moments and the
 * players first, an analyst the tactics and the numbers. */
const ORDER: Record<Mode, (Focus | Mode)[]> = {
  casual: ["moments", "players", "casual", "tactics"],
  analyst: ["tactics", "analyst", "players", "moments"],
};

/** The match questions for this fan, best first: their focus, then their mode's order. */
export function questions(fan: Fan, teams: TeamNames): string[] {
  const { us, them } = sides(fan, teams);
  const fill = (q: string) => q.replaceAll("{us}", us).replaceAll("{them}", them);
  const groups = [fan.focus, ...ORDER[fan.mode].filter((g) => g !== fan.focus)];
  return [...new Set(groups.flatMap((g) => BANK[g]).map(fill))];
}

/** The Story feed's starting filter: a casual fan opens on the key plays, an analyst on every play. */
export const storyMode = (fan: Fan): "key" | "all" => (fan.mode === "casual" ? "key" : "all");

/** The settings row's summary ("London · Analyst"). */
export function summary(fan: Fan): string {
  const mode = CHOICES.mode.find(([k]) => k === fan.mode)![1];
  return `${short(CLUBS[fan.club])} · ${mode}`;
}
