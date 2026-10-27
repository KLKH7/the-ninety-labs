// Match mode: a condensed match played back to back at real speed. A chapter bar (one chapter per
// segment, named from the detected events), the scoreline from detected goals, each team's stats
// from the footage shown, and a "time skip" label at each cut, where the match clock jumps. All of
// it is match.json (ninety/condensed.py); this only shows it at the right moment.

import { type Bundle, type Cue, type Manifest, clock } from "./bundle";
import { crestOf } from "./crests";
import { timescaleOf } from "./radar";
import type { TeamNames } from "./teams";

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
  /** The line-up by track; a name with source id_feed is the player-ID feed's (docs/FEED_SPEC.md). */
  lineup?: { id: string; name?: string | null; source?: string }[];
}

/** How long the "time skip" label stays up after a cut (design: long enough to read, gone before
 * the play it skipped to matters). */
export const SKIP_LABEL_S = 2.5;

/** A chapter's label with the club's name for the side it names ("Goal, home" -> "Goal · London"):
 * match.json names sides, the screen names clubs. */
export function chapterLabel(c: Pick<Chapter, "label">, teams: TeamNames): string {
  return c.label.replace(/, (home|away)$/, (_, side: "home" | "away") => ` · ${teams[side]}`);
}

/** How long the big screen's pairing card stays up at kick-off (design: long enough to scan, short
 * enough not to sit on the play). After it, the control bar's QR button brings it back. */
export const PAIR_CARD_S = 20;

/** Where the big screen's pairing card is at video time `v`: "up" over the picture for the first
 * PAIR_CARD_S seconds (until a fan closes it) or while the QR button has it open; else "hidden".
 * Never docked on screen (Kian, Oct 25: option A). */
export function pairCardAt(v: number, s: { open: boolean; closed: boolean }): "up" | "hidden" {
  return s.open || (v < PAIR_CARD_S && !s.closed) ? "up" : "hidden";
}

/** The big screen's lower thirds, as a broadcaster runs them: only moments that matter (a shot, a
 * Scout insight, a recap; never a routine pass, which stays in the phone's All plays), at most one
 * starting every BROADCAST_GAP_S, each held BROADCAST_HOLD_S at most (design: a TV graphics
 * cadence, about 6 s on screen, Kian). An insight is the analyst's cue; the big screen has no personas, so
 * it takes it. A producer's order: a goal's insight always airs (as the INSIGHT bar airs every goal,
 * ninety/agents/insight_bar.py), then the other insights, then a shot or a recap where there is room:
 * nothing airs from BROADCAST_HOLD_S before a graphic already chosen (its own shot's among them) to
 * BROADCAST_GAP_S after it, and one on air when the next comes is cut short. */
export const BROADCAST_KINDS = new Set(["shot_speed", "insight", "recap"]);
export const BROADCAST_GAP_S = 30;
export const BROADCAST_HOLD_S = 6;
export const isGoalInsight = (c: Cue) => c.kind === "insight" && c.id.startsWith("insight-goal:");
export function broadcastSchedule(cues: Cue[]): Cue[] {
  const rank = (c: Cue) => (c.kind === "insight" ? 0 : c.kind === "shot_speed" ? 1 : 2);
  const fit = cues
    .filter((c) => c.slot === "lower_third" && BROADCAST_KINDS.has(c.kind) && c.persona !== "audio")
    .sort((a, b) => a.t_in - b.t_in || rank(a) - rank(b));
  // The same moment told for two personas airs once; a cue with no event behind it (an overload is
  // read from positions) is its own moment.
  const key = (c: Cue) => (c.evidence.length ? `${c.kind}|${c.evidence.join()}` : c.id);
  const tier = (c: Cue) => (isGoalInsight(c) ? 0 : c.kind === "insight" ? 1 : 2);
  const chosen: Cue[] = [];
  const seen = new Set<string>();
  for (const level of [0, 1, 2]) {
    for (const c of fit) {
      if (tier(c) !== level || seen.has(key(c))) continue;
      const crowded = chosen.some((x) => c.t_in > x.t_in - BROADCAST_HOLD_S && c.t_in < x.t_in + BROADCAST_GAP_S);
      if (level > 0 && crowded) continue;
      seen.add(key(c));
      chosen.push(c);
    }
  }
  const out = chosen.sort((a, b) => a.t_in - b.t_in);
  return out.map((c, i) => ({
    ...c,
    replaces: null,
    t_out: Math.min(c.t_out, c.t_in + BROADCAST_HOLD_S, out[i + 1]?.t_in ?? Infinity),
  }));
}

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
export function setupMatch(b: Bundle, seek: (videoT: number) => void, teams: TeamNames) {
  const m = b.match;
  const root = $("match");
  const statsPanel = $("match-stats");
  if (!m) {
    root.hidden = true;
    statsPanel.hidden = true;
    return null;
  }
  // Chapters count images; the video shows fps * timescale of them a second (the baked speed).
  const fps = b.manifest.fps * timescaleOf(b.manifest);
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
    const named = chapterLabel(c, teams);
    btn.setAttribute("aria-label", `Chapter ${c.n} of ${m.chapters.length}: ${named}, match clock ${span}`);
    btn.title = `${named} · ${span}`;
    const label = document.createElement("span");
    label.className = "chapter-label";
    label.textContent = named;
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
  for (const side of ["home", "away"] as const) {
    const crest = document.getElementById(`score-crest-${side}`);
    if (crest) crest.innerHTML = crestOf(teams[side]) ?? "";
  }
  const chapterNow = $("chapter-now");
  const skip = $("time-skip");
  const announce = $("match-live");
  const table = $("stats-table");
  const rows: [string, (s: TeamStats) => string][] = [
    ["Shots (on target)", (s) => `${s.shots} (${s.shots_on_target})`],
    ["Passes completed", (s) => `${s.passes_completed} of ${s.passes_attempted}`],
  ];
  let shown = "";
  let lastSkip = -1;
  let lastChapter = -1;

  const tick = (v: number, t: number, reduceMotion: boolean) => {
    const c = chapterAt(m.chapters, fps, v);
    // The clubs, never a score counted from detected goals: the broadcast's scorebug carries it, and
    // vision can miss a goal (Kian, Oct 25).
    const fixture = `${teams.home} v ${teams.away}`;
    if (score.textContent !== fixture) score.textContent = fixture;
    head.style.left = `${Math.min(100, (100 * v * fps) / total)}%`;
    if (c && c.n !== lastChapter) {
      lastChapter = c.n;
      chapterNow.textContent = `Chapter ${c.n} of ${m.chapters.length} · ${chapterLabel(c, teams)}`;
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
        announce.textContent = `Time skip to ${clock(sk.to)}: ${chapterLabel(c, teams)}.`;
      }
    } else if (c && v - c.index / fps >= SKIP_LABEL_S) lastSkip = -1;
    const st = statsAt(m, t);
    const key = JSON.stringify(st);
    if (key !== shown) {
      shown = key;
      const headRow = document.createElement("tr");
      headRow.append(cell("th", ""), cell("th", teams.home, "col"), cell("th", teams.away, "col"));
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
    // Focus follows to the chapter's button where the chapter bar is shown (not on the big screen,
    // whose chapters are ticks on the scrubber).
    const btn = buttons.find((x) => x.c.n === target.n)?.btn;
    if (btn?.offsetParent) btn.focus({ preventScroll: true });
  };
  (window as unknown as { ninetyMatch: unknown }).ninetyMatch = {
    chapterAt: (v: number) => chapterAt(m.chapters, fps, v),
    scoreAt: (t: number) => scoreAt(m, t),
    statsAt: (t: number) => statsAt(m, t),
    skipAt: (v: number) => skipAt(m.chapters, fps, v),
    pairCardAt: (v: number, st: { open: boolean; closed: boolean }) => pairCardAt(v, st),
    broadcastSchedule: (cues: Cue[]) => broadcastSchedule(cues),
  };
  return { tick, step };
}
