// The two clubs' names, as every screen shows them: never "home" and "away", never a colour or an
// id. Both clubs are fictional (AGENTS.md: synthetic data only, no real clubs). The renderer draws
// each clip's two clubs on the scorebug as three-letter codes (ninety/render/params.py, TEAM_CODES)
// and the bundle carries them (ninety/e2e.py, `teams`); each code has one club name here, starting
// with its code's letters, so the screen and the picture name the same club.

export type Side = "home" | "away";
export type TeamNames = Record<Side, string>;

/** One name per code in ninety/render/params.py's TEAM_CODES (design: invented, no real club). */
export const CLUBS: Record<string, string> = {
  ASH: "Ashvale",
  CRW: "Crowmere",
  DUN: "Dunhollow",
  ELM: "Elmwick",
  FEN: "Fenwick",
  GRV: "Grovely",
  HLT: "Holtmoor",
  IVY: "Ivydale",
  KST: "Kestwood",
  MRL: "Merlton",
  OAK: "Oakfield",
  QRY: "Quarrydale",
};

/** For a bundle that names no clubs (made before the codes were carried). */
export const DEFAULT_TEAMS: TeamNames = { home: "Oakfield", away: "Fenwick" };

/** The clubs a payload names, by code (a bundle's `teams`) or by name (an answer's); otherwise the
 * default. */
export function teamNames(from: unknown): TeamNames {
  const t = from as Partial<TeamNames> | null | undefined;
  const name = (s: unknown): string | null =>
    typeof s !== "string" ? null : (CLUBS[s] ?? (/^[\p{L}][\p{L} .'-]{0,23}$/u.test(s) && !/^(home|away)$/i.test(s) ? s : null));
  const home = name(t?.home);
  const away = name(t?.away);
  return home && away && home !== away ? { home, away } : DEFAULT_TEAMS;
}

/** A player as a fan reads him: the name or role a payload gives (`names`), otherwise his club and
 * shirt ("Fenwick 7"), or for a tracked player his club and the tracker's number ("Fenwick player
 * 12"): never an invented name, shirt or role. */
export function playerLabel(id: string, teams: TeamNames, names?: Record<string, string>): string {
  const given = names?.[id];
  if (given) return given;
  const club = teams[id.startsWith("h") ? "home" : "away"];
  const track = /^[ha]-t(\d+)$/.exec(id);
  return track ? `${club} player ${track[1]}` : `${club} ${id.slice(1)}`;
}

/** Text with every player id (h7, a-t12) said as `playerLabel` says it; only the names change. */
export function nameIds(text: string, teams: TeamNames, names?: Record<string, string>): string {
  return text.replace(/\b[ha](?:-t\d+|[1-9]|1[01])\b/g, (id) => playerLabel(id, teams, names));
}
