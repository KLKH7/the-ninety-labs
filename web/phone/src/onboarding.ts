// The first-run onboarding, inside Ask where the starter grid sits: three iOS-style choices, one tap
// each (favourite club, mode, what matters most), then Ask's questions follow them (fan.ts). The
// composer stays below, so a fan can always just type. Reopened from the settings sheet's
// "Personalise" row with the saved choices ticked.

import { crestOf } from "../../viewer/src/crests";
import { CLUBS, short } from "../../viewer/src/teams";
import { CHOICES, type Club, type Fan, type Focus, type Mode } from "./fan";

type Step = "club" | "mode" | "focus";
const STEPS: Step[] = ["club", "mode", "focus"];
/** The mode and focus tiles' glyphs (SF Symbols' shapes, drawn here). */
const GLYPHS: Record<string, string> = {
  casual: '<circle cx="12" cy="12" r="8.5"/><path d="M12 8.2l3.2 2.3-1.2 3.8h-4l-1.2-3.8zM12 3.5v4.7M15.2 10.5l4.4-1.4M14 14.3l2.6 3.6M10 14.3l-2.6 3.6M8.8 10.5 4.4 9.1"/>',
  analyst: '<path d="M4 20h16M6.5 17v-5M11 17V7M15.5 17v-8M20 17V4.5"/>',
  moments: '<path d="M12 3.5 14.5 9l6 .5-4.6 3.9 1.4 5.9L12 16.2l-5.3 3.1 1.4-5.9L3.5 9.5l6-.5z"/>',
  tactics: '<rect x="3" y="5" width="18" height="14" rx="2.5"/><path d="M12 5v14"/><circle cx="12" cy="12" r="2.6"/>',
  players: '<circle cx="12" cy="8" r="3.5"/><path d="M5 20c.8-3.8 3.6-6 7-6s6.2 2.2 7 6"/>',
};
const TITLES: Record<Step, string> = { club: "Your club", mode: "How do you watch?", focus: "What matters most?" };

export interface Onboarding {
  open(current: Fan | null, editing: boolean): void;
  close(): void;
  readonly isOpen: boolean;
  readonly editing: boolean;
}

export function mountOnboarding(root: HTMLElement, done: (fan: Fan | null, editing: boolean) => void): Onboarding {
  let step = 0;
  let editing = false;
  let draft: Partial<Fan> = {};

  root.innerHTML = `
    <div class="onboard-nav">
      <button type="button" class="nav-link onboard-back" aria-label="Back"><svg viewBox="0 0 24 24" aria-hidden="true"><path d="M14.5 5.5 8 12l6.5 6.5"/></svg></button>
      <span class="page-dots" aria-hidden="true"><i></i><i></i><i></i></span>
      <button type="button" class="nav-link onboard-skip">Skip</button>
    </div>
    <div class="onboard-body">
      <h2 class="onboard-title" id="onboard-title" tabindex="-1"></h2>
      <p class="sr-only" id="onboard-step"></p>
      <ul class="onboard-tiles" role="radiogroup" aria-labelledby="onboard-title"></ul>
    </div>`;
  const back = root.querySelector<HTMLButtonElement>(".onboard-back")!;
  const skip = root.querySelector<HTMLButtonElement>(".onboard-skip")!;
  const title = root.querySelector<HTMLElement>(".onboard-title")!;
  const list = root.querySelector<HTMLUListElement>(".onboard-tiles")!;
  const dots = [...root.querySelectorAll<HTMLElement>(".page-dots i")];

  /** A choice as a large tile: the club's crest, or a glyph, over its name. */
  function row(key: string, label: string, on: boolean, crest: string | null): HTMLLIElement {
    const li = document.createElement("li");
    const b = document.createElement("button");
    b.type = "button";
    b.className = "onboard-option";
    b.setAttribute("role", "radio");
    b.setAttribute("aria-checked", String(on));
    b.dataset.value = key;
    const art = crest
      ? `<span class="onboard-crest" aria-hidden="true">${crest}</span>`
      : `<svg class="onboard-glyph" viewBox="0 0 24 24" aria-hidden="true">${GLYPHS[key]}</svg>`;
    b.innerHTML = `${art}<span class="row-title"></span><svg class="tick" viewBox="0 0 24 24" aria-hidden="true"><path d="m5 12.5 4.5 4.5L19 7.5"/></svg>`;
    b.querySelector(".row-title")!.textContent = label;
    b.addEventListener("click", () => choose(key));
    li.append(b);
    return li;
  }

  function render(focus = true) {
    const s = STEPS[step];
    title.textContent = TITLES[s];
    root.querySelector("#onboard-step")!.textContent = `Step ${step + 1} of ${STEPS.length}`;
    back.classList.toggle("gone", step === 0); // keeps its place, so the dots stay centred
    back.setAttribute("aria-hidden", String(step === 0));
    back.tabIndex = step === 0 ? -1 : 0;
    skip.textContent = editing ? "Cancel" : "Skip";
    dots.forEach((d, i) => d.classList.toggle("on", i === step));
    const chosen = draft[s];
    list.dataset.step = s;
    list.replaceChildren(
      ...CHOICES[s].map(([key, label]) => row(key, label, chosen === key, s === "club" ? crestOf(short(CLUBS[key as Club])) : null)),
    );
    if (focus) title.focus({ preventScroll: true });
  }

  function choose(key: string) {
    const s = STEPS[step];
    if (s === "club") draft.club = key as Club;
    else if (s === "mode") draft.mode = key as Mode;
    else draft.focus = key as Focus;
    if (step < STEPS.length - 1) {
      step += 1;
      render();
      return;
    }
    const was = editing;
    api.close();
    done(draft as Fan, was);
  }

  back.addEventListener("click", () => {
    step = Math.max(0, step - 1);
    render();
  });
  skip.addEventListener("click", () => {
    const was = editing;
    api.close();
    done(null, was);
  });

  const api: Onboarding = {
    open(current, isEditing) {
      editing = isEditing;
      draft = current ? { ...current } : {};
      step = 0;
      root.hidden = false;
      render(isEditing);
    },
    close() {
      root.hidden = true;
      editing = false;
    },
    get isOpen() {
      return !root.hidden;
    },
    get editing() {
      return editing;
    },
  };
  return api;
}
