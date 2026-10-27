// The audio description track (ninety/speech/describe.py), played in time with the footage.
//
// Each line is said once, as the clock passes its start, from the bundle's recorded audio
// (`ninety-e2e --speech azure`), placed in stereo by its `pan`. A line without its file is not
// spoken: the browser's voice is never used (Kian, Oct 27: "robotic"); the viewer shows and the
// screen reader reads its text instead (`at`, main.ts). A seek or a pause stops the voice: nothing
// is said late.

import type { AudioLine } from "./bundle";

const SEEK_S = 0.5; // a clock jump bigger than this is a seek, not playback

export interface NarratorState {
  spoken: string[]; // ids said so far, in order (the viewer tests read this)
  voice: "recorded" | "none";
}

export class Narrator {
  readonly state: NarratorState;
  private last = Number.NaN;
  private ctx: AudioContext | null = null;
  private current: AudioBufferSourceNode | null = null;

  constructor(
    private readonly lines: AudioLine[],
    private readonly base: string,
  ) {
    const recorded = lines.length > 0 && lines.every((l) => l.file);
    // Recorded lines only: a line without its file is silent, its caption kept (Kian, Oct 27: the
    // browser's voice sounds robotic). "browser" stays in the type for bundles' notes, never set.
    this.state = { spoken: [], voice: recorded ? "recorded" : "none" };
  }

  /** Called every frame with match time. Says the lines whose start the clock just passed. */
  update(t: number, playing: boolean, on: boolean) {
    const from = this.last;
    this.last = t;
    if (!on || !playing) {
      this.stop();
      return;
    }
    if (Number.isNaN(from) || t < from || t - from > SEEK_S) {
      this.stop();
      return;
    }
    for (const line of this.lines) {
      if (line.t_in > from && line.t_in <= t) this.say(line);
    }
  }

  /** The line on air at match time `t` (its start passed, its end not), or null: what the viewer
   * shows and a screen reader reads when the bundle's lines are not voiced. */
  at(t: number): AudioLine | null {
    return this.lines.find((l) => l.t_in <= t && t < l.t_out) ?? null;
  }

  /** Says the line on air at `t` again, or the last one before it. */
  repeat(t: number) {
    const line = [...this.lines].reverse().find((l) => l.t_in <= t);
    if (line) this.say(line);
  }

  stop() {
    this.current?.stop();
    this.current = null;
  }

  private audio(): AudioContext | null {
    if (typeof navigator !== "undefined" && navigator.webdriver) return null; // automated: silent (speech.ts)
    if (!this.ctx && typeof AudioContext !== "undefined") this.ctx = new AudioContext();
    if (this.ctx?.state === "suspended") void this.ctx.resume();
    return this.ctx;
  }

  private say(line: AudioLine) {
    this.stop();
    this.state.spoken.push(line.id);
    const ctx = this.audio();
    if (line.file && ctx) {
      void fetch(this.base + line.file)
        .then((r) => r.arrayBuffer())
        .then((b) => ctx.decodeAudioData(b))
        .then((buffer) => {
          const src = new AudioBufferSourceNode(ctx, { buffer });
          src.connect(new StereoPannerNode(ctx, { pan: line.pan })).connect(ctx.destination);
          src.start();
          this.current = src;
        })
        .catch(() => undefined); // a file that will not play: silent, never the browser's voice
    }
    // No file: silent, the caption only.
  }
}
