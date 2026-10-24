// The one way the viewer and the phone speak with the browser's voice. Read-aloud is off until a
// fan turns it on with a tap; and an automated browser (tests, screenshot runs: Playwright sets
// navigator.webdriver) never speaks aloud: the line is kept in window.ninetySpokenAloud instead, so
// a test can still check what would have been said and no one hears the system voice.

export function speakAloud(text: string, opts: { lang?: string; rate?: number } = {}): void {
  if (typeof navigator !== "undefined" && navigator.webdriver) {
    const w = window as unknown as { ninetySpokenAloud?: string[] };
    (w.ninetySpokenAloud ??= []).push(text);
    return;
  }
  if (typeof speechSynthesis === "undefined") return;
  const u = new SpeechSynthesisUtterance(text);
  if (opts.lang) u.lang = opts.lang;
  if (opts.rate) u.rate = opts.rate;
  speechSynthesis.speak(u);
}
