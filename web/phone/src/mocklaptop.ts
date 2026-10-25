// The mock laptop (mock-laptop.html): stands in for the viewer while there is no companion server.
// It plays a clock and relays it, with a focus, to the phone in another tab of this browser.

import { MockLaptop, newCode } from "./mockrelay";
import { clock } from "./types";

const $ = <T extends HTMLElement>(id: string) => document.getElementById(id) as T;
const params = new URLSearchParams(location.search);
const code = params.get("code") ?? newCode();
const relay = new MockLaptop(code, () => ({ type: "clock", t: Math.round(now() * 100) / 100, playing }));
(window as unknown as { ninetyLaptop: object }).ninetyLaptop = { relay, time: () => now() }; // read by tests/test_phone.py

let playing = false;
let origin = 0; // match time at `since`
let since = performance.now();
const now = () => origin + (playing ? (performance.now() - since) / 1000 : 0);
const sendClock = () => relay.send({ type: "clock", t: Math.round(now() * 100) / 100, playing });

$("code").textContent = code;
$<HTMLAnchorElement>("phone-link").href = `./?mock=1&code=${code}&clip=mock`;
$("play").addEventListener("click", () => {
  origin = now();
  since = performance.now();
  playing = !playing;
  $("play").textContent = playing ? "Pause" : "Play";
  sendClock();
});
$<HTMLInputElement>("seek").addEventListener("input", (e) => {
  origin = Number((e.target as HTMLInputElement).value);
  since = performance.now();
  sendClock();
});
const focus = $<HTMLSelectElement>("focus");
for (const side of ["h", "a"]) for (let n = 1; n <= 11; n++) focus.add(new Option(`${side === "h" ? "Home" : "Away"} ${n}`, `${side}${n}`));
focus.addEventListener("change", () => relay.send({ type: "focus", player: focus.value || null }));
setInterval(sendClock, 1000);
sendClock();
const tick = () => {
  $("t").textContent = clock(now());
  if (document.activeElement !== $("seek")) $<HTMLInputElement>("seek").value = String(now());
  requestAnimationFrame(tick);
};
requestAnimationFrame(tick);
