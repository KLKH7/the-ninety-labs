// The big screen's scorebug (Kian, Oct 26). The broadcast feed carries its own scorebug, baked into
// the render, and vision reads it (ninety/vision/scorebug.py, #356); the player draws its own from
// that read. So the render never changes: this one is an opaque layer exactly over the baked bug's
// box (web/render/render.js `layoutBug`: at a 720-line picture, 28 px in, 24 px down, at most 400 by
// 40 px with the GOAL panel and the period card open, scaled by height / 720), with a margin for the
// encode's soft edges and the rounded corners. It is opaque whatever it shows, so the baked bug
// never shows through: not on a seek, a stinger, a half-time card or before the first read.
//
// It shows only what was read: the score of the latest gated reading at or before the clock, 0–0
// before the first reading only when that reading is 0–0, and no digits otherwise. A score change
// read off the broadcast is the goal: the scoring club's colour sweeps the bug with its crest and
// GOAL, then the digit rolls over (about 2 s, driven by the match clock, so a pause or a seek shows
// the right moment).

import { clock } from "./bundle";
import { crestOf } from "./crests";
import type { ScoreRead } from "./lowerthird";
import { type Side, type TeamNames, CLUBS, short } from "./teams";

/** The baked bug's widest box, as fractions of the picture (render.js, at 1280 by 720). */
export const BAKED = { x: 28 / 1280, y: 24 / 720, w: 400 / 1280, h: 40 / 720 };
/** A detected goal and the scorebug's change for it, at most this far apart (web/phone, SCOREBUG_MATCH_S). */
const SCOREBUG_MATCH_S = 3;
/** The goal moment's length and its phases, as fractions of it (design: ~2 s, Kian). */
export const GOAL_S = 2.0;
const SWEEP_IN = 0.15, SWEEP_OUT = 0.65, ROLL = 0.8;
/** Half-time from the clock's 45:00 to the second half's detected kick-off; full time at the
 * engine's 90:00 (Law 7, two halves of 45 minutes, no added time: ninety/render/clip.py `periods`). */
const HALF_S = 45 * 60, MATCH_S = 90 * 60, FT_LEAD_S = 1.2;

export interface BugState {
  score: { home: number; away: number } | null;
  period: "HT" | "FT" | null;
  /** The goal moment: its side, 0 -> 1 through GOAL_S, and the score before it. */
  goal: { side: Side; p: number; before: { home: number; away: number } } | null;
}

/** What the bug shows at match time `t`, from the gated readings only. `secondHalf`: the second
 * half's detected kick-off, when there is one; `ended`: the footage has played out. */
export function bugAt(reads: ScoreRead[], t: number, secondHalf: number | null, ended = false, goalS = GOAL_S,
  goals: number[] = []): BugState {
  // A score never goes down in a match: a reading lower than one already read is a misread, skipped
  // (as the phone's scorebugGoals does).
  const sorted: ScoreRead[] = [];
  for (const r of reads.filter((x) => x.score).sort((a, b) => a.t - b.t)) {
    const last = sorted[sorted.length - 1]?.score;
    if (!last || (r.score!.home >= last.home && r.score!.away >= last.away)) sorted.push(r);
  }
  let at: ScoreRead | null = null;
  for (const r of sorted) {
    if (r.t > t + 1e-6) break;
    at = r;
  }
  const first = sorted[0];
  const kickoff = first && first.score!.home === 0 && first.score!.away === 0;
  // A goal vision detected after the last reading (its change unread, or under the gate) leaves that
  // score stale: no digits until a reading says the new one.
  const since = at ? at.t : -Infinity;
  const stale = goals.some((g) => g > since + SCOREBUG_MATCH_S && g <= t + 1e-6);
  const score = stale ? null : at ? at.score! : kickoff ? { home: 0, away: 0 } : null;
  let goal: BugState["goal"] = null;
  // The change that raised a side's count, read within the moment: the read's own `team`, else the
  // side whose count rose.
  const change = [...sorted].reverse().find((r) => r.type === "score_change" && r.t <= t + 1e-6 && t - r.t < goalS);
  if (change && at) {
    const idx = sorted.indexOf(change);
    const before = idx > 0 ? sorted[idx - 1].score! : { home: 0, away: 0 };
    const rose = (["home", "away"] as const).find((s) => change.score![s] > before[s]);
    const side = change.team === "home" || change.team === "away" ? change.team : rose;
    if (side) goal = { side, p: Math.min(1, Math.max(0, (t - change.t) / goalS)), before };
  }
  const period = ended || t >= MATCH_S - FT_LEAD_S ? "FT" : secondHalf !== null && t >= HALF_S && t < secondHalf ? "HT" : null;
  return { score, period, goal };
}

/** A club's three-letter code as the renderer draws it (the bundle's `teams`), else its name's. */
const code = (teams: TeamNames, side: Side, codes?: Partial<Record<Side, string>>) =>
  (/^[A-Z]{3}$/.test(codes?.[side] ?? "") ? codes![side]! : null) ?? Object.entries(CLUBS).find(([, full]) => short(full) === teams[side])?.[0] ?? teams[side].slice(0, 3).toUpperCase();

function el(tag: string, cls: string, text = ""): HTMLElement {
  const e = document.createElement(tag);
  e.className = cls;
  if (text) e.textContent = text;
  return e;
}

/** The bug, built once; `tick` sets what it shows each frame. */
/** The clubs' codes as the bug shows them. */
export const codesOf = (teams: TeamNames, codes?: Partial<Record<Side, string>>): Record<Side, string> =>
  ({ home: code(teams, "home", codes), away: code(teams, "away", codes) });

/** `root`: the bug's row, over the baked one; `clockTab`: the clock's tab under it. */
export function setupScorebug(root: HTMLElement, clockTab: HTMLElement, teams: TeamNames, reads: ScoreRead[],
  secondHalf: number | null, codes?: Partial<Record<Side, string>>, goals: number[] = [], said: HTMLElement | null = null) {
  const digit: Record<Side, { now: HTMLElement; was: HTMLElement; box: HTMLElement }> = {} as never;
  const score = el("span", "sb-score");
  const tabs: Record<Side, HTMLElement> = {} as never;
  for (const side of ["home", "away"] as const) {
    const team = el("span", `sb-team sb-${side}`);
    const crest = el("span", "sb-crest");
    const svg = crestOf(teams[side]);
    if (svg) crest.innerHTML = svg;
    else crest.hidden = true;
    const box = el("span", "sb-digit");
    const now = el("span", "sb-now"), was = el("span", "sb-was");
    box.append(was, now);
    digit[side] = { now, was, box };
    team.append(crest, el("span", "sb-code", code(teams, side, codes)));
    tabs[side] = team;
    if (side === "home") score.append(box, el("span", "sb-dash", "–"));
    else score.append(box);
  }
  const clockEl = el("span", "sb-clock");
  clockTab.replaceChildren(clockEl);
  clockTab.hidden = false;
  const sweep = el("div", "sb-sweep");
  const sweepCrest = el("span", "sb-crest");
  sweep.append(sweepCrest, el("span", "sb-goal", "GOAL"));
  root.replaceChildren(tabs.home, score, tabs.away, sweep);
  root.hidden = false;
  let key = "";
  let shownScore: BugState["score"] = null;
  let lastSay = "";
  // The moment's length is a design token (style.css --g-goal-s), so an identity can retime it.
  const token = parseFloat(getComputedStyle(document.documentElement).getPropertyValue("--g-goal-s"));
  const goalS = token > 0 ? token : GOAL_S;
  return {
    /** What the bug shows at match time t; returns the score it shows, for the stats panel. */
    tick(t: number, ended: boolean, reduceMotion: boolean): BugState["score"] {
      const s = bugAt(reads, t, secondHalf, ended, goalS, goals);
      shownScore = s.score;
      const time = s.period ?? clock(t);
      const g = reduceMotion ? null : s.goal;
      const k = `${s.score?.home}-${s.score?.away}|${time}|${g?.side}|${g ? g.p.toFixed(3) : ""}`;
      if (k === key) return shownScore;
      key = k;
      clockEl.textContent = time;
      // The score to a screen reader, when it or the period changes (never the running clock).
      const text = s.score
        ? `${s.goal ? `Goal, ${teams[s.goal.side]}. ` : ""}${teams.home} ${s.score.home}, ${teams.away} ${s.score.away}${s.period === "HT" ? ", half-time" : s.period === "FT" ? ", full time" : ""}`
        : `${teams.home} v ${teams.away}`;
      const sayKey = `${s.score?.home}-${s.score?.away}|${s.period}`;
      if (said && sayKey !== lastSay) {
        lastSay = sayKey;
        said.textContent = text;
      }
      clockTab.dataset.period = s.period ?? "";
      for (const side of ["home", "away"] as const) {
        const d = digit[side];
        d.now.textContent = s.score ? String(s.score[side]) : "";
        d.was.textContent = g && g.side === side ? String(g.before[side]) : "";
        // The roll: the old figure up and out, the new one up and in, in the last part of the moment.
        const roll = g && g.side === side ? Math.min(1, Math.max(0, (g.p - ROLL) / (1 - ROLL))) : 1;
        const e = 1 - (1 - roll) ** 3;
        d.box.style.setProperty("--roll", String(e));
        d.box.classList.toggle("hot", !!g && g.side === side);
      }
      if (g) {
        // In from the scoring side, held with the crest and GOAL, out the other way.
        const inP = Math.min(1, g.p / SWEEP_IN), outP = Math.min(1, Math.max(0, (g.p - SWEEP_OUT) / (ROLL - SWEEP_OUT)));
        const ease = (x: number) => 1 - (1 - x) ** 3;
        root.dataset.goal = g.side;
        sweep.style.setProperty("--in", String(ease(inP)));
        sweep.style.setProperty("--out", String(ease(outP)));
        if (sweep.dataset.side !== g.side) {
          sweep.dataset.side = g.side;
          sweepCrest.innerHTML = crestOf(teams[g.side]) ?? "";
        }
      } else {
        root.dataset.goal = "";
      }
      return shownScore;
    },
  };
}
