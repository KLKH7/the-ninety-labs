// Live's shot map: the detected shots so far on one half pitch, the goal at the top. Both clubs'
// shots are drawn toward the same goal: away attacks x = 0 (pitch.ts, attacksRight), so its shots
// are turned half a circle. A goal is a filled dot, a shot on target a ringed one, any other a
// hollow one. Only shots the fact-checker would let through (match.json's min_confidence).

const SVG = "http://www.w3.org/2000/svg";
const X = 105;
const Y = 68;
const DEPTH = X / 2; // the half shown, goal line to halfway

export interface Shot {
  id: string;
  t: number;
  team: "home" | "away";
  x: number;
  y: number;
  outcome: string | null;
  player: string | null;
}

/** A shot's place on the half pitch: across (0 at the attacker's left touchline) and down from the
 * goal line. Facing the goal it attacks, a team's left is toward y = 68 if it attacks x = 105
 * (pitch.ts, zoneFor), toward y = 0 otherwise. */
export function place(s: Pick<Shot, "team" | "x" | "y">): { across: number; down: number } {
  const home = s.team === "home";
  return { across: home ? Y - s.y : s.y, down: home ? X - s.x : s.x };
}

/** A shot's dot: filled for a goal, ringed on target, hollow for a miss or a block, and a plain
 * neutral ring for a shot whose outcome is not known. The live path writes no saves (lesson 258), so
 * a null outcome says nothing about where the shot went and is never drawn as a miss. */
export const kind = (o: string | null | undefined) =>
  o === "goal" ? "goal" : o === "on_target" ? "on" : o === "blocked" || o === "off_target" ? "off" : "plain";

/** The sentence for a shot: only what its outcome says, nothing for one that is not known. */
export const said = (o: string | null | undefined, who: string) =>
  o === "goal" ? `${who} scores.` : o === "on_target" ? `Shot saved, from ${who}.` : o === "blocked" ? `${who}'s shot is blocked.`
    : o === "off_target" ? `${who} shoots wide.` : `${who} shoots.`;

export const label = (o: string | null) =>
  o === "goal" ? "goal" : o === "on_target" ? "saved" : o === "blocked" ? "blocked" : o === "off_target" ? "off target" : "shot";

export function draw(svg: SVGSVGElement, shots: Shot[]) {
  const el = (tag: string, attrs: Record<string, string | number>) => {
    const e = document.createElementNS(SVG, tag);
    for (const [k, v] of Object.entries(attrs)) e.setAttribute(k, String(v));
    return e;
  };
  svg.setAttribute("viewBox", `-1 -3 ${Y + 2} ${DEPTH + 4}`);
  const mid = Y / 2;
  // Law 1 markings (docs/GROUNDING.md, L1): the penalty area 16.5 m deep and 40.32 m wide, the goal
  // area 5.5 by 18.32, the spot 11 m out, the arc 9.15 m round it, the goal 7.32 m wide.
  const arcY = 16.5;
  const dx = Math.sqrt(9.15 ** 2 - (arcY - 11) ** 2);
  const parts: Element[] = [
    el("rect", { x: 0, y: 0, width: Y, height: DEPTH, class: "turf" }),
    el("rect", { x: 0, y: 0, width: Y, height: DEPTH, class: "line" }),
    el("rect", { x: mid - 20.16, y: 0, width: 40.32, height: 16.5, class: "line" }),
    el("rect", { x: mid - 9.16, y: 0, width: 18.32, height: 5.5, class: "line" }),
    el("rect", { x: mid - 3.66, y: -2, width: 7.32, height: 2, class: "line" }),
    el("circle", { cx: mid, cy: 11, r: 0.35, class: "spot" }),
    el("path", { d: `M ${mid - dx} ${arcY} A 9.15 9.15 0 0 0 ${mid + dx} ${arcY}`, class: "line" }),
    el("path", { d: `M ${mid - 9.15} ${DEPTH} A 9.15 9.15 0 0 1 ${mid + 9.15} ${DEPTH}`, class: "line" }),
  ];
  for (const s of shots) {
    const p = place(s);
    const k = kind(s.outcome);
    parts.push(el("circle", { cx: p.across, cy: p.down, r: k === "off" || k === "plain" ? 1.1 : 1.4, class: `shot ${s.team} ${k}` }));
  }
  svg.replaceChildren(...parts);
}
