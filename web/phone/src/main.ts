// The phone companion: pairs with the big screen by code, then has three tabs. Radar: every tracked
// player and the ball in step with the big screen's clock, across its cuts, drawn by the viewer's
// own radar (viewer/src/radar.ts), with a player card for the player tapped. Ask: questions to the
// Companion agent, each answer with the picture its tool data draws. Insights: the hidden-stat
// cards pushed so far, each with "Why?", which asks the Companion.
//
// ?code=ABC234&clip=seed7&bundle=/bundle/ joins straight away (the big screen's QR code); ?mock=1
// reads the mock feed.

import "./ionic";
import { COLORS as RADAR_COLORS, RadarModel, type RadarState, describe as describeRadar, drawRadar, projection, timeline, within } from "../../viewer/src/radar";
import { type MatchData, chapterAt, chapterLabel, scoreAt, statsAt } from "../../viewer/src/match";
import { nameIds, teamNames } from "../../viewer/src/teams";
import { LaptopClock } from "./clock";
import { ApiError, type Closed, type Feed, GroundTruth, HttpFeed, type Link, guarded } from "./feed";
import { CODE_ALPHABET, CODE_LENGTH } from "./mockrelay";
import { COLORS, type Positions, aspect, describeHeat, describePlay, drawHeat, drawPitch, fit, radarFromMinimap, zoneFor } from "./pitch";
import {
  type AnswerMessage,
  type InsightCard,
  MAX_QUESTION,
  type Minimap,
  type PlayerCard,
  type RelayMessage,
  type ViewerAnswer,
  type ScoutVisual,
  type Visual,
  clock,
  isTrack,
  playerName,
  shirt,
  team,
  teams,
} from "./types";
import { describeVisual, drawVisual, drawable, fromScout, headline, title } from "./visual";

const $ = <T extends HTMLElement>(id: string) => document.getElementById(id) as T;
const params = new URLSearchParams(location.search);

const CARD_EVERY_MS = 1000; // speed now is a one-second mean (ninety/intel/window.py)
// design: a 30 s field moves little in 5 s, and two flows every 5 s stay far under the API's 120
// reads a minute (ninety/api/companion.py, LIMITS) beside the card's one a second.
const FLOW_EVERY_MS = 5000;
// design: a card pushed in the last few seconds shows within one poll; 12 reads a minute is a tenth
// of the API's read limit.
const INSIGHTS_EVERY_MS = 5000;
const TRAIL = 10; // the ball's last frames drawn behind it, as on the viewer's radar

/** Every payload the phone received, for tests/test_phone.py to check against the schemas. */
const seen: unknown[] = [];
// The mock exists only in the dev bundle (`vite build --mode mock`): in production this condition is
// false at build time, so neither mock.ts nor its data is in the bundle.
let source: Feed = new HttpFeed();
if (__PHONE_MOCK__) {
  if (params.get("mock") === "1") source = new (await import("./mock")).MockFeed();
}
const feed: Feed = guarded(source, (p) => seen.push(p));
const laptop = new LaptopClock();

type Tab = "radar" | "ask" | "insights";
interface State {
  code: string;
  clip: string;
  minimap: Minimap | null;
  radar: RadarModel | null;
  /** Where the radar's positions come from: the bundle's radar.json (vision's tracked output at
   * the video's frame rate) or the companion's minimap feed. */
  radarFrom: "bundle" | "minimap" | null;
  match: MatchData | null;
  refused: string | null; // why the positions are not shown
  selected: string | null;
  following: boolean; // the selection came from the laptop's focus
  card: PlayerCard | null;
  wind: boolean;
  tab: Tab;
  insights: InsightCard[];
}
const state: State = {
  code: "",
  clip: "",
  minimap: null,
  radar: null,
  radarFrom: null,
  match: null,
  refused: null,
  selected: null,
  following: false,
  card: null,
  wind: false,
  tab: "radar",
  insights: [],
};
let link: Link | null = null;
let lastState: RadarState | null = null;
let lastPositions: Positions | null = null;

/** Where pitch metres (x, y) are drawn on the radar, in CSS pixels from its top left. */
function screenOf(x: number, y: number): [number, number] {
  const p = projection(mapCanvas.clientWidth);
  return [p.X(x), p.Y(y)];
}

// Read by tests/test_phone.py.
(window as unknown as { ninetyPhone: object }).ninetyPhone = {
  seen,
  state,
  laptop,
  positions: () => lastPositions,
  radar: () => lastState,
  radarAt: (t: number) => state.radar?.at(t, false) ?? null,
  screenOf,
  name: playerName,
  // An agents' visual (schemas/insight_card.schema.json) the phone would draw, or not.
  drawable: (sv: ScoutVisual, t: number | null = null) => {
    const v = fromScout(sv, t);
    return !!v && drawable(v);
  },
  // The How we know / VAR check sheet for a visual, as a card's chip opens it.
  how: (visual: ScoutVisual) => openHow({ t: visual.t ?? 0, visual, source: "code", evidence: [visual.fact] }),
  // A picture built as an answer's would be, for previews and screenshots.
  picture: (sv: ScoutVisual, t: number | null = null) => picture(sv, t),
  // What a drawable visual's headline and words say, from its own data.
  preview: (sv: ScoutVisual, t: number | null = null) => {
    const v = fromScout(sv, t);
    return v && drawable(v) ? { headline: headline(v), words: describeVisual(v) } : null;
  },
};

if (params.get("marks") === "1") document.body.classList.add("marks"); // open choices, for review
const reduceMotion = matchMedia("(prefers-reduced-motion: reduce)");

// --- pairing ---------------------------------------------------------------------------------

const codeInput = $<HTMLInputElement>("code");
const pairError = $("pair-error");

function normalise(code: string): string {
  return code.toUpperCase().replace(/[^A-Z0-9]/g, "");
}

function validCode(code: string): boolean {
  return code.length === CODE_LENGTH && [...code].every((c) => CODE_ALPHABET.includes(c));
}

const CLOSED_WORDS: Record<Closed, string> = {
  "unknown-code": "No screen is showing that code. Check the code on the big screen and try again.",
  "room-full": "Eight phones are already following this screen.",
  expired: "That code has expired. The big screen shows a new one when it pairs again.",
  refused: "The big screen's connection refused this phone.",
  lost: "Lost the connection to the big screen.",
  "not-joined": "Could not join: no screen is showing that code, or the server cannot be reached. Check the code and try again.",
};

function setStatus(kind: "off" | "synced" | "paused" | "waiting" | "lost", text: string) {
  const s = $("status");
  if (s.textContent !== text) s.textContent = text;
  s.dataset.state = kind;
}

async function connect(code: string) {
  pairError.textContent = "";
  if (!validCode(code)) {
    pairError.textContent = `A code is ${CODE_LENGTH} letters and digits, like K7MP3Q.`;
    codeInput.focus();
    return;
  }
  const button = $<HTMLButtonElement>("connect");
  button.disabled = true;
  button.textContent = "Connecting…";
  try {
    link = await feed.join(code, onRelay, onClosed);
  } catch (why) {
    pairError.textContent = typeof why === "string" ? CLOSED_WORDS[why as Closed] : "Could not reach the server. Check your connection.";
    button.disabled = false;
    button.textContent = "Connect";
    return;
  }
  let clip = params.get("clip");
  if (!clip) {
    try {
      clip = await feed.clipOf(code);
    } catch {
      link.close();
      pairError.textContent = "This server needs the big screen's QR code to connect: scan it with your camera.";
      button.disabled = false;
      button.textContent = "Connect";
      return;
    }
  }
  state.code = code;
  state.clip = clip;
  button.disabled = false;
  button.textContent = "Connect";
  history.replaceState(null, "", `?${new URLSearchParams({ ...Object.fromEntries(params), code, clip })}`);
  showLive();
  await Promise.all([loadMinimap(), loadBundle()]);
  buildRadar();
  void refreshInsights(true);
}

function onRelay(m: RelayMessage) {
  if (m.type === "clock") laptop.update(m);
  else if (m.type === "focus" && m.player !== null && rosterIds().includes(m.player)) {
    select(m.player, true);
  }
}

function onClosed(why: Closed) {
  if (why === "lost") {
    setStatus("lost", "Reconnecting…");
    const retry = async () => {
      try {
        link = await feed.join(state.code, onRelay, onClosed);
      } catch (again) {
        if (again === "lost" || again === "not-joined") setTimeout(retry, 2000);
        else backToPairing(again as Closed);
      }
    };
    setTimeout(retry, 1000);
    return;
  }
  backToPairing(why);
}

function backToPairing(why: Closed) {
  link = null;
  document.body.dataset.state = "pair";
  $("live").hidden = true;
  $("pair").hidden = false;
  setStatus("off", "Not connected");
  pairError.textContent = CLOSED_WORDS[why];
}

function showLive() {
  document.body.dataset.state = "live";
  $("pair").hidden = true;
  $("live").hidden = false;
  $("mockbar").hidden = !feed.mock;
  setStatus("waiting", "Waiting");
}

$("pair-form").addEventListener("submit", (e) => {
  e.preventDefault();
  void connect(normalise(codeInput.value));
});
codeInput.addEventListener("input", () => {
  const v = normalise(codeInput.value).slice(0, CODE_LENGTH);
  if (v !== codeInput.value) codeInput.value = v;
  $<HTMLButtonElement>("connect").disabled = !validCode(v); // as a TV-code form: on once it can work
});

// --- tabs (WAI-ARIA tabs pattern: arrow keys move between them, Home and End to the ends) ------

const TABS: Tab[] = ["radar", "ask", "insights"];

type IonTabs = HTMLElement & { select(tab: string): Promise<boolean> };
type IonModal = HTMLElement & { present(): Promise<void>; dismiss(): Promise<boolean>; isOpen: boolean; breakpoints?: number[]; initialBreakpoint?: number };

function showTab(tab: Tab, focus = false) {
  state.tab = tab;
  for (const t of TABS) {
    const button = $(`tab-button-${t}`);
    const on = t === tab;
    button.setAttribute("aria-selected", String(on));
    button.tabIndex = on ? 0 : -1;
  }
  // ion-tabs shows the panel; keyboard focus follows once it has.
  void ($("live") as IonTabs).select(tab).then(() => focus && $(`tab-button-${tab}`).focus());
  document.body.dataset.tab = tab;
  if (tab === "insights") {
    unread = 0;
    showUnread();
  }
  if (tab === "ask") requestAnimationFrame(redrawPictures); // canvases sized while hidden draw now
}

$("live").addEventListener("ionTabsDidChange", (e) => {
  const tab = (e as CustomEvent<{ tab: Tab }>).detail.tab;
  if (tab !== state.tab) showTab(tab);
});
// Ionic's tab buttons carry no tab stop of their own (the link inside has neither href nor
// tabindex), so the bar gets a roving one: the selected tab is in the Tab order, the others are
// reached with the arrow keys (WAI-ARIA tabs pattern), and Enter or Space opens the focused tab.
for (const t of TABS) {
  const button = $(`tab-button-${t}`);
  button.tabIndex = t === state.tab ? 0 : -1;
  button.setAttribute("aria-selected", String(t === state.tab));
  button.addEventListener("click", () => showTab(t));
  button.addEventListener("keydown", (e) => {
    if (e.key === "Enter" || e.key === " ") {
      e.preventDefault();
      showTab(t, true);
      return;
    }
    const i = TABS.indexOf(state.tab);
    const to =
      e.key === "ArrowRight" ? TABS[(i + 1) % TABS.length] : e.key === "ArrowLeft" ? TABS[(i + TABS.length - 1) % TABS.length] : e.key === "Home" ? TABS[0] : e.key === "End" ? TABS[TABS.length - 1] : null;
    if (!to) return;
    e.preventDefault();
    showTab(to, true);
  });
}

// --- the bundle: the big screen's cuts, its tracked positions and its match --------------------

interface BundleManifest {
  format: number;
  clip: string;
  fps: number;
  t_start: number;
  segments?: { index: number; frame: number; frames: number }[];
  width: number;
  height: number;
  footage: { kind: "video" | "frames"; src: string; frames: number };
  detector?: string | null;
  teams?: unknown;
  radar?: unknown;
  match?: unknown;
  cards?: unknown;
}

let bundleFps = 25;
let bundle: { base: URL; manifest: BundleManifest } | null = null;
let bundleCards: InsightCard[] | null = null;
interface DetectedEvent {
  id: string;
  t: number;
  type: string;
  player?: string | null;
  receiver?: string | null;
  outcome?: string | null;
  team?: string;
  x?: number;
  y?: number;
}
let bundleEvents = new Map<string, DetectedEvent>(); // detected events, by id
let bundleRadar: { data: import("../../viewer/src/radar").RadarData; fps: number; segmentOf: (k: number) => [number, number] } | null = null;

/** The bundle the big screen plays, named by its QR code: a path on this origin, never another site. */
function bundleBase(): URL | null {
  const path = params.get("bundle");
  if (!path) return null;
  const u = new URL(path.endsWith("/") ? path : `${path}/`, location.href);
  return u.origin === location.origin ? u : null;
}

async function loadBundle() {
  const base = bundleBase();
  if (!base) return;
  try {
    const get = async (file: string) => {
      const r = await fetch(new URL(file, base));
      if (!r.ok) throw new Error(`${file}: ${r.status}`);
      return r.json();
    };
    const m = (await get("manifest.json")) as BundleManifest;
    // The mock plays its own clip against any bundle; otherwise only the paired clip's bundle.
    if (m.format !== 1 || (m.clip !== state.clip && !feed.mock)) return;
    Object.assign(teams, teamNames(m.teams));
    showTeams();
    const cuts = timeline(m);
    laptop.cuts = cuts;
    bundle = { base, manifest: m };
    bundleFps = m.fps;
    const [radar, match, cards] = await Promise.all([
      m.radar ? get("radar.json") : null,
      m.match ? get("match.json") : null,
      m.cards ? get("cards.json") : null,
    ]);
    if (Array.isArray(cards)) bundleCards = (cards as InsightCard[]).filter((c) => c.status === "verified");
    {
      // The detected events: who scored each detected goal, and a player's part in the play.
      const r = await fetch(new URL("events.jsonl", base));
      if (r.ok) {
        for (const line of (await r.text()).split("\n")) {
          if (!line.trim()) continue;
          const e = JSON.parse(line) as DetectedEvent;
          bundleEvents.set(e.id, e);
        }
      }
    }
    if (radar) bundleRadar = { data: radar, fps: m.fps, segmentOf: cuts.segmentOf };
    state.match = match as MatchData | null;
    $("match-card").hidden = !state.match;
  } catch {
    // The minimap feed still draws the radar; only the cuts and the match are missing.
  }
}

/** The two clubs' colours (DESIGN.md: Oakfield navy, Fenwick claret; another club takes the one
 * left), on the page's variables and on every pitch drawing. Colour follows the club, not the side. */
function clubColours() {
  const root = document.documentElement;
  const own = (club: string) => (club === "Oakfield" ? "a" : club === "Fenwick" ? "b" : null);
  let h = own(teams.home);
  let a = own(teams.away);
  if (!h) h = a === "a" ? "b" : "a";
  if (!a || a === h) a = h === "a" ? "b" : "a";
  root.style.setProperty("--home", `var(--team-${h})`);
  root.style.setProperty("--away", `var(--team-${a})`);
  root.style.setProperty("--crest-home", `var(--crest-${h})`);
  root.style.setProperty("--crest-away", `var(--crest-${a})`);
  const css = getComputedStyle(root);
  const read = (name: string) => css.getPropertyValue(name).trim();
  const palette = {
    home: read(`--team-${h}`),
    away: read(`--team-${a}`),
    grass: read("--pitch"),
    stripe: read("--pitch-stripe"),
    line: read("--pitch-line"),
    lineWidth: 1.5,
    homeInk: "#ffffff",
    awayInk: "#ffffff",
  };
  Object.assign(RADAR_COLORS, palette);
  Object.assign(COLORS, palette);
}
matchMedia("(prefers-color-scheme: dark)").addEventListener("change", () => {
  clubColours();
  requestAnimationFrame(redrawPictures);
});

function showTeams() {
  clubColours();
  for (const side of ["home", "away"] as const) {
    for (const el of document.querySelectorAll(`.${side}-name`)) el.textContent = teams[side];
    for (const el of document.querySelectorAll(`.${side}-letter`)) el.textContent = teams[side].charAt(0);
  }
  $("legend-home").textContent = `${teams.home} →`;
  $("legend-away").textContent = `← ${teams.away}`;
  $("map-sides").textContent = `${teams.home} attack to the right of the radar, ${teams.away} to the left.`;
}
showTeams();

// --- the radar ---------------------------------------------------------------------------------

const mapCanvas = $<HTMLCanvasElement>("map");
const windCanvas = $<HTMLCanvasElement>("wind");
$("map-box").style.aspectRatio = String(aspect());
$<HTMLCanvasElement>("heat").style.aspectRatio = String(aspect());

async function loadMinimap() {
  try {
    state.minimap = await feed.minimap(state.clip);
    state.refused = null;
  } catch (e) {
    state.minimap = null;
    state.refused =
      e instanceof GroundTruth || (e instanceof ApiError && e.status === 503)
        ? "Live player positions aren't available for this match yet, so there is no radar, player card " +
          "or question to show. They turn on once positions are tracked from the video itself. " +
          "The match clock above still follows the big screen."
        : `Could not load the radar: ${(e as Error).message}`;
  }
}

/** The radar from the bundle's tracked positions when the big screen's bundle has them, otherwise
 * from the minimap feed; the same drawing either way. */
function buildRadar() {
  state.radar = null;
  state.radarFrom = null;
  if (state.minimap || bundleRadar) {
    try {
      if (bundleRadar) {
        state.radar = new RadarModel(bundleRadar.data, bundleRadar.fps, bundleRadar.segmentOf);
        state.radarFrom = "bundle";
      } else {
        const m = state.minimap!;
        state.radar = new RadarModel(radarFromMinimap(m), m.fps, () => [-Infinity, Infinity], feed.mock ? "mock" : "tracked");
        state.radarFrom = "minimap";
      }
    } catch (e) {
      state.refused = `The radar is not drawn: ${(e as Error).message}.`;
    }
  }
  const on = state.radar !== null;
  const refused = $("refused");
  refused.hidden = state.refused === null || on;
  refused.textContent = on ? "" : state.refused ?? "";
  mapCanvas.dataset.source = on ? (state.radarFrom === "bundle" ? "tracked" : state.minimap!.source) : "refused";
  mapCanvas.dataset.from = state.radarFrom ?? "";
  $("map-box").hidden = !on;
  for (const id of ["pick-hint", "roster-box", "now-box", "legend"]) $(id).hidden = !on;
  $("legend-view").hidden = state.radarFrom !== "bundle";
  $("wind-toggle").hidden = !state.minimap;
  if (on) {
    renderRoster(rosterIds());
    const tracked = rosterIds().some(isTrack);
    $("seen-note").hidden = !tracked;
    $("roster-summary").textContent = "Players";
  }
  renderChips();
}

function rosterIds(): string[] {
  if (state.radarFrom === "bundle" && state.radar) return state.radar.ids().map((p) => p.id);
  return state.minimap?.roster ?? [];
}

function renderRoster(roster: string[]) {
  const button = (id: string) => {
    const b = document.createElement("button");
    b.type = "button";
    b.className = `who ${team(id)}`;
    b.dataset.player = id;
    b.textContent = playerName(id);
    b.setAttribute("aria-label", playerName(id));
    b.setAttribute("aria-pressed", "false");
    b.addEventListener("click", () => {
      select(id);
      ($("roster-box") as HTMLDetailsElement).open = false;
    });
    return b;
  };
  $("roster").replaceChildren(
    ...(["home", "away"] as const).flatMap((side) => {
      const ids = roster.filter((id) => team(id) === side).sort((a, b) => Number(shirt(a)) - Number(shirt(b)));
      const label = document.createElement("p");
      label.className = "roster-team";
      label.textContent = teams[side];
      label.setAttribute("aria-hidden", "true"); // each button already says its team
      const row = document.createElement("div");
      row.className = "roster-row";
      row.append(...ids.map(button));
      return [label, row];
    }),
  );
}

mapCanvas.addEventListener("click", (e) => {
  if (!lastState) return;
  const r = mapCanvas.getBoundingClientRect();
  const ids = within(lastState, mapCanvas.clientWidth, e.clientX - r.left, e.clientY - r.top);
  if (ids.length === 1) select(ids[0]);
  else if (ids.length > 1) choose(ids); // dots on top of each other: ask rather than guess
});

/** Dots too close to tell apart under a thumb: offer each of them as a button. */
function choose(ids: string[]) {
  const box = $("which");
  const buttons = ids.map((id) => {
    const b = document.createElement("button");
    b.type = "button";
    b.className = `who ${team(id)}`;
    b.textContent = playerName(id);
    b.addEventListener("click", () => {
      box.hidden = true;
      select(id);
    });
    return b;
  });
  const cancel = document.createElement("button");
  cancel.type = "button";
  cancel.className = "toggle";
  cancel.textContent = "Cancel";
  cancel.addEventListener("click", () => (box.hidden = true));
  $("which-row").replaceChildren(...buttons, cancel);
  box.hidden = false;
  buttons[0].focus();
}

let summaryAt = -1;
function describeMap(t: number, s: RadarState, pos: Positions) {
  // The canvas's label, refreshed every few seconds of match time, not every frame.
  if (Math.abs(t - summaryAt) < 5) return;
  summaryAt = t;
  const who = state.selected ? ` ${playerName(state.selected)} is circled.` : "";
  const play = pos.players.length ? ` ${describePlay(pos)}` : "";
  mapCanvas.setAttribute("aria-label", `Radar at ${clock(t)}. ${describeRadar(s, teams)}${play}${who}`);
}

// For a fan who cannot see the big screen: one sentence on demand, or, with "Describe as it
// happens" on, a sentence whenever the play changes (the ball changes half, or the nearest player
// changes side), at most one every LIVE_GAP_S of match time. The live region reads each one.
const LIVE_GAP_S = 8; // design: about one sentence between two passes, so the reader can keep up
let saidAt = -Infinity;
let saidKey = "";

function sayNow(t: number) {
  if (!lastPositions) return;
  const said = $("now-said");
  const sentence = `At ${clock(t)}: ${describePlay(lastPositions)}`;
  said.textContent = "";
  saidAt = t;
  requestAnimationFrame(() => (said.textContent = sentence)); // a fresh change, so it is read again
}

$("now").addEventListener("click", () => sayNow(laptop.time()));
$<HTMLInputElement>("now-live").addEventListener("change", () => (saidKey = ""));

function liveDescription(t: number, pos: Positions) {
  const [bx, by] = pos.ball;
  const near = [...pos.players].sort((a, b) => Math.hypot(a[1] - bx, a[2] - by) - Math.hypot(b[1] - bx, b[2] - by))[0];
  const key = `${bx < 52.5 ? "home" : "away"}:${near ? team(near[0]) : ""}`;
  const live = $<HTMLInputElement>("now-live").checked;
  if (live && laptop.isPlaying() && key !== saidKey && t - saidAt >= LIVE_GAP_S) {
    saidKey = key;
    sayNow(t);
  }
  // An old sentence says how old it is, so it is never read as now.
  const age = Math.floor(t - saidAt);
  $("now-age").textContent = Number.isFinite(saidAt) && age >= 3 ? `(${age} s ago)` : "";
}

let speaking = false;
/** Says a line in the live region; with read-aloud on, also speaks it (the speaker button). */
function announce(text: string) {
  $("announce").textContent = text;
  if (speaking && "speechSynthesis" in window) {
    speechSynthesis.cancel();
    speechSynthesis.speak(new SpeechSynthesisUtterance(text));
    lockScreen(text);
  }
}

/** The latest line on the lock screen while read-aloud plays, where the browser shows its Now
 * Playing card (Media Session). A web page cannot post a Live Activity; this is the nearest it gets. */
function lockScreen(text: string) {
  if (!("mediaSession" in navigator) || typeof MediaMetadata === "undefined") return;
  const score = state.match ? `${teams.home} ${$("score-home").textContent}–${$("score-away").textContent} ${teams.away}` : `${teams.home} v ${teams.away}`;
  navigator.mediaSession.metadata = new MediaMetadata({ title: text, artist: `${score} · ${clock(laptop.time())}`, album: "Ninety" });
}
for (const b of document.querySelectorAll<HTMLButtonElement>(".speak")) {
  b.addEventListener("click", () => {
    speaking = !speaking;
    for (const x of document.querySelectorAll(".speak")) x.setAttribute("aria-pressed", String(speaking));
    // Read-aloud on also describes the play as it happens: one control for a fan who can't see it.
    const live = $<HTMLInputElement>("now-live");
    if (live.checked !== speaking) {
      live.checked = speaking;
      live.dispatchEvent(new Event("change"));
    }
    if (!speaking && "speechSynthesis" in window) speechSynthesis.cancel();
  });
}

// --- the player sheet (ion-modal with a grabber and two heights) --------------------------------

const playerSheet = $("player-sheet") as IonModal;
playerSheet.breakpoints = [0, 0.6, 1];
playerSheet.initialBreakpoint = 1; // player analysis opens at full height
// The heat map is drawn at the sheet's size, so draw it again once the sheet is up.
playerSheet.addEventListener("ionModalDidPresent", () => state.card && showCard(state.card));
let sheetUp = false; // presented with present(): ion-modal's own isOpen stays false
playerSheet.addEventListener("ionModalWillPresent", () => (sheetUp = true));
playerSheet.addEventListener("ionModalWillDismiss", () => (sheetUp = false));
let keepSelection = false; // the sheet closed to ask about its player: he stays picked
playerSheet.addEventListener("ionModalDidDismiss", () => {
  if (!keepSelection && state.selected !== null) select(null);
  keepSelection = false;
});
/** Close the sheet for the Ask tab, keeping its player as the question's subject. */
function askAboutPlayer() {
  keepSelection = true;
  $("player").hidden = true;
  void playerSheet.dismiss();
  showTab("ask");
}
$("ask-about").addEventListener("click", () => {
  askAboutPlayer();
  requestAnimationFrame(() => $("question").focus());
});
function showSheet(open: boolean) {
  $("player").hidden = !open;
  if (open && !sheetUp) {
    sheetUp = true;
    void playerSheet.present();
  } else if (!open && sheetUp) void playerSheet.dismiss();
}

// Live's sticky header: the score band collapses to one row once it scrolls away (Apple Sports).
$("live-content").addEventListener("ionScroll", (e) => {
  const y = (e as CustomEvent<{ scrollTop: number }>).detail.scrollTop;
  $("live-bar").classList.toggle("collapsed", y > 120);
});

// The Match tab's Pitch and Stats.
$("match-seg").addEventListener("ionChange", (e) => {
  const v = (e as CustomEvent<{ value: string }>).detail.value;
  $("seg-pitch").hidden = v !== "pitch";
  $("seg-stats").hidden = v !== "stats";
  if (v === "pitch") requestAnimationFrame(() => (summaryAt = -1));
});

const trail: { frame: number; x: number; y: number }[] = [];
function drawMap(t: number) {
  const v = fit(mapCanvas);
  const s = state.radar!.at(t, !reduceMotion.matches);
  // The ball's last few tenths of a second, as long as it stays on the same run of frames.
  if (s.ball) {
    const last = trail[trail.length - 1];
    if (last && (s.frame < last.frame || s.frame - last.frame > 2)) trail.length = 0;
    if (!last || last.frame !== s.frame) trail.push({ frame: s.frame, x: s.ball.x, y: s.ball.y });
    while (trail.length > TRAIL) trail.shift();
  } else trail.length = 0;
  drawRadar(v.ctx, v.w, v.h, s, {
    reduceMotion: reduceMotion.matches,
    trail: [...trail, ...(s.ball ? [s.ball] : [])],
    selected: state.selected,
  });
  lastState = s;
  return s;
}

// --- the player card -------------------------------------------------------------------------

function select(id: string | null, fromLaptop = false) {
  state.selected = id;
  state.following = fromLaptop;
  state.card = null;
  for (const b of document.querySelectorAll<HTMLButtonElement>("#roster .who")) {
    b.setAttribute("aria-pressed", String(b.dataset.player === id));
  }
  showSheet(id !== null);
  $("pick-hint").hidden = state.radar === null;
  if (id) {
    $("player-title").textContent = fromLaptop ? `${playerName(id)} · followed from the big screen` : playerName(id);
    $("player").dataset.team = team(id);
    for (const s of ["speed", "peak", "distance"]) $(s).textContent = "–";
    renderCompareChips(id);
    cardAsked = -1;
    void refreshCard(true);
    if (fromLaptop) announce(`The big screen is following ${playerName(id)}.`);
    else if (state.tab === "radar") {
      // Focus moves to the sheet's title, so a screen reader lands on it.
      playerSheet.addEventListener("ionModalDidPresent", () => $("player-title").focus(), { once: true });
      if (sheetUp) requestAnimationFrame(() => $("player-title").focus());
    }
  }
  $("ask-who").textContent = id ? playerName(id) : "the match";
  renderChips();
}

$("close-player").addEventListener("click", () => {
  select(null);
  document.querySelector<HTMLElement>("#roster-box summary")?.focus(); // the list closes on a pick
});

let cardBusy = false;
let cardAsked = -1; // the match time the shown card was asked for
let cardAt = 0;
async function refreshCard(force = false) {
  const id = state.selected;
  if (!id || !state.minimap || cardBusy) return;
  const t = Math.round(laptop.time() * 10) / 10;
  if (!force && (performance.now() - cardAt < CARD_EVERY_MS || t === cardAsked)) return;
  cardBusy = true;
  cardAt = performance.now();
  try {
    const card = await feed.card(state.clip, id, t);
    if (state.selected !== id) return;
    state.card = card;
    cardAsked = t;
    showCard(card);
  } catch (e) {
    if (e instanceof GroundTruth) {
      state.selected = null;
      showSheet(false);
    }
    $("card-note").textContent = e instanceof ApiError && e.status === 404 ? "No positions for this player yet." : (e as Error).message;
  } finally {
    cardBusy = false;
  }
}

function showCard(c: PlayerCard) {
  $("speed").textContent = c.speed_kmh.toFixed(1);
  $("peak").textContent = c.peak_kmh.toFixed(1);
  $("distance").textContent = String(Math.round(c.distance_m));
  // The card covers t_from..t_to, but nothing was tracked before the feed's first frame: say the
  // stretch the positions really cover, not the one asked for.
  const from = Math.max(c.t_from, state.minimap?.frames[0]?.t ?? c.t_from);
  $("heat-title").textContent = `Heat map, ${clock(from)} to ${clock(c.t_to)}`;
  // Always say how much play the card covers, so a short window is never mistaken for a match.
  const span = Math.max(0, c.t_to - from);
  $("heat-span").textContent =
    `Covering ${span < 60 ? `${Math.round(span)} s` : `${Math.floor(span / 60)} min ${Math.round(span % 60)} s`} of play` +
    (span < 60 ? ": the heat map means more as the match goes on." : ".");
  $("player").dataset.t = String(c.t_to);
  const heat = $<HTMLCanvasElement>("heat");
  const v = fit(heat);
  drawPitch(v);
  drawHeat(v, c.heat, team(c.player) === "home" ? COLORS.home : COLORS.away);
  heat.setAttribute("aria-label", `Heat map of ${playerName(c.player)}: ${describeHeat(c.heat, team(c.player))}`);
  // His average position: the heat map's own shares, weighted over its cells' centres.
  const total = c.heat.cells.reduce((a, b) => a + b, 0);
  if (total > 0) {
    let ax = 0;
    let ay = 0;
    c.heat.cells.forEach((share, k) => {
      ax += share * ((k % c.heat.nx) + 0.5) * (105 / c.heat.nx);
      ay += share * (Math.floor(k / c.heat.nx) + 0.5) * (68 / c.heat.ny);
    });
    ax /= total;
    ay /= total;
    v.ctx.beginPath();
    v.ctx.arc(v.X(ax), v.Y(ay), 6, 0, Math.PI * 2);
    v.ctx.lineWidth = 2.5;
    v.ctx.strokeStyle = "#fff";
    v.ctx.stroke();
    $("avg-pos").textContent = `The ring is his average position: his ${zoneFor(team(c.player), ax, ay)}.`;
  } else $("avg-pos").textContent = "";
  showInvolved(c.player, c.t_to);
  const busiest = Math.max(...c.heat.cells);
  $("heat-legend").textContent = `Brighter means more time there; the brightest square is ${Math.round(busiest * 100)}% of the time.`;
  $("card-note").textContent =
    `Updated at ${clock(c.t_to)}. Computed by code from ${feed.mock ? "the mock positions" : "positions tracked from the video"}; ` +
    "speed now is the average over the last second.";
}

/** His part in the play so far, counted from the detected events (hidden when there are none). */
function showInvolved(id: string, t: number) {
  const mine = [...bundleEvents.values()].filter((e) => e.t <= t);
  const rows: [string, number][] = [
    ["Passes", mine.filter((e) => e.type === "pass" && e.player === id).length],
    ["Passes received", mine.filter((e) => e.type === "pass" && e.receiver === id && e.outcome === "success").length],
    ["Shots", mine.filter((e) => e.type === "shot" && e.player === id).length],
  ];
  const any = bundleEvents.size > 0 && rows.some(([, n]) => n > 0);
  $("involved-box").hidden = !any;
  $("involved").replaceChildren(
    ...rows.map(([label, n]) => {
      const li = document.createElement("li");
      const k = document.createElement("span");
      k.textContent = label;
      const v = document.createElement("span");
      v.className = "kv-v";
      v.textContent = String(n);
      li.append(k, v);
      return li;
    }),
  );
}

/** Compare with another player: both cards, side by side as mirrored rows. */
function renderCompareChips(id: string) {
  const others = rosterIds().filter((o) => o !== id);
  $("compare-rows").hidden = true;
  $("compare-chips").replaceChildren(
    ...others.map((o) => {
      const b = document.createElement("button");
      b.type = "button";
      b.className = `chip who-chip ${team(o)}`;
      b.textContent = playerName(o);
      b.addEventListener("click", () => void compare(id, o));
      return b;
    }),
  );
}

async function compare(a: string, b: string) {
  const t = state.card?.t_to ?? Math.round(laptop.time() * 10) / 10;
  let ca: PlayerCard;
  let cb: PlayerCard;
  try {
    [ca, cb] = await Promise.all([feed.card(state.clip, a, t), feed.card(state.clip, b, t)]);
  } catch (e) {
    $("compare-rows").hidden = false;
    $("compare-rows").textContent = `Could not compare: ${(e as Error).message}`;
    return;
  }
  const rows: [string, number, number, number][] = [
    ["Speed now (km/h)", ca.speed_kmh, cb.speed_kmh, 1],
    ["Top speed (km/h)", ca.peak_kmh, cb.peak_kmh, 1],
    ["Distance (m)", ca.distance_m, cb.distance_m, 0],
  ];
  const head = document.createElement("li");
  head.className = "compare-head";
  head.innerHTML = '<span class="na"></span><span class="nb"></span>';
  head.querySelector(".na")!.textContent = playerName(a);
  head.querySelector(".nb")!.textContent = playerName(b);
  $("compare-rows").replaceChildren(
    head,
    ...rows.map(([label, x, y, places]) => {
      const li = document.createElement("li");
      li.className = "stat-row";
      li.setAttribute("aria-label", `${label}: ${playerName(a)} ${x.toFixed(places)}, ${playerName(b)} ${y.toFixed(places)}`);
      li.innerHTML = '<span class="v home-v"></span><span class="label"></span><span class="v away-v"></span><span class="bar home-bar"></span><span class="bar away-bar"></span>';
      li.querySelector(".home-v")!.textContent = x.toFixed(places);
      li.querySelector(".away-v")!.textContent = y.toFixed(places);
      li.querySelector(".label")!.textContent = label;
      const sum = Math.max(1e-9, x + y);
      (li.querySelector(".home-bar") as HTMLElement).style.width = `calc(${(50 * x) / sum}% - 1px)`;
      (li.querySelector(".away-bar") as HTMLElement).style.width = `calc(${(50 * y) / sum}% - 1px)`;
      (li.querySelector(".home-bar") as HTMLElement).style.background = `var(--${team(a)})`;
      (li.querySelector(".away-bar") as HTMLElement).style.background = `var(--${team(b)})`;
      for (const v of li.querySelectorAll(".v, .label, .bar")) v.setAttribute("aria-hidden", "true");
      return li;
    }),
  );
  $("compare-rows").hidden = false;
}

// --- questions -------------------------------------------------------------------------------

function playerQuestions(id: string): string[] {
  const n = playerName(id);
  return [`How fast is ${n} running now?`, `What is ${n}'s top speed?`, `How far has ${n} run?`];
}

/** The match questions the Companion's tools answer with a picture. */
function matchQuestions(): string[] {
  return [
    `Where are ${teams.home} overloading?`,
    `Which pass broke ${teams.away}'s lines?`,
    `What are ${teams.home}'s passing options?`,
    `How are ${teams.away} set up?`,
    "How are the teams moving?",
  ];
}

function chip(q: string, onTab: Tab | null) {
  const b = document.createElement("button");
  b.type = "button";
  b.className = "chip";
  b.textContent = q;
  b.addEventListener("click", () => {
    if (onTab === "ask" && sheetUp) askAboutPlayer();
    else if (onTab) showTab(onTab);
    void ask(q);
  });
  return b;
}

function renderChips() {
  const own = state.selected ? playerQuestions(state.selected).map((q) => chip(q, "ask")) : [];
  $("chips").replaceChildren(...own);
  const all = [...(state.selected ? playerQuestions(state.selected) : []), ...matchQuestions()];
  $("ask-chips").replaceChildren(...all.slice(0, 3).map((q) => chip(q, null))); // three, as a message app suggests
}

const STATUS_WORDS: Record<ViewerAnswer["status"], string> = {
  verified: "Fact-checked", // only for the Companion agent's answers: see `badgeFor`
  held: "Still being checked",
  rejected: "Refused by the fact-checker",
  unanswerable: "Can't answer that",
};

/** What an answer's badge may claim: "Fact-checked" only when the fact-checking agent's Judge saw
 * it (a model answer); a code answer is the cited fact in a template, through the code checks only. */
function badgeFor(a: ViewerAnswer): string {
  if (a.status !== "verified") return STATUS_WORDS[a.status];
  if (a.source === "model") return STATUS_WORDS.verified;
  return feed.mock ? "Computed from mock positions" : "Computed from tracked positions";
}

const METRIC_WORDS: Record<string, string> = {
  speed_now: "speed now",
  peak_speed: "top speed",
  distance_run: "distance run",
  overload: "players in the overload",
  line_break: "defenders bypassed",
  pass_options: "open teammates",
};

/** The API names players by id (a7); fans read "Fenwick 7", or the name the answer carries. Only
 * the names change, never a number. */
function named(text: string, names?: Record<string, string>): string {
  return nameIds(text, teams, names);
}

async function ask(text: string) {
  const q = text.trim().slice(0, MAX_QUESTION);
  if (!q) return;
  const input = $<HTMLInputElement>("question");
  const button = $<HTMLButtonElement>("ask-button");
  if (button.getAttribute("aria-disabled") === "true") return;
  button.setAttribute("aria-disabled", "true"); // not `disabled`: that would drop a screen reader's focus
  // About the shown player, ask at the card's time, so the answer and the card agree.
  const at = state.card && state.card.player === state.selected ? state.card.t_to : Math.round(Math.max(0, laptop.time()) * 10) / 10;
  const pending = document.createElement("li");
  pending.className = "answer pending";
  pending.setAttribute("aria-hidden", "true"); // the button's state says it; the answer is read when it comes
  pending.textContent = `Fact-checking: “${q}”`;
  $("answers").append(pending); // a thread reads down: the newest answer last
  void ($("ask-content") as HTMLElement & { scrollToBottom(ms?: number): Promise<void> }).scrollToBottom(reduceMotion.matches ? 0 : 300);
  let answer: ViewerAnswer | null = null;
  let failed = "";
  try {
    const message: AnswerMessage = await feed.ask({ session: state.code, player: state.selected, text: q, t: at });
    answer = { ...message.answer, source: message.source ?? message.answer.source };
  } catch (e) {
    failed =
      e instanceof ApiError && e.status === 429
        ? "Too many questions in a minute. Wait a moment and ask again."
        : e instanceof ApiError && e.status === 503
          ? "Questions are off for this match until tracked positions are ready."
          : `Could not ask: ${(e as Error).message}`;
  } finally {
    button.removeAttribute("aria-disabled");
  }
  if (input.value.trim() === q) input.value = "";
  pending.replaceWith(renderAnswer(q, at, answer, failed));
  requestAnimationFrame(() => void ($("ask-content") as HTMLElement & { scrollToBottom(ms?: number): Promise<void> }).scrollToBottom(reduceMotion.matches ? 0 : 300));
}

function renderAnswer(question: string, at: number, a: ViewerAnswer | null, failed: string): HTMLLIElement {
  // Like a message thread: the question on the right, the answer below it in a plain bubble with
  // its one number, a sentence or two, the diagram when it helps, and a quiet "How we know ›".
  const li = document.createElement("li");
  li.className = `answer ${a?.status ?? "error"}`;
  li.dataset.status = a?.status ?? "error";
  li.dataset.source = a?.source ?? "code";
  const asked = document.createElement("p");
  asked.className = "asked";
  const when = document.createElement("span");
  when.className = "sr-only";
  when.textContent = `You asked at ${clock(at)}: `;
  asked.append(when, question); // shown as text, never as markup
  const bubble = document.createElement("div");
  bubble.className = "bubble";
  const body = document.createElement("p");
  body.className = "said";
  if (!a) body.textContent = failed;
  else if (a.status === "verified") body.textContent = named(a.text, a.names);
  else if (a.status === "held") body.textContent = "Still being checked, so not shown yet.";
  else if (a.status === "rejected") body.textContent = "The fact-checker turned that answer down, so there's nothing to show.";
  else body.textContent = named(a.text, a.names) || "I can't answer that one. Try a player's speed, an overload or a team's shape.";
  if (a && a.status === "verified") {
    // The headline: a natural phrase for a picture's kind ("1 v 2 round the ball"), else the figure.
    const v = a.visual ? fromScout(a.visual, a.t_to) : null;
    const line = v && drawable(v) ? title(v) : a.value !== null ? `${a.value} ${a.unit ?? ""}`.trim() : "";
    if (line) {
      const big = document.createElement("p");
      big.className = "figure";
      big.textContent = line;
      bubble.append(big);
    }
  }
  bubble.append(body);
  // Who answered, said quietly: "Fact-checked" only when the Judge read it (badgeFor).
  const badge = document.createElement("p");
  badge.className = "badge";
  badge.textContent = a ? badgeFor(a) : "Not sent";
  li.append(asked, bubble, badge);
  if (a && a.status === "verified") {
    // Only a checked answer draws its picture: the picture carries the same numbers as the text.
    // The evidence chip at the end of the sentence it supports (as answer engines cite a source).
    body.append(" ", howButton({ t: at, visual: a.visual ?? null, source: a.source ?? "code", evidence: a.evidence, names: a.names, answer: a }));
    if (a.visual) bubble.append(picture(a.visual, a.t_to, a.names));
    if (a.follow_ups?.length) li.append(followUps(a.follow_ups));
    if (a.spoken) li.setAttribute("aria-label", a.spoken); // a sentence that needs no picture
  }
  return li;
}

// --- pictures (visual.ts): drawn once the canvas has a size, and again when it changes ---------

const pictures = new Map<HTMLCanvasElement, () => void>();
function redrawPictures() {
  for (const [canvas, draw] of pictures) if (canvas.isConnected && canvas.clientWidth) draw();
}
const sized = new ResizeObserver((entries) => {
  for (const e of entries) pictures.get(e.target as HTMLCanvasElement)?.();
});

/** The suggested next questions an answer carries, as one-tap chips. */
function followUps(qs: string[]): HTMLElement {
  const box = document.createElement("div");
  box.className = "chips follow";
  box.setAttribute("role", "group");
  box.setAttribute("aria-label", "Ask next");
  box.append(...qs.slice(0, 3).map((q) => chip(q, null)));
  return box;
}

/** The answer's or card's picture, with its headline and its words for a screen reader: the agents'
 * visual (schemas/insight_card.schema.json) made drawable by `fromScout`, or a line saying there
 * is none. */
function picture(sv: ScoutVisual, at: number | null, names?: Record<string, string>): HTMLElement {
  const fig = document.createElement("figure");
  fig.className = "picture";
  const v = fromScout(sv, at);
  fig.dataset.kind = v?.kind ?? "none";
  if (!v || !drawable(v)) {
    // Missing data draws nothing rather than a guess.
    fig.dataset.kind = "none";
    fig.textContent = "No picture: the answer's data was incomplete.";
    return fig;
  }
  const canvas = document.createElement("canvas");
  canvas.setAttribute("role", "img");
  canvas.setAttribute("aria-label", describeVisual(v, names));
  canvas.style.aspectRatio = String(aspect());
  const cap = document.createElement("figcaption");
  const head = headline(v);
  cap.textContent = `${head ? `${head} · ` : ""}at ${clock(v.t)}`;
  fig.dataset.headline = head;
  fig.append(canvas, cap);
  const draw = () => {
    if (!canvas.clientWidth) return;
    const view = fit(canvas);
    drawVisual(view, v);
    if (v.kind === "wind") void windPicture(canvas, v);
    canvas.dataset.drawn = "1";
  };
  pictures.set(canvas, draw);
  sized.observe(canvas);
  return fig;
}

/** The wind picture: both teams' flow over the visual's window, as still arrows (wind.ts). */
async function windPicture(canvas: HTMLCanvasElement, v: Visual) {
  if (canvas.dataset.wind === "1") return;
  canvas.dataset.wind = "1";
  try {
    const mod = await import("./wind");
    const map = new mod.WindMap(() => fit(canvas));
    const flows = await Promise.all((["home", "away"] as const).map((side) => feed.flow(state.clip, side, v.t_from!, v.t_to!)));
    for (const f of flows) map.set(f);
    drawPitch(fit(canvas));
    map.still(false);
    canvas.setAttribute("aria-label", `${describeVisual(v)} ${flows.map((f) => mod.describe(f)).join(" ")}`);
  } catch (e) {
    canvas.dataset.wind = "";
    canvas.setAttribute("aria-label", `No picture: ${(e as Error).message}`);
  }
}

/** What an answer measured, over which stretch, and from which facts: rows for "How we know". */
function evidence(a: ViewerAnswer): HTMLElement[] {
  const panel = document.createElement("dl");
  panel.className = "evidence";
  const who = a.evidence.map((id) => /player_([ha](?:-t\d+|[1-9]|1[01]))_/.exec(id)?.[1]).find(Boolean);
  const what = a.metric ? METRIC_WORDS[a.metric] ?? a.metric.replace(/_/g, " ") : "";
  const rows: [string, string][] = [
    ["What", `${who ? `${playerName(who, a.names)}'s ` : ""}${what}${a.value !== null ? `: ${a.value} ${a.unit ?? ""}`.trimEnd() : ""}`],
  ];
  if (a.t_from !== null && a.t_to !== null) rows.push(["Over", a.t_from === a.t_to ? `${clock(a.t_from)} of the match` : `${clock(a.t_from)} to ${clock(a.t_to)} of the match`]);
  rows.push(["Computed by", `code, from ${feed.mock ? "the mock positions" : "positions tracked from the video"}`]);
  rows.push(
    a.source === "model"
      ? ["Checked by", "the fact-checking agent: code checks the number against the cited fact, then the Judge reads the sentence"]
      : ["Checked by", "code: the number is the cited fact itself, put in a fixed sentence; no AI wrote it"],
  );
  for (const [k, v] of rows) {
    const dt = document.createElement("dt");
    dt.textContent = k;
    const dd = document.createElement("dd");
    dd.textContent = v;
    panel.append(dt, dd);
  }
  const technical = document.createElement("details");
  technical.className = "technical";
  const summary = document.createElement("summary");
  summary.textContent = "Facts cited";
  const ids = document.createElement("p");
  ids.className = "ids";
  ids.textContent = a.evidence.join(", ");
  technical.append(summary, ids);
  return [panel, technical];
}

$("ask-form").addEventListener("submit", (e) => {
  e.preventDefault();
  void ask($<HTMLInputElement>("question").value);
});

// --- "How do we know?": what the cameras saw, what was measured, what checked it ---------------

interface How {
  t: number;
  visual: ScoutVisual | null;
  source: "code" | "model";
  evidence: string[];
  names?: Record<string, string>;
  answer?: ViewerAnswer;
  /** A card's precomputed, fact-checked "why it matters". */
  why?: { question: string; text: string };
}

/** An offside picture opens as the VAR check; everything else as How we know. */
const isVar = (h: Pick<How, "visual">) => h.visual?.kind === "offside";

/** The VAR check's verdict in one plain sentence, from the fact's own call: a call only when the
 * fact makes one, otherwise why it can't be called. */
function varVerdict(v: ScoutVisual): string {
  const g = v.geometry;
  if (g.verdict === "offside" && typeof g.margin_m === "number") return `Offside, by ${g.margin_m.toFixed(1)} metres.`;
  if (g.verdict === "onside" && typeof g.margin_m === "number") return `Onside, by ${g.margin_m.toFixed(1)} metres.`;
  if (g.verdict === "unsure") return "We can't call it: a defender was out of the cameras' view.";
  if (g.verdict === "restart") return "No offside call: the pass came straight from a restart.";
  return "Too close to call from the cameras: the gap is smaller than what tracking can measure.";
}
interface FrameDetections {
  frame: number;
  detections: { cls: string; bbox: [number, number, number, number]; score: number }[];
}

const howSheet = $("how-sheet") as IonModal;
howSheet.breakpoints = [0, 0.95];
howSheet.initialBreakpoint = 0.95;
let detections: Promise<Map<number, FrameDetections>> | null = null;

/** The bundle's detections, by match frame: what the detector found, read once, on first use. */
function bundleDetections(): Promise<Map<number, FrameDetections>> {
  if (!bundle) return Promise.resolve(new Map());
  detections ??= fetch(new URL("detections.jsonl", bundle.base))
    .then((r) => (r.ok ? r.text() : ""))
    .then((text) => {
      const byFrame = new Map<number, FrameDetections>();
      for (const line of text.split("\n")) {
        if (!line.trim()) continue;
        const row = JSON.parse(line) as FrameDetections;
        byFrame.set(row.frame, row);
      }
      return byFrame;
    });
  return detections;
}

function howButton(h: How): HTMLButtonElement {
  const b = document.createElement("button");
  b.type = "button";
  b.className = "how";
  b.textContent = isVar(h) ? "VAR check" : "How we know";
  b.addEventListener("click", () => void openHow(h));
  return b;
}

/** The broadcast picture at match time `t`, drawn onto `canvas` from the bundle's footage, with
 * every detection of that frame boxed and its confidence. Resolves to the detections drawn. */
async function drawSeen(canvas: HTMLCanvasElement, t: number): Promise<FrameDetections["detections"]> {
  if (!bundle) return [];
  const m = bundle.manifest;
  const frame = Math.round(t * m.fps);
  const v = laptop.cuts ? laptop.cuts.videoTime(t) : t - m.t_start;
  const index = Math.max(0, Math.min(m.footage.frames - 1, Math.floor(v * m.fps)));
  canvas.width = m.width;
  canvas.height = m.height;
  const ctx = canvas.getContext("2d")!;
  const picture = await new Promise<CanvasImageSource | null>((resolve) => {
    if (m.footage.kind === "frames") {
      const img = new Image();
      img.onload = () => resolve(img);
      img.onerror = () => resolve(null);
      img.src = new URL(`${m.footage.src}${String(index).padStart(5, "0")}.jpg`, bundle!.base).toString();
    } else {
      const video = document.createElement("video");
      video.muted = true;
      video.preload = "auto";
      video.src = new URL(m.footage.src, bundle!.base).toString();
      video.addEventListener("loadedmetadata", () => (video.currentTime = (index + 0.5) / m.fps), { once: true });
      video.addEventListener("seeked", () => resolve(video), { once: true });
      video.addEventListener("error", () => resolve(null), { once: true });
    }
  });
  if (picture) ctx.drawImage(picture, 0, 0, m.width, m.height);
  const found = (await bundleDetections()).get(frame)?.detections ?? [];
  ctx.lineWidth = Math.max(2, m.width / 400);
  ctx.font = `700 ${Math.round(m.width / 45)}px system-ui, sans-serif`;
  for (const d of found) {
    const [x0, y0, x1, y1] = d.bbox;
    const sure = d.score >= 0.8; // design: the same cut the caption states
    ctx.strokeStyle = sure ? "#ffffff" : "#ffd60a";
    ctx.strokeRect(x0, y0, x1 - x0, y1 - y0);
    ctx.lineWidth = Math.max(3, m.width / 300);
    ctx.strokeStyle = "#000";
    ctx.strokeText(`${Math.round(d.score * 100)}%`, x0, y0 - 6);
    ctx.fillStyle = sure ? "#ffffff" : "#ffd60a";
    ctx.fillText(`${Math.round(d.score * 100)}%`, x0, y0 - 6);
    ctx.lineWidth = Math.max(2, m.width / 400);
  }
  return found;
}

/** The VAR check's margin, on a scale either side of the line: the shaded band is where the Scout
 * makes no call, within two tracking errors (CALL_M, the Insight Scout's rule, PR #266). */
const CALL_M = 1.78;
const SCALE_M = 3; // design: the scale's half-width, past the band with room for a clear call
function marginScale(v: ScoutVisual): HTMLElement | null {
  const g = v.geometry;
  if (g.verdict === "unsure" || g.verdict === "restart" || typeof g.margin_m !== "number") return null;
  // Offside is ahead of the line (+), onside behind it (-); too close sits inside the band.
  const signed = g.verdict === "onside" ? -g.margin_m : g.margin_m;
  const at = (m: number) => `${(50 + (50 * Math.max(-SCALE_M, Math.min(SCALE_M, m))) / SCALE_M).toFixed(1)}%`;
  const scale = document.createElement("div");
  scale.className = "margin-scale";
  scale.setAttribute("role", "img");
  scale.setAttribute("aria-label", `${Math.abs(signed).toFixed(2)} metres ${signed >= 0 ? "ahead of" : "behind"} the second-last defender; within ${CALL_M} metres we don't call it.`);
  const band = document.createElement("span");
  band.className = "band-zone";
  band.style.left = at(-CALL_M);
  band.style.right = `calc(100% - ${at(CALL_M)})`;
  const line = document.createElement("span");
  line.className = "zero";
  const mark = document.createElement("span");
  mark.className = "mark";
  mark.style.left = at(signed);
  const labels = document.createElement("div");
  labels.className = "scale-labels";
  labels.innerHTML = "<span>Onside</span><span>Too close</span><span>Offside</span>"; // fixed words, no data
  scale.append(band, line, mark);
  const wrap = document.createElement("div");
  wrap.append(scale, labels);
  return wrap;
}

async function openHow(h: How) {
  const body = $("how-body");
  const p = (text: string, cls = "fine") => {
    const el = document.createElement("p");
    el.className = cls;
    el.textContent = text;
    return el;
  };
  // A stepper (as setup flows show progress): each check a circle on a line, a title, its evidence.
  const step = (title: string, ...children: HTMLElement[]) => {
    const li = document.createElement("li");
    li.className = "step done";
    const dot = document.createElement("span");
    dot.className = "step-dot";
    dot.setAttribute("aria-hidden", "true");
    dot.textContent = "✓";
    const box = document.createElement("div");
    box.className = "step-body";
    const h3 = document.createElement("h3");
    h3.textContent = title;
    box.append(h3, ...children);
    li.append(dot, box);
    return li;
  };
  const top: HTMLElement[] = [];
  $("how-title").textContent = isVar(h) ? "VAR check" : "How we know";
  if (isVar(h) && h.visual) {
    top.push(p(varVerdict(h.visual), "said lead"));
    const scale = marginScale(h.visual);
    if (scale) top.push(scale);
    top.push(picture(h.visual, h.t, h.names));
  }
  if (h.why) top.push(p(h.why.text, "said lead"));
  const steps: HTMLElement[] = [];
  if (bundle) {
    const canvas = document.createElement("canvas");
    canvas.className = "seen";
    canvas.setAttribute("role", "img");
    canvas.setAttribute("aria-label", `The broadcast picture at ${clock(h.t)}.`);
    const caption = p(`The broadcast picture at ${clock(h.t)}.`);
    steps.push(step("What the cameras saw", canvas, caption));
    void drawSeen(canvas, h.t).then((found) => {
      const unsure = found.filter((d) => d.score < 0.8).length;
      const said = found.length
        ? `${found.length} things our detector found in this frame, each boxed with how sure it was${unsure ? `; ${unsure} under 80% (yellow)` : ""}.`
        : "The detector found nothing in this frame.";
      caption.textContent = `${said} ${bundle!.manifest.detector ? `Detector: ${bundle!.manifest.detector}.` : ""}`.trim();
      canvas.setAttribute("aria-label", `The broadcast picture at ${clock(h.t)}: ${found.map((d) => `${d.cls} ${Math.round(d.score * 100)} percent`).join(", ") || "nothing detected"}.`);
    });
  } else steps.push(step("What the cameras saw", p("This phone has no footage from the big screen to show.")));
  if (h.visual && !isVar(h)) steps.push(step("What was measured", picture(h.visual, h.t, h.names), p("From positions tracked in the video.")));
  else steps.push(step("What was measured", p("From positions tracked in the video.")));
  const checked =
    h.source === "model"
      ? "The Companion agent wrote the sentence. Code checked every number against the cited facts, and the Judge read it before it reached you."
      : "Code worked out every number and put it in a fixed sentence. No AI wrote it.";
  const rows = h.answer ? evidence(h.answer) : [p(`Facts cited: ${h.evidence.join(", ") || "none"}`, "fine ids")];
  steps.push(step("What the fact-checker did", p(checked, "said"), ...rows));
  const count = p(`${steps.length} checks · all passed`, "count-line");
  const list = document.createElement("ol");
  list.className = "stepper";
  list.append(...steps);
  body.replaceChildren(...top, count, list);
  await howSheet.present();
  requestAnimationFrame(redrawPictures);
  $("how-title").focus();
}
$("close-how").addEventListener("click", () => void howSheet.dismiss());

// --- insights: the hidden-stat cards pushed so far -----------------------------------------------

let unread = 0;
let insightsAt = 0;
let insightsBusy = false;
let insightsShownTo = -1;

function showUnread() {
  const badge = $("insights-new");
  badge.hidden = unread === 0;
  badge.textContent = unread ? `${unread} new` : "";
}

async function refreshInsights(force = false) {
  if (!state.code || insightsBusy || (!force && performance.now() - insightsAt < INSIGHTS_EVERY_MS)) return;
  insightsBusy = true;
  insightsAt = performance.now();
  const t = laptop.time();
  try {
    // The bundle's cards.json (the Insight Scout's, precomputed for the replay), else the feed's.
    const cards = bundleCards ?? (await feed.insights(state.clip, t));
    // A replay must not show what is still to come: only cards up to the big screen's clock.
    const shown = cards.filter((c) => c.t <= t + 1e-6).sort((a, b) => b.t - a.t);
    const known = new Set(state.insights.map((c) => c.id));
    const fresh = shown.filter((c) => !known.has(c.id));
    const rewound = shown.length < state.insights.length; // the big screen went back in the match
    if (fresh.length || rewound) {
      state.insights = shown;
      renderInsights();
      if (fresh.length && !rewound && insightsShownTo >= 0) {
        if (state.tab !== "insights") unread += fresh.length;
        showUnread();
        announce(`New insight: ${fresh[0].spoken ?? named(fresh[0].text, fresh[0].names)}`);
      }
    }
    insightsShownTo = t;
    $("insights-note").textContent = "What the broadcast can't show, computed by code from the tracked positions, newest first.";
  } catch (e) {
    $("insights-note").textContent =
      e instanceof ApiError && e.status === 404 ? "No hidden stats for this match yet." : e instanceof GroundTruth ? e.message : `Could not load the hidden stats: ${(e as Error).message}`;
  } finally {
    insightsBusy = false;
  }
}

/** Live's "Just now": the newest Story moment, its sentence, chip and minute. */
function renderJustNow() {
  const c = state.insights[0];
  $("just-now").hidden = !c;
  if (!c) return;
  const text = document.createElement("p");
  text.className = "just-text";
  text.textContent = named(c.text, c.names);
  text.append(
    " ",
    howButton({ t: c.t, visual: c.visual, source: c.source, evidence: c.evidence, names: c.names, why: c.why ? { question: c.why.question, text: named(c.why.answer.text, c.names) } : undefined }),
  );
  const when = document.createElement("time");
  when.className = "when-line";
  when.textContent = `${c.minute}′ · ${teams[c.team]}`;
  $("just-now-body").replaceChildren(text, when);
}

function renderInsights() {
  renderJustNow();
  // A live blog: the minute on the left, one sentence, a small diagram, a quiet "How we know ›".
  const list = $("insights");
  if (!state.insights.length) {
    const li = document.createElement("li");
    li.className = "story-empty";
    li.textContent = "Nothing yet. The story fills in as the match goes on.";
    list.replaceChildren(li);
    return;
  }
  list.replaceChildren(
    ...state.insights.map((c) => {
      const li = document.createElement("li");
      li.className = `insight ${c.team}`;
      li.dataset.id = c.id;
      // One sentence with its evidence chip at the end, the minute in grey under it, then the small
      // diagram; a 3 pt rule in the club's colour down the left (Apple Sports' play-by-play).
      const body = document.createElement("div");
      body.className = "story-body";
      const head = document.createElement("h3");
      head.className = "sr-only";
      head.textContent = named(c.headline, c.names);
      const text = document.createElement("p");
      text.textContent = named(c.text, c.names);
      text.append(
        " ",
        howButton({ t: c.t, visual: c.visual, source: c.source, evidence: c.evidence, names: c.names, why: c.why ? { question: c.why.question, text: named(c.why.answer.text, c.names) } : undefined }),
      );
      const minute = document.createElement("time");
      minute.className = "when-line";
      minute.textContent = `${c.minute}′ · ${teams[c.team]}`;
      body.append(head, text, minute);
      if (c.spoken) li.setAttribute("aria-label", `${c.minute}th minute. ${c.spoken}`);
      if (c.visual) body.append(picture(c.visual, c.t, c.names));
      li.append(body);
      return li;
    }),
  );
}

// --- team stats and the score, from the bundle's match.json (match mode) -----------------------

let statsKey = "";
function showMatch(t: number) {
  const m = state.match;
  if (!m) return;
  const s = scoreAt(m, t);
  const v = laptop.cuts ? laptop.cuts.videoTime(t) : t;
  const c = chapterAt(m.chapters, bundleFps, v);
  const line = $("scoreline");
  line.hidden = !c;
  const chapter = c ? chapterLabel(c, teams) : "";
  if (line.textContent !== chapter) line.textContent = chapter;
  const score = `${s.home} – ${s.away}`;
  $("score-home").textContent = String(s.home);
  $("score-away").textContent = String(s.away);
  if ($("score").textContent !== score) {
    $("score").textContent = score;
    $("score").setAttribute("aria-label", `Score: ${teams.home} ${s.home}, ${teams.away} ${s.away}`);
  }
  $("match-card").hidden = false;
  $("no-stats").hidden = true;
  // Scorers under the band: detected goals only, so far ("Fenwick player 9 43′", or the club alone
  // when the detection names no player).
  const scored = m.goals.filter((g) => g.t <= t && g.team);
  const scorers = $("scorers");
  scorers.hidden = scored.length === 0;
  const said = scored
    .map((g) => {
      const who = bundleEvents.get(g.event)?.player;
      return `${who ? playerName(who) : teams[g.team!]} ${Math.floor(g.t / 60) + 1}′`;
    })
    .join(", ");
  if (scorers.textContent !== said) scorers.textContent = said;
  const st = statsAt(m, t);
  const key = JSON.stringify(st);
  if (key === statsKey) return;
  statsKey = key;
  renderStats(st);
}

/** Match stats as mirrored bars (Apple Sports): the home value at the left edge, the away value at
 * the right, the label centred, each bar in its club's colour. Only rows the data holds. */
function renderStats(st: MatchData["stats"][number]) {
  const rows: [string, number, number][] = [
    ["Shots", st.home.shots, st.away.shots],
    ["Shots on target", st.home.shots_on_target, st.away.shots_on_target],
    ["Passes completed", st.home.passes_completed, st.away.passes_completed],
    ["Passes tried", st.home.passes_attempted, st.away.passes_attempted],
  ];
  const items = rows
    .filter(([, h, a]) => Number.isFinite(h) && Number.isFinite(a))
    .map(([label, h, a]) => {
      const li = document.createElement("li");
      li.className = "stat-row";
      li.setAttribute("aria-label", `${label}: ${teams.home} ${h}, ${teams.away} ${a}`);
      const total = Math.max(1, h + a);
      li.innerHTML = '<span class="v home-v"></span><span class="label"></span><span class="v away-v"></span><span class="bar home-bar"></span><span class="bar away-bar"></span>';
      li.querySelector(".home-v")!.textContent = String(h);
      li.querySelector(".away-v")!.textContent = String(a);
      li.querySelector(".label")!.textContent = label;
      (li.querySelector(".home-bar") as HTMLElement).style.width = `calc(${(50 * h) / total}% - 1px)`;
      (li.querySelector(".away-bar") as HTMLElement).style.width = `calc(${(50 * a) / total}% - 1px)`;
      for (const v of li.querySelectorAll(".v, .label, .bar")) v.setAttribute("aria-hidden", "true");
      return li;
    });
  $("stat-rows").replaceChildren(...items);
  $("live-stats").hidden = items.length === 0;
}

// --- the wind map on the radar (first in the cut order: wind.ts loads only when turned on) -----

type Wind = import("./wind").WindMap;
let wind: Wind | null = null;
let windWords: typeof import("./wind").describe | null = null;
let flowAt = 0;
let flowBusy = false;

$("pitch-mode").addEventListener("ionChange", (e) => {
  const flow = (e as CustomEvent<{ value: string }>).detail.value === "flow";
  if (flow !== state.wind) $("wind-toggle").click();
});
$("wind-toggle").addEventListener("click", async () => {
  state.wind = !state.wind;
  $("wind-toggle").setAttribute("aria-pressed", String(state.wind));
  windCanvas.hidden = !state.wind;
  $("map").classList.toggle("faint", state.wind); // the players fade under the flow
  $("wind-words").hidden = !state.wind;
  if (state.wind && !wind) {
    const mod = await import("./wind");
    wind = new mod.WindMap(() => fit(windCanvas));
    windWords = mod.describe;
  }
  flowAt = 0;
  if (!state.wind) wind?.clear();
});

async function refreshFlow() {
  if (!state.wind || !wind || !state.minimap || flowBusy || performance.now() - flowAt < FLOW_EVERY_MS) return;
  flowBusy = true;
  flowAt = performance.now();
  const { WINDOW_S } = await import("./wind");
  const t = laptop.time();
  try {
    const flows = await Promise.all((["home", "away"] as const).map((side) => feed.flow(state.clip, side, Math.max(0, t - WINDOW_S), t)));
    for (const f of flows) wind.set(f);
    const words = $("wind-words");
    words.replaceChildren(
      ...[`Team movement over the last ${WINDOW_S} seconds.`, ...flows.map((f) => windWords!(f))].map((s) => {
        const p = document.createElement("p");
        p.textContent = s;
        return p;
      }),
    );
    windCanvas.dataset.t = String(t);
  } catch (e) {
    $("wind-words").textContent = e instanceof GroundTruth ? e.message : `Could not load the wind map: ${(e as Error).message}`;
    $("wind-note").hidden = false;
    $("wind-note").textContent = "Flow isn't available for this match yet.";
  } finally {
    flowBusy = false;
  }
}

// --- every frame -----------------------------------------------------------------------------

function frame(now: number) {
  const t = laptop.time();
  $("clock").textContent = link ? clock(t) : "–:––";
  const mini = state.match
    ? `${teams.home}  ${$("score-home").textContent}   ${link ? clock(t) : "–:––"}   ${$("score-away").textContent}  ${teams.away}`
    : `${teams.home}   ${link ? clock(t) : "–:––"}   ${teams.away}`;
  for (const el of document.querySelectorAll(".score-line")) if (el.textContent !== mini) el.textContent = mini;
  if (link) {
    if (!laptop.heard) setStatus("waiting", "Waiting");
    else if (laptop.stale()) setStatus("waiting", "Screen lost");
    else if (state.radar === null && state.refused !== null) setStatus("paused", "Clock only");
    else if (laptop.isPlaying()) setStatus("synced", "Synced");
    else setStatus("paused", "Paused");
    showMatch(t);
    void refreshInsights();
  }
  if (state.radar && !$("live").hidden) {
    if (state.tab === "radar") {
      const s = drawMap(t);
      const pos: Positions = { ball: s.ball ? [s.ball.x, s.ball.y] : [52.5, 34], players: s.players.map((p) => [p.id, p.x, p.y]) };
      lastPositions = s.ball ? pos : null;
      describeMap(t, s, pos);
      if (lastPositions) liveDescription(t, lastPositions);
      mapCanvas.dataset.frame = String(s.frame);
      mapCanvas.dataset.dots = String(s.players.length);
    }
    mapCanvas.dataset.t = t.toFixed(2);
    void refreshCard();
    void refreshFlow();
    if (state.wind && wind) {
      if (reduceMotion.matches) wind.still();
      else wind.step(now);
    }
  } else {
    mapCanvas.dataset.dots = "0";
    mapCanvas.dataset.t = t.toFixed(2);
  }
  requestAnimationFrame(frame);
}

$("mockbar").hidden = !feed.mock;
renderChips();
renderInsights();
requestAnimationFrame(frame);
const start = params.get("code");
if (start) {
  codeInput.value = normalise(start);
  void connect(normalise(start));
}
