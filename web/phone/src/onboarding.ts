// The first-run onboarding, inside Ask where the starter grid sits: three iOS-style choices, one tap
// each (favourite club, mode, what matters most), then Ask's questions follow them (fan.ts). The
// composer stays below, so a fan can always just type. Reopened from the settings sheet's
// "Personalise" row with the saved choices ticked.

import { crestOf } from "../../viewer/src/crests";
import { CLUBS, short } from "../../viewer/src/teams";
import { CHOICES, type Club, type Fan, type Focus, type Mode } from "./fan";

type Step = "club" | "mode" | "focus";
const STEPS: Step[] = ["club", "mode", "focus"];
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
      <button type="button" class="nav-link onboard-back"><svg viewBox="0 0 24 24" aria-hidden="true"><path d="M15 5l-7 7 7 7"/></svg>Back</button>
      <span class="page-dots" aria-hidden="true"><i></i><i></i><i></i></span>
      <button type="button" class="nav-link onboard-skip">Skip</button>
    </div>
    <h2 class="onboard-title" id="onboard-title" tabindex="-1"></h2>
    <p class="sr-only" id="onboard-step"></p>
    <ul class="group onboard-list" role="radiogroup" aria-labelledby="onboard-title"></ul>`;
  const back = root.querySelector<HTMLButtonElement>(".onboard-back")!;
  const skip = root.querySelector<HTMLButtonElement>(".onboard-skip")!;
  const title = root.querySelector<HTMLElement>(".onboard-title")!;
  const list = root.querySelector<HTMLUListElement>(".onboard-list")!;
  const dots = [...root.querySelectorAll<HTMLElement>(".page-dots i")];

  function row(key: string, label: string, on: boolean, crest: string | null): HTMLLIElement {
    const li = document.createElement("li");
    li.className = "setting-row radio";
    const b = document.createElement("button");
    b.type = "button";
    b.className = "radio-main onboard-option";
    b.setAttribute("role", "radio");
    b.setAttribute("aria-checked", String(on));
    b.dataset.value = key;
    b.innerHTML = `${crest ? `<span class="onboard-crest" aria-hidden="true">${crest}</span>` : ""}<span class="row-title"></span><svg class="tick" viewBox="0 0 24 24" aria-hidden="true"><path d="m5 12.5 4.5 4.5L19 7.5"/></svg>`;
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
