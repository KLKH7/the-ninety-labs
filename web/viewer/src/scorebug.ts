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
export function bugAt(reads: ScoreRead[], t: number, secondHalf: number | null, ended = false): BugState {
  const sorted = reads.filter((r) => r.score).sort((a, b) => a.t - b.t);
  let at: ScoreRead | null = null;
  for (const r of sorted) {
    if (r.t > t + 1e-6) break;
    at = r;
  }
  const first = sorted[0];
  const kickoff = first && first.score!.home === 0 && first.score!.away === 0;
  const score = at ? at.score! : kickoff ? { home: 0, away: 0 } : null;
  let goal: BugState["goal"] = null;
  // The change that raised a side's count, read within the moment: the read's own `team`, else the
  // side whose count rose.
  const change = [...sorted].reverse().find((r) => r.type === "score_change" && r.t <= t + 1e-6 && t - r.t < GOAL_S);
  if (change && at) {
    const idx = sorted.indexOf(change);
    const before = idx > 0 ? sorted[idx - 1].score! : { home: 0, away: 0 };
    const rose = (["home", "away"] as const).find((s) => change.score![s] > before[s]);
    const side = change.team === "home" || change.team === "away" ? change.team : rose;
    if (side) goal = { side, p: Math.min(1, Math.max(0, (t - change.t) / GOAL_S)), before };
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
export function setupScorebug(root: HTMLElement, teams: TeamNames, reads: ScoreRead[], secondHalf: number | null,
  codes?: Partial<Record<Side, string>>) {
  const digit: Record<Side, { now: HTMLElement; was: HTMLElement; box: HTMLElement }> = {} as never;
  const plate = el("div", "sb-plate");
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
    team.append(el("span", "sb-bar"), crest, el("span", "sb-code", code(teams, side, codes)));
    if (side === "home") plate.append(team, box, el("span", "sb-dash", "–"));
    else plate.append(box, team);
  }
  const clockEl = el("span", "sb-clock");
  const sweep = el("div", "sb-sweep");
  const sweepCrest = el("span", "sb-crest");
  sweep.append(sweepCrest, el("span", "sb-goal", "GOAL"));
  root.replaceChildren(plate, el("span", "sb-rule"), clockEl, sweep);
  root.hidden = false;
  let key = "";
  return {
    tick(t: number, ended: boolean, reduceMotion: boolean) {
      const s = bugAt(reads, t, secondHalf, ended);
      const time = s.period ?? clock(t);
      const g = reduceMotion ? null : s.goal;
      const k = `${s.score?.home}-${s.score?.away}|${time}|${g?.side}|${g ? g.p.toFixed(3) : ""}`;
      if (k === key) return;
      key = k;
      clockEl.textContent = time;
      root.dataset.period = s.period ?? "";
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
    },
  };
}
