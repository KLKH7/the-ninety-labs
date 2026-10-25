// The two demo clubs' crests (Kian's choice), as inline SVG: shared by the big screen and the phone.
import londonCrest from "./crests/london-athletic.svg?raw";
import lisbonCrest from "./crests/lisbon-esportes.svg?raw";

/** A club's crest by its short name, or null for a club without one (drawn as nothing). */
export function crestOf(club: string): string | null {
  return club === "London" ? londonCrest : club === "Lisbon" ? lisbonCrest : null;
}
