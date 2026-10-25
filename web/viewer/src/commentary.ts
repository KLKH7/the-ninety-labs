// The big screen's audio tracks, as a streaming app's audio menu offers them: "Stadium" (the crowd
// and whistles bed alone) or "Commentary" (the bundle's pre-rendered commentary lines over it, the
// bed ducked under each line), and optional captions for the commentary. Off by default: the
// picture starts with the stadium only. Format: commentary.json, agreed with the commentary's
// producer (R4 shape agents): lines in match seconds, oldest first, never overlapping.

export interface CommentaryLine {
  id: string;
  t: number; // match seconds
  t_end: number;
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

/** The line on air at match time `t`, if any. */
export function lineAt(lines: CommentaryLine[], t: number): CommentaryLine | null {
  for (const l of lines) if (l.t <= t && t < l.t_end) return l;
  return null;
}

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

  constructor(
    private base: string,
    private commentary: Commentary | null,
    stadium: string | null,
    private captionEl: HTMLElement,
  ) {
    this.bed = stadium ? new Audio(new URL(stadium, new URL(base, location.href)).href) : null;
    if (this.bed) this.bed.loop = false;
    this.voice.preload = "auto";
  }

  get hasCommentary(): boolean {
    return !!this.commentary?.lines.length;
  }
  /** Whether this bundle offers anything to choose: commentary, or an audio description. */
  described = false;
  get hasSound(): boolean {
    return !!this.bed || this.hasCommentary;
  }

  /** Each frame: `v` video seconds, `t` match seconds, whether the picture plays. */
  update(v: number, t: number, playing: boolean) {
    const on = this.track === "commentary" && this.commentary ? lineAt(this.commentary.lines, t) : null;
    if (on?.id !== this.line?.id) {
      this.line = on;
      this.voice.pause();
      if (on?.audio) this.voice.src = new URL(on.audio, new URL(this.base, location.href)).href;
    }
    const shown = this.captions && on ? on.text : "";
    if (this.captionEl.textContent !== shown) this.captionEl.textContent = shown;
    this.captionEl.hidden = !shown;
    document.body.dataset.commentary = on ? on.id : "";
    for (const [el, at] of [[this.bed, v], [on?.audio ? this.voice : null, on ? t - on.t : 0]] as const) {
      if (!el) continue;
      el.muted = this.muted;
      if (!playing) {
        if (!el.paused) el.pause();
        continue;
      }
      if (Math.abs(el.currentTime - at) > DRIFT_S && el.readyState > 0) el.currentTime = Math.max(0, at);
      if (el.paused) void el.play().catch(() => undefined); // a browser may refuse before a tap
    }
    if (this.bed) {
      this.bed.volume = on ? DUCK : 1;
      document.body.dataset.bed = on ? "ducked" : "full";
    }
  }

  stop() {
    this.voice.pause();
    this.bed?.pause();
  }
}
