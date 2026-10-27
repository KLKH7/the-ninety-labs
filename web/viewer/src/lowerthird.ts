// The big screen's lower third (Kian, Oct 26: "the insights look really bad"): a broadcast graphic
// in HTML over the picture, not drawn into the canvas, so it can sit on frosted glass, carry the
// club's crest and set the ID feed's names in bold. Bottom left, inside the title-safe area: clear of
// the scorebug (top left, baked into the footage) and of the play, which the camera keeps central.
// It only lays out words the fact-checking agent passed; it never adds a number of its own. The one
// number it shows beside them, a goal's new score, is the broadcast's own scorebug as vision read it
// (scorebug.jsonl, #356), through the gate the bundle states (manifest.scorebug).

import type { Cue } from "./bundle";
import { crestOf } from "./crests";
import { type Side, type TeamNames, CLUBS, fullName, short } from "./teams";

/** The insight bar's fact kinds (ninety/agents/insight_bar.py, SIGNIFICANCE), by the prefix of the
 * fact id its cue carries (`insight-<fact id>`), as a broadcaster labels them. */
const LABELS: Record<string, string> = {
  goal: "Goal",
  counter: "Counter-attack",
  lb: "Line break",
  spell: "Passing move",
  ov: "Overload",
  cp: "Won back",
  po: "Open team-mate",
  onetwo: "One-two",
};
const KIND_LABELS: Record<string, string> = { shot_speed: "Shot", recap: "Recap", insight: "Insight" };

/** How long a goal stays a full card before it collapses into the lower third (design). */
export const GOAL_CARD_S = 3.5;
/** The slide in and the slide out (design: a TV graphics cadence). */
const SLIDE_S = 0.5;
/** A goal and the scorebug's change for it, at most this far apart (web/phone, SCOREBUG_MATCH_S). */
const SCOREBUG_MATCH_S = 3;

export interface ScoreRead {
  type: string;
  t: number;
  score?: { home: number; away: number } | null;
  team?: string | null;
  confidence?: number | null;
}

export interface Context {
  teams: TeamNames;
  /** Every player name the ID feed gives (match.json `lineup`, source id_feed). */
  names: string[];
  /** match.json `goals`: each detected goal's side, by its event. */
  goals: { t: number; team: Side | null; event: string }[];
  /** The scorebug's readings that pass the bundle's gate. */
  scorebug: ScoreRead[];
}

export interface Graphic {
  id: string;
  goal: boolean;
  label: string; // "Line break · 26′"
  side: Side | null;
  head: string; // one line, the sentence's lead
  sub: string; // the rest, or ""
  score: { home: number; away: number } | null; // a goal's, from the scorebug
  scorer: string | null; // a goal's, only where the ID feed names him in the sentence
  verified: boolean;
}

const cap = (s: string) => s.charAt(0).toUpperCase() + s.slice(1);

/** The side a sentence is about: the club it names first (its subject, in the bar's sentences). */
function sideOf(text: string, teams: TeamNames): Side | null {
  let best: { at: number; side: Side } | null = null;
  for (const side of ["home", "away"] as const) {
    const names = new Set([teams[side], ...Object.values(CLUBS).filter((full) => short(full) === teams[side])]);
    for (const name of names) {
      const at = text.search(new RegExp(`\\b${name.replace(/[.*+?^${}()|[\]\\]/g, "\\$&")}\\b`));
      if (at >= 0 && (!best || at < best.at)) best = { at, side };
    }
  }
  return best?.side ?? null;
}

/** The sentence as a lead and the rest: its first sentence, or a single sentence's place ("…, in
 * their own third") as the second line. The words are the checked text's, in order, none changed. */
export function split(text: string): { head: string; sub: string } {
  const sentences = text.trim().match(/[^.!?]+[.!?]*(\s+|$)/g)?.map((s) => s.trim()) ?? [text.trim()];
  const [first, ...rest] = sentences;
  if (rest.length) return { head: first.replace(/\.$/, ""), sub: rest.join(" ") };
  const comma = first.indexOf(", ");
  if (comma >= 12 && first.length - comma > 14) {
    return { head: first.slice(0, comma), sub: cap(first.slice(comma + 2)) };
  }
  return { head: first.replace(/\.$/, ""), sub: "" };
}

/** What a big-screen cue shows: its label, club, lead and second line. */
export function describe(cue: Cue, c: Context): Graphic {
  const fact = /^insight-([a-z_]+):/.exec(cue.id)?.[1] ?? null;
  const goal = fact === "goal";
  let text = cap(cue.text.trim());
  // The minute goes to the label ("Line break · 26′"), so the sentence does not say it twice.
  const said = /\b[Ii]n minute (\d+)\b/.exec(text);
  const minute = said ? Number(said[1]) : Math.floor(cue.t_in / 60) + 1;
  text = cap(text.replace(/^In minute \d+, /, "").replace(/ in minute \d+(?=[.,])/, ""));
  const idSide = /^insight-[a-z_]+:(home|away):/.exec(cue.id)?.[1] as Side | undefined;
  const event = goal ? cue.id.slice("insight-goal:".length) : null;
  const detected = event ? c.goals.find((g) => g.event === event) : undefined;
  const side = idSide ?? detected?.team ?? sideOf(text, c.teams);
  const kind = fact ? LABELS[fact] ?? KIND_LABELS.insight : KIND_LABELS[cue.kind] ?? cap(cue.kind.replace(/_/g, " "));
  let score: Graphic["score"] = null;
  if (goal) {
    const change = c.scorebug.find((r) => r.type === "score_change" && r.score && Math.abs(r.t - cue.t_in) <= SCOREBUG_MATCH_S);
    score = change?.score ?? null;
  }
  const { head, sub } = split(text);
  const scorer = goal ? c.names.find((n) => text.includes(`${n} scor`)) ?? null : null;
  return { id: cue.id, goal, label: `${kind} · ${minute}′`, side, head, sub, score, scorer, verified: !!cue.verified };
}

/** `text` as nodes, every name the ID feed gives in bold. */
function withNames(text: string, names: string[]): Node[] {
  const known = names.filter((n) => text.includes(n)).sort((a, b) => b.length - a.length);
  if (!known.length) return [document.createTextNode(text)];
  const re = new RegExp(`(${known.map((n) => n.replace(/[.*+?^${}()|[\]\\]/g, "\\$&")).join("|")})`);
  return text.split(re).filter(Boolean).map((part) => {
    if (!known.includes(part)) return document.createTextNode(part);
    const b = document.createElement("b");
    b.textContent = part;
    return b;
  });
}

const CHECK =
  '<svg viewBox="0 0 16 16" aria-hidden="true"><circle cx="8" cy="8" r="7.25"/><path d="m4.9 8.2 2.1 2.1 4.1-4.4"/></svg>';

function el(tag: string, cls: string, ...kids: (Node | string)[]): HTMLElement {
  const e = document.createElement(tag);
  e.className = cls;
  e.append(...kids);
  return e;
}

function crest(side: Side | null, teams: TeamNames): HTMLElement {
  const box = el("span", "lt-crest");
  const svg = side ? crestOf(teams[side]) : null;
  if (svg) box.innerHTML = svg;
  else box.hidden = true;
  return box;
}

function check(verified: boolean): HTMLElement {
  const box = el("span", "lt-check");
  box.innerHTML = CHECK;
  box.title = "Fact-checked";
  box.setAttribute("role", "img");
  box.setAttribute("aria-label", "Fact-checked");
  box.hidden = !verified;
  return box;
}

function scoreLine(g: Graphic, teams: TeamNames): HTMLElement {
  const row = el("span", "lt-score");
  for (const side of ["home", "away"] as const) {
    const club = el("span", `lt-club${side === g.side ? " scored" : ""}`, teams[side]);
    const n = el("span", `lt-n${side === g.side ? " scored" : ""}`, String(g.score![side]));
    if (side === "home") row.append(club, n, el("span", "lt-dash", "–"));
    else row.append(n, club);
  }
  return row;
}

/** The lower third's content for one graphic: the compact strip, and a goal's full card above it. */
function build(g: Graphic, c: Context): Node[] {
  const label = el("p", "lt-label", crest(g.side, c.teams), el("span", "lt-kind", g.label.toUpperCase()), check(g.verified));
  const compact = el("div", "lt-strip", label);
  if (g.goal && g.score) compact.append(el("p", "lt-head", scoreLine(g, c.teams)));
  else compact.append(el("p", "lt-head", ...withNames(g.head, c.names)));
  // A goal's strip leads with the score; its sentence's lead ("London Athletic scored") says no more.
  const sub = g.sub;
  if (sub) compact.append(el("p", "lt-sub", ...withNames(sub, c.names)));
  if (!g.goal) return [compact];
  const club = g.side ? c.teams[g.side] : "";
  const card = el("div", "lt-card",
    crest(g.side, c.teams),
    el("div", "lt-card-text",
      el("p", "lt-card-kind", "GOAL", el("span", "lt-card-min", g.label.split(" · ")[1] ?? ""), check(g.verified)),
      el("p", "lt-card-club", club ? fullName(club) : g.head),
      ...(g.scorer ? [el("p", "lt-card-scorer", ...withNames(g.scorer, c.names))] : []),
    ),
    ...(g.score ? [el("p", "lt-card-score", `${g.score.home}–${g.score.away}`)] : []),
  );
  return [card, compact];
}

/** A strip as wide as its longest line, not its max-width: a box does not shrink to text that
 * wrapped. Kept in the picture's units (--u), so it scales with the picture until it rewraps. */
function fit(root: HTMLElement) {
  const strip = root.querySelector<HTMLElement>(".lt-strip");
  const head = strip?.querySelector<HTMLElement>(".lt-head");
  if (!strip || !head) return;
  strip.style.width = "";
  const u = parseFloat(getComputedStyle(head).fontSize) / 28; // the head is 28 units
  const left = head.getBoundingClientRect().left;
  let right = 0;
  for (const line of strip.querySelectorAll<HTMLElement>(".lt-head, .lt-sub, .lt-label")) {
    const range = document.createRange();
    range.selectNodeContents(line);
    for (const r of range.getClientRects()) right = Math.max(right, r.right);
  }
  const pad = parseFloat(getComputedStyle(strip).paddingLeft) + parseFloat(getComputedStyle(strip).paddingRight);
  if (right > left && u > 0) strip.style.width = `calc(${((right - left + pad) / u).toFixed(1)} * var(--u))`;
}

/** The lower third on screen: shows the big screen's cue on air, slides it in and out, collapses a
 * goal's card. Returns what main.ts calls each frame. */
export function setupLowerThird(root: HTMLElement, c: Context) {
  let shown: Graphic | null = null;
  let cue: Cue | null = null;
  if (root.parentElement) new ResizeObserver(() => !root.hidden && fit(root)).observe(root.parentElement);
  return {
    /** `aired`: the broadcast's cues on air at match time `t` (at most one lower third). */
    tick(aired: Cue[], t: number, reduceMotion: boolean) {
      const next = aired.find((x) => x.slot === "lower_third") ?? null;
      if (next?.id !== cue?.id) {
        cue = next;
        if (next) {
          shown = describe(next, c);
          root.replaceChildren(...build(shown, c));
          root.dataset.side = shown.side ?? "";
          root.dataset.goal = shown.goal ? "1" : "0";
          root.dataset.id = next.id;
          root.hidden = false;
          fit(root);
          // From the start of the slide, so the transition runs (none with reduced motion).
          root.dataset.on = "0";
          void root.offsetWidth;
        } else {
          shown = null;
          root.dataset.id = "";
        }
      }
      root.classList.toggle("still", reduceMotion);
      if (!cue || !shown) {
        root.dataset.on = "0";
        if (reduceMotion || !root.getAnimations().length) root.hidden = true;
        return;
      }
      const leaving = !reduceMotion && t > cue.t_out - SLIDE_S;
      root.dataset.on = leaving ? "0" : "1";
      root.dataset.card = shown.goal && t - cue.t_in < GOAL_CARD_S ? "1" : "0";
    },
  };
}
