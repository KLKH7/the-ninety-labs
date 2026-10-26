// Judge-proof playback for the big screen: whatever browser opens the link, the picture starts fast
// and keeps going.
//
// Source order: the bundle's HLS ladder (footage.hls), played natively where hls.js cannot run
// (Safari on iOS) and by hls.js everywhere else; else the H.264 MP4 (footage.mp4); else the legacy
// file (footage.src, a WebM in bundles written before #397). The ladder starts at its lowest
// rendition so the first frame comes quickly, and hls.js's ABR climbs from there.
//
// Self-heal: a media error first gets hls.js's recoverMediaError, then a reload of the source at
// the current time; a stall longer than STALL_MS while playing gets the same. After REPEATS failed
// recoveries on one rendition it is capped one rung lower. The spinner is up whenever the picture
// waits, so the screen is never a silent black frame. The poster frame shows until the first frame
// decodes.

import Hls, { type ErrorData, ErrorTypes, Events } from "hls.js";

const STALL_MS = 3000; // design: past a buffering blip, short of a viewer giving up
const REPEATS = 2; // design: two failed recoveries on a rendition, then a rung lower
const RECOVER_GAP_MS = 4000; // a second media error within this is not helped by recoverMediaError
const NET_TRIES = 4; // design: segment loads retried with backoff, then the source reloaded
const NET_BACKOFF_MS = 500; // doubled each try, at most NET_BACKOFF_MAX_MS
const NET_BACKOFF_MAX_MS = 8000;
const SPIN_AFTER_MS = 700; // design: a clock stopped this long while it should play shows the spinner

export interface FootageSources {
  src: string;
  mp4?: string;
  hls?: string;
  poster?: string;
  audio?: "muxed" | null;
}

export interface PlayerState {
  source: "hls.js" | "native-hls" | "mp4" | "legacy";
  recoveries: number; // recoverMediaError calls and source reloads, for the tests
  reloads: number;
  capped: number; // the highest rendition still allowed, -1 for none (hls.js only)
  stalls: number;
}

/** Picks the source, attaches it to `video`, and keeps it playing. `spinner` is shown while it waits. */
export function attachPlayer(video: HTMLVideoElement, base: string, f: FootageSources, spinner: HTMLElement) {
  const url = (p: string) => new URL(p, new URL(base, location.href)).href;
  const state: PlayerState = { source: "legacy", recoveries: 0, reloads: 0, capped: -1, stalls: 0 };
  if (f.poster) video.poster = url(f.poster);
  let hls: Hls | null = null;
  let failures = 0;
  let lastMediaError = -Infinity;
  let netTries = 0;
  // Whether the viewer wants it playing (set by the controls through want()): a pause a reload
  // causes never clears it, and a pause the viewer asks for is never undone.
  let wanted = false;
  let healing = 0; // performance.now() until which a recovery is under way
  video.addEventListener("ended", () => (wanted = false)); // the final whistle: never restarted
  const resumeIfWanted = () => wanted && void video.play().catch(() => undefined);

  const nativeHls = () => video.canPlayType("application/vnd.apple.mpegurl") !== "";
  const mp4Plays = () => video.canPlayType('video/mp4; codecs="avc1.640028"') !== "";

  /** (Re)loads the chosen source, resuming at `at` seconds and playing on if it was. */
  const load = (at = 0, resume = false) => {
    hls?.destroy();
    hls = null;
    const seekOnce = () => {
      if (at > 0) video.currentTime = at;
      if (resume) void video.play().catch(() => undefined);
    };
    if (f.hls && Hls.isSupported()) {
      state.source = "hls.js";
      // No worker: the CSP has no worker-src for its blob: worker; the demo's ladder is light.
      hls = new Hls({ enableWorker: false, startLevel: 0, capLevelToPlayerSize: true, startPosition: at > 0 ? at : -1 });
      if (state.capped >= 0) hls.autoLevelCapping = state.capped;
      hls.on(Events.ERROR, (_e, data) => onHlsError(data));
      hls.on(Events.FRAG_LOADED, () => (netTries = 0));
      hls.loadSource(url(f.hls));
      hls.attachMedia(video);
      if (resume) hls.once(Events.MANIFEST_PARSED, () => void video.play().catch(() => undefined));
      return;
    }
    if (f.hls && nativeHls()) {
      state.source = "native-hls";
      video.src = url(f.hls);
    } else if (f.mp4 && mp4Plays()) {
      state.source = "mp4";
      video.src = url(f.mp4);
    } else {
      state.source = "legacy";
      video.src = url(f.src);
    }
    if (at > 0 || resume) video.addEventListener("loadedmetadata", seekOnce, { once: true });
  };

  /** One step up the recovery ladder: recoverMediaError, then a reload, then a rung lower. */
  const recover = (why: string) => {
    state.recoveries++;
    document.body.dataset.playback = `recovering:${why}`;
    const at = video.currentTime;
    const resume = wanted;
    const now = performance.now();
    healing = now + RECOVER_GAP_MS;
    if (hls && why !== "network" && now - lastMediaError > RECOVER_GAP_MS) {
      lastMediaError = now;
      hls.recoverMediaError();
      resumeIfWanted();
      return;
    }
    failures++;
    if (hls && failures >= REPEATS) {
      const level = hls.currentLevel >= 0 ? hls.currentLevel : hls.levels.length - 1;
      state.capped = Math.max(0, level - 1);
      failures = 0;
    }
    state.reloads++;
    load(at, resume);
  };

  const onHlsError = (data: ErrorData) => {
    if (!data.fatal) return;
    if (data.type === ErrorTypes.NETWORK_ERROR) {
      // A segment that would not load: the network again, backing off, before anything heavier.
      if (++netTries > NET_TRIES) {
        netTries = 0;
        return recover("network");
      }
      document.body.dataset.playback = "recovering:network";
      state.recoveries++;
      const h = hls;
      setTimeout(() => h === hls && h?.startLoad(video.currentTime), Math.min(NET_BACKOFF_MAX_MS, NET_BACKOFF_MS * 2 ** netTries));
      return;
    }
    recover("media");
  };
  video.addEventListener("error", () => {
    if (!hls) recover("media"); // hls.js reports its own through onHlsError
  });

  // Stall watchdog and spinner: wanted playing, but the clock has not moved for STALL_MS. The
  // spinner is up before the first frame and whenever the clock stops while it should play.
  let lastT = -1;
  let since = performance.now();
  const watch = () => {
    const now = performance.now();
    const moving = video.currentTime !== lastT;
    if (moving || !wanted || video.ended) {
      lastT = video.currentTime;
      since = now;
    }
    const stuck = wanted && !video.ended && now - since > SPIN_AFTER_MS;
    spinner.hidden = !(video.readyState < 2 || stuck);
    if (moving && wanted) document.body.dataset.playback = "playing";
    if (wanted && video.paused && now > healing) resumeIfWanted(); // paused by a reload, not by the viewer
    if (wanted && !video.ended && now - since > STALL_MS) {
      state.stalls++;
      since = now;
      recover("stall");
    }
  };
  setInterval(watch, 250);

  load();
  (window as unknown as { ninetyPlayer: unknown }).ninetyPlayer = {
    state,
    hls: () => hls,
    /** Tests: force a media error as a decoder failure would raise it. */
    fail: () => (hls ? onHlsError({ fatal: true, type: ErrorTypes.MEDIA_ERROR } as ErrorData) : recover("media")),
  };
  return {
    state,
    /** The controls' play and pause: what the viewer wants, which healing keeps to. */
    want(on: boolean) {
      wanted = on;
      if (on) void video.play().catch(() => undefined);
      else video.pause();
    },
  };
}
