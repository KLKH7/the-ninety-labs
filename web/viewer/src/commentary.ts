// The big screen's audio tracks, as a streaming app's audio menu offers them: "Stadium" (the crowd
// and whistles bed alone) or "Commentary" (the bundle's commentary lines over it, the bed ducked
// under each line), and optional captions for the commentary. Commentary is on by default when the
// bundle has it (Kian, Oct 26: "no stadium noise and no commentary"). A line with no recorded audio
// is silent, its caption kept: the browser's voice is never used (Kian, Oct 27: "robotic").
//
// The bed is the footage's own sound track when the render has one, else the bundle's `stadium`
// file, else a placeholder crowd murmur made here (filtered noise, no data in it) until the
// re-render with crowd sound lands. Format: commentary.json, agreed with the commentary's
// producer (R4 shape agents): lines in match seconds, oldest first, never overlapping.

export interface CommentaryLine {
  id: string;
  t: number; // match seconds
  t_end: number;
  /** Video seconds (shape agents, #328): the calls are spaced on the video's clock, so a line
   * never spans a cut. Played by these when present; `t` stays the match time. */
  v?: number;
  v_end?: number;
  text: string;
  audio: string | null; // relative to the bundle; null when the line was not voiced: caption only
}
export interface Commentary {
  format: 1;
  lines: CommentaryLine[];
}

/** Stadium alone; commentary over it; or the audio description persona (src/narrator.ts), which
 * the main page runs. */
export type Track = "stadium" | "commentary" | "described";
const DUCK = 0.3; // design: the crowd under a line, as a broadcast mix sits it
const DRIFT_S = 0.3; // re-align an audio element further than this from the picture
const MURMUR_GAIN = 0.16; // design: the placeholder crowd, well under a voice
const DESCRIBED_BED = 0.5; // design: the bed under the audio description's lines

/** The line on air at video time `v` (match time `t` for a line without video times), if any. */
export function lineAt(lines: CommentaryLine[], t: number, v: number): CommentaryLine | null {
  for (const l of lines) {
    if (typeof l.v === "number" && typeof l.v_end === "number" ? l.v <= v && v < l.v_end : l.t <= t && t < l.t_end) return l;
  }
  return null;
}
/** Seconds of its audio into line `l` at video time `v`, match time `t`: a line timed on the match
 * clock is heard at real time while the footage may run faster (`timescale`, match s per video s). */
const into = (l: CommentaryLine, t: number, v: number, timescale = 1) =>
  typeof l.v === "number" ? v - l.v : (t - l.t) / timescale;

export function readCommentary(body: unknown): Commentary | null {
  const c = body as Partial<Commentary> | null;
  if (!c || c.format !== 1 || !Array.isArray(c.lines)) return null;
  const lines = c.lines.filter(
    (l): l is CommentaryLine =>
      !!l && typeof l.id === "string" && typeof l.t === "number" && typeof l.t_end === "number" && l.t_end > l.t &&
      typeof l.text === "string" && (l.audio === null || (typeof l.audio === "string" && !/^[a-z]+:|^\/|\.\./i.test(l.audio))),
  );
  return { format: 1, lines: lines.sort((a, b) => a.t - b.t) };
}

export class AudioTracks {
  track: Track = "stadium";
  captions = false;
  muted = false;
  private line: CommentaryLine | null = null;
  private voice = new Audio();
  private bed: HTMLAudioElement | null;
  private murmur: Murmur | null = null;
  private own = false; // the footage has its own sound track: it is the bed

  /** The footage's baked speed (manifest footage.timescale), set by main.ts. */
  timescale = 1;

  constructor(
    private base: string,
    private commentary: Commentary | null,
    stadium: string | null,
    private captionEl: HTMLElement,
    private video: HTMLVideoElement | null = null,
    muxed = false, // the manifest says the footage carries the crowd bed (footage.audio, #397)
  ) {
    this.own = muxed && !!video;
    this.bed = stadium ? new Audio(new URL(stadium, new URL(base, location.href)).href) : null;
    if (this.bed) this.bed.loop = false;
    this.voice.preload = "auto";
    if (!this.bed && !this.own) this.murmur = new Murmur();
    if (commentary?.lines.length) this.track = "commentary";
  }

  get hasCommentary(): boolean {
    return !!this.commentary?.lines.length;
  }
  /** Whether this bundle offers anything to choose: commentary, or an audio description. */
  described = false;
  /** There is always a bed on the big screen: the footage's, the bundle's or the murmur. */
  get hasSound(): boolean {
    return true;
  }
  /** Where the bed comes from, for the tests and the pipeline note. */
  get bedSource(): "footage" | "stadium" | "murmur" {
    return this.own ? "footage" : this.bed ? "stadium" : "murmur";
  }

  /** Each frame: `v` video seconds, `t` match seconds, whether the picture plays. */
  update(v: number, t: number, playing: boolean) {
    const on = this.track === "commentary" && this.commentary ? lineAt(this.commentary.lines, t, v) : null;
    if (on?.id !== this.line?.id) {
      this.line = on;
      this.voice.pause();
      if (on?.audio) this.voice.src = new URL(on.audio, new URL(this.base, location.href)).href;
      // Not recorded: silent, its caption only (Kian, Oct 27: the browser's voice sounds robotic).
      // Commentary is the bundle's voiced audio (ninety/speech/bundle.py) or nothing.
    }
    const shown = this.captions && on ? on.text : "";
    if (this.captionEl.textContent !== shown) this.captionEl.textContent = shown;
    this.captionEl.hidden = !shown;
    document.body.dataset.commentary = on ? on.id : "";
    for (const [el, at] of [[this.bed, v], [on?.audio ? this.voice : null, on ? into(on, t, v, this.timescale) : 0]] as const) {
      if (!el) continue;
      el.muted = this.muted;
      if (!playing) {
        if (!el.paused) el.pause();
        continue;
      }
      if (Math.abs(el.currentTime - at) > DRIFT_S && el.readyState > 0) el.currentTime = Math.max(0, at);
      if (el.paused) void el.play().catch(() => undefined); // a browser may refuse before a tap
    }
    const level = on ? DUCK : this.track === "described" ? DESCRIBED_BED : 1;
    // The footage's own track, once it has decoded any sound: it replaces the placeholder for good.
    if (this.video && !this.own && playing && hasAudio(this.video)) {
      this.own = true;
      this.murmur?.stop();
      this.murmur = null;
    }
    if (this.video) {
      this.video.muted = this.muted;
      this.video.volume = level;
    }
    if (this.bed) this.bed.volume = level;
    this.murmur?.set(playing && !this.muted, level);
    document.body.dataset.bed = on ? "ducked" : "full";
    document.body.dataset.bedSource = this.bedSource;
  }
}

/** Whether a <video> has decoded any sound (Chrome, Safari) or says it has a track (Firefox). */
export function hasAudio(v: HTMLVideoElement): boolean {
  const m = v as HTMLVideoElement & { audioTracks?: { length: number }; mozHasAudio?: boolean; webkitAudioDecodedByteCount?: number };
  return (m.audioTracks?.length ?? 0) > 0 || !!m.mozHasAudio || (m.webkitAudioDecodedByteCount ?? 0) > 0;
}

/** The placeholder crowd: pink noise through a band a crowd's murmur sits in, swelling slowly.
 * Made only after a tap has started play (browsers start an AudioContext then) and never in an
 * automated browser (src/speech.ts): tests read `data-bed-source`, nobody hears them. */
class Murmur {
  private ctx: AudioContext | null = null;
  private gain: GainNode | null = null;
  private on = false;

  set(on: boolean, level: number) {
    if (on && !this.ctx) this.start();
    if (!this.ctx || !this.gain) return;
    if (on && this.ctx.state === "suspended") void this.ctx.resume();
    const want = on ? MURMUR_GAIN * level : 0;
    if (on !== this.on || Math.abs(this.gain.gain.value - want) > 0.01) {
      this.gain.gain.setTargetAtTime(want, this.ctx.currentTime, 0.25);
      this.on = on;
    }
  }

  stop() {
    void this.ctx?.close();
    this.ctx = null;
    this.gain = null;
  }

  private start() {
    if (typeof navigator !== "undefined" && navigator.webdriver) return;
    if (typeof AudioContext === "undefined") return;
    const ctx = new AudioContext();
    const seconds = 6;
    const buffer = ctx.createBuffer(2, ctx.sampleRate * seconds, ctx.sampleRate);
    for (let c = 0; c < 2; c++) {
      // Paul Kellet's pink-noise filter, one channel at a time so the two sides differ.
      const d = buffer.getChannelData(c);
      let b0 = 0, b1 = 0, b2 = 0, b3 = 0, b4 = 0, b5 = 0, b6 = 0;
      for (let i = 0; i < d.length; i++) {
        const w = Math.random() * 2 - 1;
        b0 = 0.99886 * b0 + w * 0.0555179;
        b1 = 0.99332 * b1 + w * 0.0750759;
        b2 = 0.969 * b2 + w * 0.153852;
        b3 = 0.8665 * b3 + w * 0.3104856;
        b4 = 0.55 * b4 + w * 0.5329522;
        b5 = -0.7616 * b5 - w * 0.016898;
        d[i] = (b0 + b1 + b2 + b3 + b4 + b5 + b6 + w * 0.5362) * 0.11;
        b6 = w * 0.115926;
      }
      // Cross-fade the loop's ends so it never clicks.
      const fade = ctx.sampleRate / 2;
      for (let i = 0; i < fade; i++) {
        const k = i / fade;
        d[i] = d[i] * k + d[d.length - fade + i] * (1 - k);
      }
    }
    const src = new AudioBufferSourceNode(ctx, { buffer, loop: true, loopStart: 0, loopEnd: seconds - 0.5 });
    const low = new BiquadFilterNode(ctx, { type: "highpass", frequency: 180 });
    const high = new BiquadFilterNode(ctx, { type: "lowpass", frequency: 1600 });
    const swell = new GainNode(ctx, { gain: 0.8 });
    const lfo = new OscillatorNode(ctx, { frequency: 0.09 });
    const depth = new GainNode(ctx, { gain: 0.2 });
    lfo.connect(depth).connect(swell.gain);
    const gain = new GainNode(ctx, { gain: 0 });
    src.connect(low).connect(high).connect(swell).connect(gain).connect(ctx.destination);
    src.start();
    lfo.start();
    this.ctx = ctx;
    this.gain = gain;
  }
}
