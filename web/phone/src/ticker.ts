// Number ticker: a number moves to its new value on a spring instead of jumping, for the score and
// the team stats. Ported from Magic UI's NumberTicker (MIT, Copyright (c) Magic UI; recorded in
// THIRD_PARTY_NOTICES.md): the same spring (stiffness 100, damping 60, mass 1) and whole numbers in
// tabular figures, without React or motion: one requestAnimationFrame loop per element. With
// reduced motion the number is set at once.

const STIFFNESS = 100;
const DAMPING = 60;
const SETTLED = 0.01; // within a hundredth of a unit and nearly still: done

interface Spring {
  x: number;
  v: number;
  to: number;
  raf: number;
  last: number;
}
const springs = new WeakMap<HTMLElement, Spring>();
const reduce = () => matchMedia("(prefers-reduced-motion: reduce)").matches;

/** Shows `to` in `el`, ticking from what it shows now (or from `from`). */
export function tickTo(el: HTMLElement, to: number, from?: number) {
  const s = springs.get(el);
  if (s && s.to === to) return;
  const start = from ?? s?.x ?? Number(el.textContent);
  if (reduce() || !Number.isFinite(start) || start === to) {
    if (s) cancelAnimationFrame(s.raf);
    springs.delete(el);
    el.textContent = String(to);
    return;
  }
  const spring: Spring = s ?? { x: start, v: 0, to, raf: 0, last: performance.now() };
  spring.to = to;
  spring.last = performance.now();
  cancelAnimationFrame(spring.raf);
  const step = (now: number) => {
    const dt = Math.min(1 / 30, (now - spring.last) / 1000);
    spring.last = now;
    const a = -STIFFNESS * (spring.x - spring.to) - DAMPING * spring.v;
    spring.v += a * dt;
    spring.x += spring.v * dt;
    if (Math.abs(spring.x - spring.to) < SETTLED && Math.abs(spring.v) < SETTLED) {
      el.textContent = String(spring.to);
      springs.delete(el);
      return;
    }
    el.textContent = String(Math.round(spring.x));
    spring.raf = requestAnimationFrame(step);
  };
  springs.set(el, spring);
  spring.raf = requestAnimationFrame(step);
}
