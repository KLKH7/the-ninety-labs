// What a ball speed on screen may say (the Coordinator's option H, Oct 25). Every "N km/h" in a
// graphic is a ball speed from vision (ninety/agents/cues.py). Until its error is measured (#331),
// a graphic says no speed. Once it is measured, a speed shows only with its error band, and never one
// a ball can't reach: GROUNDING P3, 40 m/s.

import type { Cue } from "./bundle";

export const BALL_CAP_KMH = 40 * 3.6; // GROUNDING P3

/** manifest.speed: whether vision's ball-speed error is measured, and that error (km/h). */
export interface SpeedGate {
  measured?: boolean;
  error_kmh?: number | null;
}

// ", 49 km/h" (a pass arc, a shot) and " at 146 km/h" (an insight's sentence).
const SPEED = /(,\s*|\s+at\s+)(\d+(?:\.\d+)?)\s*km\/h/g;

/** The text with each ball speed it may not say taken out, and each one it may say given its band. */
export function airSpeed(text: string, gate?: SpeedGate | null): string {
  const band = gate?.measured && gate.error_kmh != null ? gate.error_kmh : null;
  return text.replace(SPEED, (_whole, lead: string, v: string) =>
    band === null || Number(v) > BALL_CAP_KMH ? "" : `${lead}${v}${band > 0 ? ` ± ${Math.round(band)}` : ""} km/h`,
  );
}

/** The cues with their speeds gated; a cue left with nothing to say is dropped. */
export function airSpeeds(cues: Cue[], gate?: SpeedGate | null): Cue[] {
  return cues
    .map((c) => ({ ...c, text: airSpeed(c.text, gate) }))
    .filter((c) => c.text.trim() !== "");
}
