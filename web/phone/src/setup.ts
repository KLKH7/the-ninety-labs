// "Make it yours": three taps that shape the phone for one fan (Kian's onboarding idea, Oct 25).
// Who they support, how deep they want it (casual or die-hard), and what they want most, which
// opens that part of the phone. Kept in this browser only (localStorage, guarded: private windows
// refuse it), never sent anywhere. Every choice only picks what is shown; it changes no number.

export type Depth = "casual" | "diehard";
export type Want = "action" | "stats" | "story" | "ask";

export interface Setup {
  done: boolean; // answered or skipped: the card is not offered again until "Redo setup"
  club: string | null; // the club's name as the bundle names it; null supports neither
  depth: Depth;
  want: Want | null;
}

const KEY = "ninety.setup";
// design: until a fan picks, the phone shows every stat, as it did before this card existed.
export const DEFAULTS: Setup = { done: false, club: null, depth: "diehard", want: null };

export const DEPTHS: { value: Depth; label: string; desc: string }[] = [
  { value: "casual", label: "Casual", desc: "The key numbers, kept simple" },
  { value: "diehard", label: "Die-hard", desc: "Every stat we measure: pressing, shape, distance" },
];

export const WANTS: { value: Want; label: string; desc: string }[] = [
  { value: "action", label: "Live action", desc: "The pitch, as it happens" },
  { value: "stats", label: "Stats", desc: "Team numbers, side by side" },
  { value: "story", label: "The story", desc: "Key moments and why they matter" },
  { value: "ask", label: "Ask", desc: "Ask about any player or moment" },
];

/** The stat groups a casual fan sees; a die-hard sees every group (main.ts, renderStats). */
export const CASUAL_GROUPS = ["Attack", "Passing"];

/** Where each answer opens the phone: a tab, and for Live which of its panes. */
export function destination(want: Want | null): { tab: "radar" | "ask" | "insights"; pane: "pitch" | "stats" | null } {
  if (want === "stats") return { tab: "radar", pane: "stats" };
  if (want === "story") return { tab: "insights", pane: null };
  if (want === "ask") return { tab: "ask", pane: null };
  return { tab: "radar", pane: "pitch" };
}

export function load(): Setup {
  try {
    const raw = JSON.parse(localStorage.getItem(KEY) ?? "{}") as Partial<Setup>;
    return {
      done: raw.done === true,
      club: typeof raw.club === "string" ? raw.club : null,
      depth: raw.depth === "casual" ? "casual" : "diehard",
      want: WANTS.some((w) => w.value === raw.want) ? (raw.want as Want) : null,
    };
  } catch {
    return { ...DEFAULTS };
  }
}

export function save(s: Setup) {
  try {
    localStorage.setItem(KEY, JSON.stringify(s));
  } catch {
    // a private window: the choice lasts for this visit only
  }
}
