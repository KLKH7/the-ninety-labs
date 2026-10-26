import { PhonePanel } from "./companion";
import { type Bundle, type ClaimTrace, type Cue, PERSONAS, type Persona, clock, loadBundle, onAir } from "./bundle";
import { drawCues, drawDetections } from "./draw";
import { AudioTracks, readCommentary } from "./commentary";
import { setupHud } from "./hud";
import { broadcastSchedule, pairCardAt, setupMatch } from "./match";
import { Narrator } from "./narrator";
import { RadarModel, type RadarState, aspect, describe, drawRadar, projection, timeline } from "./radar";
import { type TeamNames, nameIds, setSidesKnown, teamNames } from "./teams";
import { airSpeed, airSpeeds, claimSpeeds, commentarySpeeds, spokenSpeeds } from "./speed";

const $ = <T extends HTMLElement>(id: string) => document.getElementById(id) as T;

const video = $<HTMLVideoElement>("video");
const framesCanvas = $<HTMLCanvasElement>("frames");
const overlay = $<HTMLCanvasElement>("overlay");
const playButton = $<HTMLButtonElement>("play");
const scrub = $<HTMLInputElement>("scrub");
const clockOut = $<HTMLOutputElement>("clock");
const showBoxes = $<HTMLInputElement>("show-boxes");
const reduceMotionBox = $<HTMLInputElement>("reduce-motion");
const onAirText = $<HTMLParagraphElement>("on-air");
const voiceBox = $<HTMLInputElement>("voice");
const radarCanvas = $<HTMLCanvasElement>("radar");
const showRadar = $<HTMLInputElement>("show-radar");

/** Per-viewer conveniences only: storage can be missing or throw, and the page works without it. */
const store = {
  get(key: string): string | null {
    try {
      return localStorage.getItem(`ninety.${key}`);
    } catch {
      return null;
    }
  },
  set(key: string, value: string) {
    try {
      localStorage.setItem(`ninety.${key}`, value);
    } catch {
      /* not remembered */
    }
  },
};

/** The footage as one clock: a <video>, or JPEG frames drawn to a canvas at the clip's fps. */
interface Footage {
  time(): number; // seconds since the clip's first frame
  duration: number;
  paused(): boolean;
  play(): void;
  pause(): void;
  seek(seconds: number): void;
}

/** The first clean picture of a match's video: past the stinger over its first frames, half of the
 * renderer's STINGER_S (0.6 s, ninety/render/edit.py), and one frame more at 25 fps. */
const POSTER_S = 0.6 / 2 + 1 / 25;

function videoFootage(b: Bundle): Footage {
  video.src = b.base + b.manifest.footage.src;
  return {
    time: () => video.currentTime,
    duration: b.manifest.footage.frames / b.manifest.fps,
    paused: () => video.paused,
    play: () => void video.play(),
    pause: () => video.pause(),
    seek: (s) => (video.currentTime = s),
  };
}

function frameFootage(b: Bundle): Footage {
  const { fps, footage, width, height } = b.manifest;
  video.hidden = true;
  framesCanvas.hidden = false;
  framesCanvas.width = width;
  framesCanvas.height = height;
  const ctx = framesCanvas.getContext("2d")!;
  const images = new Map<number, HTMLImageElement>();
  const image = (i: number) => {
    if (!images.has(i)) {
      const img = new Image();
      img.src = `${b.base}${footage.src}${String(i).padStart(5, "0")}.jpg`;
      images.set(i, img);
    }
    return images.get(i)!;
  };
  const duration = footage.frames / fps;
  let origin = 0; // performance.now() at time 0 while playing
  let at = 0; // the time while paused
  let playing = false;
  let shown = -1;
  const time = () => (playing ? Math.min(duration, (performance.now() - origin) / 1000) : at);
  const draw = () => {
    const i = Math.min(footage.frames - 1, Math.floor(time() * fps));
    for (let k = 1; k <= 5; k++) if (i + k < footage.frames) image(i + k); // read ahead
    const img = image(i);
    if (i !== shown && img.complete && img.naturalWidth) {
      ctx.drawImage(img, 0, 0, width, height);
      shown = i;
    }
    if (playing && time() >= duration) {
      at = duration;
      playing = false;
    }
    requestAnimationFrame(draw);
  };
  requestAnimationFrame(draw);
  return {
    time,
    duration,
    paused: () => !playing,
    play() {
      if (at >= duration) at = 0;
      origin = performance.now() - at * 1000;
      playing = true;
    },
    pause() {
      at = time();
      playing = false;
    },
    seek(s) {
      at = Math.max(0, Math.min(duration, s));
      origin = performance.now() - at * 1000;
      shown = -1;
    },
  };
}

function renderPipeline(b: Bundle) {
  const m = b.manifest;
  const rows: [string, string, boolean?][] = [
    ["Clip", `${m.clip}, ${m.footage.frames} frames at ${m.fps} fps`],
    ["Detector", `${m.detector ?? "none"} (${m.detections.source}, ${m.detections.frames} frames)`],
    ["Events", `${m.events.count}: ${m.events.source}`, m.events.standin],
    ["Held", m.events.held.length ? `${m.events.held.join(", ")}: detected too unsure to air` : "none"],
    ["Stats", `${m.facts} facts computed in code`],
    ["Agents", `${m.agents.accepted} of ${m.agents.claims} claims accepted (${m.agents.mode}${m.agents.planted ? ", a false number planted on purpose" : ""})`],
    ["Graphics", `${m.cues} cues`],
    [
      "Described",
      m.audio
        ? `${m.audio.lines} lines spoken, ${m.audio.dropped} left out to keep pace, at most ${m.audio.max_lag_s.toFixed(1)} s after the play (${m.audio.mode === "azure" ? "Azure AI Speech" : "timing estimated, browser voice"})`
        : "no audio description in this bundle",
      !m.audio,
    ],
    [
      "Radar",
      m.radar
        ? `${m.radar.frames} frames of vision's tracked positions, the camera's view from its own fit in ${m.radar.footprints}`
        : "no tracked positions in this bundle",
      !m.radar,
    ],
  ];
  $("pipeline").replaceChildren(
    ...rows.flatMap(([k, v, warn]) => {
      const dt = document.createElement("dt");
      dt.textContent = k;
      const dd = document.createElement("dd");
      dd.textContent = v;
      if (warn) dd.className = "warn";
      return [dt, dd];
    }),
  );
}

function renderTrace(b: Bundle, seekTo: (matchT: number) => void) {
  const list = $("claims");
  if (!b.claims.length) {
    const li = document.createElement("li");
    li.textContent = "No claims for this clip.";
    list.replaceChildren(li);
    return;
  }
  list.replaceChildren(
    ...b.claims.map((c: ClaimTrace) => {
      const li = document.createElement("li");
      li.className = `claim ${c.status}`;
      li.dataset.claim = c.id;
      const head = document.createElement("div");
      head.className = "claim-head";
      const chip = document.createElement("span");
      chip.className = "chip";
      chip.textContent = c.status === "accepted" ? "Accepted" : c.verdict === "held" ? "Held: unsure" : "Rejected";
      const meta = document.createElement("span");
      meta.className = "meta";
      meta.textContent = `minute ${c.minute} · ${c.drafts} draft${c.drafts === 1 ? "" : "s"} · ${c.mode}`;
      head.append(chip, meta);
      const text = document.createElement("p");
      text.className = "claim-text";
      text.textContent = c.text;
      const steps = document.createElement("ol");
      steps.className = "steps";
      for (const s of c.steps) {
        const step = document.createElement("li");
        step.className = `step ${s.role} ${s.action}`;
        const who = document.createElement("strong");
        who.textContent = s.role.replace("_", " ");
        const what = document.createElement("span");
        what.className = "action";
        what.textContent = s.action;
        step.append(who, " ", what, ` ${s.detail}${s.ms ? ` (${(s.ms / 1000).toFixed(1)} s)` : ""}`);
        steps.append(step);
      }
      li.append(head, text, steps);
      if (c.t !== null) {
        const go = document.createElement("button");
        go.type = "button";
        go.className = "seek";
        go.textContent = `Watch it (${clock(c.t)})`;
        go.addEventListener("click", () => seekTo(c.t!));
        li.append(go);
      }
      return li;
    }),
  );
}

/** The big screen: in match mode the TV shows only the broadcast, its on-screen graphics, the score
 * and clock, the chapters and the QR code to pair a phone; the radar, stats, trace and pipeline
 * live on the phone. `?dev=1` keeps every panel, for building and judging the pipeline. */
export function bigScreen(matchMode: boolean, search: string): boolean {
  return matchMode && new URLSearchParams(search).get("dev") !== "1";
}

async function start() {
  const base = new URLSearchParams(location.search).get("bundle") ?? "bundle/";
  let b: Bundle;
  try {
    b = await loadBundle(base.endsWith("/") ? base : `${base}/`);
  } catch (e) {
    document.body.dataset.state = "error";
    $("claims").textContent = `Could not open the bundle: ${(e as Error).message}. Run ninety-e2e first.`;
    return;
  }
  const { manifest: m } = b;
  overlay.width = m.width;
  overlay.height = m.height;
  document.documentElement.style.setProperty("--aspect", `${m.width} / ${m.height}`);
  document.documentElement.style.setProperty("--ar", String(m.width / m.height)); // the big screen's fit
  const footage = m.footage.kind === "video" ? videoFootage(b) : frameFootage(b);
  const { matchTime, videoTime, segmentOf } = timeline(m);
  const teams = teamNames(m.teams);
  // The graphics name players by id (h4, a-t5); on screen they are the club's (src/teams.ts). Only
  // the names change, never a number, so what the fact-checking agent passed is what airs.
  setSidesKnown(m.sides_known);  // a tracked player on an unsure side is "a player", not a club
  // A ball speed airs only once its error is measured, with its band, and never above P3 (src/speed.ts).
  b.cues = airSpeeds(b.cues, m.speed).map((c) => ({ ...c, text: nameIds(c.text, teams) }));
  b.claims = claimSpeeds(b.claims, m.speed);
  if (b.audio) b.audio = { ...b.audio, said: spokenSpeeds(b.audio.said, m.speed) };
  (window as unknown as { ninetyCues: Cue[] }).ninetyCues = b.cues; // what can air; read by tests/test_viewer.py
  (window as unknown as { ninetySpeed: typeof airSpeed }).ninetySpeed = airSpeed; // read by tests/test_viewer.py
  const big = bigScreen(!!b.match, location.search);
  if (big) {
    document.body.dataset.screen = "big";
    // Open on a clean picture (demo audit 2, row 5): the match's first frames carry the stinger that
    // joins the broadcast's segments, mid-wipe. It clears within half of the renderer's STINGER_S
    // (ninety/render/edit.py, edge_stingers), so the first frame shown is the one just after it.
    if (m.footage.kind === "video")
      video.addEventListener("loadedmetadata", () => { if (video.currentTime === 0) footage.seek(POSTER_S); }, { once: true });
    showBoxes.checked = false; // the detector's boxes are the pipeline's view, not the broadcast's
  }
  scrub.max = String(footage.duration);
  scrub.step = String(1 / m.fps);
  const detections = new Map(b.detections.map((f) => [Math.round(f.t * m.fps), f]));

  let lastAired = "";
  const rememberedPersona = store.get("persona") as Persona | null;
  // The big screen has no persona switch: personas are the phone's (Kian, Oct 24).
  let persona: Persona = !big && rememberedPersona && PERSONAS.includes(rememberedPersona) ? rememberedPersona : "casual";
  const narrator = new Narrator(b.audio?.said ?? [], b.base);
  document.body.dataset.voice = narrator.state.voice;
  (window as unknown as { ninetyNarrator: Narrator }).ninetyNarrator = narrator; // read by tests/test_viewer.py
  const audioNote = $("audio-note");
  audioNote.textContent = !b.audio
    ? "This bundle has no audio description: run ninety-e2e again."
    : narrator.state.voice === "recorded"
      ? "Spoken by Azure AI Speech, placed left to right where the play is."
      : "Spoken by your browser's voice; a short tone, placed left to right, says where the play is.";
  // The voice is off until a fan picks audio description on this page: a remembered choice never
  // starts it speaking on load.
  voiceBox.checked = false;
  const applyVoice = () => {
    // With the voice on, the live region stays quiet so a screen reader does not say it twice.
    onAirText.setAttribute("aria-live", persona === "audio" && voiceBox.checked ? "off" : "polite");
  };
  voiceBox.addEventListener("change", () => {
    store.set("voice", voiceBox.checked ? "1" : "0");
    if (!voiceBox.checked) narrator.stop();
    applyVoice();
  });
  const motionQuery = matchMedia("(prefers-reduced-motion: reduce)");
  // The big screen has no motion switch: it follows the system setting alone.
  const remembered = big ? null : store.get("reduceMotion");
  reduceMotionBox.checked = remembered === null ? motionQuery.matches : remembered === "1";
  const applyMotion = () => (document.documentElement.dataset.motion = reduceMotionBox.checked ? "reduce" : "full");
  applyMotion();
  motionQuery.addEventListener("change", () => {
    if (big || store.get("reduceMotion") === null) reduceMotionBox.checked = motionQuery.matches;
    applyMotion();
  });
  reduceMotionBox.addEventListener("change", () => {
    store.set("reduceMotion", reduceMotionBox.checked ? "1" : "0");
    applyMotion();
  });

  const personaButtons = [...document.querySelectorAll<HTMLButtonElement>("#persona [role=radio]")];
  const setPersona = (p: Persona, focus = false, picked = true) => {
    if (picked && p === "audio") voiceBox.checked = store.get("voice") !== "0";
    if (big && p !== "audio") p = "casual"; // only the audio menu changes it here
    persona = p;
    if (!big) store.set("persona", p);
    document.body.dataset.persona = p;
    for (const btn of personaButtons) {
      const on = btn.dataset.persona === p;
      btn.setAttribute("aria-checked", String(on));
      btn.tabIndex = on ? 0 : -1;
      if (on && focus) btn.focus();
    }
    const audio = p === "audio";
    $("voice-toggle").hidden = !audio;
    $("audio-keys").hidden = !audio;
    audioNote.hidden = !audio;
    if (!audio) narrator.stop();
    applyVoice();
    lastAired = ""; // announce what this persona sees now
  };
  for (const btn of personaButtons) {
    btn.addEventListener("click", () => setPersona(btn.dataset.persona as Persona));
    btn.addEventListener("keydown", (e) => {
      // A radio group moves with the arrow keys (WAI-ARIA radio group pattern).
      if (["ArrowLeft", "ArrowRight", "ArrowUp", "ArrowDown"].includes(e.key)) {
        e.preventDefault();
        e.stopPropagation();
        const step = e.key === "ArrowLeft" || e.key === "ArrowUp" ? -1 : 1;
        setPersona(PERSONAS[(PERSONAS.indexOf(persona) + step + PERSONAS.length) % PERSONAS.length], true);
      }
    });
  }

  const seekMatch = (matchT: number) => {
    footage.seek(Math.max(0, videoTime(matchT) - 0.5));
    overlay.focus();
  };
  const togglePlay = () => (footage.paused() ? footage.play() : footage.pause());
  playButton.addEventListener("click", togglePlay);
  scrub.addEventListener("input", () => footage.seek(Number(scrub.value)));
  renderPipeline(b);
  renderTrace(b, seekMatch);
  const radar = setupRadar(b, segmentOf, matchTime, teams, big);
  const match = setupMatch(b, (v) => footage.seek(v), teams);
  // The phone runs on match time, across the broadcast's cuts: the same clock the radar and the
  // graphics use (lesson 33), so its radar shows the frame on the TV.
  const phone = new PhonePanel(
    m.clip,
    { time: () => matchTime(footage.time()), playing: () => !footage.paused() },
    new URL(b.base, location.href).pathname,
    big,
  );
  // The clock also goes out on a timer, not only from the frame loop: a big screen whose frames
  // stall (a hidden tab, a busy machine) while its video plays on would otherwise leave every
  // phone at "Screen lost" (demo audit, Oct 25). tick() sends only when a message is due.
  setInterval(() => phone.tick(), 500);
  // The big screen's audio menu: commentary lines (off by default) over the stadium bed.
  // Audio description (the third persona) is a track in the same menu, as streaming apps offer it.
  let tracks: AudioTracks | null = null;
  if (big) {
    const body = m.commentary?.count
      ? await fetch(new URL("commentary.json", new URL(b.base, location.href))).then((r) => (r.ok ? r.json() : null)).catch(() => null)
      : null;
    const commentary = readCommentary(body);
    if (commentary) commentary.lines = commentarySpeeds(commentary.lines, m.speed);
    tracks = new AudioTracks(b.base, commentary, m.stadium ?? null, $("captions"));
    tracks.described = !!b.audio;
  }
  // The QR after kick-off is behind the control bar's button only (Kian, Oct 25: option A).
  const qrState = { open: false, closed: false };
  const hud = big
    ? setupHud({
        footage,
        video: m.footage.kind === "video" ? video : null,
        chapters: (b.match?.chapters ?? []).map((c) => ({ at: c.index / m.fps, goal: c.kind === "goal" })),
        play: playButton,
        scrub,
        clock: clockOut,
        qrOpen: (open) => {
          qrState.open = open;
          if (!open) qrState.closed = true;
        },
        audio: tracks,
        onTrack: (track) => setPersona(track === "described" ? "audio" : "casual"),
      })
    : null;

  document.addEventListener("keydown", (e) => {
    const target = e.target as HTMLElement;
    if (e.metaKey || e.ctrlKey || e.altKey) return;
    const inControl = target.tagName === "BUTTON" || target.tagName === "INPUT";
    const step = 1 / m.fps;
    switch (e.key) {
      case " ":
      case "k":
        if (target.tagName === "BUTTON" && e.key === " ") return; // the button's own click
        // A radio or checkbox's own Space (the audio menu): it chooses, it does not play.
        if (e.key === " " && target instanceof HTMLInputElement && ["radio", "checkbox"].includes(target.type)) return;
        e.preventDefault();
        togglePlay();
        break;
      case "ArrowLeft":
      case "ArrowRight":
        if (target === scrub) return; // the slider moves itself
        if (inControl && target.getAttribute("role") === "radio") return;
        e.preventDefault();
        footage.seek(footage.time() + (e.key === "ArrowRight" ? 1 : -1));
        break;
      case ",":
      case ".":
        footage.pause(); // to the middle of the next or previous frame
        footage.seek((Math.floor(footage.time() * m.fps) + (e.key === "." ? 1 : -1) + 0.5) * step);
        break;
      case "f":
        if (!hud) return;
        hud.toggleFull();
        break;
      case "Escape":
        if (!hud) return;
        hud.closeQr();
        hud.closeMenu();
        qrState.closed = true;
        break;
      case "1":
        if (big) return; // personas are the phone's; audio description is in the audio menu
        setPersona("casual");
        break;
      case "2":
        if (big) return; // personas are the phone's; audio description is in the audio menu
        setPersona("analyst");
        break;
      case "3":
        if (big) return; // personas are the phone's; audio description is in the audio menu
        setPersona("audio");
        break;
      case "d":
        if (big) return;
        showBoxes.checked = !showBoxes.checked;
        break;
      case "[":
      case "]":
        if (!match) return;
        e.preventDefault();
        match.step(footage.time(), e.key === "]" ? 1 : -1);
        break;
      case "m":
        if (!b.radar || big) return;
        showRadar.checked = !showRadar.checked;
        showRadar.dispatchEvent(new Event("change"));
        break;
      case "v":
        if (persona !== "audio") return;
        voiceBox.checked = !voiceBox.checked;
        voiceBox.dispatchEvent(new Event("change"));
        break;
      case "r":
        if (persona === "audio" && voiceBox.checked) narrator.repeat(matchTime(footage.time()));
        break;
    }
  });

  const broadcast = broadcastSchedule(b.cues);
  const ctx = overlay.getContext("2d")!;
  const frame = () => {
    const v = footage.time();
    const t = matchTime(v);
    // The big screen airs the broadcast's few lower thirds; audio description keeps its own cues.
    const aired: Cue[] = big && persona !== "audio" ? broadcast.filter((c) => c.t_in <= t && t < c.t_out) : onAir(b.cues, persona, t);
    ctx.clearRect(0, 0, overlay.width, overlay.height);
    if (showBoxes.checked) drawDetections(ctx, detections.get(Math.round(t * m.fps)));
    drawCues(ctx, aired, { t, reduceMotion: reduceMotionBox.checked });
    narrator.update(t, !footage.paused(), persona === "audio" && voiceBox.checked);
    phone.tick();
    radar.tick(v);
    match?.tick(v, t, reduceMotionBox.checked);
    if (hud) {
      const at = phone.paired ? pairCardAt(v, qrState) : "hidden";
      const card = $("pair-card");
      if (card.dataset.at !== at) {
        card.dataset.at = at;
        card.hidden = at === "hidden";
        card.classList.toggle("still", reduceMotionBox.checked);
      }
      hud.tick();
      tracks?.update(v, t, !footage.paused());
    }

    const ids = aired.map((c) => c.id).sort().join(" ");
    overlay.dataset.onAir = ids;
    overlay.dataset.t = t.toFixed(2);
    if (ids !== lastAired) {
      lastAired = ids;
      const sentence = aired
        .sort((a, c) => (a.slot === "top_right" ? -1 : c.slot === "top_right" ? 1 : 0))
        .map((c) => {
          // The check's result belongs in How we know, never prefixed to what is shown or said.
          const said = c.text.replace(/\.$/, "");
          return c.fallback ? `${said} (fallback: ${c.fallback})` : said;
        })
        .join(". ");
      onAirText.textContent = sentence;
      overlay.setAttribute("aria-label", sentence ? `On-screen graphics: ${sentence}` : "No graphics on screen");
      for (const li of document.querySelectorAll<HTMLElement>("#claims .claim")) {
        const claim = b.claims.find((c) => c.id === li.dataset.claim);
        const live = !!claim && aired.some((c) => c.kind === "insight" && c.evidence.join() === claim.evidence.join());
        if (live) li.setAttribute("aria-current", "true");
        else li.removeAttribute("aria-current");
      }
    }
    if (document.activeElement !== scrub) scrub.value = String(v);
    clockOut.textContent = clock(t);
    const paused = footage.paused();
    if (!hud) {
      playButton.textContent = paused ? "Play" : "Pause";
      playButton.setAttribute("aria-label", paused ? "Play" : "Pause");
    }
    requestAnimationFrame(frame);
  };
  setPersona(persona, false, false);
  document.body.dataset.state = "ready";
  requestAnimationFrame(frame);
}

/** The radar panel: drawn each frame from the bundle's radar.json, or a note saying it has none. */
function setupRadar(
  b: Bundle,
  segmentOf: (k: number) => [number, number],
  matchTime: (v: number) => number,
  teams: TeamNames,
  big: boolean,
) {
  const panel = $("radar-panel");
  const note = $("radar-note");
  let model: RadarModel | null = null;
  let why = "This bundle has no tracked positions: run ninety-e2e with --tracked and --observations.";
  try {
    model = b.radar ? new RadarModel(b.radar, b.manifest.fps, segmentOf) : null;
  } catch (e) {
    why = `Radar not drawn: ${(e as Error).message}.`;
  }
  if (!model) {
    note.textContent = why;
    showRadar.disabled = true;
    radarCanvas.hidden = true;
    $("radar-legend").hidden = true;
  }
  for (const side of ["home", "away"] as const) $(`radar-${side}`).textContent = teams[side];
  if (big) {
    // On the phone instead (web/phone); nothing is drawn here.
    $("radar-section").hidden = true;
    showRadar.checked = false;
    return { tick: () => null };
  }
  const remembered = store.get("radar");
  showRadar.checked = remembered !== "0";
  const apply = () => {
    panel.hidden = !showRadar.checked;
    store.set("radar", showRadar.checked ? "1" : "0");
  };
  showRadar.addEventListener("change", apply);
  apply();
  radarCanvas.style.aspectRatio = String(aspect());

  const trail: { frame: number; x: number; y: number }[] = [];
  let spoken = "";
  let spokenAt = -Infinity;
  const stateAt = (v: number): RadarState | null =>
    model ? model.at(matchTime(v), !reduceMotionBox.checked) : null;
  const draw = (v: number) => {
    const dpr = Math.min(3, window.devicePixelRatio || 1);
    const w = radarCanvas.clientWidth;
    const h = radarCanvas.clientHeight;
    if (!w || !h) return null;
    if (radarCanvas.width !== Math.round(w * dpr) || radarCanvas.height !== Math.round(h * dpr)) {
      radarCanvas.width = Math.round(w * dpr);
      radarCanvas.height = Math.round(h * dpr);
    }
    const ctx = radarCanvas.getContext("2d")!;
    ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
    const state = stateAt(v);
    // The ball's last few tenths of a second, as long as it stays on the same run of frames.
    if (state?.ball) {
      const last = trail[trail.length - 1];
      if (last && (state.frame < last.frame || state.frame - last.frame > 2)) trail.length = 0;
      if (!last || last.frame !== state.frame) trail.push({ frame: state.frame, x: state.ball.x, y: state.ball.y });
      while (trail.length > 10) trail.shift();
    } else trail.length = 0;
    drawRadar(ctx, w, h, state, { reduceMotion: reduceMotionBox.checked, trail: [...trail, ...(state?.ball ? [state.ball] : [])] });
    radarCanvas.dataset.frame = state ? String(state.frame) : "";
    // The description changes at most once a second, so a screen reader is not flooded.
    const now = performance.now();
    const said = describe(state, teams);
    if (said !== spoken && now - spokenAt > 1000) {
      spoken = said;
      spokenAt = now;
      radarCanvas.setAttribute("aria-label", said);
    }
    return state;
  };
  // Read by tests/test_radar.py: the state at a video time, and a drawn pixel at pitch metres.
  (window as unknown as { ninetyRadar: unknown }).ninetyRadar = {
    at: (v: number) => stateAt(v),
    drawAt: (v: number) => draw(v),
    pixel: (x: number, y: number, dx = 0) => {
      const p = projection(radarCanvas.width); // device pixels; dx in CSS pixels to the right
      const at = [Math.round(p.X(x) + dx * (radarCanvas.width / radarCanvas.clientWidth)), Math.round(p.Y(y))];
      return [...radarCanvas.getContext("2d")!.getImageData(at[0], at[1], 1, 1).data];
    },
  };
  return { tick: (v: number) => (model && showRadar.checked ? draw(v) : null) };
}

void start();
