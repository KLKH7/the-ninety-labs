// A fan's listening and reading choices: the voice, how fast it speaks, whether what is read
// aloud is also shown as a transcript, and the text size. Kept in this browser only (localStorage,
// guarded: private windows refuse it), never sent anywhere.

export type TextSize = "normal" | "large" | "xlarge";
export interface Settings {
  voice: string | null; // a speechSynthesis voice name; null is the browser's default
  rate: number; // 0.8 to 1.6
  transcript: boolean;
  text: TextSize;
}

const KEY = "ninety.settings";
export const RATES = { min: 0.8, max: 1.6, step: 0.1 }; // design: slow enough to follow, fast enough to keep up
const DEFAULTS: Settings = { voice: null, rate: 1, transcript: true, text: "normal" };

export function load(): Settings {
  try {
    const raw = JSON.parse(localStorage.getItem(KEY) ?? "{}") as Partial<Settings>;
    const rate = typeof raw.rate === "number" ? Math.min(RATES.max, Math.max(RATES.min, raw.rate)) : DEFAULTS.rate;
    const text: TextSize = ["normal", "large", "xlarge"].includes(raw.text as string) ? (raw.text as TextSize) : DEFAULTS.text;
    return {
      voice: typeof raw.voice === "string" ? raw.voice : null,
      rate,
      transcript: typeof raw.transcript === "boolean" ? raw.transcript : DEFAULTS.transcript,
      text,
    };
  } catch {
    return { ...DEFAULTS };
  }
}

export function save(s: Settings) {
  try {
    localStorage.setItem(KEY, JSON.stringify(s));
  } catch {
    // a private window: the choice lasts for this visit only
  }
}

// The novelty and robotic voices macOS and iOS ship (sound effects and the old Eloquence set):
// never offered to a fan.
const NOVELTY = new Set(["Albert", "Bad News", "Bahh", "Bells", "Boing", "Bubbles", "Cellos", "Good News", "Jester", "Organ",
  "Superstar", "Trinoids", "Whisper", "Wobble", "Zarvox", "Junior", "Ralph", "Fred", "Kathy", "Grandma", "Grandpa", "Rocko",
  "Shelley", "Flo", "Eddy", "Reed", "Sandy"]);

/** The English voices this browser has worth listening to, British first. */
export function voices(): SpeechSynthesisVoice[] {
  if (typeof speechSynthesis === "undefined") return [];
  const rank = (v: SpeechSynthesisVoice) => (v.lang.toLowerCase().startsWith("en-gb") ? 0 : 1);
  return speechSynthesis
    .getVoices()
    .filter((v) => v.lang.toLowerCase().startsWith("en") && !NOVELTY.has(v.name.replace(/ \(.*\)$/, "")))
    .sort((a, b) => rank(a) - rank(b) || a.name.localeCompare(b.name))
    .slice(0, 8);
}
