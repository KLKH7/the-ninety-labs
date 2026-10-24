// Live's territory strip: where vision's tracked ball was, per five minutes (match.json's
// `territory`, ninety/match/territory.py), drawn mirrored like a momentum graphic. Above the line is
// the home club's share, in its colour; below, the away club's. A dashed line marks half-time and a
// dot each detected goal. Dragging along it (or the arrow keys) rewinds the screen to that minute.
// It is territory, not possession: our data has no measured possession.

export interface TerritoryBin {
  t: number;
  t_end: number;
  home_s: number;
  away_s: number;
  seen_s: number;
  home: number | null;
}
export interface Territory {
  format: number;
  source: string;
  bin_s: number;
  bins: TerritoryBin[];
}

export const HALF_S = 45 * 60; // Law 7: two halves of 45 minutes
export const FULL_S = 2 * HALF_S;
const SVG = "http://www.w3.org/2000/svg";
const W = 350; // viewBox units; the strip scales to its box
const H = 72;
const MID = H / 2;

/** The strip's time axis: the whole match, or longer once the clock passes 90 minutes. */
export function span(now: number): number {
  return Math.max(FULL_S, now);
}

/** The bar for one bin: its x range and, above or below the line, how far it reaches. Even
 * territory (50%) draws nothing; all of it reaches the edge. */
export function bar(b: TerritoryBin, end: number): { x0: number; x1: number; up: number; down: number } | null {
  if (b.home === null) return null;
  const lean = b.home - 0.5; // > 0 toward home
  return {
    x0: (b.t / end) * W,
    x1: (Math.min(b.t_end, end) / end) * W,
    up: lean > 0 ? lean * 2 * (MID - 2) : 0,
    down: lean < 0 ? -lean * 2 * (MID - 2) : 0,
  };
}

/** Minute n as the match clock says it (the 1st minute is 0:00 to 0:59). */
export const minuteOf = (t: number) => Math.floor(Math.max(0, t) / 60) + 1;

/** The bin holding time t, if the footage has one. */
export function binAt(tr: Territory, t: number): TerritoryBin | undefined {
  return tr.bins.find((b) => b.t <= t && t < b.t_end);
}

/** What the strip says at time t, in words (the slider's value text). */
export function sayAt(tr: Territory, t: number, names: { home: string; away: string }): string {
  const b = binAt(tr, t);
  const m = `Minute ${minuteOf(t)}`;
  if (!b || b.home === null) return `${m}: no footage of this spell`;
  const h = Math.round(b.home * 100);
  const lead = h === 50 ? "territory even" : h > 50 ? `${names.home} ${h}% of territory` : `${names.away} ${100 - h}% of territory`;
  return `${m}: ${lead}, from ${Math.round(b.seen_s)} seconds of footage`;
}

/** Draws the strip into `svg`: bars, the half-time line, goal dots, the now line and the playhead. */
export function draw(
  svg: SVGSVGElement,
  tr: Territory,
  now: number,
  at: number | null,
  goals: { t: number; team: "home" | "away" | null }[],
) {
  const end = span(now);
  svg.setAttribute("viewBox", `0 0 ${W} ${H}`);
  const el = (tag: string, attrs: Record<string, string | number>) => {
    const e = document.createElementNS(SVG, tag);
    for (const [k, v] of Object.entries(attrs)) e.setAttribute(k, String(v));
    return e;
  };
  const parts: Element[] = [el("line", { x1: 0, x2: W, y1: MID, y2: MID, class: "axis" })];
  for (const b of tr.bins) {
    if (b.t > now) continue; // never ahead of the big screen
    const r = bar(b, end);
    if (!r) continue;
    const w = Math.max(1, r.x1 - r.x0 - 1); // a 1-unit gap between bins: the 5-minute cells
    if (r.up) parts.push(el("rect", { x: r.x0, y: MID - r.up, width: w, height: r.up, rx: 1, class: "home-area" }));
    if (r.down) parts.push(el("rect", { x: r.x0, y: MID, width: w, height: r.down, rx: 1, class: "away-area" }));
    if (!r.up && !r.down) parts.push(el("rect", { x: r.x0, y: MID - 0.75, width: w, height: 1.5, class: "even" }));
  }
  const ht = (HALF_S / end) * W;
  parts.push(el("line", { x1: ht, x2: ht, y1: 2, y2: H - 2, class: "ht" }));
  for (const g of goals) {
    if (g.t > now || !g.team) continue;
    parts.push(el("circle", { cx: (g.t / end) * W, cy: g.team === "home" ? 4 : H - 4, r: 3.5, class: `goal ${g.team}` }));
  }
  const x = ((at ?? now) / end) * W;
  parts.push(el("line", { x1: x, x2: x, y1: 0, y2: H, class: at === null ? "now" : "head" }));
  svg.replaceChildren(...parts);
}
