// The audio description track (ninety/speech/describe.py), played in time with the footage.
//
// Each line is said once, as the clock passes its start. With synthesised audio in the bundle
// (`ninety-e2e --speech azure`) the line itself is placed in stereo by its `pan`; without it, a
// short tone placed by `pan` says where the play is, and the browser's own voice says the line.
// A seek or a pause stops the voice: nothing is said late.

import { speakAloud } from "./speech";
import type { AudioLine } from "./bundle";

const TONE_HZ = 880; // design: a soft, high blip, apart from crowd noise
const TONE_S = 0.09;
const TONE_GAIN = 0.12;
const SEEK_S = 0.5; // a clock jump bigger than this is a seek, not playback

export interface NarratorState {
  spoken: string[]; // ids said so far, in order (the viewer tests read this)
  voice: "recorded" | "browser" | "none";
}

export class Narrator {
  readonly state: NarratorState;
  private last = Number.NaN;
  private ctx: AudioContext | null = null;
  private current: AudioBufferSourceNode | null = null;
  private speaking = false; // the browser's voice is ours: stop() never cuts the commentary's line

  constructor(
    private readonly lines: AudioLine[],
    private readonly base: string,
  ) {
    const recorded = lines.length > 0 && lines.every((l) => l.file);
    const browser = typeof speechSynthesis !== "undefined";
    this.state = { spoken: [], voice: recorded ? "recorded" : browser ? "browser" : "none" };
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

  /** Says the line on air at `t` again, or the last one before it. */
  repeat(t: number) {
    const line = [...this.lines].reverse().find((l) => l.t_in <= t);
    if (line) this.say(line);
  }

  stop() {
    this.current?.stop();
    this.current = null;
    if (this.speaking && typeof speechSynthesis !== "undefined" && (speechSynthesis.speaking || speechSynthesis.pending)) {
      speechSynthesis.cancel();
    }
    this.speaking = false;
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
        .catch(() => this.speak(line));
      return;
    }
    if (ctx) {
      const osc = new OscillatorNode(ctx, { frequency: TONE_HZ });
      const gain = new GainNode(ctx, { gain: 0 });
      const now = ctx.currentTime;
      gain.gain.setValueAtTime(0, now);
      gain.gain.linearRampToValueAtTime(TONE_GAIN, now + 0.01);
      gain.gain.linearRampToValueAtTime(0, now + TONE_S);
      osc.connect(gain).connect(new StereoPannerNode(ctx, { pan: line.pan })).connect(ctx.destination);
      osc.start(now);
      osc.stop(now + TONE_S);
    }
    this.speak(line);
  }

  private speak(line: AudioLine) {
    this.speaking = true;
    speakAloud(line.spoken, { lang: "en-GB", rate: 1.1 });
  }
}
