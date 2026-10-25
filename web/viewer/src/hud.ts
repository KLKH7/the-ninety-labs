// The big screen's player controls, as a streaming app draws them: over the picture, shown on a
// move, a tap or a key and faded out after IDLE_MS while playing; always up while paused. Play or
// pause, the scrubber with the chapters marked on it, the match clock, volume (only when the
// footage has a sound track), the phone's pairing code and full screen.

const IDLE_MS = 3000; // design: Apple TV and the web players fade after about three seconds

const ICONS = {
  play: '<svg viewBox="0 0 24 24" aria-hidden="true"><path d="M7 4.5v15l13-7.5z"/></svg>',
  pause: '<svg viewBox="0 0 24 24" aria-hidden="true"><path d="M6 4h4v16H6zM14 4h4v16h-4z"/></svg>',
  sound: '<svg viewBox="0 0 24 24" aria-hidden="true"><path d="M4 9h4l5-4v14l-5-4H4z"/><path class="line" d="M16 8.5a5 5 0 0 1 0 7M18.5 6a8.5 8.5 0 0 1 0 12"/></svg>',
  muted: '<svg viewBox="0 0 24 24" aria-hidden="true"><path d="M4 9h4l5-4v14l-5-4H4z"/><path class="line" d="m16 9 5 6m0-6-5 6"/></svg>',
  qr: '<svg viewBox="0 0 24 24" aria-hidden="true"><path d="M3 3h7v7H3zm2 2v3h3V5zM14 3h7v7h-7zm2 2v3h3V5zM3 14h7v7H3zm2 2v3h3v-3zM14 14h3v3h-3zm4 0h3v3h-3zm-4 4h3v3h-3zm4 0h3v3h-3z"/></svg>',
  full: '<svg viewBox="0 0 24 24" aria-hidden="true"><path class="line" d="M4 9V4h5M15 4h5v5M20 15v5h-5M9 20H4v-5"/></svg>',
  exit: '<svg viewBox="0 0 24 24" aria-hidden="true"><path class="line" d="M9 4v5H4M20 9h-5V4M15 20v-5h5M4 15h5v5"/></svg>',
};

export interface HudFootage {
  paused(): boolean;
  duration: number;
}

export function setupHud(opts: {
  footage: HudFootage;
  video: HTMLVideoElement | null;
  chapters: { at: number; goal: boolean }[]; // video seconds
  play: HTMLButtonElement;
  scrub: HTMLInputElement;
  clock: HTMLOutputElement;
  qrOpen: (open: boolean) => void;
}) {
  const $ = (id: string) => document.getElementById(id) as HTMLElement;
  const hud = $("hud");
  const stage = $("stage");
  // The page's own controls move onto the picture: the same elements, so their keys and labels hold.
  $("hud-scrub").prepend(opts.scrub);
  $("hud-left").append(opts.play, opts.clock);
  opts.play.innerHTML = ICONS.play + ICONS.pause;
  opts.play.classList.add("icon");
  $("ticks").replaceChildren(
    ...opts.chapters
      .filter((c) => c.at > 0.5 && c.at < opts.footage.duration)
      .map((c) => {
        const i = document.createElement("i");
        i.className = c.goal ? "goal" : "";
        i.style.left = `${(100 * c.at) / opts.footage.duration}%`;
        return i;
      }),
  );

  const volume = $("hud-volume") as HTMLButtonElement;
  const full = $("hud-full") as HTMLButtonElement;
  const qr = $("hud-qr") as HTMLButtonElement;
  qr.innerHTML = ICONS.qr;
  const v = opts.video;
  const hasSound = () => {
    if (!v) return false;
    const m = v as HTMLVideoElement & { audioTracks?: { length: number }; mozHasAudio?: boolean; webkitAudioDecodedByteCount?: number };
    return (m.audioTracks?.length ?? 0) > 0 || !!m.mozHasAudio || (m.webkitAudioDecodedByteCount ?? 0) > 0;
  };
  const showVolume = () => {
    volume.hidden = !hasSound();
    if (!v) return;
    volume.innerHTML = v.muted ? ICONS.muted : ICONS.sound;
    volume.setAttribute("aria-label", v.muted ? "Sound on" : "Mute");
  };
  volume.addEventListener("click", () => {
    if (v) v.muted = !v.muted;
    showVolume();
  });
  v?.addEventListener("loadeddata", showVolume);
  v?.addEventListener("playing", () => setTimeout(showVolume, 1000));
  showVolume();

  const showFull = () => {
    const on = !!document.fullscreenElement;
    full.innerHTML = on ? ICONS.exit : ICONS.full;
    full.setAttribute("aria-label", on ? "Exit full screen" : "Full screen");
  };
  const toggleFull = () => {
    if (document.fullscreenElement) void document.exitFullscreen();
    else void document.documentElement.requestFullscreen?.().catch(() => undefined);
  };
  full.addEventListener("click", toggleFull);
  document.addEventListener("fullscreenchange", showFull);
  showFull();

  let qrIsOpen = false;
  const setQr = (open: boolean) => {
    qrIsOpen = open;
    qr.setAttribute("aria-expanded", String(open));
    opts.qrOpen(open);
  };
  qr.addEventListener("click", () => setQr(!qrIsOpen));

  // Shown on any move, tap or key; faded after IDLE_MS of nothing while the match plays.
  let timer = 0;
  const wake = () => {
    document.body.dataset.ui = "on";
    clearTimeout(timer);
    timer = window.setTimeout(sleep, IDLE_MS);
  };
  const sleep = () => {
    if (opts.footage.paused() || hud.contains(document.activeElement) && document.activeElement !== opts.scrub) return wake();
    document.body.dataset.ui = "off";
  };
  for (const ev of ["pointermove", "pointerdown", "keydown", "focusin"]) document.addEventListener(ev, wake);
  stage.addEventListener("pointerleave", () => {
    if (!opts.footage.paused()) document.body.dataset.ui = "off";
  });
  wake();

  return {
    toggleFull,
    /** Each frame: the play button's icon and label follow the footage. */
    tick() {
      const paused = opts.footage.paused();
      opts.play.dataset.paused = String(paused);
      opts.play.setAttribute("aria-label", paused ? "Play" : "Pause");
    },
    closeQr: () => setQr(false),
    get qrOpen() {
      return qrIsOpen;
    },
  };
}
