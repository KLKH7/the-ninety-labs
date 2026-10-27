// The big screen's half-time and full-time stats (Kian, Oct 26): the score large with the crests, then a
// stack of white pills, one per measured row (home | the split bar and label | away).
// Rows are only what the bundle measured: the team stats counted from detected events (match.json
// `stats`) and the Insight Scout's confident rows (`insight_stats`, the phone's gate: an unsure row
// is not shown). A count that contradicts the scorebug (fewer attempts than goals: every goal is an
// attempt) is not shown either. The score is the scorebug's read (src/scorebug.ts), never counted.

import { crestOf } from "./crests";
import { splitBar } from "./lowerthird";
import type { MatchData } from "./match";
import type { Side, TeamNames } from "./teams";
import { fullName } from "./teams";

type Pair = { home: number; away: number };
export interface Row { key: string; label: string; home: number; away: number; unit: string }

interface ScoutRow { key: string; series: { minute_to: number; home: number | null; away: number | null; confident: boolean }[] }
type Stats = MatchData & { insight_stats?: { rows?: ScoutRow[] } };

/** A share of passes means something only over this many (web/phone MIN_SHARE_PASSES, ninety/agents
 * companion_match: "a share only over 15 passes"). */
const MIN_SHARE_PASSES = 15;
/** How long the half-time panel stays up (Kian: ~8 s); full time holds on the last frame. */
export const PANEL_S = 8;
const HALF_S = 45 * 60, MATCH_S = 90 * 60, FT_LEAD_S = 1.2;

/** A Scout row's confident values at match time t: its latest bin at or before t. */
export function scoutAt(m: Stats | null, key: string, t: number): Pair | null {
  const row = m?.insight_stats?.rows?.find((r) => r.key === key);
  let at: ScoutRow["series"][number] | null = null;
  for (const s of row?.series ?? []) if (s.minute_to * 60 <= t + 1e-6) at = s;
  return at && at.confident && typeof at.home === "number" && typeof at.away === "number" ? { home: at.home, away: at.away } : null;
}

const SCOUT: [string, string, string][] = [
  ["corner", "Corners", ""], ["crosses", "Crosses", ""], ["one_twos", "One-twos", ""],
  ["overload_moments", "Overloads", ""], ["regains_within_5s", "Won back in 5 s", ""],
];

/** Every row the bundle measured at match time t, against the scorebug's `score` (null: unread). */
export function rowsAt(m: Stats | null, t: number, score: Pair | null): Row[] {
  const out: Row[] = [];
  const poss = scoutAt(m, "possession", t);
  if (poss) out.push({ key: "possession", label: "Possession", ...poss, unit: "%" });
  let st: MatchData["stats"][number] | null = null;
  for (const s of m?.stats ?? []) if (s.t <= t + 1e-6) st = s;
  if (st) {
    const sides = ["home", "away"] as const;
    const atLeastGoals = (k: "shots" | "shots_on_target") => !!score && sides.every((s) => st![s][k] >= score[s]);
    if (atLeastGoals("shots")) out.push({ key: "shots", label: "Attempts", home: st.home.shots, away: st.away.shots, unit: "" });
    if (atLeastGoals("shots_on_target"))
      out.push({ key: "on_target", label: "On target", home: st.home.shots_on_target, away: st.away.shots_on_target, unit: "" });
    out.push({ key: "passes", label: "Passes", home: st.home.passes_attempted, away: st.away.passes_attempted, unit: "" });
    if (sides.every((s) => st![s].passes_attempted >= MIN_SHARE_PASSES)) {
      const acc = (s: Side) => Math.round((100 * st![s].passes_completed) / st![s].passes_attempted);
      out.push({ key: "accuracy", label: "Pass accuracy", home: acc("home"), away: acc("away"), unit: "%" });
    }
  }
  for (const [key, label, unit] of SCOUT) {
    const v = scoutAt(m, key, t);
    if (v) out.push({ key, label, ...v, unit });
  }
  return out;
}

/** Whether the panel is up at video time v (match time t): at half-time, the first PANEL_S of footage
 * from the clock's 45:00; at full time, from the engine's 90:00 (Law 7) or the footage's end, held. */
export function statsGraphicAt(v: number, t: number, videoTime: (t: number) => number, start: number, ended: boolean):
  { kind: "panel"; period: "HT" | "FT" } | null {
  if (ended || t >= MATCH_S - FT_LEAD_S) return { kind: "panel", period: "FT" };
  if (start < HALF_S) {
    const ht = videoTime(HALF_S);
    if (v >= ht && v < ht + PANEL_S) return { kind: "panel", period: "HT" };
  }
  return null;
}

function el(tag: string, cls: string, ...kids: (Node | string)[]): HTMLElement {
  const e = document.createElement(tag);
  e.className = cls;
  e.append(...kids);
  return e;
}

function crestBox(teams: TeamNames, side: Side): HTMLElement {
  const box = el("span", "sp-crest");
  box.innerHTML = crestOf(teams[side]) ?? "";
  return box;
}

/** One stat as a pill: home's number, the label over a thin split bar, away's number. */
function statPill(r: Row): HTMLElement {
  return el("div", "stat-pill", el("span", "stat-h", `${r.home}${r.unit}`),
    el("span", "stat-mid", el("span", "stat-label", r.label), splitBar(r.home, r.away)), el("span", "stat-a", `${r.away}${r.unit}`));
}

/** The half-time and full-time panel, built when what it shows changes. */
export function setupStats(panel: HTMLElement, m: Stats | null, teams: TeamNames) {
  let key = "";
  return {
    tick(v: number, t: number, videoTime: (t: number) => number, start: number, ended: boolean, score: Pair | null) {
      const g = m ? statsGraphicAt(v, t, videoTime, start, ended) : null;
      const rows = g ? rowsAt(m, t, score) : [];
      const k = g ? `${g.period}|${score?.home}-${score?.away}|${rows.map((r) => `${r.key}${r.home}${r.away}`).join()}` : "";
      if (k === key) return;
      key = k;
      panel.hidden = !g;
      if (!g) return;
      panel.dataset.period = g.period;
      panel.replaceChildren(el("div", "sp-stack",
        el("p", "sp-period", g.period === "HT" ? "HALF-TIME" : "FULL-TIME"),
        el("div", "sp-head", crestBox(teams, "home"), el("span", "sp-score", score ? `${score.home} – ${score.away}` : ""),
          crestBox(teams, "away")),
        el("p", "sp-clubs", el("span", "", fullName(teams.home)), el("span", "", fullName(teams.away))),
        ...rows.map(statPill),
      ));
    },
  };
}
