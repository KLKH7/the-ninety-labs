// The big screen's companion, on the computer (Kian, Oct 26): judges open the web link on a laptop
// and never see the phone behind the QR code, so the phone app itself (web/phone) is docked on the
// right of the picture, paired to this screen with no code to type. Open by default on a wide
// window; below 1000 px (style.css), where a 380 px panel leaves the picture too small, it is a
// bottom sheet. "Take it to your phone" keeps the QR code a tap away. Full screen starts with
// the picture alone; the control bar's button docks the companion beside it again.
//
// The embedded app is a second phone in this screen's room (ninety/api/companion.py allows
// MAX_PHONES): it gets the same clock and focus messages as a phone in a fan's hand.

type QR = { createSvgTag(opts: { cellSize: number; margin: number; scalable: boolean }): string };

export interface Store {
  get(key: string): string | null;
  set(key: string, value: string): void;
}

const $ = <T extends HTMLElement>(id: string) => document.getElementById(id) as T;

export function setupDock(store: Store) {
  const panel = $("companion");
  const toggle = $<HTMLButtonElement>("companion-toggle");
  const qrButton = $<HTMLButtonElement>("companion-qr");
  const pair = $("companion-pair");
  const frame = $<HTMLIFrameElement>("companion-frame");
  const wait = $("companion-wait");
  const hint = $<HTMLButtonElement>("ask-hint");
  const hudButton = $<HTMLButtonElement>("hud-companion");
  panel.hidden = false;
  hudButton.hidden = false;
  hudButton.innerHTML =
    '<svg viewBox="0 0 24 24" aria-hidden="true"><path class="line" d="M3.5 5.5h17v13h-17zM15 5.5v13"/></svg>';

  // Open unless this viewer closed it (a docked panel, or a sheet on a narrow window); full screen
  // starts with the picture alone.
  let open = store.get("dock") !== "closed";
  let full = false;
  const apply = () => {
    const shown = full ? fullOpen : open;
    document.body.dataset.dock = shown ? "open" : "closed";
    toggle.setAttribute("aria-expanded", String(shown));
    hudButton.setAttribute("aria-expanded", String(shown));
    hudButton.setAttribute("aria-label", shown ? "Hide the companion" : "Show the companion");
    toggle.setAttribute("aria-label", shown ? "Hide the companion" : "Show the companion");
  };
  let fullOpen = false;
  const set = (shown: boolean) => {
    if (full) fullOpen = shown;
    else {
      open = shown;
      store.set("dock", shown ? "open" : "closed");
    }
    apply();
  };
  toggle.addEventListener("click", () => set(document.body.dataset.dock !== "open"));
  hudButton.addEventListener("click", () => set(document.body.dataset.dock !== "open"));
  document.addEventListener("fullscreenchange", () => {
    full = !!document.fullscreenElement;
    fullOpen = false;
    apply();
  });
  apply();

  const showPair = (shown: boolean) => {
    pair.hidden = !shown;
    qrButton.setAttribute("aria-expanded", String(shown));
  };
  qrButton.addEventListener("click", () => showPair(pair.hidden));
  // With the companion open the picture's QR card stays down (style.css): the control bar's QR
  // button opens the companion's own instead.
  $("hud-qr").addEventListener("click", () => document.body.dataset.dock === "open" && showPair(pair.hidden));

  // The first-run pill: once, until the companion is first used (its pill, its panel or its QR).
  let hintUsed = store.get("askHint") === "used";
  const used = () => {
    if (hintUsed) return;
    hintUsed = true;
    store.set("askHint", "used");
    hint.hidden = true;
  };
  hint.hidden = hintUsed;
  hint.addEventListener("click", () => {
    set(true);
    frame.contentWindow?.postMessage({ type: "ninety-open", tab: "ask" }, location.origin);
    frame.focus();
    used();
  });
  qrButton.addEventListener("click", used);
  // A click inside the embedded app moves focus into its frame: that is a use too.
  window.addEventListener("blur", () => setTimeout(() => document.activeElement === frame && used(), 0));

  frame.addEventListener("load", () => (wait.hidden = !!frame.getAttribute("src")));

  return {
    /** A pairing code is up: embed the phone app on it and put its QR code behind the button. */
    setCode(code: string, url: string, qr: QR) {
      const u = new URL(url);
      u.searchParams.set("embed", "1");
      if (frame.getAttribute("src") !== u.href) frame.src = u.href;
      $("companion-qr-code").innerHTML = qr.createSvgTag({ cellSize: 4, margin: 2, scalable: true });
      $("companion-url").textContent = `${location.host}/phone`;
      $("companion-code").textContent = `${code.slice(0, 3)} ${code.slice(3)}`;
    },
    toggle: () => set(document.body.dataset.dock !== "open"),
  };
}
