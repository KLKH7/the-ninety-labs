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
import { type MatchData, chapterAt, chapterLabel, statsAt } from "../../viewer/src/match";
import * as momentum from "./momentum";
import { tickTo } from "./ticker";
import { crestOf } from "../../viewer/src/crests";
import * as prefs from "./settings";
import * as fans from "./fan";
import { mountOnboarding } from "./onboarding";
import { speakAloud } from "../../viewer/src/speech";
import * as shotMap from "./shots";
import { CLUBS, DEFAULT_TEAMS, fullName, nameIds, setSidesKnown, short, sideUnsure, teamNames } from "../../viewer/src/teams";
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
  tacticalSheet,
  teamSheet,
  type SheetEntry,
  unnamedTrack,
  eventName,
} from "./types";
import { describeVisual, drawVisual, drawable, fromScout, headline, title } from "./visual";

const $ = <T extends HTMLElement>(id: string) => document.getElementById(id) as T;
const params = new URLSearchParams(location.search);
/** Docked beside the big screen on a desktop (`?embed=1`, web/viewer's companion panel): already
 * paired by the page around it, which plays every sound; it opens on Live and talks to its parent
 * page about tabs, same origin only. */
const embed = params.get("embed") === "1" && window.parent !== window;
if (embed) document.body.dataset.embed = "1";

/** The demo passcode (ninety/api/companion.py): with it the server's agents answer Ask. Kept on this
 * device only (localStorage, guarded: a private window refuses it); taken once from `?pass=` and
 * struck from the address bar at once; never logged, never sent but as Ask's header. */
const PASS_KEY = "ninety.passcode";
let passcode: string | null = (() => {
  try {
    return localStorage.getItem(PASS_KEY);
  } catch {
    return null;
  }
})();
function setPasscode(value: string | null) {
  passcode = value ? value.trim() || null : null;
  try {
    if (passcode) localStorage.setItem(PASS_KEY, passcode);
    else localStorage.removeItem(PASS_KEY);
  } catch {
    // a private window: the passcode lasts for this visit only
  }
}
if (params.has("pass")) {
  setPasscode(params.get("pass"));
  params.delete("pass");
  const rest = params.toString();
  history.replaceState(history.state, "", `${location.pathname}${rest ? `?${rest}` : ""}${location.hash}`);
}

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

/** How long a phone that lost its screen keeps asking for the same code when the server does not know
 * it (design: a restarted server, whose big screen claims its code back within about 2 s,
 * desktop-companion, Oct 26); a code typed or scanned still fails at once. */
const RECLAIM_S = 30;
let reclaimUntil = 0; // while reconnecting, an unknown code is the server coming back, not a wrong code
function onClosed(why: Closed) {
  const reclaiming = (w: unknown) => w === "unknown-code" && Date.now() < reclaimUntil;
  if (why === "lost" || reclaiming(why)) {
    if (Date.now() >= reclaimUntil) reclaimUntil = Date.now() + RECLAIM_S * 1000;
    setStatus("lost", "Reconnecting…");
    const retry = async () => {
      try {
        link = await feed.join(state.code, onRelay, onClosed);
      } catch (again) {
        if (again === "lost" || again === "not-joined" || reclaiming(again)) setTimeout(retry, 2000);
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
  if (embed) window.parent.postMessage({ type: "ninety-tab", tab }, location.origin);
  if (tab === "insights") {
    unread = 0;
    showUnread();
  }
  if (tab === "ask") requestAnimationFrame(redrawPictures); // canvases sized while hidden draw now
}

// The big screen around an embedded phone may open a tab ("Ask anything about this match →").
const OPEN_TABS: Record<string, Tab> = { live: "radar", radar: "radar", ask: "ask", story: "insights", insights: "insights" };
if (embed) {
  window.addEventListener("message", (e) => {
    if (e.origin !== location.origin || e.source !== window.parent) return; // the parent page only
    const m = e.data as { type?: unknown; tab?: unknown } | null;
    // The passcode entered on the big screen, so the docked panel's Ask is the agents' too.
    const pm = e.data as { type?: unknown; passcode?: unknown } | null;
    if (pm && pm.type === "ninety-passcode" && (typeof pm.passcode === "string" || pm.passcode === null)) setPasscode(pm.passcode);
    const tab = m && m.type === "ninety-open" && typeof m.tab === "string" ? OPEN_TABS[m.tab] : undefined;
    if (tab && document.body.dataset.state === "live") showTab(tab, true);
  });
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
  sides_known?: unknown;
  min_team_confidence?: unknown;
  /** scorebug.jsonl (ninety-e2e --scorebug): shown only once the reader is measured. */
  scorebug?: { readings: number; measured: boolean; min_confidence: number } | null;
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
  team_confidence?: number | null;
  interceptor?: string | null;
  /** score_change only (#356): the score the broadcast's scorebug shows from this event on. */
  score?: { home: number; away: number } | null;
}
/** The side threshold the fact-checker uses (the bundle's `min_team_confidence`, from
 * ninety/agents/factcheck.py); null for a bundle that does not say, where every detected side is unsure. */
let minTeamConfidence: number | null = null;

/** An event's side, only where the fact-checker would name it (factcheck.side_known): ground truth
 * (no detection confidence), or a detection whose side was told above the threshold. Else null, and
 * no screen names a club for it. */
function sureSide(e: DetectedEvent): "home" | "away" | null {
  if (e.team !== "home" && e.team !== "away") return null;
  if (e.confidence === undefined || e.confidence === null) return e.team;
  const told = e.team_confidence;
  return minTeamConfidence !== null && typeof told === "number" && told > minTeamConfidence ? e.team : null;
}
let bundleEvents = new Map<string, DetectedEvent>(); // detected events, by id
let scorebugEvents: DetectedEvent[] = []; // the scorebug's readings (scorebug.jsonl), in time order
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
    // A bundle that does not name both clubs is not given the demo's: neutral sides, said so.
    // (teamNames hands back DEFAULT_TEAMS itself only when it falls back.)
    const named = teamNames(m.teams);
    const confirmed = named !== DEFAULT_TEAMS;
    Object.assign(teams, confirmed ? named : { home: "Home", away: "Away" });
    $("teams-note").hidden = confirmed;
    setSidesKnown(m.sides_known);  // a tracked player on an unsure side is "a player", not a club
    minTeamConfidence = typeof m.min_team_confidence === "number" ? m.min_team_confidence : null;
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
      // The scorebug's own readings (vision's, from the broadcast's graphic: ninety/vision/
      // scorebug.py), when the bundle carries them: a start reading and each change of score.
      // One gate with the Companion (ninety/intel/scoring.py, SCOREBUG_MEASURED, which the bundle
      // carries): nothing from the scorebug until its reader is measured; then only readings at or
      // above the fact-checker's confidence, and never one that takes a goal away (a misread).
      scorebugEvents = [];
      const gate = m.scorebug;
      const sb = gate?.measured ? await fetch(new URL("scorebug.jsonl", base)).catch(() => null) : null;
      if (gate && sb?.ok) {
        let last = { home: 0, away: 0 };
        for (const line of (await sb.text()).split("\n")) {
          if (!line.trim()) continue;
          const e = JSON.parse(line) as DetectedEvent;
          if ((e.type !== "score_read" && e.type !== "score_change") || !e.score) continue;
          if ((e.confidence ?? 1) < gate.min_confidence) continue;
          if (e.score.home < last.home || e.score.away < last.away) continue;
          last = e.score;
          scorebugEvents.push(e);
        }
      }
    }
    if (radar) bundleRadar = { data: radar, fps: m.fps, segmentOf: cuts.segmentOf };
    state.match = match as MatchData | null;
    // The team sheet: names, shirts and positions the line-up tool is confident of (never a guess).
    type Rows = { lineup?: Row[]; lineup_tactical?: Row[]; identity?: { label?: string; note?: string } } | null;
    type Row = SheetEntry & { id: string; confident?: boolean };
    for (const [sheet, rows] of [[teamSheet, (match as Rows)?.lineup], [tacticalSheet, (match as Rows)?.lineup_tactical]] as const) {
      for (const k of Object.keys(sheet)) delete sheet[k];
      for (const e of rows ?? []) if (e.confident === true) sheet[e.id] = { name: e.name, number: e.number, position: e.position };
    }
    const id = (match as Rows)?.identity;
    identity = id?.label ? { label: id.label, note: id.note } : null;
    $("match-card").hidden = !state.match;
    renderChips(); // the Ask grid's player questions come from the match's numbers
  } catch {
    // The minimap feed still draws the radar; only the cuts and the match are missing.
  }
}

/** The two clubs' colours (DESIGN.md: London team-a, Lisbon team-b; another club takes the one
 * left), on the page's variables and on every pitch drawing. Colour follows the club, not the side. */
function clubColours() {
  const root = document.documentElement;
  const own = (club: string) => (club === "London" ? "a" : club === "Lisbon" ? "b" : null);
  let h = own(teams.home);
  let a = own(teams.away);
  if (!h) h = a === "a" ? "b" : "a";
  if (!a || a === h) a = h === "a" ? "b" : "a";
  root.style.setProperty("--home", `var(--team-${h})`);
  root.style.setProperty("--away", `var(--team-${a})`);
  root.style.setProperty("--crest-home", `var(--crest-${h})`);
  root.style.setProperty("--crest-away", `var(--crest-${a})`);
  root.style.setProperty("--field-home", `var(--field-${h})`);
  root.style.setProperty("--field-away", `var(--field-${a})`);
  const css = getComputedStyle(root);
  const read = (name: string) => css.getPropertyValue(name).trim();
  const palette = {
    home: read(`--team-${h}`),
    away: read(`--team-${a}`),
    grass: read("--pitch"),
    stripe: read("--pitch-stripe"),
    line: read("--pitch-line"),
    lineWidth: 1,
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
    for (const el of document.querySelectorAll(`.crest.${side}`)) el.innerHTML = crestSvg(teams[side], side);
    for (const el of document.querySelectorAll(`.${side}-letter`)) el.textContent = teams[side].charAt(0);
    $(`goals-${side}`).setAttribute("aria-label", `${teams[side]} goals`);
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
  syncPlayersTab();
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
  // From tracking, a player can come back under a new track after an occlusion, so the line-up is
  // who is on the pitch now (at most eleven a side), not every track the clip ever had.
  if (state.radarFrom === "bundle" && state.radar) {
    const now = state.radar.at(viewTime(), false);
    const ids = now?.players.map((p) => p.id) ?? [];
    return ids.length ? ids : state.radar.ids().map((p) => p.id);
  }
  return state.minimap?.roster ?? [];
}

/** Each player's average position over the footage so far, in pitch metres: from the bundle's
 * tracked frames, else the minimap feed. Only what was tracked; a player never seen has none. */
function averagePositions(): Map<string, [number, number]> {
  const sum = new Map<string, [number, number, number]>();
  const add = (id: string, x: number, y: number) => {
    const s = sum.get(id) ?? [0, 0, 0];
    sum.set(id, [s[0] + x, s[1] + y, s[2] + 1]);
  };
  const now = viewTime();
  if (bundleRadar) for (const f of bundleRadar.data.frames) { if (f.t <= now) for (const p of f.players) add(p.id, p.x, p.y); }
  else if (state.minimap) for (const f of state.minimap.frames) { if (f.t <= now) for (const [id, x, y] of f.players) add(id, x, y); }
  return new Map([...sum].map(([id, [x, y, n]]) => [id, [x / n, y / n]]));
}

/** A club's crest, as inline SVG: the two demo clubs' are Kian's chosen crests (src/crests,
 * README); any other club a plain shield in its colour with its initial. */
function crestSvg(club: string, side: "home" | "away"): string {
  const own = crestOf(club);
  if (own) return own;
  return `<svg viewBox="0 0 54 62"><path d="M27 2 50 9v22c0 14-10 24-23 29C14 55 4 45 4 31V9z" style="fill: var(--crest-${side})" stroke="#fff" stroke-width="2.5"/><text x="27" y="38" text-anchor="middle" font-size="22" font-weight="700" fill="#fff">${club.charAt(0)}</text></svg>`;
}

/** A name as said mid-sentence: "a player", not "A player" ("Heat map of a player"). */
const mid = (name: string) => name.replace(/^A player\b/, "a player");

/** A player as a list tells him apart: his name, else where he has mostly played ("Left defender"),
 * or on a side not told surely, where on the screen ("A player, left of the pitch"); never the
 * tracker's number, and never "London player" twice in one list. */
function distinctName(id: string): string {
  if (!unnamedTrack(id)) return playerName(id);
  const at = averagePositions().get(id);
  if (!at) return playerName(id);
  if (!sideUnsure(id)) return roleWords(team(id), at[0], at[1]);
  const across = at[0] < 105 / 3 ? "left" : at[0] > (2 * 105) / 3 ? "right" : "middle";
  return `A player, ${across} of the pitch`;
}

/** A player the line-up cannot name, by where he has mostly played ("Left defender"). */
function roleWords(side: "home" | "away", x: number, y: number): string {
  const [flank, depth] = spot(side, x, y).split(" · ");
  return `${flank} ${depth === "defence" ? "defender" : depth === "midfield" ? "midfielder" : "forward"}`;
}

/** Where a player has mostly been, in two words a line-up uses ("Left · defence"). */
function spot(side: "home" | "away", x: number, y: number): string {
  const z = zoneFor(side, x, y); // "defensive third, on the left"
  const depth = z.startsWith("defensive") ? "defence" : z.startsWith("middle") ? "midfield" : "attack";
  const flank = z.includes("on the left") ? "Left" : z.includes("on the right") ? "Right" : "Centre";
  return `${flank} · ${depth}`;
}

const POSITION_WORDS: Record<string, string> = {
  GK: "Goalkeeper", RB: "Right back", CB: "Centre back", LB: "Left back", RWB: "Right wing-back", LWB: "Left wing-back",
  DM: "Defensive midfielder", CM: "Centre midfielder", AM: "Attacking midfielder", RM: "Right midfielder", LM: "Left midfielder",
  RW: "Right winger", LW: "Left winger", ST: "Striker", CF: "Centre forward",
};

function renderRoster(roster: string[]) {
  const avg = averagePositions();
  const button = (id: string) => {
    const b = document.createElement("button");
    b.type = "button";
    b.className = `who ${team(id)}`;
    b.dataset.player = id;
    // A tracked player without a team-sheet name has no shirt we know: no number, and his label is
    // where he plays ("Left midfielder") until the line-up names him.
    const at = avg.get(id);
    const sheet = teamSheet[id];
    const unnamed = unnamedTrack(id);
    const num = document.createElement("span");
    num.className = "num";
    num.textContent = sheet?.number !== undefined ? String(sheet.number) : unnamed ? "" : shirt(id);
    const name = document.createElement("span");
    name.className = "name";
    // A sheet player with a shirt but no name is his position in words ("Goalkeeper"), never
    // "London 1" beside a "1" already in the number column.
    const roleOnly = !!sheet && !sheet.name && !!sheet.position;
    name.textContent = roleOnly ? POSITION_WORDS[sheet!.position!] ?? sheet!.position! : unnamed && at ? roleWords(team(id), at[0], at[1]) : playerName(id);
    // Apple Sports' line-up: the position after the name, quiet ("GK"); from the team sheet only.
    const where = document.createElement("span");
    where.className = sheet?.position ? "where pos" : "where";
    where.textContent = roleOnly ? "" : sheet?.position ?? (at && !unnamed ? spot(team(id), at[0], at[1]) : "");
    b.append(num, name, where);
    b.setAttribute("aria-label", name.textContent ?? playerName(id)); // its name contains what it shows
    if (at) {
      where.id = `where-${id}`;
      b.setAttribute("aria-describedby", where.id); // "Left · defence", read after the name
    }
    b.setAttribute("aria-pressed", "false");
    b.addEventListener("click", () => select(id));
    return b;
  };
  // The team sheet, when the bundle carries one (match.json `sheets`, names-by-role): each club's
  // eleven as the line-up, never a tracked fragment. Without one, only players with a real shirt
  // (the simulator's); a tracked player is never listed as a player (demo audit, Oct 25).
  const sheets = (state.match as { sheets?: Record<"home" | "away", SheetPlayer[]> } | null)?.sheets;
  if (sheets?.home?.length || sheets?.away?.length) {
    renderSheets(sheets);
    return;
  }
  roster = roster.filter((id) => !isTrack(id));
  $("roster-box").hidden = roster.length === 0;
  syncPlayersTab();
  // One card per club, home first (Apple Sports and FotMob line-ups): crest and full name, the
  // club's players at their average positions on a small pitch, then #, name and where he plays.
  $("roster").replaceChildren(
    ...(["home", "away"] as const).map((side) => {
      const ids = roster.filter((id) => team(id) === side).sort((a, b) => Number(shirt(a)) - Number(shirt(b)));
      const card = document.createElement("section");
      card.className = "card roster-card";
      const head = document.createElement("h3");
      head.className = "card-title roster-team";
      head.innerHTML = `<span class="crest" aria-hidden="true">${crestSvg(teams[side], side)}</span>`;
      head.append(fullName(teams[side]));
      // The small pitch: x 0..105 left to right, y 0..68 bottom to top, as the radar draws it.
      const svgNS = "http://www.w3.org/2000/svg";
      const pitch = document.createElementNS(svgNS, "svg");
      pitch.setAttribute("viewBox", "-2 -2 109 72");
      pitch.setAttribute("class", "lineup-pitch");
      pitch.setAttribute("aria-hidden", "true");
      pitch.innerHTML =
        '<rect x="0" y="0" width="105" height="68" rx="2" class="turf"/><rect x="0" y="0" width="105" height="68" class="line"/>' +
        '<line x1="52.5" y1="0" x2="52.5" y2="68" class="line"/><circle cx="52.5" cy="34" r="9.15" class="line"/>' +
        '<rect x="0" y="13.84" width="16.5" height="40.32" class="line"/><rect x="88.5" y="13.84" width="16.5" height="40.32" class="line"/>';
      for (const id of ids) {
        const at = avg.get(id);
        if (!at) continue;
        const g = document.createElementNS(svgNS, "g");
        g.setAttribute("transform", `translate(${at[0].toFixed(1)} ${(68 - at[1]).toFixed(1)})`);
        g.innerHTML = `<circle r="3.6" class="shirt ${side}"/><text y="1.3" text-anchor="middle" class="shirt-no"></text>`;
        g.querySelector("text")!.textContent = teamSheet[id]?.number !== undefined ? String(teamSheet[id].number) : unnamedTrack(id) ? "" : shirt(id);
        pitch.append(g);
      }
      const cols = document.createElement("p");
      cols.className = "roster-cols";
      cols.setAttribute("aria-hidden", "true");
      const anySheet = ids.some((id) => teamSheet[id]?.position);
      const anyWhere = ids.some((id) => avg.has(id) && !(unnamedTrack(id)));
      cols.innerHTML = anySheet ? "<span>#</span><span>Name</span><span></span>" : anyWhere ? "<span>#</span><span>Name</span><span>Mostly</span>" : "<span>#</span><span>Player</span><span></span>";
      const row = document.createElement("div");
      row.className = "roster-row";
      row.append(...ids.map(button));
      card.append(head, pitch, cols, row);
      return card;
    }),
  );
}

/** A team-sheet player (match.json `sheets`): pre-match facts, no track id. */
interface SheetPlayer {
  number: number;
  name: string;
  position: string;
  line: "goalkeeper" | "defender" | "midfielder" | "forward";
}
/** Where a line stands on the line-up pitch, for a club attacking to the right (x, 0..105). */
const LINE_X: Record<SheetPlayer["line"], number> = { goalkeeper: 6, defender: 26, midfielder: 52, forward: 78 };

/** The line-ups from the team sheet: per club its crest and name, its eleven on a small pitch by
 * line (the sheet lists each line right to left), then #, name and position. Pre-match facts, so no
 * tracked number is attached to anyone unless the line-up names the track (none on the demo). */
function renderSheets(sheets: Record<"home" | "away", SheetPlayer[]>) {
  $("roster-box").hidden = false;
  syncPlayersTab();
  const svgNS = "http://www.w3.org/2000/svg";
  $("roster").replaceChildren(
    ...(["home", "away"] as const).map((side) => {
      const xi = sheets[side] ?? [];
      const card = document.createElement("section");
      card.className = "card roster-card";
      const head = document.createElement("h3");
      head.className = "card-title roster-team";
      head.innerHTML = `<span class="crest" aria-hidden="true">${crestSvg(teams[side], side)}</span>`;
      head.append(fullName(teams[side]));
      const pitch = document.createElementNS(svgNS, "svg");
      pitch.setAttribute("viewBox", "-2 -2 109 72");
      pitch.setAttribute("class", "lineup-pitch");
      pitch.setAttribute("aria-hidden", "true");
      pitch.innerHTML =
        '<rect x="0" y="0" width="105" height="68" rx="2" class="turf"/><rect x="0" y="0" width="105" height="68" class="line"/>' +
        '<line x1="52.5" y1="0" x2="52.5" y2="68" class="line"/><circle cx="52.5" cy="34" r="9.15" class="line"/>' +
        '<rect x="0" y="13.84" width="16.5" height="40.32" class="line"/><rect x="88.5" y="13.84" width="16.5" height="40.32" class="line"/>';
      for (const line of Object.keys(LINE_X) as SheetPlayer["line"][]) {
        const men = xi.filter((p) => p.line === line);
        men.forEach((p, k) => {
          // Facing the goal it attacks (to the right), a team's right is the bottom of the pitch.
          const y = (68 * (k + 1)) / (men.length + 1);
          const g = document.createElementNS(svgNS, "g");
          g.setAttribute("transform", `translate(${LINE_X[line]} ${(68 - y).toFixed(1)})`);
          g.innerHTML = `<circle r="3.6" class="shirt ${side}"/><text y="1.3" text-anchor="middle" class="shirt-no"></text>`;
          g.querySelector("text")!.textContent = String(p.number);
          pitch.append(g);
        });
      }
      const cols = document.createElement("p");
      cols.className = "roster-cols";
      cols.setAttribute("aria-hidden", "true");
      cols.innerHTML = "<span>#</span><span>Name</span><span></span>";
      const rows = document.createElement("ul");
      rows.className = "roster-row sheet-rows";
      rows.setAttribute("aria-label", `${fullName(teams[side])} line-up`);
      for (const p of xi) {
        const li = document.createElement("li");
        li.className = `who sheet ${side}`;
        li.innerHTML = '<span class="num"></span><span class="name"></span><span class="where pos"></span>';
        li.querySelector(".num")!.textContent = String(p.number);
        li.querySelector(".name")!.textContent = p.name;
        li.querySelector(".where")!.textContent = p.position.charAt(0).toUpperCase() + p.position.slice(1);
        rows.append(li);
      }
      card.append(head, pitch, cols, rows);
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
    b.textContent = distinctName(id); // the near players apart, not "London player" twice
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
  // Never a score: the broadcast carries it (Kian, Oct 25).
  navigator.mediaSession.metadata = new MediaMetadata({ title: text, artist: `${teams.home} v ${teams.away} · ${clock(laptop.time())}`, album: "Ninety" });
}
for (const b of document.querySelectorAll<HTMLButtonElement>(".speak")) {
  b.addEventListener("click", () => {
    speaking = !speaking;
    for (const x of document.querySelectorAll(".speak")) {
      x.setAttribute("aria-pressed", String(speaking));
      x.setAttribute("aria-checked", String(speaking));
    }
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
  if (embed) return; // the big screen around it plays all sound
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
const SAMPLE = "This is the voice that will read the match to you."; // the preview line voice bundles pre-generate (#279)

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
        if (!embed) speakAloud(SAMPLE, { rate: settings.rate, voice: v.name }); // a preview: only on this tap
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
  if (onboard.isOpen && !onboard.editing) {
    onboard.close(); // a question about a player wins over the choices: they wait for next visit
    syncAsk();
  }
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
    // The ID feed's shirt and position beside the name (lesson 269); vision's numbers below as before.
    const row = tacticalSheet[id];
    const shirt = row?.name ? [row.number !== undefined ? `#${row.number}` : "", row.position ?? ""].filter(Boolean).join(" · ") : "";
    const title = shirt ? `${playerName(id)}, ${shirt}` : playerName(id);
    $("player-title").textContent = fromLaptop ? `${title} · followed from the big screen` : title;
    $("player").dataset.team = team(id);
    for (const s of ["speed", "peak", "distance"]) $(s).textContent = "–";
    // Nothing shows until the player's numbers have loaded: no dashes, no empty heat map.
    $("so-far-box").hidden = true;
    $("heat-box").hidden = true;
    renderCompareChips(id);
    cardAsked = -1;
    void refreshCard(true);
    if (fromLaptop) announce(`The big screen is following ${mid(playerName(id))}.`);
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
  $("so-far-box").hidden = false;
  $("heat-box").hidden = c.heat.cells.every((v) => v <= 0);
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
  heat.setAttribute("aria-label", `Heat map of ${mid(playerName(c.player))}: ${describeHeat(c.heat, team(c.player))}`);
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
  // Who is on the pitch now, at most eleven a side: never every track fragment the clip had.
  const side = { home: 0, away: 0 };
  const byName = new Intl.Collator(undefined, { numeric: true }); // "Lisbon player 3" before "… 10"
  const others = rosterIds()
    .filter((o) => o !== id)
    .sort((x, y) => (team(x) === team(y) ? byName.compare(playerName(x), playerName(y)) : team(x) === "home" ? -1 : 1))
    // One chip a label (UI inventory #11): unnamed players who read alike are one choice, not a dozen.
    .filter(((seen) => (o: string) => !seen.has(distinctName(o)) && !!seen.add(distinctName(o)))(new Set<string>()))
    .filter((o) => ++side[team(o)] <= 11);
  $("compare-box").hidden = others.length === 0;
  $("compare-rows").hidden = true;
  $("compare-chips").replaceChildren(
    ...others.map((o) => {
      const b = document.createElement("button");
      b.type = "button";
      b.className = `chip who-chip ${team(o)}`;
      b.dataset.player = o;
      b.textContent = distinctName(o);
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
  } catch {
    // No numbers for one of them yet: nothing is drawn, and that player's chip says so quietly.
    $("compare-rows").hidden = true;
    const chip = $("compare-chips").querySelector<HTMLButtonElement>(`[data-player="${b}"]`);
    chip?.setAttribute("aria-disabled", "true");
    chip?.setAttribute("aria-label", `${playerName(b)}: no numbers yet`);
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
      li.setAttribute("aria-label", `${label}: ${distinctName(a)} ${x.toFixed(places)}, ${mid(distinctName(b))} ${y.toFixed(places)}`);
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

// --- the fan's choices (fan.ts, onboarding.ts): club, mode, focus; on this device only ----------

let fan = fans.load();
const chosen = () => (fan && fan !== "skipped" ? fan : null);
let storyTouched = false; // the fan picked All or Key plays this visit: their pick stands
const onboard = mountOnboarding($("onboard"), (picked, editing) => {
  if (picked) fan = picked;
  else if (!editing) fan = "skipped"; // not now: Personalise in the settings sheet reopens it
  if (picked || !editing) fans.save(fan!);
  applyFan(true);
});

/** What the choices shape: Ask's questions and which come first, the Story feed's starting filter,
 * and the settings row. */
function applyFan(rerender = false) {
  const f = chosen();
  $("fan-value").textContent = f ? fans.summary(f) : "";
  // The persona (Kian, Oct 26: "make personalisation more visible"): the fan's club, mode and focus
  // lay Live out (style.css, body[data-mode], [data-focus], [data-us]); no number changes.
  const us = usSide();
  document.body.dataset.mode = f?.mode ?? "";
  document.body.dataset.focus = f?.focus ?? "";
  document.body.dataset.us = us ?? "";
  document.body.dataset.club = f?.club ?? "";
  for (const [id, v] of [["persona-mode", f?.mode], ["persona-club", f?.club]] as const)
    ($(id) as HTMLElement & { value: string }).value = v ?? "";
  if (rerender) { statsKey = ""; spottedKey = ""; squadKey = ""; if (state.match) showMatch(viewTime()); renderJustNow(); renderSquad(); }
  $("ask-start").dataset.focus = f?.focus ?? "";
  if (f && !storyTouched) {
    const mode = fans.storyMode(f);
    ($("story-mode") as HTMLElement & { value: string }).value = mode;
    $("insights").dataset.mode = mode;
    if (rerender) renderInsights();
  }
  syncAsk();
  if (rerender) renderChips();
}

/** The side of this match the fan supports, when it is one of its two clubs. */
function usSide(): "home" | "away" | null {
  const f = chosen();
  if (!f) return null;
  const us = short(CLUBS[f.club]);
  return teams.home === us ? "home" : teams.away === us ? "away" : null;
}

/** The one-tap persona switch in the ••• sheet: the mode and the club, kept as #362's choices. */
function setPersona(change: Partial<fans.Fan>) {
  const base: fans.Fan = chosen() ?? { club: "LON", mode: "casual", focus: "moments" };
  fan = { ...base, ...change };
  fans.save(fan);
  storyTouched = false;
  applyFan(true);
}
// The demo passcode field (••• sheet): blank removes it. Its value is never echoed anywhere.
const passField = $<HTMLInputElement>("passcode");
passField.value = passcode ?? "";
passField.addEventListener("change", () => setPasscode(passField.value));

$("persona-mode").addEventListener("ionChange", (e) => {
  const v = (e as CustomEvent<{ value: string }>).detail.value;
  if ((v === "casual" || v === "analyst") && v !== chosen()?.mode) setPersona({ mode: v });
});
$("persona-club").addEventListener("ionChange", (e) => {
  const v = (e as CustomEvent<{ value: string }>).detail.value;
  if ((v === "LON" || v === "LIS") && v !== chosen()?.club) setPersona({ club: v });
});

$("fan-edit").addEventListener("click", () => {
  void settingsSheet.dismiss();
  showTab("ask");
  onboard.open(chosen(), true);
  syncAsk();
  void ($("ask-content") as HTMLElement & { scrollToTop(ms?: number): Promise<void> }).scrollToTop(0);
});

// --- questions -------------------------------------------------------------------------------

function playerQuestions(id: string): string[] {
  const n = mid(playerName(id));
  return [`How fast is ${n} running now?`, `What is ${n}'s top speed?`, `How far has ${n} run?`];
}

/** The match questions the Companion's tools answer with a picture. */
function matchQuestions(): string[] {
  const f = chosen();
  if (f) return fans.questions(f, teams); // the fan's club and focus first
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

/** A starter card's glyph: its topic's (SF Symbols' shapes, drawn here), else its kind's
 * (fan.ts, `kindOf`), so a grid of one kind still reads as six different questions. */
const KIND_GLYPHS: Record<fans.Kind, string> = {
  moments: '<path d="M12 3.5 14.5 9l6 .5-4.6 3.9 1.4 5.9L12 16.2l-5.3 3.1 1.4-5.9L3.5 9.5l6-.5z"/>',
  tactics: '<rect x="3.5" y="5" width="17" height="14" rx="2.5"/><path d="M12 5v14"/><circle cx="12" cy="12" r="2.6"/>',
  players: '<circle cx="12" cy="8" r="3.5"/><path d="M5 20c.8-3.8 3.6-6 7-6s6.2 2.2 7 6"/>',
  numbers: '<path d="M5 20V12M10 20V6M15 20v-9M20 20V9"/>',
};
const TOPIC_GLYPHS: [RegExp, string][] = [
  [/overload/i, '<circle cx="6" cy="8" r="2.5"/><circle cx="18" cy="8" r="2.5"/><circle cx="12" cy="18" r="2.5"/><circle cx="12" cy="11.5" r="1"/>'], // three round the ball
  [/lines/i, '<path d="M3.5 11h5M15.5 11h5M3.5 17h5M15.5 17h5M12 20.5V4M8.5 7.5 12 4l3.5 3.5"/>'], // a pass up through the gap in two lines
  [/options/i, '<circle cx="6" cy="12" r="2.2"/><path d="M8.2 12h12M7.9 10.8 19 5M7.9 13.2 19 19"/>'], // three passes from one man
  [/shape/i, '<path d="M5 6h.01M12 6h.01M19 6h.01M5 12h.01M12 12h.01M19 12h.01M8.5 18h.01M15.5 18h.01" stroke-width="3"/>'], // a formation
  [/ball back/i, '<path d="M19 12a7 7 0 1 1-2.1-5"/><path d="M17.5 3v4h-4"/>'], // the ball won back
  [/compact/i, '<path d="M3 12h6M21 12h-6M6.5 9.5 9 12l-2.5 2.5M17.5 9.5 15 12l2.5 2.5M12 4v16"/>'], // squeezed together
  [/missed/i, '<circle cx="12" cy="12" r="8.5"/><path d="M12 7v5l3.5 2"/>'],
  [/shots/i, '<circle cx="12" cy="12" r="8.5"/><circle cx="12" cy="12" r="4.5"/><circle cx="12" cy="12" r="1"/>'],
  [/corners/i, '<path d="M6 21V3l11 4.5L6 12"/>'],
  [/furthest|run/i, '<circle cx="4.8" cy="19.2" r="1.8"/><circle cx="19.2" cy="4.8" r="1.8"/><path d="M6.6 19.2c3.4 0 3.4-7.2 5.4-7.2s2-7.2 5.4-7.2"/>'],
  [/fastest|speed/i, '<path d="M13.5 3 6 13.5h5.5L10.5 21 18 10.5h-5.5z"/>'],
  [/linking/i, '<path d="M10 14a4 4 0 0 0 5.7 0l3-3a4 4 0 0 0-5.7-5.7l-1 1M14 10a4 4 0 0 0-5.7 0l-3 3a4 4 0 0 0 5.7 5.7l1-1"/>'],
  [/more of the ball/i, '<circle cx="12" cy="12" r="8.5"/><path d="M12 3.5V12l6 6"/>'],
  [/halves/i, '<rect x="3.5" y="5" width="17" height="14" rx="2.5"/><path d="M12 5v14M7 12h.01M17 12h.01" stroke-width="2"/>'],
];
const glyphFor = (q: string) => TOPIC_GLYPHS.find(([re]) => re.test(q))?.[1] ?? KIND_GLYPHS[fans.kindOf(q)];
function card(q: string) {
  const b = chip(q, null);
  b.classList.add("q-card");
  b.textContent = "";
  const text = document.createElement("span");
  text.textContent = q;
  b.insertAdjacentHTML("afterbegin", `<svg class="q-glyph" viewBox="0 0 24 24" aria-hidden="true">${glyphFor(q)}</svg>`);
  b.append(text);
  return b;
}

/** Questions this fan has already asked: never suggested back to them. */
const asked = new Set<string>();

/** An empty conversation shows the starter grid instead of the composer's chips; after the first
 * answer, the answers under "Recent" and the chips (or an answer's follow-ups) above the composer. */
function syncAsk() {
  const any = $("answers").children.length > 0;
  if (any && onboard.isOpen && !onboard.editing) onboard.close(); // they asked instead: next visit
  // The composer waits for the choices (Kian, Oct 25), then rises in once they are made or skipped.
  const panel = $("panel-ask");
  if (panel.classList.contains("onboarding") && !onboard.isOpen) panel.classList.add("composer-in");
  panel.classList.toggle("onboarding", onboard.isOpen);
  $("ask-start").hidden = any || onboard.isOpen;
  $("recent-title").hidden = !any;
  if (!any) $("ask-chips").hidden = true;
  else if ($("ask-chips").dataset.started !== "1") {
    $("ask-chips").dataset.started = "1";
    $("ask-chips").hidden = false;
  }
}
new MutationObserver(syncAsk).observe($("answers"), { childList: true });
$("panel-ask").addEventListener("animationend", () => $("panel-ask").classList.remove("composer-in"));
if (fan === null && !embed) onboard.open(null, false); // the first visit opens on the three choices
applyFan();

function renderChips() {
  const own = state.selected ? playerQuestions(state.selected).map((q) => chip(q, "ask")) : [];
  $("chips").replaceChildren(...own);
  const all = [...(state.selected ? playerQuestions(state.selected) : []), ...matchQuestions()].filter((q) => !asked.has(q));
  $("ask-chips").replaceChildren(...all.slice(0, 3).map((q) => chip(q, null))); // three, as a message app suggests
  // An empty conversation opens on a grid of questions (never a blank page), then the answers.
  $("ask-grid").replaceChildren(...all.slice(0, 6).map(card));
  // And about the players most in the game (the Scout's per-player numbers), when there are any.
  const sq = state.match as (MatchData & Squads & { insight_stats?: StatsBlock }) | null;
  const ps = (sq?.insight_stats?.player_stats ?? sq?.player_stats ?? []).filter((p) => typeof p.involvements === "number");
  const most = [...ps].sort((a, b) => b.involvements! - a.involvements!).slice(0, 4);
  const theirs = most.map((p, i) => playerQuestions(p.id)[i % 3]).filter((q) => !asked.has(q));
  $("ask-players").replaceChildren(...theirs.map(card));
  $("ask-players").hidden = $("ask-players-title").hidden = theirs.length === 0;
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
  // By what the answer rests on: the scorebug's reading, a name from the ID feed, or tracking.
  if (a.metric === "scorebug" || a.evidence.some((e) => e.startsWith("scorebug:"))) return "Read from the broadcast's scorebug";
  if (identity && feedNamed(a.headline)) return identity.label;
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

/** The API names players by id (a7); fans read "Lisbon 7", or the name the answer carries. Only
 * the names change, never a number. */
/** An answer's or a card's text, its player ids said as the payload names them (tactical ids: never
 * the team sheet's line-up, which names broadcast tracks; names-by-role, Oct 25). */
function named(text: string, names?: Record<string, string>): string {
  // Answers and cards name TACTICAL tracks: the ID feed's rows for them, under what a payload says.
  const feed: Record<string, string> = {};
  for (const [id, e] of Object.entries(tacticalSheet)) if (e.name) feed[id] = e.name;
  return nameIds(text, teams, { ...feed, ...names });
}

/** The player-ID feed (match.json `identity`): where names come from, never vision (lesson 269). */
let identity: { label: string; note?: string } | null = null;
/** Whether any of these words carry a name the ID feed gave. */
function feedNamed(...texts: (string | null | undefined)[]): boolean {
  const all = [...Object.values(teamSheet), ...Object.values(tacticalSheet)].map((e) => e.name).filter((n): n is string => !!n);
  return all.some((n) => texts.some((t) => !!t && t.includes(n)));
}

/** A detected event's text (broadcast track ids): the team sheet names a track the line-up is sure
 * of. */
function eventNamed(text: string): string {
  const sheet: Record<string, string> = {};
  for (const [id, e] of Object.entries(teamSheet)) if (e.name) sheet[id] = e.name;
  return nameIds(text, teams, sheet);
}

async function ask(text: string) {
  const q = text.trim().slice(0, MAX_QUESTION);
  if (!q) return;
  const input = $<HTMLInputElement>("question");
  const button = $<HTMLButtonElement>("ask-button");
  if (button.getAttribute("aria-disabled") === "true") return;
  asked.add(q);
  if (onboard.isOpen) onboard.close(); // a typed question wins over the choices: they wait
  renderChips();
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
    const message: AnswerMessage = await feed.ask({ session: state.code, player: state.selected, text: q, t: at }, passcode);
    answer = { ...message.answer, source: message.source ?? message.answer.source, ...(message.model_off ? { model_off: true } : {}) };
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
  if (input.value.trim() === q) {
    input.value = "";
    fitQuestion();
  }
  pending.replaceWith(renderAnswer(q, at, answer, failed));
  // The new question at the top, whole, with its answer under it (Messages scrolls a new thread
  // turn into view; it never leaves the question cut under the bar).
  requestAnimationFrame(() => {
    const turn = $("answers").lastElementChild as HTMLElement | null;
    const content = $("ask-content") as HTMLElement & { scrollToPoint(x: number, y: number, ms?: number): Promise<void> };
    if (turn) void content.scrollToPoint(0, Math.max(0, turn.offsetTop - 8), reduceMotion.matches ? 0 : 300);
  });
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
    // The headline answers the question (Kian): code's own headline when the answer carries one,
    // else the picture's, else the figure. Player ids in it are named like the sentence.
    const line = a.headline
      ? named(a.headline, a.names)
      : v && drawable(v) ? title(v) : a.value !== null ? `${a.value} ${a.unit ?? ""}`.trim() : "";
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
    // One set of suggestions at a time: an answer's follow-ups replace the starter chips.
    $("ask-chips").hidden = !!a.follow_ups?.length;
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
    // A score's number never shows (Kian, Oct 25: the broadcast carries it; #350 sends none).
    ["What", `${who ? `${playerName(who, a.names)}'s ` : ""}${what}${a.value !== null && !/score|goals?$/.test(a.metric ?? "") ? `: ${a.value} ${a.unit ?? ""}`.trimEnd() : ""}`],
  ];
  if (a.t_from !== null && a.t_to !== null) rows.push(["Over", a.t_from === a.t_to ? `${clock(a.t_from)} of the match` : `${clock(a.t_from)} to ${clock(a.t_to)} of the match`]);

  for (const [k, v] of rows) {
    const dt = document.createElement("dt");
    dt.textContent = k;
    const dd = document.createElement("dd");
    dd.textContent = v;
    panel.append(dt, dd);
  }
  if (!a.evidence.length) return [panel]; // nothing to cite: no empty "Facts cited" heading
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
// The composer grows with the question, up to five lines, then scrolls; Return sends, as in
// Messages (Shift-Return for a new line).
function fitQuestion() {
  const q = $<HTMLTextAreaElement>("question");
  q.style.height = "auto";
  q.style.height = `${Math.min(q.scrollHeight, 22 * 5 + 18)}px`;
}
$("question").addEventListener("input", fitQuestion);
$("question").addEventListener("keydown", (e) => {
  if (e.key === "Enter" && !e.shiftKey && !e.isComposing) {
    e.preventDefault();
    $<HTMLFormElement>("ask-form").requestSubmit();
  }
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
  const list = document.createElement("ol");
  list.className = "stepper";
  if (bundle) {
    const canvas = document.createElement("canvas");
    canvas.className = "seen";
    canvas.setAttribute("role", "img");
    canvas.setAttribute("aria-label", `The broadcast picture at ${clock(h.t)}.`);
    // The frame the claim cites, with what the detector boxed; its words are for screen readers only.
    const cameras = step("What the cameras saw", canvas);
    steps.push(cameras);
    void drawSeen(canvas, h.t).then((found) => {
      if (!found.length) {
        cameras.remove(); // a frame with nothing found is no evidence: the step is not shown
        count.textContent = `${list.children.length} checks · all passed`;
        return;
      }
      canvas.setAttribute("aria-label", `The broadcast picture at ${clock(h.t)}: ${found.map((d) => `${d.cls} ${Math.round(d.score * 100)} percent`).join(", ")}.`);
    });
  }
  // A name in it came from the player-ID feed (lesson 269): say so, never that vision named him.
  if (identity && feedNamed(h.why?.text, h.answer?.text, h.answer?.headline, ...Object.values(h.names ?? {})))
    steps.push(step("Who the players are", p(identity.label, "said")));
  const measured = p("Measured from player tracking", "said");
  if (h.visual && !isVar(h)) steps.push(step("What was measured", picture(h.visual, h.t, h.names), measured));
  else steps.push(step("What was measured", measured));
  const checked = h.source === "model" ? "Answered by our agents, checked by the fact-checker" : "Computed from tracking";
  const off = h.answer?.model_off ? [p("Model off", "fine model-off")] : [];
  steps.push(step("What the fact-checker did", p(checked, "said"), ...off, ...(h.answer ? evidence(h.answer) : [])));
  const count = p(`${steps.length} checks · all passed`, "count-line");
  list.replaceChildren(...steps);
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
let insightsMissing = false; // the server has no cards route or none for this clip: not asked again

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
    if (!bundleCards && insightsMissing) return; // the server has none for this clip: asked once
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
    if (e instanceof ApiError && e.status === 404) insightsMissing = true;
    $("insights-note").textContent =
      e instanceof ApiError && e.status === 404 ? "" : e instanceof GroundTruth ? e.message : `Could not load the hidden stats: ${(e as Error).message}`;
  } finally {
    insightsBusy = false;
    if (!insightsLoaded) {
      insightsLoaded = true;
      renderInsights();
    }
  }
}

/** Live's "Just now": the newest Story moment, its sentence, chip and minute. */
/** The tactics focus: the latest card of each tactical kind (overload, line break, passing options,
 * shape), newest first, as large cards above the pitch; each opens How we know. */
const TACTICAL: Record<string, string> = { overload: "Overload", line_break: "Line break", pass_options: "Passing options", team_shape: "Shape", shape: "Shape" };
function renderTacticsStrip() {
  const seen = new Set<string>();
  const latest = state.insights.filter((c) => TACTICAL[c.kind] && !seen.has(c.kind) && !!seen.add(c.kind)).slice(0, 3);
  $("tactics-strip").hidden = latest.length === 0;
  $("tactics-strip").replaceChildren(
    focusList(latest.map((c) => {
      const row = focusRow(`${TACTICAL[c.kind]} · ${c.minute}′`, named(c.headline || c.text, c.names), c.team);
      row.addEventListener("click", () => void openHow({ t: c.t, visual: c.visual, source: c.source, evidence: c.evidence, names: c.names, why: c.why ? { question: c.why.question, text: named(c.why.answer.text, c.names) } : undefined }));
      return row;
    })),
  );
}

/** One rounded group of rows, hairlines between them (Apple Sports' lists). */
function focusList(rows: HTMLElement[]): HTMLUListElement {
  const ul = document.createElement("ul");
  ul.className = "focus-list";
  ul.append(...rows.map((r) => { const li = document.createElement("li"); li.append(r); return li; }));
  return ul;
}
/** A row: a small grey label (a club's dot where its side is sure) over one line of text, a chevron. */
function focusRow(label: string, text: string, side: string | null, lead?: HTMLElement): HTMLButtonElement {
  const b = document.createElement("button");
  b.type = "button";
  b.className = "focus-row";
  const body = document.createElement("span");
  body.className = "focus-body";
  const small = document.createElement("span");
  small.className = `focus-label ${side === "home" || side === "away" ? side : ""}`;
  small.textContent = label;
  const line = document.createElement("span");
  line.className = "focus-text";
  line.textContent = text;
  body.append(small, line);
  const chev = document.createElement("span");
  chev.className = "focus-chev";
  chev.setAttribute("aria-hidden", "true");
  chev.textContent = "›";
  b.append(...(lead ? [lead] : []), body, chev);
  return b;
}
const shirtCircle = (n: number | undefined, side: string) => {
  const c = document.createElement("span");
  c.className = `shirt-dot ${side}`;
  c.setAttribute("aria-hidden", "true");
  c.textContent = n !== undefined ? String(n) : "";
  return c;
};

/** The players focus: the players most in the game (the Scout's per-player numbers), named as the
 * radar names them (the ID feed's name, shirt and position where it has a row); a tap opens his card,
 * with Compare. Never the team sheet: line-ups are the Players tab's alone (Kian, Oct 26). */
function renderPlayersStrip(ps: PlayerStats[]) {
  const most = ps.filter((p) => typeof p.involvements === "number").sort((a, b) => b.involvements! - a.involvements!).slice(0, 4);
  const cap = (s: string) => s.charAt(0).toUpperCase() + s.slice(1);
  let rows: HTMLButtonElement[] = [];
  if (most.length) {
    rows = most.map((p) => {
      const row = tacticalSheet[p.id];
      const d = distinctName(p.id); // "London player, left of the pitch": where he plays, when unnamed
      const where = row?.name ? cap(row.position ?? "") : d.includes(", ") ? d.slice(d.indexOf(", ") + 2) : "";
      const s = sideUnsure(p.id) ? "neutral" : team(p.id);
      const r = focusRow(where ? `${where} · ${Math.round(p.involvements!)} involvements` : `${Math.round(p.involvements!)} involvements`, playerName(p.id), s, shirtCircle(row?.name ? row.number : undefined, s));
      r.classList.add("player-row");
      r.addEventListener("click", () => select(p.id));
      return r;
    });
  }
  $("players-strip").hidden = rows.length === 0;
  $("players-strip").replaceChildren(...(rows.length ? [focusList(rows)] : []));
}

function renderJustNow() {
  renderTacticsStrip();
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

const cap = (t: string) => t.charAt(0).toUpperCase() + t.slice(1);

/** A detected event as a play-by-play line (Apple Sports: "Kyle Walker takes a throw-in."), from
 * its own fields only; a player the detection did not name is his club. */
function playSentence(e: DetectedEvent): string | null {
  const side = sureSide(e);
  // A tracked player nobody has named is "a London player", never the tracker's number; a pass
  // between two of them reaches "a teammate".
  const who = (id?: string | null) => (id ? cap(eventNamed(id)) : side ? teams[side] : "A player");
  const low = (t: string) => t.replace(/^A /, "a "); // named() capitalises a sentence's first word
  // "a teammate" only when both sides are vouched for: the id letters are the tracker's votes.
  const mates = (id: string) => !!e.player && isTrack(id) && isTrack(e.player) && !sideUnsure(id) && !sideUnsure(e.player);
  const to = (id: string) => (mates(id) && team(id) === team(e.player!) ? "a teammate" : low(eventNamed(id)));
  switch (e.type) {
    case "pass":
      if (e.outcome === "success") return e.receiver ? `${who(e.player)} passes to ${to(e.receiver)}.` : `${who(e.player)} completes a pass.`;
      return e.interceptor ? `${who(e.player)}'s pass is cut out by ${low(eventNamed(e.interceptor))}.` : `${who(e.player)}'s pass doesn't find a teammate.`;
    case "shot":
      // A shot vision could not tell the end of (outcome null, #368: saves are not read from video)
      // says only that it was taken, never "wide".
      return e.outcome === "goal" ? `${who(e.player)} scores.` : e.outcome === "on_target" ? `Shot saved, from ${low(who(e.player))}.` : e.outcome === "blocked" ? `${who(e.player)}'s shot is blocked.` : e.outcome === "off_target" ? `${who(e.player)} shoots wide.` : `${who(e.player)} takes a shot.`;
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
let goalsShown = -1;

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

/** Live's Key moments: the newest goals and Scout moments, a minute and a line each (Apple Sports'
 * key plays); "See all" opens Story. Hidden until there is one. */
function renderKeyMoments(plays: DetectedEvent[]) {
  type Moment = { t: number; team: "home" | "away" | null; text: string; goal: boolean };
  // The match's goals (reconciled with the scorebug), then any detected goal none of them tells.
  const now = viewTime();
  const goals: Moment[] = [
    ...goalsUpTo(now).map((g) => { const side = goalSide(g); return { t: g.t, team: side, text: side ? `${teams[side]} goal` : "Goal", goal: true }; }),
    ...plays
      .filter((e) => e.type === "shot" && e.outcome === "goal" && !toldByGoal(e, now))
      .map((e) => ({ t: e.t, team: sureSide(e), text: playSentence(e)!, goal: true })), // a club's colour only on a side told surely
  ];
  const cards: Moment[] = state.insights.map((c) => ({ t: c.t, team: c.team, text: named(c.headline || c.text, c.names), goal: false }));
  const moments = [...goals, ...cards].sort((a, b) => b.t - a.t).slice(0, 4);
  $("key-moments").hidden = moments.length === 0;
  $("key-rows").replaceChildren(
    ...moments.map((m) => {
      const li = document.createElement("li");
      li.className = `moment-row ${m.team ?? "neutral"}${m.goal ? " goal" : ""}`;
      const min = document.createElement("span");
      min.className = "min";
      min.textContent = `${momentum.minuteOf(m.t)}′`;
      const text = document.createElement("span");
      text.className = "text";
      text.textContent = m.text;
      li.append(min, text);
      return li;
    }),
  );
}

function renderInsights() {
  renderJustNow();
  // Apple Sports' play-by-play: one card per play, newest first, the time under the sentence, the
  // club's rule on its own side. All plays adds every detected play; Key plays keeps the Scout's
  // moments (with their diagrams) and goals.
  const list = $("insights");
  const now = viewTime();
  const plays = playsUpTo(now);
  playsShown = plays.length;
  goalsShown = goalsUpTo(now).length;
  renderKeyMoments(plays);
  const key = list.dataset.mode === "key";
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
  // Goals first in weight (demo audit 2, row 8): each of the match's goals as a larger card with its
  // club's crest, "Goal", the club and minute, and the scorer where the team sheet names him.
  for (const g of goalsUpTo(now)) {
    const side = goalSide(g);
    const who = bundleEvents.get(g.event)?.player;
    const scorer = who && !unnamedTrack(who, undefined, true) ? eventName(who) : "";
    const { li, body } = storyItem(side, scorer ? `${goalLine(g)} · ${scorer}` : goalLine(g), g.t);
    li.classList.add("goal-card");
    if (side && side === usSide()) li.classList.add("ours");
    li.dataset.goal = g.event;
    const head = document.createElement("h3");
    head.className = "goal-head";
    head.innerHTML = side ? `<span class="crest" aria-hidden="true">${crestSvg(teams[side], side)}</span>` : "";
    head.append("Goal");
    body.prepend(head);
    rows.push({ t: g.t, el: li });
  }
  for (const e of plays) {
    const goal = e.type === "shot" && e.outcome === "goal";
    if (goal && toldByGoal(e, now)) continue; // its goal's card says it
    if (key && !goal) continue;
    const { li } = storyItem(sureSide(e), playSentence(e)!, e.t);
    li.classList.add("play");
    li.dataset.event = e.id;
    if (goal) li.classList.add("goal"); // no running score: the broadcast carries it
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
  // In Key plays the fan's club's moments come first (newest first within each), then the rest.
  const us = key ? usSide() : null;
  const mine = (r: Row) => (us && r.el.classList.contains(us) ? 1 : 0);
  list.replaceChildren(...rows.sort((a, b) => mine(b) - mine(a) || b.t - a.t).map((r) => r.el));
}

$("story-mode").addEventListener("ionChange", (e) => {
  storyTouched = true;
  $("insights").dataset.mode = (e as CustomEvent<{ value: string }>).detail.value;
  renderInsights();
  requestAnimationFrame(redrawPictures);
});

// --- team stats and the score, from the bundle's match.json (match mode) -----------------------

/** Each club's scorers under its crest, as Apple Sports writes them ("⚽ Okafor 12′, 59′"): goals
 * vision spotted, never a score (Kian, Oct 25: vision finds 2 of the demo's 3 goals, so a count
 * would contradict the broadcast's scorebug). The scorer's name when the detection names him, else
 * "London goal"; a goal on a side not told surely sits under the clock as "Goal". Each line opens
 * How we know, with the detection's confidence; none is printed on the band. */
/** How near a scorebug change must be to a goal to give it a side (design: the graphic updates just
 * after the ball goes in; on the demo match each goal event is 0.2 to 1.6 s before its change, and
 * changes are minutes apart, so 3 s cannot pick the wrong one). */
const SCOREBUG_MATCH_S = 3;
let spottedKey = "";
function renderSpotted(m: MatchData, t: number) {
  const goals = m.goals.filter((g) => g.t <= t);
  // Redrawn when a goal, a club's name or a scorer's name (the team sheet loads later) changes.
  const names = goals.map((g) => { const p = bundleEvents.get(g.event)?.player; return p ? playerName(p) : ""; });
  const key = `${goals.map((g) => g.event).join()}|${teams.home}|${teams.away}|${names.join()}|${scorebugEvents.length}|${scorebugGoals(t)?.length ?? -1}`;
  if (key === spottedKey) return;
  spottedKey = key;
  const minute = (g: { t: number }) => `${momentum.minuteOf(g.t)}′`;
  const sideOf = goalSide;
  // With the scorebug's readings, every goal it counted, under its club (Coordinator, Oct 26: the
  // score and the lines agree): each rise in a side's count is a goal at that minute; a scorer only
  // where a goal vision spotted beside it is named by the team sheet.
  const bug = scorebugGoals(t);
  if (bug) {
    for (const side of ["home", "away"] as const) {
      const mine = bug.filter((g) => g.side === side);
      // Each goal by its scorer's surname where the player-ID feed names him (#389, through the
      // line-up of broadcast tracks), else by the club ("Rondell 38′", "London 22′ 68′").
      // One spotted goal a scorebug goal, the nearest within SCOREBUG_MATCH_S, each used once.
      const used = new Set<(typeof goals)[number]>();
      const nearOf = new Map(mine.map((g) => {
        const near = goals
          .filter((v) => !used.has(v) && sideOf(v) === side && Math.abs(v.t - g.t) <= SCOREBUG_MATCH_S)
          .sort((a, b) => Math.abs(a.t - g.t) - Math.abs(b.t - g.t))[0];
        if (near) used.add(near);
        return [g, near] as const;
      }));
      const label = (g: (typeof mine)[number]) => {
        const near = nearOf.get(g);
        const who = near ? bundleEvents.get(near.event)?.player : undefined;
        const name = who ? teamSheet[who]?.name : undefined; // the line-up's (the ID feed's), never a label
        return name ? name.split(" ").slice(-1)[0] : teams[side];
      };
      const lines = new Map<string, typeof mine>();
      for (const g of mine) lines.set(label(g), [...(lines.get(label(g)) ?? []), g]);
      $(`goals-${side}`).replaceChildren(
        ...[...lines].map(([who, gs]) => {
          const li = document.createElement("li");
          const b = document.createElement("button");
          b.type = "button";
          b.className = "side-goal";
          b.textContent = `${who} ${gs.map(minute).join(" ")}`;
          const named = who !== teams[side];
          b.addEventListener("click", () => {
            void openHow({ t: gs[gs.length - 1].t, visual: null, source: "code", evidence: [],
              why: { question: "", text: `${teams[side]}'s goals, read from the broadcast's score graphic: ${gs.map(minute).join(", ")}.${named && identity ? ` The scorer's name is from the ${identity.label}.` : ""}` } });
          });
          li.append(b);
          return li;
        }),
      );
    }
    $("goals-unsure").replaceChildren();
    return;
  }
  for (const side of ["home", "away", null] as const) {
    const mine = goals.filter((g) => sideOf(g) === side);
    // One line per scorer, his goals' minutes in order.
    const lines = new Map<string, typeof mine>();
    for (const g of mine) {
      const who = bundleEvents.get(g.event)?.player;
      // The scorer's name only where the team sheet names him; else his club's goal (never a track id).
      const label = who && !unnamedTrack(who, undefined, true) ? eventName(who) : side ? `${teams[side]} goal` : "Goal";
      lines.set(label, [...(lines.get(label) ?? []), g]);
    }
    $(side ? `goals-${side}` : "goals-unsure").replaceChildren(
      ...[...lines].map(([label, gs]) => {
        const li = document.createElement("li");
        const b = document.createElement("button");
        b.type = "button";
        b.className = "side-goal";
        b.textContent = `${label} ${gs.map(minute).join(", ")}`;
        const sure = gs.map((g) => bundleEvents.get(g.event)?.confidence).filter((c): c is number => typeof c === "number");
        b.addEventListener("click", () => {
          const said = gs.map((g, k) => `${minute(g)}${typeof sure[k] === "number" ? `, ${Math.round(100 * sure[k])}% sure` : ""}`).join("; ");
          void openHow({ t: gs[gs.length - 1].t, visual: null, source: "code", evidence: gs.map((g) => g.event),
            why: { question: "", text: `Vision spotted ${gs.length === 1 ? "this goal" : "these goals"}: ${said}. The score is the broadcast's.` } });
        });
        li.append(b);
        return li;
      }),
    );
  }
}

/** Each goal the scorebug counted up to t: a rise in a side's count between readings (one goal a rise
 * of one); null when the bundle carries no readings that pass the gate. */
function scorebugGoals(t: number): { t: number; side: "home" | "away" }[] | null {
  const reads = scorebugEvents.filter((e) => (e.type === "score_change" || e.type === "score_read") && e.score && e.t <= t + 1e-6);
  if (!reads.length) return null;
  const out: { t: number; side: "home" | "away" }[] = [];
  let prev = { home: 0, away: 0 };
  for (const e of [...reads].sort((a, b) => a.t - b.t)) {
    const now = e.score!;
    for (const side of ["home", "away"] as const) for (let k = prev[side]; k < now[side]; k++) if (e.type === "score_change") out.push({ t: e.t, side });
    prev = { home: Math.max(prev.home, now.home), away: Math.max(prev.away, now.away) };
  }
  return out;
}

/** A goal's club: its own side, or else the side whose count the broadcast's scorebug raised within
 * SCOREBUG_MATCH_S of it (the scorebug is the broadcast's own graphic, read from pixels). */
function goalSide(g: { t: number; team?: string | null }): "home" | "away" | null {
  if (g.team === "home" || g.team === "away") return g.team;
  const change = scorebugEvents.find(
    (e) => e.type === "score_change" && (e.team === "home" || e.team === "away") && Math.abs(e.t - g.t) <= SCOREBUG_MATCH_S,
  );
  return change ? (change.team as "home" | "away") : null;
}

/** "London · 38′": a goal's club (when known) and minute, as Apple Sports heads a goal. */
function goalLine(g: { t: number; team?: string | null }): string {
  const side = goalSide(g);
  return side ? `${teams[side]} · ${momentum.minuteOf(g.t)}′` : `${momentum.minuteOf(g.t)}′`;
}

/** The match's goals up to t (match.json `goals`, reconciled with the scorebug, #356). */
const goalsUpTo = (t: number) => (state.match?.goals ?? []).filter((g) => g.t <= t);
const GOAL_SHOT_S = 5; // design: a shot that goes in is followed by its goal event within seconds
type GoalRow = MatchData["goals"][number];
/** Each detected goal shot up to t with the match's goal that tells it: one goal a shot, the nearest
 * after it within GOAL_SHOT_S and of the same club (either side may be unknown). */
function goalShots(t: number): Map<string, GoalRow> {
  const out = new Map<string, GoalRow>();
  const used = new Set<GoalRow>();
  const shots = [...bundleEvents.values()].filter((e) => e.type === "shot" && e.outcome === "goal" && e.t <= t).sort((a, b) => a.t - b.t);
  for (const s of shots) {
    const side = sureSide(s);
    const g = goalsUpTo(t)
      .filter((g) => !used.has(g) && g.t >= s.t - 1 && g.t - s.t <= GOAL_SHOT_S)
      .filter((g) => { const gs = goalSide(g); return gs === null || side === null || gs === side; })
      .sort((a, b) => Math.abs(a.t - s.t) - Math.abs(b.t - s.t))[0];
    if (g) { used.add(g); out.set(s.id, g); }
  }
  return out;
}
/** A detected goal shot that one of the match's goals already tells. */
const toldByGoal = (e: { id: string }, t: number) => goalShots(t).has(e.id);

/** The score, only as vision read it off the broadcast's own scorebug: the latest `score_change`
 * (#356) at or before t; nothing before the first reading. Never counted from detected goals
 * (Kian, Oct 25): vision can miss a goal, the scorebug cannot. */
export function scorebugAt(events: Iterable<{ type: string; t: number; score?: { home: number; away: number } | null }>, t: number) {
  let best: { t: number; score: { home: number; away: number } } | null = null;
  for (const e of events) {
    if ((e.type !== "score_change" && e.type !== "score_read") || !e.score || e.t > t + 1e-6) continue;
    if (!best || e.t >= best.t) best = { t: e.t, score: e.score };
  }
  return best;
}
let scorebugKey = "";
function renderScorebug(t: number) {
  const read = scorebugAt(scorebugEvents, t);
  const key = read ? `${read.score.home}-${read.score.away}|${teams.home}|${teams.away}` : "";
  if (key === scorebugKey) return;
  scorebugKey = key;
  document.body.dataset.scorebug = read ? "read" : "";
  for (const side of ["home", "away"] as const) {
    const el = $(`score-${side}`);
    el.hidden = !read;
    // The first reading is set, not counted up from 0; a change after it ticks.
    if (read) tickTo(el, read.score[side], el.hidden || el.textContent === "" ? read.score[side] : undefined);
  }
  const btn = $("score-read");
  btn.hidden = !read;
  btn.textContent = read ? `Score, read from the broadcast's score graphic: ${teams.home} ${read.score.home}, ${teams.away} ${read.score.away}` : "";
  for (const el of document.querySelectorAll<HTMLElement>(".score-line")) el.dataset.score = read ? `${read.score.home} ${read.score.away}` : "";
}
for (const id of ["score-home", "score-away", "score-read"]) {
  $(id).addEventListener("click", () => {
    const read = scorebugAt(scorebugEvents, viewTime());
    if (!read) return;
    void openHow({ t: read.t, visual: null, source: "code", evidence: [],
      why: { question: "", text: `${teams.home} ${read.score.home}, ${teams.away} ${read.score.away}: read from the broadcast's score graphic at ${clock(read.t)}, never counted from the goals vision spotted.` } });
  });
}

let statsKey = "";
function showMatch(t: number) {
  const m = state.match;
  if (!m) return;
  const v = laptop.cuts ? laptop.cuts.videoTime(t) : t;
  const c = chapterAt(m.chapters, bundleFps, v);
  const line = $("scoreline");
  line.hidden = !c;
  const chapter = c ? chapterLabel(c, teams) : "";
  if (line.textContent !== chapter) line.textContent = chapter;
  $("match-card").hidden = false;
  $("no-stats").hidden = true;
  renderSpotted(m, t);
  renderScorebug(t);
  renderShots(t);
  renderSquad();
  if (playsUpTo(t).length !== playsShown || goalsUpTo(t).length !== goalsShown) renderInsights();
  const st = statsAt(m, t);
  const key = `${JSON.stringify(st)}|${momentum.minuteOf(t)}`; // the Scout's rows step by minute
  if (key === statsKey) return;
  statsKey = key;
  renderStats(st);
}

/** Match stats as mirrored bars (Apple Sports): the home value at the left edge, the away value at
 * the right, the label centred, each bar in its club's colour. Only rows the data holds. */
interface StatsBlock {
  rows: { group: string; key: string; label: string; unit: string | null; series: { minute_to: number; home: number | null; away: number | null; confident: boolean }[] }[];
  /** Each half on its own (#338): the same rows with one value per team; `second` from minute 46. */
  halves?: Partial<Record<"first" | "second", { minute_from: number; minute_to: number; rows: HalfRow[] }>>;
  player_stats?: PlayerStats[];
  pass_network?: Record<"home" | "away", PassNetwork>;
}
type HalfRow = { group: string; key: string; label: string; unit: string | null; home: number | null; away: number | null; confident: boolean };
let statsPeriod: "match" | "first" | "second" = "match";
const round1 = (n: number) => Math.round(n * 10) / 10;
interface TeamStatsFacts {
  from_footage: boolean;
  within_pct?: number; // the distance is measured to within this many percent (#300)
  distance?: Record<"home" | "away", { km: number; coverage: number }>;
  possession?: Record<"home" | "away", { share: number }>;
}
const shownStats = new Map<string, [number, number]>();
/** A row's label with its unit, unless the unit says nothing new: a count of what the label names
 * ("Corners", not "Corners (corners)") or one of the plain counting units. */
function withUnit(label: string, unit: string | null): string {
  if (!unit || /^(opponents|passes|players|times|turnovers|regains|overloads|moments)$/.test(unit)) return label;
  const stem = (w: string) => w.toLowerCase().replace(/s$/, "");
  return label.toLowerCase().split(/[^a-z-]+/).some((w) => w && stem(w) === stem(unit)) ? label : `${label} (${unit})`;
}

/** Events a row of counts must rest on before it shows (Coordinator, Oct 26: counted only on sides told
 * surely, a row of 0 and 1 says nothing; design): fewer, and the row is not drawn. */
const MIN_ROW_EVENTS = (window as { __ninetyMinRowEvents?: number }).__ninetyMinRowEvents ?? 10; // tests' seam: tests/test_phone.py watch()
const enough = (total: number) => total >= MIN_ROW_EVENTS;
function renderStats(st: MatchData["stats"][number]) {
  type Row = [string, number, number];
  const pct = (n: number, d: number) => (d > 0 ? Math.round((100 * n) / d) : NaN);
  // Grouped as Apple Sports and FotMob group a match's stats; every number computed by code from the
  // detected events (match.json) or the measured team facts (team_stats, #269).
  const ts = (state.match as (MatchData & { team_stats?: TeamStatsFacts }) | null)?.team_stats;
  const groups: [string, Row[]][] = [
    ["Attack", [
      ...(ts?.possession ? [["Possession %", Math.round(ts.possession.home.share), Math.round(ts.possession.away.share)] as Row] : []),
      // Counted from what vision saw: it can miss a shot or a goal the broadcast showed, so the
      // label says so (video-prep, Oct 25: 3 goals seen under a 4-1 scorebug).
      ...(enough(st.home.shots + st.away.shots) ? [
        ["Shots seen", st.home.shots, st.away.shots],
        ["Shots on target seen", st.home.shots_on_target, st.away.shots_on_target],
      ] as Row[] : []),
    ]],
    ["Passing", enough(st.home.passes_attempted + st.away.passes_attempted) ? [
      ["Passes completed", st.home.passes_completed, st.away.passes_completed],
      ["Passes tried", st.home.passes_attempted, st.away.passes_attempted],
      ["Pass accuracy %", pct(st.home.passes_completed, st.home.passes_attempted), pct(st.away.passes_completed, st.away.passes_attempted)],
    ] : []],
    ["Pressing", []],
    ["Shape", []],
    ["Physical", ts?.distance ? [["Distance (km)", Math.round(ts.distance.home.km * 10) / 10, Math.round(ts.distance.away.km * 10) / 10]] : []],
  ];
  // The Insight Scout's computed rows (match.json `insight_stats`, #269): each the latest value "so far" at
  // or before the clock's minute; null is not measurable (not shown), confident:false is "unsure".
  const block = state.match as unknown as { insight_stats?: StatsBlock } | null;
  const minute = momentum.minuteOf(viewTime());
  const unsure = new Set<string>();
  for (const r of block?.insight_stats?.rows ?? []) {
    const v = [...r.series].reverse().find((x) => x.minute_to <= minute);
    if (!v || v.home === null || v.away === null || v.home === undefined || v.away === undefined) continue;
    if (r.key === "distance_km" && groups.some(([, rows]) => rows.some(([l]) => l === "Distance (km)"))) continue;
    const label = withUnit(r.label, r.unit);
    if (!v.confident) unsure.add(label);
    groups.find(([g]) => g === r.group)?.[1].push([label, round1(v.home), round1(v.away)]);
  }
  const covered = ts?.distance ? Math.round(100 * Math.min(ts.distance.home.coverage, ts.distance.away.coverage)) : null;
  $("stats-note").textContent = covered === null ? "From the footage shown, so far." : `From the footage shown, so far. Distance covers ${covered}% of the players' time.`;
  const row = ([label, h, a]: Row) => {
    const li = document.createElement("li");
    li.className = "stat-row";
    li.setAttribute("aria-label", `${label}: ${teams.home} ${h}, ${teams.away} ${a}${unsure.has(label) ? " (unsure)" : ""}`);
    if (unsure.has(label)) li.classList.add("unsure");
    li.innerHTML = '<span class="v home-v"></span><span class="label"></span><span class="v away-v"></span><span class="bar home-bar"></span><span class="bar away-bar"></span>';
    // The numbers tick up from what the row showed before (ticker.ts).
    const was = shownStats.get(label);
    li.querySelector<HTMLElement>(".home-v")!.textContent = String(was?.[0] ?? h);
    li.querySelector<HTMLElement>(".away-v")!.textContent = String(was?.[1] ?? a);
    tickTo(li.querySelector<HTMLElement>(".home-v")!, h);
    tickTo(li.querySelector<HTMLElement>(".away-v")!, a);
    shownStats.set(label, [h, a]);
    li.querySelector(".label")!.textContent = label;
    // Distance carries how close it is measured: a quiet "±15%" after it, in words for a screen reader.
    if (label === "Distance (km)" && ts?.within_pct) {
      const pm = document.createElement("span");
      pm.className = "within";
      pm.textContent = ` ±${ts.within_pct}%`;
      li.querySelector(".label")!.append(pm);
      li.setAttribute("aria-label", `${li.getAttribute("aria-label")}, measured to within ${ts.within_pct} percent`);
    }
    // One track split at the home share (Apple Sports): 0 v 0 splits it evenly, in grey (nothing to
    // share yet, so no club's colour); 1 v 0 is all home.
    const share = h + a === 0 ? 0.5 : h / (h + a);
    li.classList.toggle("empty", h + a === 0);
    (li.querySelector(".home-bar") as HTMLElement).style.width = share === 0 ? "0" : `calc(${100 * share}% - ${share < 1 ? 2 : 0}px)`;
    (li.querySelector(".away-bar") as HTMLElement).style.width = share === 1 ? "0" : `calc(${100 * (1 - share)}% - ${share > 0 ? 2 : 0}px)`;
    for (const v of li.querySelectorAll(".v, .label, .bar")) v.setAttribute("aria-hidden", "true");
    return li;
  };
  const listOf = (groups: [string, Row[]][]) => {
  const items: HTMLLIElement[] = [];
  for (const [name, rows] of groups) {
    const shown = rows.filter(([, h, a]) => Number.isFinite(h) && Number.isFinite(a));
    if (!shown.length) continue;
    const head = document.createElement("li");
    head.className = "stat-group";
    head.setAttribute("role", "presentation");
    const h3 = document.createElement("h3");
    h3.textContent = name;
    head.append(h3);
    items.push(head, ...shown.map(row));
  }
  return items;
  };
  const items = listOf(groups);
  // A half on its own (Apple Sports' period toggle): the Scout's half rows, when it has written them.
  const halves = block?.insight_stats?.halves;
  $("stats-period").hidden = !halves?.first;
  for (const btn of $("stats-period").querySelectorAll<HTMLElement>("ion-segment-button[value=second]")) btn.hidden = !halves?.second;
  const half = statsPeriod === "match" ? null : halves?.[statsPeriod];
  if (half) {
    const byGroup: [string, Row[]][] = ["Attack", "Passing", "Pressing", "Shape", "Physical"].map((g) => [g, []]);
    for (const r of half.rows) {
      if (r.home === null || r.away === null) continue;
      const label = withUnit(r.label, r.unit);
      if (!r.confident) unsure.add(label);
      byGroup.find(([g]) => g === r.group)?.[1].push([label, round1(r.home), round1(r.away)]);
    }
    $("stat-rows").replaceChildren(...listOf(byGroup));
  } else $("stat-rows").replaceChildren(...items);
  $("live-stats").hidden = items.length === 0;
  // Live shows the first rows under the pitch, as Apple Sports shows Team Stats under its band.
  // An analyst's Live carries every row (a dense strip); everyone else the first four.
  const summary = items.filter((li) => li.classList.contains("stat-row")).slice(0, chosen()?.mode === "analyst" ? undefined : 4).map((li) => li.cloneNode(true) as HTMLLIElement);
  $("summary-rows").replaceChildren(...summary);
  $("live-summary").hidden = summary.length === 0;
}

// --- the shot map: detected shots up to the clock, those the fact-checker would let through -----

let shotFilter: "all" | "home" | "away" = "all";
let shotsKey = "";
let liveShotsKey = "";
$("shot-filter").addEventListener("ionChange", (e) => {
  shotFilter = (e as CustomEvent<{ value: typeof shotFilter }>).detail.value;
  shotsKey = "";
  renderShots(viewTime());
});

function renderShots(t: number) {
  const min = state.match?.min_confidence ?? 1;
  const all: (shotMap.Shot & { sure: boolean })[] = [...bundleEvents.values()]
    .filter((e) => e.type === "shot" && e.t <= t && (e.team === "home" || e.team === "away") && e.x !== undefined && e.y !== undefined && (e.confidence ?? 0) >= min)
    .map((e) => ({ id: e.id, t: e.t, team: e.team as "home" | "away", x: e.x!, y: e.y!, outcome: e.outcome ?? null, player: e.player ?? null, sure: sureSide(e) !== null }));
  // The card shows only what it draws (UI inventory #8): a shot is placed only on a side told surely.
  $("shot-map").hidden = !all.some((s) => s.sure);
  // A shot on an unsure side is in "All" only: no club's filter claims it.
  const shown = all.filter((s) => shotFilter === "all" || (s.sure && s.team === shotFilter));
  // Live's card draws what the Stats map draws: a shot only on a sure side (its place on the half
  // pitch is read from that side's direction of attack); no sure shot, no card.
  const drawn = all.filter((s) => s.sure);
  $("live-shots").hidden = drawn.length === 0;
  const allKey = drawn.map((s) => s.id).join();
  if (allKey !== liveShotsKey) {
    liveShotsKey = allKey;
    shotMap.draw($("live-shots-svg") as unknown as SVGSVGElement, drawn);
    // Shots counted, never goals: a goal count is a score (Kian, Oct 25), and the broadcast carries it.
    $("live-shots-said").textContent = `${all.length} ${all.length === 1 ? "shot" : "shots"}.`;
  }
  const key = `${shotFilter}|${shown.map((s) => s.id).join()}|${goalsUpTo(t).length}|${scorebugEvents.length}`;
  if (key === shotsKey) return;
  shotsKey = key;
  const svg = $("shots") as unknown as SVGSVGElement;
  // Placed and coloured only on a sure side: where a shot sits on the half pitch is read from the
  // direction its side attacks. An unsure one is listed, not drawn.
  shotMap.draw(svg, shown.filter((s) => s.sure));
  svg.setAttribute("aria-label", `Shot map: ${shown.length} ${shown.length === 1 ? "shot" : "shots"}. The list follows.`);
  const paired = goalShots(t);
  $("shot-list").replaceChildren(
    ...shown.map((s) => {
      const li = document.createElement("li");
      // Who and where only on a sure side: the zone is read from that side's direction of attack.
      // "London · 38′" (demo audit 2, row 10): the club where it is known, a goal's from its
      // reconciled goal; the scorer only where the team sheet names him.
      const goal = paired.get(s.id);
      const side = s.sure ? s.team : goal ? goalSide(goal) : null;
      const named = s.player && !unnamedTrack(s.player, undefined, true) ? `, ${eventName(s.player)}` : "";
      li.textContent = `${side ? `${teams[side]} · ` : ""}${momentum.minuteOf(s.t)}′, ${shotMap.label(s.outcome)}${named}` + (s.sure ? `, from the ${zoneFor(s.team, s.x, s.y)}` : "");
      return li;
    }),
    // The match's goals vision has no shot for (missed shots, #356's reconciled goals).
    ...(shotFilter === "all" ? goalsUpTo(t) : goalsUpTo(t).filter((g) => goalSide(g) === shotFilter))
      .filter((g) => ![...paired.values()].includes(g))
      .map((g) => {
        const li = document.createElement("li");
        li.textContent = `${goalLine(g)}, goal`;
        return li;
      }),
  );
}

// --- Live's text tabs (Apple Sports: Stats / Play-By-Play / Rankings): Pitch, Stats, Players ----

const LIVE_PANES = ["pitch", "stats", "players"] as const;
type LivePane = (typeof LIVE_PANES)[number];
/** Players is a tab only while it has something to show (demo audit 2, row 1: a blank pane reads as
 * a crash): the team sheet or the line-up, the pass network, the top performers. */
function syncPlayersTab() {
  const empty = ["roster-box", "pass-network", "top-players"].every((id) => $(id).hidden);
  $("lt-players").hidden = empty;
  if (empty && document.body.dataset.pane === "players") showPane("pitch");
}
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
  if (pane === "players" && state.radar) renderRoster(rosterIds()); // who is on the pitch now
}
for (const p of LIVE_PANES) {
  const tab = $(`lt-${p}`);
  tab.addEventListener("click", () => showPane(p));
  tab.addEventListener("keydown", (e) => {
    const shown = LIVE_PANES.filter((q) => !$(`lt-${q}`).hidden);
    const i = shown.indexOf(p);
    const to = e.key === "ArrowRight" ? i + 1 : e.key === "ArrowLeft" ? i - 1 : e.key === "Home" ? 0 : e.key === "End" ? shown.length - 1 : null;
    if (to === null) return;
    e.preventDefault();
    showPane(shown[(to + shown.length) % shown.length], true);
  });
}

// --- the squads: Live's line-ups teaser, the pass network, the top performers ------------------

/** match.json's per-player numbers (Insight Scout): computed by code from tracking, each with the
 * player's id; a missing number is not measured and its list is not drawn. */
interface PlayerStats { id: string; distance_km?: number | null; top_speed_kmh?: number | null; involvements?: number | null }
/** match.json's pass network (Insight Scout): per club, each player's average position and passes
 * made, and completed passes between pairs. */
interface PassNetwork { named_passes_only?: boolean; nodes: { id: string; x: number; y: number; passes: number }[]; links: { a: string; b: string; n: number }[] }
type Squads = { player_stats?: PlayerStats[]; pass_network?: Record<"home" | "away", PassNetwork> };

let squadKey = "";
let networkSide: "home" | "away" = "home";
function renderSquad() {
  const m0 = state.match as (MatchData & Squads & { insight_stats?: StatsBlock }) | null;
  // The Scout's numbers ride in insight_stats (#338); top-level kept for a bundle that has them there.
  const m = m0 ? { ...m0, player_stats: m0.insight_stats?.player_stats ?? m0.player_stats, pass_network: m0.insight_stats?.pass_network ?? m0.pass_network } : null;
  const sheet = Object.entries(teamSheet);
  const net0 = m?.pass_network?.[networkSide];
  const sheetsN = ((m0 as { sheets?: Record<string, unknown[]> } | null)?.sheets?.home?.length ?? 0);
  const key = `${sheet.length}|${Object.keys(tacticalSheet).length}|${sheetsN}|${m?.player_stats?.length ?? 0}|${networkSide}|${teams.home}|${net0?.nodes.length ?? 0}|${net0?.links.length ?? 0}`;
  if (key === squadKey) return;
  squadKey = key;
  renderPlayersStrip(m?.player_stats ?? []);
  // Live's teaser: each club's crest, name and the shirts the team sheet is sure of.
  const rows = (["home", "away"] as const).map((side) => {
    // The team sheet's shirts (match.json `sheets`), else the line-up's.
    const xi = (m as { sheets?: Record<"home" | "away", SheetPlayer[]> } | null)?.sheets?.[side];
    const shirts = (xi?.length ? xi.map((p) => p.number) : sheet.filter(([id, e]) => team(id) === side && e.number !== undefined).map(([, e]) => e.number!)).sort((a, b) => a - b);
    const row = document.createElement("div");
    row.className = `teaser ${side}`;
    row.innerHTML = `<span class="crest" aria-hidden="true">${crestSvg(teams[side], side)}</span>`;
    const name = document.createElement("span");
    name.className = "teaser-name";
    name.textContent = fullName(teams[side]);
    const nums = document.createElement("span");
    nums.className = "teaser-shirts";
    if (shirts.length) {
      nums.setAttribute("role", "list");
      nums.setAttribute("aria-label", `Shirts ${shirts.join(", ")}`);
    }
    for (const n of shirts.slice(0, 11)) {
      const b = document.createElement("b");
      b.setAttribute("role", "listitem");
      b.textContent = String(n);
      nums.append(b);
    }
    row.append(name, nums);
    return { row, n: shirts.length };
  });
  $("lineups-teaser").hidden = rows.every((r) => r.n === 0);
  $("teaser-rows").replaceChildren(...rows.map((r) => r.row));

  // Top performers: the three highest of each measured number, as FotMob lists them.
  const ps = m?.player_stats ?? [];
  const lists: [string, keyof PlayerStats, (v: number) => string][] = [
    ["Distance", "distance_km", (v) => `${v.toFixed(1)} km`],
    ["Top speed", "top_speed_kmh", (v) => `${v.toFixed(1)} km/h`],
    ["Most involved", "involvements", (v) => String(Math.round(v))],
  ];
  const blocks = lists.flatMap(([title, k, fmt]) => {
    const top = ps.filter((p) => typeof p[k] === "number").sort((a, b) => (b[k] as number) - (a[k] as number)).slice(0, 3);
    if (!top.length) return [];
    const box = document.createElement("div");
    box.className = "top-list";
    const h = document.createElement("h3");
    h.className = "caps";
    h.textContent = title;
    const ul = document.createElement("ul");
    ul.className = "stat-list";
    for (const p of top) {
      const li = document.createElement("li");
      li.className = sideUnsure(p.id) ? "" : team(p.id); // a club's dot only on a side told surely
      li.innerHTML = '<span class="dot" aria-hidden="true"></span><span class="who-name"></span><span class="v"></span>';
      li.querySelector(".who-name")!.textContent = playerName(p.id);
      li.querySelector(".v")!.textContent = fmt(p[k] as number);
      ul.append(li);
    }
    box.append(h, ul);
    return [box];
  });
  $("top-players").hidden = blocks.length === 0;
  $("top-lists").replaceChildren(...blocks);

  // Pass network: each player at his average position, a line per pair as thick as their passes.
  const net = m?.pass_network?.[networkSide];
  // The card shows while either club has a network; a club without one shows an empty pitch never.
  $("pass-network").hidden = !(m?.pass_network?.home?.nodes.length || m?.pass_network?.away?.nodes.length);
  syncPlayersTab();
  $("network").toggleAttribute("hidden", !net?.nodes.length);
  $("network-rows").hidden = !net?.nodes.length;
  if (!net?.nodes.length) return;
  const svg = $("network") as unknown as SVGSVGElement;
  const NS = "http://www.w3.org/2000/svg";
  svg.setAttribute("viewBox", "-3 -3 111 74");
  const el = (tag: string, attrs: Record<string, string | number>) => {
    const e = document.createElementNS(NS, tag);
    for (const [k, v] of Object.entries(attrs)) e.setAttribute(k, String(v));
    return e;
  };
  const at = new Map(net.nodes.map((n) => [n.id, n]));
  // The pitch drawn so the club attacks to the right, as its line-up does; y = 0 at the bottom.
  const px = (n: { x: number; y: number }) => (networkSide === "home" ? [n.x, 68 - n.y] : [105 - n.x, n.y]);
  const most = Math.max(1, ...net.links.map((l) => l.n));
  const kids: SVGElement[] = [
    el("rect", { x: 0, y: 0, width: 105, height: 68, class: "pitch-lines" }),
    el("path", { d: "M52.5 0v68", class: "pitch-lines" }),
    el("circle", { cx: 52.5, cy: 34, r: 9.15, class: "pitch-lines" }),
    el("rect", { x: 0, y: 13.85, width: 16.5, height: 40.3, class: "pitch-lines" }),
    el("rect", { x: 88.5, y: 13.85, width: 16.5, height: 40.3, class: "pitch-lines" }),
  ];
  for (const l of net.links.filter((l) => l.n >= 3)) {
    const a = at.get(l.a);
    const b = at.get(l.b);
    if (!a || !b) continue;
    const [x1, y1] = px(a);
    const [x2, y2] = px(b);
    kids.push(el("line", { x1, y1, x2, y2, class: "link", "stroke-width": (0.4 + (2.4 * l.n) / most).toFixed(2) }));
  }
  for (const n of net.nodes) {
    const [x, y] = px(n);
    kids.push(el("circle", { cx: x, cy: y, r: 2.6 + Math.min(1.6, n.passes / 25), class: `node ${networkSide}` }));
    const shirt = (teamSheet[n.id] ?? Object.values(teamSheet).find((e) => e.name === n.id))?.number;
    if (shirt !== undefined) {
      const t = el("text", { x, y: y + 1.1, class: "node-n" });
      t.textContent = String(shirt);
      kids.push(t);
    }
  }
  svg.replaceChildren(...kids);
  const pair = [...net.links].sort((a, b) => b.n - a.n)[0];
  const busiest = [...net.nodes].sort((a, b) => b.passes - a.passes)[0];
  svg.setAttribute("aria-label", `${teams[networkSide]} pass network: ${net.nodes.length} players.`);
  const who = (id: string) => (teamSheet[id] || isTrack(id) || /^[ha]\d+$/.test(id) ? playerName(id) : id); // a name is itself
  const line = (label: string, value: string) => {
    const li = document.createElement("li");
    li.innerHTML = '<span class="who-name"></span><span class="v"></span>';
    li.querySelector(".who-name")!.textContent = label;
    li.querySelector(".v")!.textContent = value;
    return li;
  };
  $("network-named").hidden = !net.named_passes_only;
  $("network-rows").replaceChildren(
    ...(pair ? [line(`${who(pair.a)} and ${who(pair.b)}`, `${pair.n} passes`)] : []),
    ...(busiest ? [line(`Most passes: ${who(busiest.id)}`, String(busiest.passes))] : []),
  );
}
$("stats-period").addEventListener("ionChange", (e) => {
  statsPeriod = (e as CustomEvent<{ value: typeof statsPeriod }>).detail.value;
  statsKey = ""; // redraw the rows now
  if (state.match) showMatch(viewTime());
});
$("network-side").addEventListener("ionChange", (e) => {
  networkSide = (e as CustomEvent<{ value: "home" | "away" }>).detail.value;
  renderSquad();
});

// "See all" on a Live card: its full section (a Live pane, or a tab).
for (const b of document.querySelectorAll<HTMLButtonElement>(".see-all")) {
  b.addEventListener("click", () => {
    if (b.dataset.pane) {
      showPane(b.dataset.pane as LivePane, true);
      void ($("live-content") as unknown as { scrollToTop?: (ms: number) => Promise<void> }).scrollToTop?.(0);
    } else if (b.dataset.tab) showTab(b.dataset.tab as Tab, true);
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
const MIN_TERRITORY_S = 30;
function renderMomentum(live: number, t: number) {
  const tr = territory();
  // With under half a minute of seen ball so far the strip would be a sliver on an empty card, so the
  // card is hidden until there is something to show (design: MIN_TERRITORY_S).
  const seenS = tr ? tr.bins.filter((b) => b.t <= live && b.home !== null).reduce((sum, b) => sum + b.seen_s, 0) : 0;
  $("momentum").hidden = !tr || seenS < MIN_TERRITORY_S;
  $("stats-territory").hidden = $("momentum").hidden;
  if (!tr || seenS < MIN_TERRITORY_S) return;
  const key = `${Math.floor(live)}|${scrubT === null ? "" : t.toFixed(1)}`;
  if (key === stripKey) return;
  stripKey = key;
  momentum.draw(strip, tr, live, scrubT === null ? null : t, state.match?.goals ?? []);
  momentum.draw($("stats-territory-svg") as unknown as SVGSVGElement, tr, live, null, state.match?.goals ?? []);
  $("stats-territory-said").textContent = momentum.sayAt(tr, live, teams);
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
  const mini = `${teams.home}   ${link ? clock(t) : "–:––"}   ${teams.away}`;
  // The collapsed row: crest, clock, crest (never a score); one label for a screen reader.
  const clockText = link ? clock(t) : "–:––";
  for (const el of document.querySelectorAll<HTMLElement>(".score-line")) {
    if (el.getAttribute("aria-label") === mini) continue;
    el.setAttribute("aria-label", mini);
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
