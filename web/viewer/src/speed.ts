// What a ball speed on screen or in the viewer's voice may say (the Coordinator's option H, Oct 25).
// Every speed in the bundle's words is a ball speed from vision (ninety/agents/cues.py, the claims,
// the audio description, the commentary). Until its error is measured (#331), nothing says one.
// Once it is measured, a speed is said only with its error band, and never one a ball can't reach:
// GROUNDING P3, 40 m/s. Fails closed: any number with a speed unit goes, however it is joined.

import type { AudioLine, ClaimTrace, Cue } from "./bundle";
import type { CommentaryLine } from "./commentary";

export const BALL_CAP_KMH = 40 * 3.6; // GROUNDING P3

/** manifest.speed: whether vision's ball-speed error is measured, and that error (km/h). */
export interface SpeedGate {
  measured?: boolean;
  error_kmh?: number | null;
}

// "49 km/h" on screen, "49 kilometres an hour" spoken, with what joins it to the sentence
// (", " or " at "), which goes with it.
// The number is whole ("1,049" is one number, not 49); km/h is the unit a band is given in, and any
// other speed unit (mph, m/s, metres a second) is never said.
const SPEED =
  /(,\s*|\s+at\s+|\s+)?(\d{1,3}(?:,\d{3})+(?:\.\d+)?|\d+(?:\.\d+)?)\s*(km\/hr?|kph|kmh|kilomet(?:re|er)s?\s+(?:an|per)\s+hour|mph|miles\s+(?:an|per)\s+hour|m\/s|met(?:re|er)s?\s+(?:a|per)\s+second)(?![a-z])/gi;
const KMH = /^(km\/hr?|kph|kmh|kilomet)/i;

/** The text with each ball speed it may not say taken out, and each one it may say given its band. */
export function airSpeed(text: string, gate?: SpeedGate | null): string {
  const band = gate?.measured === true && gate.error_kmh != null ? Math.round(gate.error_kmh) : null;
  const out = text.replace(SPEED, (_whole, lead: string | undefined, v: string, unit: string) => {
    if (band === null || !KMH.test(unit) || Number(v.replace(/,/g, "")) > BALL_CAP_KMH) return "";
    const spoken = /hour/i.test(unit);
    return `${lead ?? ""}${v} ${spoken ? `${unit}, give or take ${band}` : `± ${band} ${unit}`}`;
  });
  return out === text ? text : out.replace(/\s{2,}/g, " ").replace(/\s+([,.!?])/g, "$1").replace(/,([.!?])/g, "$1").trim();
}

/** The cues with their speeds gated; a cue left with nothing to say is dropped. */
export function airSpeeds(cues: Cue[], gate?: SpeedGate | null): Cue[] {
  return cues
    .map((c) => ({ ...c, text: airSpeed(c.text, gate) }))
    .filter((c) => c.text.trim() !== "");
}

/** The trace panel's claims: what each said, and each step's detail. */
export function claimSpeeds(claims: ClaimTrace[], gate?: SpeedGate | null): ClaimTrace[] {
  return claims.map((c) => ({
    ...c,
    text: airSpeed(c.text, gate),
    steps: c.steps.map((s) => ({ ...s, detail: airSpeed(s.detail, gate) })),
  }));
}

/** Lines the viewer says aloud (the audio description, the commentary). A line whose words change
 * loses nothing else, but one with a recording that says the speed is dropped: the recording can't be
 * edited. */
export function spokenSpeeds(said: AudioLine[], gate?: SpeedGate | null): AudioLine[] {
  return said.flatMap((l) => {
    const text = airSpeed(l.text, gate);
    const spoken = airSpeed(l.spoken, gate);
    if (text === l.text && spoken === l.spoken) return [l];
    return l.file ? [] : [{ ...l, text, spoken }];
  });
}

export function commentarySpeeds(lines: CommentaryLine[], gate?: SpeedGate | null): CommentaryLine[] {
  return lines.flatMap((l) => {
    const text = airSpeed(l.text, gate);
    if (text === l.text) return [l];
    return l.audio ? [] : [{ ...l, text }];
  });
}
