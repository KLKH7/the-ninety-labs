// The phone companion: pairs with the laptop's broadcast by code, then shows a minimap in step with
// the laptop's clock, a player card (speed and heat map) for the player tapped, and answers to the
// viewer's questions with their evidence one tap away.
//
// ?code=ABC234&clip=seed7 joins straight away (the laptop's QR code); ?mock=1 reads the mock feed.

import { LaptopClock } from "./clock";
import { ApiError, type Closed, type Feed, GroundTruth, HttpFeed, type Link, guarded } from "./feed";
import { MockFeed } from "./mock";
import { CODE_ALPHABET, CODE_LENGTH } from "./mockrelay";
import { COLORS, type Positions, type View, describeHeat, describePlay, drawHeat, drawPitch, drawPlayers, fit, positionsAt, within } from "./pitch";
import {
  type AnswerMessage,
  MAX_QUESTION,
  type Minimap,
  type PlayerCard,
  type RelayMessage,
  type ViewerAnswer,
  clock,
  isTrack,
  playerName,
  shirt,
  team,
} from "./types";

const $ = <T extends HTMLElement>(id: string) => document.getElementById(id) as T;
const params = new URLSearchParams(location.search);

const CARD_EVERY_MS = 1000; // speed now is a one-second mean (ninety/intel/window.py)
const FLOW_EVERY_MS = 5000;

/** Every payload the phone received, for tests/test_phone.py to check against the schemas. */
const seen: unknown[] = [];
const feed: Feed = guarded(params.get("mock") === "1" ? new MockFeed() : new HttpFeed(), (p) => seen.push(p));
const laptop = new LaptopClock();

interface State {
  code: string;
  clip: string;
  minimap: Minimap | null;
  refused: string | null; // why the positions are not shown
  selected: string | null;
  following: boolean; // the selection came from the laptop's focus
  card: PlayerCard | null;
  wind: boolean;
}
const state: State = { code: "", clip: "", minimap: null, refused: null, selected: null, following: false, card: null, wind: false };
let link: Link | null = null;
let lastPositions: Positions | null = null;

// Read by tests/test_phone.py.
(window as unknown as { ninetyPhone: object }).ninetyPhone = { seen, state, laptop, positions: () => lastPositions };

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
  "unknown-code": "No laptop is showing that code. Check the code on the laptop and try again.",
  "room-full": "Eight phones are already following this laptop.",
  expired: "That code has expired. Ask the laptop for a new one.",
  refused: "The laptop's connection refused this phone.",
  lost: "Lost the connection to the laptop.",
  "not-joined": "Could not join: no laptop is showing that code, or the server cannot be reached. Check the code and try again.",
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
      pairError.textContent = "This server needs the laptop's QR code to connect: scan it with your camera.";
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
  await loadMinimap();
}

function onRelay(m: RelayMessage) {
  if (m.type === "clock") laptop.update(m);
  else if (m.type === "focus" && m.player !== null && state.minimap?.roster.includes(m.player)) {
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
});

// --- the minimap -----------------------------------------------------------------------------

const mapCanvas = $<HTMLCanvasElement>("map");
const windCanvas = $<HTMLCanvasElement>("wind");

async function loadMinimap() {
  try {
    state.minimap = await feed.minimap(state.clip);
    state.refused = null;
  } catch (e) {
    state.minimap = null;
    state.refused =
      e instanceof GroundTruth || (e instanceof ApiError && e.status === 503)
        ? "Live player positions aren't available for this match yet, so there is no minimap, player card " +
          "or question to show. They turn on once positions are tracked from the video itself. " +
          "The match clock above still follows the laptop."
        : `Could not load the minimap: ${(e as Error).message}`;
  }
  const refused = $("refused");
  refused.hidden = state.refused === null;
  refused.textContent = state.refused ?? "";
  mapCanvas.dataset.source = state.minimap ? state.minimap.source : "refused";
  $("map-box").hidden = state.minimap === null;
  for (const id of ["pick-hint", "ask", "roster-box", "now-box"]) $(id).hidden = state.minimap === null;
  document.querySelector<HTMLElement>(".legend")!.hidden = state.minimap === null;
  if (state.minimap) {
    renderRoster(state.minimap.roster);
    $("wind-toggle").hidden = false;
    const tracked = state.minimap.roster.some(isTrack);
    $("seen-note").hidden = !tracked;
    $("roster-summary").textContent = tracked ? "Choose a player the camera has seen" : "Choose a player from a list";
  }
  renderChips();
}

function renderRoster(roster: string[]) {
  const button = (id: string) => {
    const b = document.createElement("button");
    b.type = "button";
    b.className = `who ${team(id)}`;
    b.dataset.player = id;
    b.textContent = shirt(id);
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
      label.textContent = side === "home" ? "Home" : "Away";
      label.setAttribute("aria-hidden", "true"); // each button already says its team
      const row = document.createElement("div");
      row.className = "roster-row";
      row.append(...ids.map(button));
      return [label, row];
    }),
  );
}

mapCanvas.addEventListener("click", (e) => {
  if (!lastPositions) return;
  const r = mapCanvas.getBoundingClientRect();
  const ids = within(fit(mapCanvas), lastPositions, e.clientX - r.left, e.clientY - r.top);
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
function describeMap(t: number, pos: Positions) {
  // The canvas's label, refreshed every few seconds of match time, not every frame.
  if (Math.abs(t - summaryAt) < 5) return;
  summaryAt = t;
  const who = state.selected ? ` ${playerName(state.selected)} is circled.` : "";
  mapCanvas.setAttribute("aria-label", `Minimap at ${clock(t)}. ${describePlay(pos, playerName)}${who}`);
}

// For a fan who cannot see the laptop: one sentence on demand, or, with "Describe as it happens"
// on, a sentence whenever the play changes (the ball changes half, or the nearest player changes
// side), at most one every LIVE_GAP_S of match time. The live region reads each one.
const LIVE_GAP_S = 8; // design: about one sentence between two passes, so the reader can keep up
let saidAt = -Infinity;
let saidKey = "";

function sayNow(t: number) {
  if (!lastPositions) return;
  const said = $("now-said");
  const sentence = `At ${clock(t)}: ${describePlay(lastPositions, playerName)}`;
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

function announce(text: string) {
  $("announce").textContent = text;
}

// --- the player card -------------------------------------------------------------------------

function select(id: string | null, fromLaptop = false) {
  state.selected = id;
  state.following = fromLaptop;
  state.card = null;
  for (const b of document.querySelectorAll<HTMLButtonElement>("#roster .who")) {
    b.setAttribute("aria-pressed", String(b.dataset.player === id));
  }
  $("player").hidden = id === null;
  $("pick-hint").hidden = id !== null || state.minimap === null;
  if (id) {
    $("player-title").textContent = fromLaptop ? `${playerName(id)} · followed from the laptop` : playerName(id);
    $("player").dataset.team = team(id);
    for (const s of ["speed", "peak", "distance"]) $(s).textContent = "–";
    cardAsked = -1;
    void refreshCard(true);
    if (fromLaptop) announce(`The laptop is following ${playerName(id)}.`);
    else {
      // Focus moves to the card, so a screen reader lands on it; the page scrolls just enough to show it.
      requestAnimationFrame(() => {
        $("player-title").focus({ preventScroll: true });
        $("player").scrollIntoView({ block: "nearest", behavior: reduceMotion.matches ? "auto" : "smooth" });
      });
    }
  }
  $("ask-who").textContent = id ? playerName(id) : "a player";
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
      $("player").hidden = true;
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
  const busiest = Math.max(...c.heat.cells);
  $("heat-legend").textContent = `Brighter means more time there; the brightest square is ${Math.round(busiest * 100)}% of the time.`;
  $("card-note").textContent =
    `Updated at ${clock(c.t_to)}. Computed by code from ${feed.mock ? "the mock positions" : "positions tracked from the video"}; ` +
    "speed now is the average over the last second.";
}

// --- questions -------------------------------------------------------------------------------

function suggestions(id: string | null): string[] {
  if (!id) return [];
  const n = playerName(id);
  return [`How fast is ${n} running now?`, `What is ${n}'s top speed?`, `How far has ${n} run?`];
}

function renderChips() {
  const chips = suggestions(state.selected).map((q) => {
    const b = document.createElement("button");
    b.type = "button";
    b.className = "chip";
    b.textContent = q;
    b.addEventListener("click", () => void ask(q));
    return b;
  });
  if (!chips.length) {
    const p = document.createElement("p");
    p.className = "fine";
    p.textContent = "Pick a player to see suggested questions.";
    chips.push(p as unknown as HTMLButtonElement);
  }
  $("chips").replaceChildren(...chips);
}

const STATUS_WORDS: Record<ViewerAnswer["status"], string> = {
  verified: "Fact-checked",
  held: "Still being checked",
  rejected: "Refused by the fact-checker",
  unanswerable: "Can't answer that",
};

const METRIC_WORDS: Record<string, string> = {
  speed_now: "speed now",
  peak_speed: "top speed",
  distance_run: "distance run",
};

/** The API names players by id (a7); fans read "Away 7". Only the names change, never a number. */
function named(text: string): string {
  return text.replace(/\b[ha](?:-t\d+|[1-9]|1[01])\b/g, (id) => playerName(id));
}

let answerSeq = 0;
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
  $("answers").prepend(pending);
  let answer: ViewerAnswer | null = null;
  let failed = "";
  try {
    const message: AnswerMessage = await feed.ask({ session: state.code, player: state.selected, text: q, t: at });
    answer = message.answer;
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
}

function renderAnswer(question: string, at: number, a: ViewerAnswer | null, failed: string): HTMLLIElement {
  const li = document.createElement("li");
  li.className = `answer ${a?.status ?? "error"}`;
  li.dataset.status = a?.status ?? "error";
  const asked = document.createElement("p");
  asked.className = "asked";
  asked.textContent = `You asked at ${clock(at)}: “${question}”`; // shown as text, never as markup
  const badge = document.createElement("span");
  badge.className = "badge";
  badge.textContent = a ? STATUS_WORDS[a.status] : "Not sent";
  const body = document.createElement("p");
  body.className = "said";
  if (!a) body.textContent = failed;
  else if (a.status === "verified") body.textContent = named(a.text);
  else if (a.status === "held") body.textContent = "The fact-checking agent has not finished checking this answer, so it is not shown yet.";
  else if (a.status === "rejected") body.textContent = "The fact-checking agent rejected the drafted answer, so nothing is shown.";
  else body.textContent = named(a.text) || "That is not something the phone can answer. Ask about a player's speed, top speed or distance run.";
  li.append(asked, badge, body);
  if (a && a.status === "verified" && a.value !== null) {
    const big = document.createElement("p");
    big.className = "figure";
    big.textContent = `${a.value} ${a.unit ?? ""}`.trim();
    li.insertBefore(big, body);
  }
  if (a && a.status === "verified") li.append(...evidence(a));
  return li;
}

/** The answer's evidence behind one button: what was measured, over which stretch, from which facts. */
function evidence(a: ViewerAnswer): HTMLElement[] {
  const id = `evidence-${++answerSeq}`;
  const toggle = document.createElement("button");
  toggle.type = "button";
  toggle.className = "evidence-toggle";
  toggle.setAttribute("aria-expanded", "false");
  toggle.setAttribute("aria-controls", id);
  toggle.textContent = "Show the evidence";
  const panel = document.createElement("dl");
  panel.className = "evidence";
  const who = a.evidence.map((id) => /player_([ha](?:-t\d+|[1-9]|1[01]))_/.exec(id)?.[1]).find(Boolean);
  const what = a.metric ? METRIC_WORDS[a.metric] ?? a.metric.replace(/_/g, " ") : "";
  const rows: [string, string][] = [
    ["What", `${who ? `${playerName(who)}'s ` : ""}${what}${a.value !== null ? `: ${a.value} ${a.unit ?? ""}`.trimEnd() : ""}`],
  ];
  if (a.t_from !== null && a.t_to !== null) rows.push(["Over", `${clock(a.t_from)} to ${clock(a.t_to)} of the match`]);
  rows.push(["Computed by", `code, from ${feed.mock ? "the mock positions" : "positions tracked from the video"}`]);
  rows.push(["Checked by", "the fact-checking agent, against the cited facts"]);
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
  summary.textContent = "Technical detail";
  const ids = document.createElement("p");
  ids.className = "ids";
  ids.textContent = `Cited facts: ${a.evidence.join(", ")}`;
  technical.append(summary, ids);
  const wrap = document.createElement("div");
  wrap.className = "evidence-wrap";
  wrap.id = id;
  wrap.hidden = true;
  wrap.append(panel, technical);
  toggle.addEventListener("click", () => {
    const open = toggle.getAttribute("aria-expanded") !== "true";
    toggle.setAttribute("aria-expanded", String(open));
    toggle.textContent = open ? "Hide the evidence" : "Show the evidence";
    wrap.hidden = !open;
  });
  return [toggle, wrap];
}

$("ask-form").addEventListener("submit", (e) => {
  e.preventDefault();
  void ask($<HTMLInputElement>("question").value);
});

// --- the wind map (first in the cut order: wind.ts loads only when turned on) ----------------

type Wind = import("./wind").WindMap;
let wind: Wind | null = null;
let windWords: typeof import("./wind").describe | null = null;
let flowAt = 0;
let flowBusy = false;

$("wind-toggle").addEventListener("click", async () => {
  state.wind = !state.wind;
  $("wind-toggle").setAttribute("aria-pressed", String(state.wind));
  windCanvas.hidden = !state.wind;
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
      ...[
        `Team movement over the last ${WINDOW_S} seconds.`,
        ...flows.map((f) => windWords!(f)),
      ].map((s) => {
        const p = document.createElement("p");
        p.textContent = s;
        return p;
      }),
    );
    windCanvas.dataset.t = String(t);
  } catch (e) {
    $("wind-words").textContent = e instanceof GroundTruth ? e.message : `Could not load the wind map: ${(e as Error).message}`;
  } finally {
    flowBusy = false;
  }
}

// --- every frame -----------------------------------------------------------------------------

function frame(now: number) {
  const t = laptop.time();
  $("clock").textContent = link ? clock(t) : "–:––";
  if (link) {
    if (!laptop.heard) setStatus("waiting", "Waiting");
    else if (laptop.stale()) setStatus("waiting", "Laptop lost");
    else if (state.refused !== null) setStatus("paused", "Clock only");
    else if (laptop.isPlaying()) setStatus("synced", "Synced");
    else setStatus("paused", "Paused");
  }
  if (state.minimap && !$("live").hidden) {
    const v: View = fit(mapCanvas);
    const pos = positionsAt(state.minimap, t);
    drawPitch(v);
    if (pos) {
      drawPlayers(v, pos, state.selected);
      lastPositions = pos;
      describeMap(t, pos);
      liveDescription(t, pos);
    }
    mapCanvas.dataset.t = t.toFixed(2);
    mapCanvas.dataset.dots = String(pos?.players.length ?? 0);
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
// The sticky header's height, so a focused element is never scrolled under it (style.css).
const header = document.querySelector<HTMLElement>(".sticky")!;
new ResizeObserver(() => document.documentElement.style.setProperty("--header-h", `${header.offsetHeight + 8}px`)).observe(header);
renderChips();
requestAnimationFrame(frame);
const start = params.get("code");
if (start) {
  codeInput.value = normalise(start);
  void connect(normalise(start));
}
