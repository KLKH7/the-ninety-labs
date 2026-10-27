// The big screen's pill under the scorebug (Kian, Oct 26: sleek, the phone's family): one white
// rounded pill, in its club's colour when it is about one club. An insight is a small caps label (its
// kind and minute) over one short bold line; a goal is the scorer's pill (crest, the name the ID feed
// gives in the sentence, else the club; the minute in a circle) after the bug's GOAL sweep. The short
// line keeps the checked sentence's own words, in order (only a lead's words are dropped).

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

/** The slide in and the slide out (design: a TV graphics cadence). */
const SLIDE_S = 0.3;
/** A goal (Kian, Oct 26: ~3 s): the club's band sweeps the bug first (src/scorebug.ts), then the
 * scorer's pill, until the moment ends (design). */
export const GOAL_PILL_IN_S = 1.0, GOAL_PILL_OUT_S = 3.2;
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
  /** Each such name's side, by its track (h-…, a-…): a sentence led by a player is his club's. */
  nameSides?: Record<string, Side>;
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
  kind: string; // "Overload"
  minute: number;
  brief: string; // one short line, the sentence's own words in order
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
  const lead = c.names.find((n) => text.startsWith(n));
  const side = idSide ?? detected?.team ?? (lead ? c.nameSides?.[lead] : undefined) ?? sideOf(text, c.teams);
  const kind = fact ? LABELS[fact] ?? KIND_LABELS.insight : KIND_LABELS[cue.kind] ?? cap(cue.kind.replace(/_/g, " "));
  let score: Graphic["score"] = null;
  if (goal) {
    const change = c.scorebug.find((r) => r.type === "score_change" && r.score && Math.abs(r.t - cue.t_in) <= SCOREBUG_MATCH_S);
    score = change?.score ?? null;
  }
  const { head, sub } = split(text);
  const scorer = goal ? c.names.find((n) => text.includes(`${n} scor`)) ?? null : null;
  return { id: cue.id, goal, label: `${kind} · ${minute}′`, side, head, sub, score, scorer, verified: !!cue.verified,
    kind, minute, brief: brief(fact, text, head, c.names) };
}

/** The sentence as one short line, by the bar's sentence shapes (ninety/agents/companion_match
 * code_texts); its own words, in order, so nothing is said that the check did not pass. */
export function brief(fact: string | null, text: string, head: string, names: string[]): string {
  const named = names.find((n) => text.startsWith(n));
  let m: RegExpExecArray | null;
  if (fact === "ov" && (m = /(\d+) players? against (\d+) players? around the ball/.exec(text)))
    return `${m[1]} against ${m[2]} around the ball`;
  if (fact === "lb" && (m = /a pass that took (\d+) .*?players? out of the game/.exec(text)))
    return named ? `${named}: pass took ${m[1]} players out of the game` : `Pass took ${m[1]} players out of the game`;
  if (fact === "spell" && (m = /(\d+) passes together in a row/.exec(text))) return `${m[1]} passes together in a row`;
  return head;
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

/** A split bar in the two clubs' colours: each side's share of the two numbers. */
export function splitBar(home: number, away: number): HTMLElement {
  const bar = el("span", "sbar");
  const total = home + away;
  bar.style.setProperty("--h", String(total > 0 ? home / total : 0.5));
  bar.append(el("i", "sbar-home"), el("i", "sbar-away"));
  return bar;
}

/** A name as a broadcast graphic sets it: the first name light, the rest bold in capitals. */
function nameNodes(name: string): Node[] {
  const [first, ...rest] = name.split(" ");
  return rest.length ? [el("span", "pill-first", first), el("span", "pill-last", rest.join(" ").toUpperCase())]
    : [el("span", "pill-last", name.toUpperCase())];
}

/** The pill for one graphic: a goal's (crest, the scorer the ID feed names in the sentence, else the
 * club; the minute in a small circle), or an insight's (a small caps label and one short bold line,
 * tinted in its club's colour when it is about one club). */
function build(g: Graphic, c: Context): Node[] {
  if (g.goal) {
    const who = g.scorer ?? (g.side ? fullName(c.teams[g.side]) : g.head);
    return [el("div", "pill pill-goal", crest(g.side, c.teams), el("p", "pill-name", ...nameNodes(who)),
      el("span", "pill-min", `${g.minute}′`), check(g.verified))];
  }
  return [el("div", "pill", crest(g.side, c.teams),
    el("div", "pill-text", el("p", "pill-label", `${g.kind.toUpperCase()} · ${g.minute}′`), el("p", "pill-line", ...withNames(g.brief, c.names))),
    check(g.verified))];
}

/** The insight tab on screen: the big screen's cue on air, slid down out of the scorebug and back up
 * into it. Returns what main.ts calls each frame. */
export function setupLowerThird(root: HTMLElement, c: Context) {
  let shown: Graphic | null = null;
  let cue: Cue | null = null;
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
      // A goal's pill comes up under the bug once its band has swept it, and goes with the moment.
      const from = shown.goal ? cue.t_in + GOAL_PILL_IN_S : cue.t_in;
      const to = shown.goal ? Math.min(cue.t_out, cue.t_in + GOAL_PILL_OUT_S) : cue.t_out;
      root.dataset.on = t >= from && (reduceMotion || t <= to - SLIDE_S) && t < to ? "1" : "0";
    },
  };
}
