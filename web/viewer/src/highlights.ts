// Highlights mode: the reel in match.json (ninety/highlights.py, its captions from
// ninety/agents/captioner.py). Every goal, the saves that made the cut, each with the word fans use
// for it ("ROCKET · 112 km/h") and a line of commentary. Code chose the moments, the labels and the
// numbers; this only shows them over the footage, and plays them one after another on request.

import { type Bundle, clock } from "./bundle";

export type Label = "THUNDERBOLT" | "SCREAMER" | "LONG-RANGE" | "ROCKET" | "REFLEX SAVE" | "TAP-IN" | "GOAL" | "SAVE";

export interface Moment {
  event: string;
  t: number; // match time of the shot
  team: "home" | "away" | null;
  player: string | null;
  kind: "goal" | "save";
  why: "goal" | "beat_the_dive" | "filter_off";
  label: Label;
  label_detail: string | null; // the number that earned the label
  d_m: number;
  v_kmh: number | null;
  T_s: number | null;
  clip: [number, number]; // match time, from the build-up to just after the shot
  caption?: string;
  caption_source?: "model" | "code";
}

export interface Reel {
  save_filter: boolean;
  labels: boolean;
  moments: Moment[];
  saves_by_pace: string[];
  saves_left_out: number;
}

/** The card stays up from the strike to the end of the moment's clip; it comes in this much before
 * the strike so it is up as the shot is struck (design: a few frames). */
export const CARD_LEAD_S = 0.2;

/** The moment whose card is up at match time `t`, if any. */
export function momentAt(r: Reel, t: number): Moment | null {
  let at: Moment | null = null;
  for (const m of r.moments) if (m.t - CARD_LEAD_S <= t && t < m.clip[1]) at = m;
  return at;
}

/** What the note under the reel says: what was left out and why, in plain words. */
export function notes(r: Reel): string[] {
  const out = [
    r.save_filter
      ? `Saves shown beat a keeper's dive (the ball in under 0.97 s); ${r.saves_left_out} slower ${r.saves_left_out === 1 ? "save" : "saves"} left out.`
      : "Every detected save is shown: the speed filter waits until vision's shot speed is measured.",
  ];
  if (!r.labels) out.push("Labels such as ROCKET appear once vision's speed and distance errors are measured.");
  return out;
}

const SPOKEN: Record<Label, string> = {
  THUNDERBOLT: "Thunderbolt", SCREAMER: "Screamer", "LONG-RANGE": "Long-range", ROCKET: "Rocket",
  "REFLEX SAVE": "Reflex save", "TAP-IN": "Tap-in", GOAL: "Goal", SAVE: "Save",
};

/** What a screen reader hears when a card comes up. */
export function said(m: Moment): string {
  const head = m.label_detail ? `${SPOKEN[m.label]}, ${m.label_detail}` : SPOKEN[m.label];
  const what = `${m.kind === "goal" ? "Goal" : "Save"}${m.team ? `, ${m.team}` : ""}, ${clock(m.t)}`;
  return [head, what, m.caption].filter(Boolean).join(". ").replace(/\.\./g, ".");
}

const $ = <T extends HTMLElement>(id: string) => document.getElementById(id) as T;

function el<K extends keyof HTMLElementTagNameMap>(tag: K, cls: string, text?: string) {
  const e = document.createElement(tag);
  e.className = cls;
  if (text !== undefined) e.textContent = text;
  return e;
}

/** The class a label is drawn with: one colour per family. */
function tone(m: Moment): string {
  if (m.label === "GOAL" || m.label === "SAVE") return m.kind;
  return `label-${m.label.toLowerCase().replace(/\s+/g, "-")}`;
}

/**
 * Highlights mode, or nothing when the bundle's match.json has no reel. `videoTime` maps match time
 * to the footage's own time across its cuts; `footage` is the player.
 */
export function setupHighlights(
  b: Bundle,
  videoTime: (t: number) => number,
  footage: { time(): number; seek(v: number): void; play(): void; pause(): void; duration: number },
) {
  const r = b.match?.highlights;
  const panel = $("highlights");
  const card = $("hl-card");
  const progress = $("hl-progress");
  if (!r || !r.moments.length) {
    panel.hidden = !r; // a reel with no moments still says why (nothing detected yet)
    if (r) $("hl-notes").replaceChildren(el("p", "hl-note", "No goal or save was detected in this footage."));
    card.hidden = true;
    progress.hidden = true;
    return null;
  }
  panel.hidden = false;
  document.body.dataset.highlights = "on";
  $("hl-count").textContent = `${r.moments.length} ${r.moments.length === 1 ? "moment" : "moments"}`;
  $("hl-notes").replaceChildren(...notes(r).map((n) => el("p", "hl-note", n)));
  if (b.manifest.events.standin)
    $("hl-notes").append(el("p", "hl-note warn", "These moments come from a hand-written stand-in, not the detector."));

  const playButton = $<HTMLButtonElement>("hl-play");
  const list = $("hl-list");
  const items = r.moments.map((m, i) => {
    const li = document.createElement("li");
    const btn = el("button", `hl-item ${tone(m)}`);
    btn.type = "button";
    btn.dataset.event = m.event;
    btn.setAttribute("aria-label", `Highlight ${i + 1} of ${r.moments.length}: ${said(m)}`);
    const top = el("span", "hl-item-top");
    top.append(el("span", "hl-chip", m.label), el("span", "hl-item-time", clock(m.t)));
    btn.append(top, el("span", "hl-item-text", m.caption ?? `${m.kind === "goal" ? "Goal" : "Save"}, ${m.team ?? ""}`));
    btn.addEventListener("click", () => playFrom(i, false));
    li.append(btn);
    return { li, btn, m };
  });
  list.replaceChildren(...items.map((x) => x.li));

  const label = $("hl-label");
  const detail = $("hl-detail");
  const meta = $("hl-meta");
  const caption = $("hl-caption");
  const source = $("hl-source");
  const announce = $("hl-live");

  // The reel: each moment's clip in turn, then stop. A manual seek or pause leaves it.
  let reel: number | null = null; // the moment playing, while the reel runs
  let shown: string | null = null;
  const playFrom = (i: number, asReel: boolean) => {
    const m = r.moments[i];
    reel = asReel ? i : null;
    footage.seek(Math.max(0, videoTime(m.clip[0])));
    footage.play();
    items[i].btn.focus({ preventScroll: true });
  };
  const stopReel = () => {
    reel = null;
  };
  const toggleReel = () => {
    if (reel === null) playFrom(0, true);
    else {
      stopReel();
      footage.pause();
    }
  };
  playButton.addEventListener("click", toggleReel);

  const tick = (v: number, t: number, reduceMotion: boolean) => {
    if (reel !== null) {
      const end = Math.min(footage.duration, videoTime(r.moments[reel].clip[1]));
      if (v >= end - 1e-3) {
        if (reel + 1 < r.moments.length) playFrom(reel + 1, true);
        else {
          stopReel();
          footage.pause();
        }
      }
    }
    const m = momentAt(r, t);
    card.hidden = !m;
    card.classList.toggle("still", reduceMotion);
    if (m && m.event !== shown) {
      label.textContent = m.label;
      card.className = `hl-card ${tone(m)}${reduceMotion ? " still" : ""}`;
      detail.textContent = m.label_detail ?? "";
      detail.hidden = !m.label_detail;
      meta.textContent = [m.kind === "goal" ? "GOAL" : "SAVE", m.team?.toUpperCase(), m.player, clock(m.t)]
        .filter(Boolean)
        .join(" · ");
      caption.textContent = m.caption ?? "";
      caption.hidden = !m.caption;
      source.textContent = m.caption_source === "model" ? "Fact-checked commentary" : "Computed";
      source.className = `hl-source ${m.caption_source ?? "code"}`;
      source.hidden = !m.caption;
      announce.textContent = said(m);
    }
    shown = m ? m.event : null;
    for (const x of items) {
      if (x.m === m) x.btn.setAttribute("aria-current", "true");
      else x.btn.removeAttribute("aria-current");
    }
    progress.hidden = reel === null;
    if (reel !== null) progress.textContent = `Highlights · ${reel + 1} / ${r.moments.length}`;
    playButton.textContent = reel === null ? "Play the reel" : "Stop the reel";
    playButton.setAttribute("aria-pressed", String(reel !== null));
    panel.dataset.reel = reel === null ? "" : String(reel + 1);
    panel.dataset.card = m ? m.event : "";
  };

  (window as unknown as { ninetyHighlights: unknown }).ninetyHighlights = {
    momentAt: (t: number) => momentAt(r, t),
    reel: () => reel,
  };
  return { tick, toggleReel, stopReel };
}
