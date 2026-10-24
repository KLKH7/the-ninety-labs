// Match mode: a condensed match played back to back at real speed. A chapter bar (one chapter per
// segment, named from the detected events), the scoreline from detected goals, each team's stats
// from the footage shown, and a "time skip" label at each cut, where the match clock jumps. All of
// it is match.json (ninety/condensed.py); this only shows it at the right moment.

import { type Bundle, type Manifest, clock } from "./bundle";
import type { Reel } from "./highlights";

export type Kind = "goal" | "save" | "shot" | "set_piece" | "build_up";

export interface Chapter {
  n: number;
  index: number; // the clip image it starts on
  frames: number;
  t: number; // match time of its first and last frames
  t_end: number;
  kind: Kind;
  label: string;
  event: string | null;
  event_t: number | null;
}

export type TeamStats = Record<"passes_attempted" | "passes_completed" | "shots" | "shots_on_target" | "goals", number>;

export interface MatchData {
  format: number;
  min_confidence: number;
  chapters: Chapter[];
  goals: { t: number; team: "home" | "away" | null; event: string }[];
  stats: ({ t: number; event: string | null } & Record<"home" | "away", TeamStats>)[];
  /** The highlights reel (ninety/highlights.py); bundles made before it have none. */
  highlights?: Reel;
}

/** How long the "time skip" label stays up after a cut (design: long enough to read, gone before
 * the play it skipped to matters). */
export const SKIP_LABEL_S = 2.5;

/** The chapter on screen at video time `v`. */
export function chapterAt(chapters: Chapter[], fps: number, v: number): Chapter | null {
  const i = Math.floor(v * fps);
  let at: Chapter | null = null;
  for (const c of chapters) if (c.index <= i) at = c;
  return at;
}

/** Goals so far at match time `t`, by team. */
export function scoreAt(m: MatchData, t: number): { home: number; away: number } {
  const s = { home: 0, away: 0 };
  for (const g of m.goals) if (g.t <= t && g.team) s[g.team] += 1;
  return s;
}

/** Each team's stats so far at match time `t`. */
export function statsAt(m: MatchData, t: number): MatchData["stats"][number] {
  let at = m.stats[0];
  for (const s of m.stats) if (s.t <= t) at = s;
  return at;
}

/** The cut just passed at video time `v`, while its label is up: the match clock either side. */
export function skipAt(chapters: Chapter[], fps: number, v: number): { from: number; to: number } | null {
  const c = chapterAt(chapters, fps, v);
  if (!c || c.n === 1) return null;
  if (v - c.index / fps >= SKIP_LABEL_S) return null;
  const before = chapters[c.n - 2];
  return { from: before.t_end, to: c.t };
}

const $ = <T extends HTMLElement>(id: string) => document.getElementById(id) as T;

function honest(m: Manifest): { text: string; warn: boolean } {
  const lead = "Condensed match, replayed at real speed.";
  if (m.events.standin)
    return { text: `${lead} Its events are a hand-written stand-in, not the detector's output: this bundle shows the layout only.`, warn: true };
  return { text: `${lead} Every event and number was computed from the pixels by our pipeline.`, warn: false };
}

function cell(tag: "td" | "th", text: string, scope?: string) {
  const el = document.createElement(tag);
  el.textContent = text;
  if (scope) el.setAttribute("scope", scope);
  return el;
}

/** Match mode's panels, or nothing when the bundle has no match.json. Returns what main.ts calls
 * each frame and the chapter keys. */
export function setupMatch(b: Bundle, seek: (videoT: number) => void) {
  const m = b.match;
  const root = $("match");
  const statsPanel = $("match-stats");
  if (!m) {
    root.hidden = true;
    statsPanel.hidden = true;
    return null;
  }
  const fps = b.manifest.fps;
  const total = b.manifest.footage.frames;
  root.hidden = false;
  statsPanel.hidden = false;
  document.body.dataset.mode = "match";
  const line = honest(b.manifest);
  const note = $("match-honest");
  note.textContent = line.text;
  note.classList.toggle("warn", line.warn);

  const bar = $("chapters");
  const buttons = m.chapters.map((c) => {
    const li = document.createElement("li");
    li.style.flexGrow = String(c.frames / total);
    const btn = document.createElement("button");
    btn.type = "button";
    btn.className = `chapter ${c.kind}`;
    btn.dataset.n = String(c.n);
    const span = `${clock(c.t)} to ${clock(c.t_end)}`;
    btn.setAttribute("aria-label", `Chapter ${c.n} of ${m.chapters.length}: ${c.label}, match clock ${span}`);
    btn.title = `${c.label} · ${span}`;
    const label = document.createElement("span");
    label.className = "chapter-label";
    label.textContent = c.label;
    const time = document.createElement("span");
    time.className = "chapter-time";
    time.textContent = clock(c.t);
    btn.append(time, label);
    btn.addEventListener("click", () => seek(c.index / fps));
    li.append(btn);
    return { li, btn, c };
  });
  bar.replaceChildren(...buttons.map((x) => x.li));
  const head = $("playhead");

  const score = $("score");
  const chapterNow = $("chapter-now");
  const skip = $("time-skip");
  const announce = $("match-live");
  const table = $("stats-table");
  const rows: [string, (s: TeamStats) => string][] = [
    ["Goals", (s) => String(s.goals)],
    ["Shots (on target)", (s) => `${s.shots} (${s.shots_on_target})`],
    ["Passes completed", (s) => `${s.passes_completed} of ${s.passes_attempted}`],
  ];
  let shown = "";
  let lastSkip = -1;
  let lastChapter = -1;

  const tick = (v: number, t: number, reduceMotion: boolean) => {
    const c = chapterAt(m.chapters, fps, v);
    const s = scoreAt(m, t);
    score.textContent = `Home ${s.home} – ${s.away} Away`;
    score.setAttribute("aria-label", `Score from detected goals: home ${s.home}, away ${s.away}`);
    head.style.left = `${Math.min(100, (100 * v * fps) / total)}%`;
    if (c && c.n !== lastChapter) {
      lastChapter = c.n;
      chapterNow.textContent = `Chapter ${c.n} of ${m.chapters.length} · ${c.label}`;
      for (const x of buttons) {
        if (x.c.n === c.n) x.btn.setAttribute("aria-current", "true");
        else x.btn.removeAttribute("aria-current");
      }
    }
    const sk = skipAt(m.chapters, fps, v);
    skip.hidden = !sk;
    skip.classList.toggle("still", reduceMotion);
    if (sk) {
      skip.textContent = `Time skip · ${clock(sk.from)} → ${clock(sk.to)}`;
      if (c && c.n !== lastSkip) {
        lastSkip = c.n;
        announce.textContent = `Time skip to ${clock(sk.to)}: ${c.label}.`;
      }
    } else if (c && v - c.index / fps >= SKIP_LABEL_S) lastSkip = -1;
    const st = statsAt(m, t);
    const key = JSON.stringify(st);
    if (key !== shown) {
      shown = key;
      const headRow = document.createElement("tr");
      headRow.append(cell("th", ""), cell("th", "Home", "col"), cell("th", "Away", "col"));
      table.replaceChildren(
        headRow,
        ...rows.map(([name, f]) => {
          const tr = document.createElement("tr");
          tr.append(cell("th", name, "row"), cell("td", f(st.home)), cell("td", f(st.away)));
          return tr;
        }),
      );
    }
    root.dataset.chapter = c ? String(c.n) : "";
    root.dataset.score = `${s.home}-${s.away}`;
  };

  /** To the start of the next (+1) or previous (-1) chapter; back to this one's start when more
   * than a second into it, as a media player's previous-track does. */
  const step = (v: number, dir: 1 | -1) => {
    const c = chapterAt(m.chapters, fps, v);
    if (!c) return;
    let to = c.n - 1 + dir;
    if (dir === -1 && v - c.index / fps > 1) to = c.n - 1;
    const target = m.chapters[Math.max(0, Math.min(m.chapters.length - 1, to))];
    seek(target.index / fps);
    buttons.find((x) => x.c.n === target.n)?.btn.focus({ preventScroll: true });
  };
  (window as unknown as { ninetyMatch: unknown }).ninetyMatch = {
    chapterAt: (v: number) => chapterAt(m.chapters, fps, v),
    scoreAt: (t: number) => scoreAt(m, t),
    statsAt: (t: number) => statsAt(m, t),
    skipAt: (v: number) => skipAt(m.chapters, fps, v),
  };
  return { tick, step };
}
