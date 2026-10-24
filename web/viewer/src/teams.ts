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
  FEN: "Lisbon Esportes", // renamed by Kian, Oct 24
  GRV: "Grovely",
  HLT: "Holtmoor",
  IVY: "Ivydale",
  KST: "Kestwood",
  MRL: "Merlton",
  OAK: "London Athletic", // renamed by Kian, Oct 24
  QRY: "Quarrydale",
};

/** The demo's two clubs (Kian, Oct 24): London Athletic at home, Lisbon Esportes away. Screens say
 * the short name ("London"); the full name heads the line-ups. */
export const DEFAULT_TEAMS: TeamNames = { home: "London", away: "Lisbon" };

/** A club's short name, as running text says it: the first word of its full name. */
export const short = (full: string) => full.split(" ")[0];

/** A club's full name from its short one, when the codes know it. */
export function fullName(name: string): string {
  return Object.values(CLUBS).find((full) => short(full) === name) ?? name;
}

/** The clubs a payload names, by code (a bundle's `teams`) or by name (an answer's); otherwise the
 * default. */
export function teamNames(from: unknown): TeamNames {
  const t = from as Partial<TeamNames> | null | undefined;
  const name = (s: unknown): string | null =>
    typeof s !== "string" ? null : CLUBS[s] ? short(CLUBS[s]) : (/^[\p{L}][\p{L} .'-]{0,23}$/u.test(s) && !/^(home|away)$/i.test(s) ? short(s) : null);
  const home = name(t?.home);
  const away = name(t?.away);
  return home && away && home !== away ? { home, away } : DEFAULT_TEAMS;
}

/** A player as a fan reads him: the name or role a payload gives (`names`), otherwise his club and
 * shirt ("Lisbon 7"), or for a tracked player his club and the tracker's number ("Lisbon player
 * 12"): never an invented name, shirt or role. */
export function playerLabel(id: string, teams: TeamNames, names?: Record<string, string>): string {
  const given = names?.[id];
  if (given) return given;
  const club = teams[id.startsWith("h") ? "home" : "away"];
  const track = /^[ha]-t(\d+)$/.exec(id);
  return track ? `${club} player ${track[1]}` : `${club} ${id.slice(1)}`;
}

/** Text with every player id (h7, a-t12) said as a fan would: a given name or role, a shirt
 * ("Lisbon 7"), or, for a tracked player the agents have not named, "a Lisbon player": the
 * tracker's number is not a shirt, and reads badly in a sentence. */
export function nameIds(text: string, teams: TeamNames, names?: Record<string, string>): string {
  return text.replace(/\b[ha](?:-t\d+|[1-9]|1[01])\b/g, (id, at: number) => {
    if (names?.[id] || !id.includes("-t")) return playerLabel(id, teams, names);
    const club = teams[id.startsWith("h") ? "home" : "away"];
    return at === 0 ? `A ${club} player` : `a ${club} player`;
  });
}
