// The big screen's match stats (Kian, Oct 26), as leagues put them up: a card under the scorebug every
// ten minutes of match time (two rows, numbers either side over a thin two-colour bar), and at
// half-time and full time the score large with the crests over a stack of white rows.
// Rows are only what the bundle measured: the team stats counted from detected events (match.json
// `stats`) and the Insight Scout's confident rows (`insight_stats`, the phone's gate: an unsure row
// is not shown). A count that contradicts the scorebug (fewer attempts than goals: every goal is an
// attempt) is not shown either. The score is the scorebug's read (src/scorebug.ts), never counted.

import { crestOf } from "./crests";
import { cardHead, splitBar, statRow } from "./lowerthird";
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
/** The card's cadence and length, and the half-time panel's (Kian: ~10 min, ~8 s); full time holds. */
export const CARD_EVERY_S = 600, CARD_S = 8, PANEL_S = 8;
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

/** Which stats graphic is up at video time v (match time t): the panel at half-time (the first
 * PANEL_S of footage from the clock's 45:00) or full time (from the engine's 90:00, Law 7, or the
 * footage's end, held), else the card for CARD_S from each tenth minute the footage reaches; or none. */
export function statsGraphicAt(v: number, t: number, videoTime: (t: number) => number, start: number, ended: boolean):
  { kind: "panel"; period: "HT" | "FT" } | { kind: "card"; minute: number } | null {
  if (ended || t >= MATCH_S - FT_LEAD_S) return { kind: "panel", period: "FT" };
  if (start < HALF_S) {
    const ht = videoTime(HALF_S);
    if (v >= ht && v < ht + PANEL_S) return { kind: "panel", period: "HT" };
  }
  for (let b = CARD_EVERY_S; b < MATCH_S; b += CARD_EVERY_S) {
    if (b <= start || b === HALF_S) continue;
    const at = videoTime(b);
    if (v >= at && v < at + CARD_S) return { kind: "card", minute: b / 60 };
  }
  return null;
}

/** The card's two rows: possession and attempts when measured, as leagues show them, else passes
 * and pass accuracy. */
const CARD_ROWS = ["possession", "shots", "passes", "accuracy"];

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

/** The card under the bug and the half-time and full-time panel, built when what they show changes.
 * `busy`: another graphic is under the bug (an insight or a goal), so the card waits its turn. */
export function setupStats(card: HTMLElement, panel: HTMLElement, m: Stats | null, teams: TeamNames, codes: Record<Side, string>) {
  let key = "";
  return {
    tick(v: number, t: number, videoTime: (t: number) => number, start: number, ended: boolean, score: Pair | null, busy: boolean) {
      const g0 = m ? statsGraphicAt(v, t, videoTime, start, ended) : null;
      const g = g0?.kind === "card" && busy ? null : g0;
      const rows = g ? rowsAt(m, g.kind === "card" ? g.minute * 60 : t, score) : [];
      const pick = g?.kind === "card" ? rows.filter((r) => CARD_ROWS.includes(r.key)).slice(0, 2) : rows;
      const k = g ? `${g.kind}|${"period" in g ? g.period : g.minute}|${score?.home}-${score?.away}|${pick.map((r) => r.key + r.home + r.away).join()}` : "";
      if (k === key) return;
      key = k;
      card.hidden = !(g?.kind === "card" && pick.length);
      panel.hidden = g?.kind !== "panel";
      if (g?.kind === "card" && pick.length) {
        card.replaceChildren(el("div", "card", cardHead("MATCH STATS", `${g.minute}′`, null, { teams, codes }),
          el("p", "card-row card-teams", el("span", "", codes.home), el("span", "", codes.away)),
          ...pick.map((r) => statRow(r.label, r.home, r.away, r.unit))));
      }
      if (g?.kind !== "panel") return;
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
