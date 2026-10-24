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
import * as momentum from "./momentum";
import { tickTo } from "./ticker";
import * as prefs from "./settings";
import { speakAloud } from "../../viewer/src/speech";
import * as shotMap from "./shots";
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
  announce: (text: string) => announce(text),
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
  // An answer as the thread would show it, for previews and screenshots of fields the mock cannot
  // send yet (follow_ups arrive with the agents' next answer schema).
  answer: (question: string, a: ViewerAnswer) => {
    const li = renderAnswer(question, laptop.time(), a, "");
    $("answers").append(li);
    requestAnimationFrame(redrawPictures);
    return li.dataset.status;
  },
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

function setStatus(kind: "off" | "synced" | "paused" | "waiting" | "lost" | "rewound", text: string) {
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
  confidence?: number | null;
  interceptor?: string | null;
}
let bundleEvents = new Map<string, DetectedEvent>(); // detected events, by id
interface DescribedLine {
  id: string;
  t_in: number;
  t_out: number;
  text: string;
}
let described: DescribedLine[] = []; // the audio description as said (audio.json), oldest first
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
    const [radar, match, cards, audio] = await Promise.all([
      m.radar ? get("radar.json") : null,
      m.match ? get("match.json") : null,
      m.cards ? get("cards.json") : null,
      get("audio.json").catch(() => null), // the audio description's lines, for Story's transcript
    ]);
    if (audio && Array.isArray(audio.said)) described = (audio.said as DescribedLine[]).slice().sort((a, b) => a.t_in - b.t_in);
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
    const num = document.createElement("span");
    num.className = "num";
    num.textContent = shirt(id);
    const name = document.createElement("span");
    name.className = "name";
    name.textContent = playerName(id);
    b.append(num, name);
    b.setAttribute("aria-label", playerName(id));
    b.setAttribute("aria-pressed", "false");
    b.addEventListener("click", () => select(id));
    return b;
  };
  // One card per club, home first (Apple Sports' line-ups): its crest and name, then # and name.
  $("roster").replaceChildren(
    ...(["home", "away"] as const).map((side) => {
      const ids = roster.filter((id) => team(id) === side).sort((a, b) => Number(shirt(a)) - Number(shirt(b)));
      const card = document.createElement("section");
      card.className = "card roster-card";
      const head = document.createElement("h3");
      head.className = "card-title roster-team";
      head.innerHTML = `<svg class="crest ${side}" viewBox="0 0 54 62" aria-hidden="true"><path d="M27 2 50 9v22c0 14-10 24-23 29C14 55 4 45 4 31V9z"/></svg>`;
      head.append(teams[side]);
      const cols = document.createElement("p");
      cols.className = "roster-cols";
      cols.setAttribute("aria-hidden", "true");
      cols.innerHTML = "<span>#</span><span>Name</span>";
      const row = document.createElement("div");
      row.className = "roster-row";
      row.append(...ids.map(button));
      card.append(head, cols, row);
      return card;
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
    say(text);
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

// --- listening and text size (settings.ts): voice, rate, transcript, text size ------------------

let settings = prefs.load();
let captionTimer = 0;
/** Speaks a line with the fan's voice and rate; with the transcript on, shows it as a caption too. */
function say(text: string) {
  speakAloud(text, { rate: settings.rate, voice: settings.voice });
  if (!settings.transcript) return;
  const caption = $("caption");
  caption.textContent = text;
  caption.hidden = false;
  clearTimeout(captionTimer);
  captionTimer = window.setTimeout(() => (caption.hidden = true), 4000 + 60 * text.length); // design: time to read it
}

function applyText() {
  document.documentElement.dataset.text = settings.text;
}

const SIZES: [prefs.TextSize, string][] = [
  ["normal", "Normal"],
  ["large", "Large"],
  ["xlarge", "Extra large"],
];
const SAMPLE = "Oakfield keep winning it back fast: four times inside five seconds this half.";

function radioRow(group: string, label: string, on: boolean, pick: () => void, extra?: HTMLElement): HTMLLIElement {
  const li = document.createElement("li");
  li.className = "setting-row radio";
  const b = document.createElement("button");
  b.type = "button";
  b.setAttribute("role", "radio");
  b.setAttribute("aria-checked", String(on));
  b.dataset.group = group;
  b.className = "radio-main";
  b.innerHTML = '<span class="row-title"></span><svg class="tick" viewBox="0 0 24 24" aria-hidden="true"><path d="m5 12.5 4.5 4.5L19 7.5"/></svg>';
  b.querySelector(".row-title")!.textContent = label;
  b.addEventListener("click", () => {
    pick();
    prefs.save(settings);
    renderSettings();
  });
  if (extra) li.append(extra);
  li.append(b);
  return li;
}

function renderSettings() {
  const vs = prefs.voices();
  $("voices").replaceChildren(
    radioRow("voice", "Phone's default voice", settings.voice === null, () => (settings.voice = null)),
    ...vs.map((v) => {
      const play = document.createElement("button");
      play.type = "button";
      play.className = "preview";
      play.setAttribute("aria-label", `Hear ${v.name}`);
      play.innerHTML = '<svg viewBox="0 0 24 24" aria-hidden="true"><path d="M9 7v10l8-5z"/></svg>';
      play.addEventListener("click", () => {
        if ("speechSynthesis" in window) speechSynthesis.cancel();
        speakAloud(SAMPLE, { rate: settings.rate, voice: v.name }); // a preview: only on this tap
      });
      return radioRow("voice", v.name, settings.voice === v.name, () => (settings.voice = v.name), play);
    }),
  );
  $<HTMLInputElement>("transcript-on").checked = settings.transcript;
  const rate = $<HTMLInputElement>("rate");
  rate.min = String(prefs.RATES.min);
  rate.max = String(prefs.RATES.max);
  rate.step = String(prefs.RATES.step);
  rate.value = String(settings.rate);
  rate.setAttribute("aria-valuetext", `${settings.rate.toFixed(1)} times`);
  $("rate-value").textContent = `${settings.rate.toFixed(1)}x`;
  $("text-sizes").replaceChildren(...SIZES.map(([size, label]) => radioRow("text", label, settings.text === size, () => (settings.text = size))));
  applyText();
}

$("transcript-on").addEventListener("change", (e) => {
  settings.transcript = (e.target as HTMLInputElement).checked;
  prefs.save(settings);
});
$("rate").addEventListener("input", (e) => {
  settings.rate = Number((e.target as HTMLInputElement).value);
  prefs.save(settings);
  $("rate-value").textContent = `${settings.rate.toFixed(1)}x`;
  $("rate").setAttribute("aria-valuetext", `${settings.rate.toFixed(1)} times`);
});
const settingsSheet = $("settings-sheet") as IonModal;
let settingsUp = false;
for (const b of document.querySelectorAll<HTMLButtonElement>(".settings-open")) {
  b.addEventListener("click", () => {
    settings = prefs.load();
    renderSettings();
    void settingsSheet.present();
  });
}
settingsSheet.addEventListener("ionModalWillPresent", () => (settingsUp = true));
settingsSheet.addEventListener("ionModalWillDismiss", () => (settingsUp = false));
settingsSheet.addEventListener("ionModalDidPresent", () => $("settings-title").focus());
$("close-settings").addEventListener("click", () => void settingsSheet.dismiss());
if ("speechSynthesis" in window) speechSynthesis.addEventListener("voiceschanged", () => settingsUp && renderSettings());
applyText();

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
  const was = state.selected;
  select(null);
  document.querySelector<HTMLElement>(`#roster [data-player="${was}"]`)?.focus(); // back where the pick was
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
    li.append(answerActions(a));
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

/** Under an answer (Perplexity's action row): read it aloud on a tap, copy it, and how many facts
 * the fact-checker held it to. */
function answerActions(a: ViewerAnswer): HTMLElement {
  const row = document.createElement("div");
  row.className = "answer-actions";
  const icon = (label: string, path: string, run: () => void) => {
    const b = document.createElement("button");
    b.type = "button";
    b.className = "act";
    b.setAttribute("aria-label", label);
    b.innerHTML = `<svg viewBox="0 0 24 24" aria-hidden="true">${path}</svg>`;
    b.addEventListener("click", run);
    return b;
  };
  const text = named(a.text, a.names);
  row.append(
    icon("Read this answer aloud", '<path d="M4 9v6h4l5 4V5L8 9H4z"/><path d="M16.5 8.5a5 5 0 0 1 0 7"/>', () => say(text)),
    icon("Copy this answer", '<rect x="8" y="8" width="12" height="12" rx="2"/><path d="M16 8V6a2 2 0 0 0-2-2H6a2 2 0 0 0-2 2v8a2 2 0 0 0 2 2h2"/>', () => void navigator.clipboard?.writeText(text)),
  );
  const n = a.evidence.length;
  const facts = document.createElement("span");
  facts.className = "facts";
  facts.textContent = `${n} ${n === 1 ? "fact" : "facts"} checked`;
  row.append(facts);
  return row;
}

/** The suggested next questions an answer carries, as Perplexity's "↳" rows: one tap asks it. */
function followUps(qs: string[]): HTMLElement {
  const box = document.createElement("ul");
  box.className = "follow-ups";
  box.setAttribute("aria-label", "Ask next");
  box.append(
    ...qs.slice(0, 3).map((q) => {
      const li = document.createElement("li");
      const b = document.createElement("button");
      b.type = "button";
      b.className = "follow-up";
      b.innerHTML = '<svg viewBox="0 0 24 24" aria-hidden="true"><path d="M6 4v8a3 3 0 0 0 3 3h10"/><path d="m15 11 4 4-4 4"/></svg>';
      b.append(q);
      b.addEventListener("click", () => void ask(q));
      li.append(b);
      return li;
    }),
  );
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
let insightsLoaded = false; // the first fetch has answered, with cards or with none

function showUnread() {
  const badge = $("insights-new");
  badge.hidden = unread === 0;
  badge.textContent = unread ? `${unread} new` : "";
}

async function refreshInsights(force = false) {
  if (!state.code || insightsBusy || (!force && performance.now() - insightsAt < INSIGHTS_EVERY_MS)) return;
  insightsBusy = true;
  insightsAt = performance.now();
  const t = viewTime();
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
      if (fresh.length && !rewound && insightsShownTo >= 0 && scrubT === null) {
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
    if (!insightsLoaded) {
      insightsLoaded = true;
      renderInsights();
    }
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
  when.textContent = clock(c.t);
  $("just-now-body").replaceChildren(text, when);
}

/** A detected event as a play-by-play line (Apple Sports: "Kyle Walker takes a throw-in."), from
 * its own fields only; a player the detection did not name is his club. */
function playSentence(e: DetectedEvent): string | null {
  const side = e.team === "home" || e.team === "away" ? e.team : null;
  const who = (id?: string | null) => (id ? playerName(id) : side ? teams[side] : "A player");
  switch (e.type) {
    case "pass":
      if (e.outcome === "success") return e.receiver ? `${who(e.player)} passes to ${playerName(e.receiver)}.` : `${who(e.player)} completes a pass.`;
      return e.interceptor ? `${who(e.player)}'s pass is cut out by ${playerName(e.interceptor)}.` : `${who(e.player)}'s pass doesn't find a teammate.`;
    case "shot":
      return e.outcome === "goal" ? `${who(e.player)} scores.` : e.outcome === "on_target" ? `Shot saved, from ${who(e.player)}.` : e.outcome === "blocked" ? `${who(e.player)}'s shot is blocked.` : `${who(e.player)} shoots wide.`;
    case "out_of_play":
      return "The ball goes out of play.";
    case "set_piece":
      return side ? `${teams[side]} take a set piece.` : "A set piece.";
    case "kickoff":
      return side ? `${teams[side]} kick off.` : "Kick-off.";
    default:
      return null;
  }
}

/** The plays up to t the fact-checker would let through, newest first. */
function playsUpTo(t: number): DetectedEvent[] {
  const min = state.match?.min_confidence ?? 1;
  return [...bundleEvents.values()].filter((e) => e.t <= t + 1e-6 && (e.confidence ?? 0) >= min && playSentence(e)).sort((a, b) => b.t - a.t);
}
let playsShown = -1;

function storyItem(team: "home" | "away" | null, text: string, t: number): { li: HTMLLIElement; body: HTMLDivElement } {
  const li = document.createElement("li");
  li.className = `insight ${team ?? "neutral"}`;
  const body = document.createElement("div");
  body.className = "story-body";
  const p = document.createElement("p");
  p.textContent = text;
  const foot = document.createElement("p");
  foot.className = "when-line";
  const time = document.createElement("time");
  time.textContent = clock(t);
  foot.append(time);
  body.append(p, foot);
  li.append(body);
  return { li, body };
}

function renderInsights() {
  renderJustNow();
  // Apple Sports' play-by-play: one card per play, newest first, the time under the sentence, the
  // club's rule on its own side. All plays adds every detected play; Key plays keeps the Scout's
  // moments (with their diagrams) and goals.
  const list = $("insights");
  const now = viewTime();
  if (list.dataset.mode === "described") return renderDescribed(list, now);
  const plays = playsUpTo(now);
  playsShown = plays.length;
  const key = list.dataset.mode === "key";
  const score = (t: number) => (state.match ? scoreAt(state.match, t) : null);
  type Row = { t: number; el: HTMLLIElement };
  const rows: Row[] = state.insights.map((c) => {
    const { li, body } = storyItem(c.team, named(c.text, c.names), c.t);
    li.classList.add("moment");
    li.dataset.id = c.id;
    const head = document.createElement("h3");
    head.className = "sr-only";
    head.textContent = named(c.headline, c.names);
    body.prepend(head);
    body.querySelector("p:not(.when-line)")!.append(
      " ",
      howButton({ t: c.t, visual: c.visual, source: c.source, evidence: c.evidence, names: c.names, why: c.why ? { question: c.why.question, text: named(c.why.answer.text, c.names) } : undefined }),
    );
    if (c.spoken) li.setAttribute("aria-label", `${clock(c.t)}. ${c.spoken}`);
    if (c.visual) body.append(picture(c.visual, c.t, c.names));
    return { t: c.t, el: li };
  });
  for (const e of plays) {
    const goal = e.type === "shot" && e.outcome === "goal";
    if (key && !goal) continue;
    const side = e.team === "home" || e.team === "away" ? e.team : null;
    const { li } = storyItem(side, playSentence(e)!, e.t);
    li.classList.add("play");
    li.dataset.event = e.id;
    if (goal) {
      const s = score(e.t);
      const tally = document.createElement("span");
      tally.className = "tally";
      if (s) tally.textContent = `${s.home} · ${s.away}`;
      li.querySelector(".when-line")!.append(tally);
    }
    rows.push({ t: e.t, el: li });
  }
  if (!rows.length && !insightsLoaded) {
    // Still loading: grey placeholders the shape of the cards (shadcn's Skeleton, ported).
    list.replaceChildren(
      ...[0, 1, 2].map(() => {
        const li = document.createElement("li");
        li.className = "insight skeleton-card";
        li.setAttribute("aria-hidden", "true");
        li.innerHTML = '<span class="skeleton line"></span><span class="skeleton line short"></span><span class="skeleton stamp"></span>';
        return li;
      }),
    );
    list.setAttribute("aria-busy", "true");
    return;
  }
  list.removeAttribute("aria-busy");
  if (!rows.length) {
    const li = document.createElement("li");
    li.className = "story-empty";
    li.textContent = "Nothing yet. The plays fill in as the match goes on.";
    list.replaceChildren(li);
    return;
  }
  list.replaceChildren(...rows.sort((a, b) => b.t - a.t).map((r) => r.el));
}

/** Story's transcript of the audio description (Spotify's lyrics view): every line said so far,
 * the one on air now bright and big, those before it dimmer; never a line still to come. */
let describedKey = "";
function renderDescribed(list: HTMLElement, now: number) {
  const said = described.filter((l) => l.t_in <= now + 1e-6);
  const key = `${said.length}|${said.length && now <= said[said.length - 1].t_out ? "on" : "off"}`;
  if (key === describedKey && list.childElementCount) return;
  describedKey = key;
  if (!said.length) {
    const li = document.createElement("li");
    li.className = "story-empty";
    li.textContent = described.length ? "The description starts with the first play." : "This match has no audio description.";
    list.replaceChildren(li);
    return;
  }
  list.replaceChildren(
    ...said.map((l, i) => {
      const li = document.createElement("li");
      li.className = "lyric";
      const text = named(l.text, undefined);
      li.textContent = text.charAt(0).toUpperCase() + text.slice(1);
      const current = i === said.length - 1 && now <= l.t_out;
      if (current) li.setAttribute("aria-current", "true");
      return li;
    }),
  );
  list.querySelector<HTMLElement>("[aria-current]")?.scrollIntoView({ block: "center", behavior: reduceMotion.matches ? "auto" : "smooth" });
}

$("story-mode").addEventListener("ionChange", (e) => {
  $("insights").dataset.mode = (e as CustomEvent<{ value: string }>).detail.value;
  describedKey = "";
  renderInsights();
  requestAnimationFrame(redrawPictures);
});

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
  tickTo($("score-home"), s.home);
  tickTo($("score-away"), s.away);
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
  renderShots(t);
  if ($("insights").dataset.mode === "described") renderDescribed($("insights"), t);
  else if (playsUpTo(t).length !== playsShown) renderInsights();
  const st = statsAt(m, t);
  const key = JSON.stringify(st);
  if (key === statsKey) return;
  statsKey = key;
  renderStats(st);
}

/** Match stats as mirrored bars (Apple Sports): the home value at the left edge, the away value at
 * the right, the label centred, each bar in its club's colour. Only rows the data holds. */
interface TeamStatsFacts {
  from_footage: boolean;
  distance?: Record<"home" | "away", { km: number; coverage: number }>;
  possession?: Record<"home" | "away", { share: number }>;
}
const shownStats = new Map<string, [number, number]>();
function renderStats(st: MatchData["stats"][number]) {
  const rows: [string, number, number][] = [
    ["Shots", st.home.shots, st.away.shots],
    ["Shots on target", st.home.shots_on_target, st.away.shots_on_target],
    ["Passes completed", st.home.passes_completed, st.away.passes_completed],
    ["Passes tried", st.home.passes_attempted, st.away.passes_attempted],
  ];
  // Measured per-team facts when the bundle has them (match.json team_stats, #269): possession only
  // if its gate passed; distance with how much of the players' time was tracked.
  const ts = (state.match as (MatchData & { team_stats?: TeamStatsFacts }) | null)?.team_stats;
  if (ts?.possession) rows.unshift(["Possession %", Math.round(ts.possession.home.share), Math.round(ts.possession.away.share)]);
  if (ts?.distance) rows.push(["Distance (km)", Math.round(ts.distance.home.km * 10) / 10, Math.round(ts.distance.away.km * 10) / 10]);
  const covered = ts?.distance ? Math.round(100 * Math.min(ts.distance.home.coverage, ts.distance.away.coverage)) : null;
  $("stats-note").textContent = covered === null ? "From the footage shown, so far." : `From the footage shown, so far. Distance covers ${covered}% of the players' time.`;
  const items = rows
    .filter(([, h, a]) => Number.isFinite(h) && Number.isFinite(a))
    .map(([label, h, a]) => {
      const li = document.createElement("li");
      li.className = "stat-row";
      li.setAttribute("aria-label", `${label}: ${teams.home} ${h}, ${teams.away} ${a}`);
      li.innerHTML = '<span class="v home-v"></span><span class="label"></span><span class="v away-v"></span><span class="bar home-bar"></span><span class="bar away-bar"></span>';
      // The numbers tick up from what the row showed before (ticker.ts).
      const was = shownStats.get(label);
      li.querySelector<HTMLElement>(".home-v")!.textContent = String(was?.[0] ?? h);
      li.querySelector<HTMLElement>(".away-v")!.textContent = String(was?.[1] ?? a);
      tickTo(li.querySelector<HTMLElement>(".home-v")!, h);
      tickTo(li.querySelector<HTMLElement>(".away-v")!, a);
      shownStats.set(label, [h, a]);
      li.querySelector(".label")!.textContent = label;
      // One track split at the home share (Apple Sports): 0 v 0 splits it evenly; 1 v 0 is all home.
      const share = h + a === 0 ? 0.5 : h / (h + a);
      (li.querySelector(".home-bar") as HTMLElement).style.width = share === 0 ? "0" : `calc(${100 * share}% - ${share < 1 ? 2 : 0}px)`;
      (li.querySelector(".away-bar") as HTMLElement).style.width = share === 1 ? "0" : `calc(${100 * (1 - share)}% - ${share > 0 ? 2 : 0}px)`;
      for (const v of li.querySelectorAll(".v, .label, .bar")) v.setAttribute("aria-hidden", "true");
      return li;
    });
  $("stat-rows").replaceChildren(...items);
  $("live-stats").hidden = items.length === 0;
}

// --- the shot map: detected shots up to the clock, those the fact-checker would let through -----

let shotFilter: "all" | "home" | "away" = "all";
let shotsKey = "";
$("shot-filter").addEventListener("ionChange", (e) => {
  shotFilter = (e as CustomEvent<{ value: typeof shotFilter }>).detail.value;
  shotsKey = "";
  renderShots(viewTime());
});

function renderShots(t: number) {
  const min = state.match?.min_confidence ?? 1;
  const all: shotMap.Shot[] = [...bundleEvents.values()]
    .filter((e) => e.type === "shot" && e.t <= t && (e.team === "home" || e.team === "away") && e.x !== undefined && e.y !== undefined && (e.confidence ?? 0) >= min)
    .map((e) => ({ id: e.id, t: e.t, team: e.team as "home" | "away", x: e.x!, y: e.y!, outcome: e.outcome ?? null, player: e.player ?? null }));
  $("shot-map").hidden = all.length === 0;
  const shown = all.filter((s) => shotFilter === "all" || s.team === shotFilter);
  const key = `${shotFilter}|${shown.map((s) => s.id).join()}`;
  if (key === shotsKey) return;
  shotsKey = key;
  const svg = $("shots") as unknown as SVGSVGElement;
  shotMap.draw(svg, shown);
  const goals = shown.filter((s) => s.outcome === "goal").length;
  svg.setAttribute("aria-label", `Shot map: ${shown.length} ${shown.length === 1 ? "shot" : "shots"}, ${goals} ${goals === 1 ? "goal" : "goals"}. The list follows.`);
  $("shot-list").replaceChildren(
    ...shown.map((s) => {
      const li = document.createElement("li");
      li.textContent = `${momentum.minuteOf(s.t)}′ ${s.player ? playerName(s.player) : teams[s.team]}, ${shotMap.label(s.outcome)}, from the ${zoneFor(s.team, s.x, s.y)}`;
      return li;
    }),
  );
}

// --- Live's text tabs (Apple Sports: Stats / Play-By-Play / Rankings): Pitch, Stats, Players ----

const LIVE_PANES = ["pitch", "stats", "players"] as const;
type LivePane = (typeof LIVE_PANES)[number];
function showPane(pane: LivePane, focus = false) {
  for (const p of LIVE_PANES) {
    const tab = $(`lt-${p}`);
    const on = p === pane;
    tab.setAttribute("aria-selected", String(on));
    tab.tabIndex = on ? 0 : -1;
    $(`pane-${p}`).hidden = !on;
    if (on && focus) tab.focus();
  }
  document.body.dataset.pane = pane;
  if (pane === "pitch") summaryAt = -1;
}
for (const p of LIVE_PANES) {
  const tab = $(`lt-${p}`);
  tab.addEventListener("click", () => showPane(p));
  tab.addEventListener("keydown", (e) => {
    const i = LIVE_PANES.indexOf(p);
    const to = e.key === "ArrowRight" ? i + 1 : e.key === "ArrowLeft" ? i - 1 : e.key === "Home" ? 0 : e.key === "End" ? LIVE_PANES.length - 1 : null;
    if (to === null) return;
    e.preventDefault();
    showPane(LIVE_PANES[(to + LIVE_PANES.length) % LIVE_PANES.length], true);
  });
}

// --- territory per 5 minutes, and rewinding the screen along it --------------------------------

/** The time the screen shows: the big screen's, or the minute the viewer rewound to. */
let scrubT: number | null = null;
function viewTime(): number {
  return scrubT === null ? laptop.time() : Math.min(scrubT, laptop.time());
}

function territory(): momentum.Territory | null {
  return (state.match as (MatchData & { territory?: momentum.Territory }) | null)?.territory ?? null;
}

/** The nearest moment at or before `live` that the footage shows: a condensed match has gaps
 * between its passages, and the screen can only rewind to what was filmed. */
function footageNear(t: number, live: number): number {
  const spans = (state.match?.chapters ?? []).map((c) => [c.t, Math.min(c.t_end, live)] as const).filter(([a, b]) => a <= b);
  if (!spans.length) return Math.max(0, Math.min(t, live));
  let best = spans[0][0];
  for (const [a, b] of spans) {
    const near = Math.max(a, Math.min(t, b));
    if (Math.abs(near - t) < Math.abs(best - t)) best = near;
  }
  return best;
}

function rewind(to: number | null) {
  const before = scrubT;
  scrubT = to === null ? null : footageNear(to, laptop.time());
  if (scrubT === before) return;
  $("to-live").hidden = scrubT === null;
  // What the rewound screen shows is fetched for its own minute; back at live nothing is "new".
  if (scrubT === null) insightsShownTo = -1;
  flowAt = 0;
  summaryAt = -1;
  void refreshInsights(true);
}

const strip = $("momentum-strip") as unknown as SVGSVGElement;
function stripTime(e: PointerEvent): number {
  const r = strip.getBoundingClientRect();
  return (Math.max(0, Math.min(1, (e.clientX - r.left) / r.width))) * momentum.span(laptop.time());
}
strip.addEventListener("pointerdown", (e) => {
  strip.setPointerCapture(e.pointerId);
  rewind(stripTime(e));
});
strip.addEventListener("pointermove", (e) => {
  if (strip.hasPointerCapture(e.pointerId)) rewind(stripTime(e));
});
strip.addEventListener("keydown", (e) => {
  const at = viewTime();
  const step: Record<string, number> = { ArrowLeft: -60, ArrowDown: -60, ArrowRight: 60, ArrowUp: 60, PageDown: -300, PageUp: 300 };
  if (e.key in step) rewind(at + step[e.key]);
  else if (e.key === "Home") rewind(0);
  else if (e.key === "End") rewind(null);
  else return;
  e.preventDefault();
});
$("to-live").addEventListener("click", () => {
  rewind(null);
  strip.focus();
});

let stripKey = "";
function renderMomentum(live: number, t: number) {
  const tr = territory();
  $("momentum").hidden = !tr || !tr.bins.length;
  if (!tr || !tr.bins.length) return;
  const key = `${Math.floor(live)}|${scrubT === null ? "" : t.toFixed(1)}`;
  if (key === stripKey) return;
  stripKey = key;
  momentum.draw(strip, tr, live, scrubT === null ? null : t, state.match?.goals ?? []);
  strip.setAttribute("aria-valuemax", String(Math.floor(live)));
  strip.setAttribute("aria-valuenow", String(Math.floor(t)));
  strip.setAttribute("aria-valuetext", (scrubT === null ? "Live. " : "") + momentum.sayAt(tr, t, teams));
  // Progress to the next 5-minute cell, and how much footage the current one rests on.
  const into = live % tr.bin_s;
  ($("next-fill") as HTMLElement).style.width = `${(100 * into) / tr.bin_s}%`;
  const b = momentum.binAt(tr, t);
  const seen = b ? `from ${Math.round(b.seen_s)} s of footage in this spell` : "no footage of this spell";
  $("momentum-note").textContent = scrubT === null ? `Next 5 minutes in ${clock(tr.bin_s - into)} · ${seen}` : `${clock(t)} · ${seen}`;
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
  const t = viewTime();
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
  const live = laptop.time();
  if (scrubT !== null && scrubT > live) scrubT = live; // never ahead of the big screen
  const t = viewTime();
  $("clock").textContent = link ? clock(t) : "–:––";
  const mini = state.match
    ? `${teams.home}  ${$("score-home").textContent}   ${link ? clock(t) : "–:––"}   ${$("score-away").textContent}  ${teams.away}`
    : `${teams.home}   ${link ? clock(t) : "–:––"}   ${teams.away}`;
  // The collapsed row (Apple Sports): crest, score, clock, score, crest; one label for a screen reader.
  const clockText = link ? clock(t) : "–:––";
  for (const el of document.querySelectorAll<HTMLElement>(".score-line")) {
    if (el.getAttribute("aria-label") === mini) continue;
    el.setAttribute("aria-label", mini);
    el.querySelector(".mh")!.textContent = state.match ? $("score-home").textContent : "";
    el.querySelector(".ma")!.textContent = state.match ? $("score-away").textContent : "";
    el.querySelector(".mc")!.textContent = clockText;
  }
  if (link) {
    if (!laptop.heard) setStatus("waiting", "Waiting");
    else if (laptop.stale()) setStatus("waiting", "Screen lost");
    else if (state.radar === null && state.refused !== null) setStatus("paused", "Clock only");
    else if (scrubT !== null) setStatus("rewound", `Rewound to ${momentum.minuteOf(t)}′`);
    else if (laptop.isPlaying()) setStatus("synced", "Synced");
    else setStatus("paused", "Paused");
    showMatch(t);
    renderMomentum(live, t);
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
