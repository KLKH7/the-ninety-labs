// Read-aloud in the voice Kian chose (en-GB-OllieMultilingualNeural, pinned in ninety/speech/voice.py),
// never the device's system voice while there is another way (lesson 232).
//
// say(text) plays, in this order:
// 1. the bundle's pre-generated MP3 for that exact line (speech.json, by the SHA-256 of the text with
//    its whitespace collapsed, the key ninety/speech/voice.py writes): every audio description line,
//    every verified card's spoken form and its "Why?" answer, made at build time;
// 2. in Live mode only (a passcode given), the API's /api/live/speak, which speaks an Ask answer the
//    server itself gave (ninety/api/speak.py);
// 3. the device's speechSynthesis, only when neither has the line (offline, or a line built on the
//    phone in Replay mode).
// A new line stops the one before. Read-aloud is off until the fan turns it on: nothing here runs
// until say() is called. In an automated browser (navigator.webdriver: tests, screenshot runs) the
// default player and device voice make no sound and keep the line in window.ninetySpokenAloud, as
// web/viewer/src/speech.ts does; tests may also inject `player` and `system`.

export interface Player {
  /** Plays an MP3 at `rate` (1 = the voice's own speed), resolving when it ends. */
  play(src: string, rate: number): Promise<void>;
  stop(): void;
  /** Called from the tap that turns read-aloud on: iOS plays audio later only once a tap has. */
  unlock(): void;
}

export interface VoiceOptions {
  /** The bundle the big screen plays (its speech.json), or null without one. */
  bundleBase: URL | null;
  /** The demo passcode in Live mode, else null: without it the API is never called. */
  passcode?: () => string | null;
  /** Where the API lives: the phone is served at /phone/, the API at /api/ on the same origin. */
  apiBase?: URL;
  /** The fan's speaking rate, 0.8 to 1.6; 1 when not given. */
  rate?: () => number;
  player?: Player;
  /** The device's voice, the last resort (the phone passes speakAloud with its rate). */
  system?: (text: string) => void;
  stopSystem?: () => void;
}

export interface Voice {
  /** `answer`: for an Ask answer, the text exactly as /api/ask returned it, when `text` is that
   * answer with its player ids named (web/viewer/src/teams.ts nameIds); the API checks the one
   * against the other before it speaks. */
  say(text: string, answer?: string): Promise<"bundle" | "api" | "system" | "none">;
  stop(): void;
  unlock(): void;
}

type Lines = Record<string, { file: string }>;

export function normalise(text: string): string {
  return text.split(/\s+/).filter(Boolean).join(" ");
}

export async function lineKey(text: string): Promise<string> {
  const digest = await crypto.subtle.digest("SHA-256", new TextEncoder().encode(normalise(text)));
  return [...new Uint8Array(digest)].map((b) => b.toString(16).padStart(2, "0")).join("");
}

/** A tenth of a second of silence as a WAV blob: what unlock() plays (the page's CSP allows blob:
 * media, not data:). */
function silence(): Blob {
  const samples = 2400;
  const view = new DataView(new ArrayBuffer(44 + samples * 2));
  const text = (at: number, s: string) => [...s].forEach((c, i) => view.setUint8(at + i, c.charCodeAt(0)));
  text(0, "RIFF");
  view.setUint32(4, 36 + samples * 2, true);
  text(8, "WAVEfmt ");
  view.setUint32(16, 16, true);
  view.setUint16(20, 1, true); // PCM
  view.setUint16(22, 1, true); // mono
  view.setUint32(24, 24000, true);
  view.setUint32(28, 48000, true);
  view.setUint16(32, 2, true);
  view.setUint16(34, 16, true);
  text(36, "data");
  view.setUint32(40, samples * 2, true);
  return new Blob([view], { type: "audio/wav" });
}

function automated(): boolean {
  return typeof navigator !== "undefined" && navigator.webdriver;
}

function record(text: string) {
  const w = window as unknown as { ninetySpokenAloud?: string[] };
  (w.ninetySpokenAloud ??= []).push(text);
}

/** One <audio> element for every line, so the tap that unlocked it unlocks them all. */
export function audioPlayer(): Player {
  const audio = new Audio();
  let done: (() => void) | null = null;
  return {
    play(src, rate) {
      this.stop();
      if (automated()) {
        record(src); // a test or screenshot run: never a sound
        return Promise.resolve();
      }
      return new Promise<void>((resolve, reject) => {
        done = resolve;
        audio.onended = () => resolve();
        audio.onerror = () => reject(new Error("audio failed"));
        audio.src = src;
        audio.playbackRate = rate; // the pitch is kept (preservesPitch defaults to true)
        audio.play().catch(reject);
      });
    },
    stop() {
      audio.pause();
      done?.();
      done = null;
    },
    unlock() {
      if (automated()) return;
      const url = URL.createObjectURL(silence());
      audio.src = url;
      audio.play().catch(() => {}).finally(() => URL.revokeObjectURL(url));
    },
  };
}

function deviceVoice(text: string) {
  if (automated()) return record(text);
  if (!("speechSynthesis" in window)) return;
  speechSynthesis.cancel();
  const u = new SpeechSynthesisUtterance(text);
  u.lang = "en-GB";
  speechSynthesis.speak(u);
}

export function createVoice(options: VoiceOptions): Voice {
  const player = options.player ?? audioPlayer();
  const system = options.system ?? deviceVoice;
  const stopSystem = options.stopSystem ?? (() => "speechSynthesis" in window && speechSynthesis.cancel());
  const apiBase = options.apiBase ?? new URL("../", location.href);
  const rate = () => Math.min(1.6, Math.max(0.8, options.rate?.() ?? 1));
  let lines: Promise<Lines> | null = null;
  let current = 0; // the line being said; an older say() that resolves late says nothing
  let blob: string | null = null;

  const index = () =>
    (lines ??= options.bundleBase
      ? fetch(new URL("speech.json", options.bundleBase))
          .then((r) => (r.ok ? r.json() : { lines: {} }))
          .then((j: { lines?: Lines }) => j.lines ?? {})
          .catch((): Lines => ({}))
      : Promise.resolve<Lines>({}));

  function stop() {
    current++;
    player.stop();
    stopSystem();
    if (blob) URL.revokeObjectURL(blob);
    blob = null;
  }

  async function say(text: string, answer?: string) {
    stop();
    const mine = current;
    const line = normalise(text);
    if (!line) return "none" as const;
    try {
      const [found, key] = await Promise.all([index(), lineKey(line)]);
      if (mine !== current) return "none" as const;
      const hit = found[key];
      if (hit && options.bundleBase) {
        await player.play(new URL(hit.file, options.bundleBase).toString(), rate());
        return "bundle" as const;
      }
      const passcode = options.passcode?.() ?? null;
      if (passcode && navigator.onLine !== false) {
        const r = await fetch(new URL("api/live/speak", apiBase), {
          method: "POST",
          headers: { "content-type": "application/json", "x-ninety-passcode": passcode },
          body: JSON.stringify(answer === undefined ? { text: line } : { text: line, answer }),
        });
        if (r.ok && mine === current) {
          blob = URL.createObjectURL(await r.blob());
          if (mine !== current) return "none" as const;
          await player.play(blob, rate());
          return "api" as const;
        }
      }
    } catch {
      // A line that cannot be played in the chosen voice is still said, by the device.
    }
    if (mine !== current) return "none" as const;
    system(line);
    return "system" as const;
  }

  return { say, stop, unlock: () => player.unlock() };
}
