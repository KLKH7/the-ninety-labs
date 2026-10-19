import { type Bundle, type ClaimTrace, type Cue, type Persona, clock, loadBundle, onAir } from "./bundle";
import { drawCues, drawDetections } from "./draw";

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
  const footage = m.footage.kind === "video" ? videoFootage(b) : frameFootage(b);
  scrub.max = String(footage.duration);
  scrub.step = String(1 / m.fps);
  const detections = new Map(b.detections.map((f) => [Math.round(f.t * m.fps), f]));

  let lastAired = "";
  let persona: Persona = store.get("persona") === "analyst" ? "analyst" : "casual";
  const motionQuery = matchMedia("(prefers-reduced-motion: reduce)");
  const remembered = store.get("reduceMotion");
  reduceMotionBox.checked = remembered === null ? motionQuery.matches : remembered === "1";
  const applyMotion = () => (document.documentElement.dataset.motion = reduceMotionBox.checked ? "reduce" : "full");
  applyMotion();
  motionQuery.addEventListener("change", () => {
    if (store.get("reduceMotion") === null) reduceMotionBox.checked = motionQuery.matches;
    applyMotion();
  });
  reduceMotionBox.addEventListener("change", () => {
    store.set("reduceMotion", reduceMotionBox.checked ? "1" : "0");
    applyMotion();
  });

  const personaButtons = [...document.querySelectorAll<HTMLButtonElement>("#persona [role=radio]")];
  const setPersona = (p: Persona, focus = false) => {
    persona = p;
    store.set("persona", p);
    document.body.dataset.persona = p;
    for (const btn of personaButtons) {
      const on = btn.dataset.persona === p;
      btn.setAttribute("aria-checked", String(on));
      btn.tabIndex = on ? 0 : -1;
      if (on && focus) btn.focus();
    }
    lastAired = ""; // announce what this persona sees now
  };
  for (const btn of personaButtons) {
    btn.addEventListener("click", () => setPersona(btn.dataset.persona as Persona));
    btn.addEventListener("keydown", (e) => {
      // A radio group moves with the arrow keys (WAI-ARIA radio group pattern).
      if (["ArrowLeft", "ArrowRight", "ArrowUp", "ArrowDown"].includes(e.key)) {
        e.preventDefault();
        e.stopPropagation();
        setPersona(persona === "casual" ? "analyst" : "casual", true);
      }
    });
  }

  const seekMatch = (matchT: number) => {
    footage.seek(Math.max(0, matchT - m.t_start - 0.5));
    overlay.focus();
  };
  const togglePlay = () => (footage.paused() ? footage.play() : footage.pause());
  playButton.addEventListener("click", togglePlay);
  scrub.addEventListener("input", () => footage.seek(Number(scrub.value)));
  renderPipeline(b);
  renderTrace(b, seekMatch);

  document.addEventListener("keydown", (e) => {
    const target = e.target as HTMLElement;
    if (e.metaKey || e.ctrlKey || e.altKey) return;
    const inControl = target.tagName === "BUTTON" || target.tagName === "INPUT";
    const step = 1 / m.fps;
    switch (e.key) {
      case " ":
      case "k":
        if (target.tagName === "BUTTON" && e.key === " ") return; // the button's own click
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
      case "1":
        setPersona("casual");
        break;
      case "2":
        setPersona("analyst");
        break;
      case "d":
        showBoxes.checked = !showBoxes.checked;
        break;
    }
  });

  const ctx = overlay.getContext("2d")!;
  const frame = () => {
    const v = footage.time();
    const t = m.t_start + v;
    const aired: Cue[] = onAir(b.cues, persona, t);
    ctx.clearRect(0, 0, overlay.width, overlay.height);
    if (showBoxes.checked) drawDetections(ctx, detections.get(Math.round(t * m.fps)));
    drawCues(ctx, aired, { t, reduceMotion: reduceMotionBox.checked });

    const ids = aired.map((c) => c.id).sort().join(" ");
    overlay.dataset.onAir = ids;
    overlay.dataset.t = t.toFixed(2);
    if (ids !== lastAired) {
      lastAired = ids;
      const sentence = aired
        .sort((a, c) => (a.slot === "top_right" ? -1 : c.slot === "top_right" ? 1 : 0))
        .map((c) => (c.verified ? `Fact-checked: ${c.text}` : c.text).replace(/\.$/, ""))
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
    playButton.textContent = paused ? "Play" : "Pause";
    playButton.setAttribute("aria-label", paused ? "Play" : "Pause");
    requestAnimationFrame(frame);
  };
  setPersona(persona);
  document.body.dataset.state = "ready";
  requestAnimationFrame(frame);
}

void start();
